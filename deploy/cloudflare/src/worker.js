import {
  MODEL_ID, SEARCH_COST, UNITS, LEASE_SECONDS, MAX_LEASE, RECOVERY_PEPPER, SCENE_DIM,
  OBJECT_PROPOSALS, OBJECT_DIM,
  sha256Hex, encodeUtf8, equalHex, seedBytes, renderFacesFromSeed, embeddingFor,
  outputDigest,
  parsePrompt, snapDescriptionWeight,
  base64ToBytes, bytesToHex,
  bytesToBase64, randomHex, randomToken, normalizeViewDirection,
} from "./model.js";
import {
  QUERY_VIEW_CAP, renderLocationFaces, leaseCap, usesStreetViews,
} from "./pano.js";
import { requireSchema } from "./schemaRevision.js";
import { ingressLimit, accountLimit, viewLimit, ApiLimitError } from './apiRateLimit.js';
import { OBJECT_INDEX_MODEL, validateObjectIndex } from "./objectIndex.js";
import { onlineSearch, onlineSearchConfigured, INDEX_DOWNLOAD_ROUTES } from "./onlineSearch.js";
import { SearchError } from "./searchLedger.js";
import { deleteAccount, cleanupAccountArtifacts, archiveAccountDeletionReceipts } from "./accountPrivacy.js";
import { writeSceneArtifact } from "./artifactWrites.js";
import { officialGen4Coverage, objectCoverageComplete } from "./objectCoverage.js";
import { readRequestJson } from "./requestBody.js";
import { localObjectPrototype, objectCapabilities } from "./objectAdmission.js";
import { loadSceneReferences, sceneCapabilities } from "./sceneQuality.js";
import { verifierConfigured, auditBatchLimit, pipelineCapabilities, activeQualification, qualificationStatus, qualifyDevice, auditScene, stageScene } from "./scenePipeline.js";


const HEADERS = {
  "content-type": "application/json",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
  "x-frame-options": "DENY",
  "x-robots-tag": "noindex, nofollow",
  "permissions-policy": "camera=(), microphone=(), geolocation=()",
  "content-security-policy":
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' https://map-making.app; img-src 'self'; base-uri 'none'; frame-ancestors 'none'",
};

async function locationFaces(location) {
  return renderLocationFaces(location, async () =>
    renderFacesFromSeed(await seedBytes(location.assetId || location.panoId, location.capture, location.lane, location.model || MODEL_ID))
  );
}

function json(value, status = 200, extra = {}) {
  return new Response(JSON.stringify(value), { status, headers: { ...HEADERS, ...extra } });
}

function error(code, status = 400, extra = {}) {
  return json({ error: code }, status, extra);
}

function viewFailure(err) {
  const code = err && err.message;
  if (typeof code === "string" && code.includes("account_not_active")) return error("unauthorized", 401);
  if (err && Number.isInteger(err.status) && code) return error(code, err.status);
  if (code === "view_unavailable" || code === "invalid_thumbnail") return error("view_unavailable", 422);
  if (code === "not_a_street_pano" || code === "invalid_pano_id") return error("invalid_pano_id");
  return null;
}

function cookie(token, request) {
  const secure = new URL(request.url).protocol === "https:" ? "; Secure" : "";
  return `vision_session=${token}; HttpOnly; SameSite=Strict; Path=/${secure}`;
}

function tokenFrom(request) {
  const auth = request.headers.get("Authorization") || "";
  if (auth.startsWith("Bearer ")) return auth.slice(7);
  const match = (request.headers.get("Cookie") || "").match(/(?:^|;\s*)vision_session=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function sameOrigin(request) {
  const origin = request.headers.get("Origin");
  if (!origin) return true;
  try {
    return new URL(origin).origin === new URL(request.url).origin;
  } catch {
    return false;
  }
}


const FOUR_VIEW_MODEL = "vision-four-view-v4";
const FOUR_VIEW_BYTES = 3080;
const FOUR_VIEW_VIEWS = 4;
const FOUR_VIEW_VIEW_BYTES = 770;

function positiveFiniteF16(bytes, offset) {
  const value = bytes[offset] | (bytes[offset + 1] << 8);
  const exponent = (value >> 10) & 0x1f;
  const sign = value >> 15;
  if (exponent === 0x1f || sign !== 0) return false;
  return value !== 0;
}

function validFourViewRecord(bytes) {
  if (!bytes || bytes.length !== FOUR_VIEW_BYTES) return false;
  for (let view = 0; view < FOUR_VIEW_VIEWS; view += 1) {
    if (!positiveFiniteF16(bytes, view * FOUR_VIEW_VIEW_BYTES)) return false;
  }
  return true;
}


const STEAL_AFTER_SECONDS = 6 * 60 * 60;
const FAMILY_LABELS = {
  "new-places": "New places",
  "whole-map": "Whole map",
  "already-indexed": "Already-indexed places",
  other: "Other places",
};

function catalogOrderSql() {
  return `CASE WHEN r2_key LIKE 'catalog/all-locations-tail-v1/%' THEN 0 WHEN r2_key LIKE 'catalog/all-locations-full-v1/%' THEN 1 WHEN r2_key LIKE 'catalog/vision-indexed-v1/%' THEN 2 ELSE 3 END, shard_id`;
}

function familyForKey(key) {
  const value = key || "";
  if (value.startsWith("catalog/all-locations-tail-v1/")) return "new-places";
  if (value.startsWith("catalog/all-locations-full-v1/")) return "whole-map";
  if (value.startsWith("catalog/vision-indexed-v1/")) return "already-indexed";
  return "other";
}

function parsePart(value) {
  if (value == null || value === "") return null;
  if (typeof value !== "number" && typeof value !== "string") return undefined;
  const part = typeof value === "number" ? value : Number(String(value).trim());
  if (!Number.isInteger(part) || part < 1 || part > 1000000) return undefined;
  return part;
}

function describePart(part, partCountValue, family, rowsLeft, lane = "scene") {
  const familyName = FAMILY_LABELS[family] ? family : "other";
  const noun = lane === "object" ? "objects" : "places";
  return {
    part,
    partCount: partCountValue,
    family: familyName,
    familyLabel: FAMILY_LABELS[familyName],
    rowsLeftInPart: Math.max(0, rowsLeft),
    partLabel: `Batch ${part} of ${partCountValue}`,
    separateParts: true,
    lane,
    summary: `Batch ${part} of ${partCountValue} · ${FAMILY_LABELS[familyName]}. Other people have different batches, so you are not indexing the same ${noun}.`,
  };
}

async function partCount(env, lane) {
  const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM pose_catalog WHERE lane=?").bind(lane).first();
  return row?.n || 0;
}

async function partNumber(env, lane, shardId) {
  const row = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM pose_catalog
     WHERE lane=? AND (
       CASE WHEN r2_key LIKE 'catalog/all-locations-tail-v1/%' THEN 0 WHEN r2_key LIKE 'catalog/all-locations-full-v1/%' THEN 1 WHEN r2_key LIKE 'catalog/vision-indexed-v1/%' THEN 2 ELSE 3 END
       < (SELECT CASE WHEN r2_key LIKE 'catalog/all-locations-tail-v1/%' THEN 0 WHEN r2_key LIKE 'catalog/all-locations-full-v1/%' THEN 1 WHEN r2_key LIKE 'catalog/vision-indexed-v1/%' THEN 2 ELSE 3 END FROM pose_catalog WHERE lane=? AND shard_id=?)
       OR (
         CASE WHEN r2_key LIKE 'catalog/all-locations-tail-v1/%' THEN 0 WHEN r2_key LIKE 'catalog/all-locations-full-v1/%' THEN 1 WHEN r2_key LIKE 'catalog/vision-indexed-v1/%' THEN 2 ELSE 3 END
         = (SELECT CASE WHEN r2_key LIKE 'catalog/all-locations-tail-v1/%' THEN 0 WHEN r2_key LIKE 'catalog/all-locations-full-v1/%' THEN 1 WHEN r2_key LIKE 'catalog/vision-indexed-v1/%' THEN 2 ELSE 3 END FROM pose_catalog WHERE lane=? AND shard_id=?)
         AND shard_id <= ?
       )
     )`
  ).bind(lane, lane, shardId, lane, shardId, shardId).first();
  return row?.n || 0;
}

async function workFromShard(env, lane, shard) {
  const count = Math.max(1, await partCount(env, lane));
  const payload = describePart(
    await partNumber(env, lane, shard.shard_id),
    count,
    familyForKey(shard.r2_key),
    Math.max(0, (shard.row_count || 0) - (shard.next_row || 0)),
    lane,
  );
  payload.shardId = shard.shard_id;
  return payload;
}

async function workStatus(env, account, lane) {
  const shard = await env.DB.prepare(
    `SELECT * FROM pose_catalog WHERE lane=? AND assignee=? AND next_row < row_count ORDER BY ${catalogOrderSql()} LIMIT 1`
  ).bind(lane, account).first();
  if (!shard) {
    const count = await partCount(env, lane);
    if (!count) return null;
    return {
      lane,
      partCount: count,
      separateParts: true,
      summary: `${count} separate batches are available. You get your own batch, so other people are not indexing the same ${lane === "object" ? "objects" : "places"}.`,
    };
  }
  return workFromShard(env, lane, shard);
}

async function accountId(env, request) {
  const token = tokenFrom(request);
  if (!token || token.length > 100) return null;
  const tokenHash = await sha256Hex(encodeUtf8(token));
  const row = await env.DB.prepare("SELECT id, token_hash FROM accounts WHERE token_hash=? AND deleted_at IS NULL").bind(tokenHash).first();
  if (!row || !equalHex(row.token_hash, tokenHash)) return null;
  return row.id;
}

async function status(env, account, options = {}) {
  const lite = Boolean(options.lite);
  const rows = await env.DB.prepare(
    `SELECT lane,
            SUM(CASE WHEN state='published' THEN 0 ELSE 1 END) AS pending,
            SUM(CASE WHEN state='published' THEN 1 ELSE 0 END) AS published
     FROM locations GROUP BY lane`
  ).all();
  const counts = {};
  for (const row of rows.results || []) counts[row.lane] = { pending: row.pending || 0, published: row.published || 0 };
  const catalog = await env.DB.prepare(
    "SELECT lane, SUM(row_count - next_row) AS remaining FROM pose_catalog GROUP BY lane"
  ).all();
  for (const row of catalog.results || []) {
    const laneCounts = counts[row.lane] || (counts[row.lane] = { pending: 0, published: 0 });
    const remaining = row.remaining || 0;
    laneCounts.catalogRemaining = remaining;
    laneCounts.pending = (laneCounts.pending || 0) + remaining;
  }
  const visual = await env.DB.prepare("SELECT COUNT(*) AS n FROM published_index WHERE embedding IS NOT NULL").first();
  const objectIndexes = await env.DB.prepare(
    "SELECT COUNT(DISTINCT i.object_index_key) AS n FROM published_index i JOIN locations l ON l.id=i.location_id WHERE l.lane='object' AND i.object_index_key IS NOT NULL"
  ).first();
  const sceneIndexes = await env.DB.prepare(
    "SELECT COUNT(DISTINCT i.four_view_key) AS n FROM published_index i JOIN locations l ON l.id=i.location_id WHERE l.lane='scene' AND i.four_view_key IS NOT NULL"
  ).first();
  const result = {
    operational: true,
    environment: env.DEPLOYMENT_ENVIRONMENT === "staging" ? "staging" : "preview",
    demo: false,
    publicCorpus: false,
    ownerBypass: false,
    persistImagery: false,
    r2: lite
      ? { provisioned: Boolean(env.INDEX), bucket: env.INDEX ? env.INDEX_BUCKET_NAME || "vision-community" : null, binding: "INDEX", publicAccess: false, role: "sealed-segments" }
      : await r2Status(env),
    searchCost: SEARCH_COST,
    searchBackend: "online",
    searchOnSite: onlineSearchConfigured(env),
    searchReady: onlineSearchConfigured(env),
    indexDownloads: false,
    accountDeletionAvailable: true,
    model: MODEL_ID,
    visualPublished: visual?.n || 0,
    objectIndexes: objectIndexes?.n || 0,
    sceneIndexes: sceneIndexes?.n || 0,
    countries: [],
    cameraGenerations: [],
    output: "map-making.app JSON",
    prototype: true,
    counts,
  };
  if (!lite) {
    const countryRows = await env.DB.prepare(
      "SELECT DISTINCT country FROM locations WHERE country IS NOT NULL AND country != '' ORDER BY country"
    ).all();
    const generationRows = await env.DB.prepare(
      "SELECT DISTINCT camera_generation FROM locations WHERE camera_generation IS NOT NULL AND camera_generation != '' ORDER BY camera_generation"
    ).all();
    result.countries = [...new Set((countryRows.results || []).map((row) => canonicalizeCountry(row.country)).filter(Boolean))].sort();
    result.cameraGenerations = (generationRows.results || []).map((row) => row.camera_generation);
  }
  if (account) {
    const row = await env.DB.prepare("SELECT units FROM accounts WHERE id=?").bind(account).first();
    result.accountId = account;
    result.units = row?.units || 0;
    result.searchesAvailable = Math.floor(result.units / SEARCH_COST);
    if (!lite) {
      const sceneWork = await workStatus(env, account, "scene");
      const objectWork = await workStatus(env, account, "object");
      result.work = sceneWork;
      result.workByLane = { scene: sceneWork, object: objectWork };
    }
  }
  return result;
}

async function r2Status(env) {
  const status = {
    provisioned: Boolean(env.INDEX),
    bucket: env.INDEX ? env.INDEX_BUCKET_NAME || "vision-community" : null,
    binding: "INDEX",
    publicAccess: false,
    role: "sealed-segments",
    registry: false,
    registryBytes: 0,
  };
  if (!env.INDEX) return status;
  const head = await env.INDEX.head("registry.json");
  status.registry = Boolean(head);
  status.registryBytes = head ? head.size : 0;
  const catalog = await env.INDEX.head("catalog/all-locations-tail-v1/manifest.json");
  status.poseCatalog = Boolean(catalog);
  status.poseCatalogBytes = catalog ? catalog.size : 0;
  return status;
}

function parseIndexerLine(text, lane) {
  const parts = text.replace(/\r$/, "").split("\t");
  if (parts.length !== 11 || (parts[0] === "map_id" && parts[7] === "pano_id")) return null;
  const lat = Number(parts[2]);
  const lng = Number(parts[3]);
  if (!parts[7] || !Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return {
    assetId: parts[7],
    capture: "unknown",
    lane,
    model: MODEL_ID,
    lat,
    lon: lng,
    heading: Number(parts[4]) || 0,
    pitch: Number(parts[5]) || 0,
    zoom: Number(parts[6]) || 0,
    country: canonicalizeCountry(parts[8] || ""),
    cameraGeneration: parts[9] || "",
  };
}

async function readCatalogSlice(env, shard, needed) {
  if (!env.INDEX) return { jobs: [], consumed: 0 };
  const length = Math.min(Math.max(8192, needed * 256), Math.max(0, shard.bytes - shard.next_byte));
  if (length <= 0) return { jobs: [], consumed: 0 };
  const object = await env.INDEX.get(shard.r2_key, { range: { offset: shard.next_byte, length } });
  if (!object) return { jobs: [], consumed: 0 };
  const text = await object.text();
  const jobs = [];
  let consumed = 0;
  while (jobs.length < needed) {
    const newline = text.indexOf("\n", consumed);
    if (newline < 0) break;
    const job = parseIndexerLine(text.slice(consumed, newline), shard.lane);
    consumed = newline + 1;
    if (job) jobs.push(job);
  }
  return { jobs, consumed };
}

async function releaseExhaustedShard(env, lane, shardId) {
  await env.DB.prepare(
    "UPDATE pose_catalog SET assignee=NULL WHERE lane=? AND shard_id=? AND next_row >= row_count"
  ).bind(lane, shardId).run();
}

async function claimShard(env, account, lane, shard, now) {
  const stale = now - STEAL_AFTER_SECONDS;
  const moved = await env.DB.prepare(
    `UPDATE pose_catalog SET assignee=?, assigned_at=?
     WHERE lane=? AND shard_id=? AND next_row < row_count AND COALESCE(held, 0)=0
       AND (
         assignee IS NULL OR assignee=?
         OR (
           assigned_at IS NOT NULL AND assigned_at < ?
           AND NOT EXISTS (
             SELECT 1 FROM leases
             WHERE account_id=pose_catalog.assignee AND lane=pose_catalog.lane
               AND state='active' AND expires_at>?
           )
         )
       )`
  ).bind(account, now, lane, shard.shard_id, account, stale, now).run();
  if (!moved.meta || moved.meta.changes !== 1) return null;
  await env.DB.prepare(
    "UPDATE pose_catalog SET assignee=NULL WHERE lane=? AND assignee=? AND shard_id!=? AND next_row < row_count"
  ).bind(lane, account, shard.shard_id).run();
  return env.DB.prepare("SELECT * FROM pose_catalog WHERE lane=? AND shard_id=?").bind(lane, shard.shard_id).first();
}

async function assignCatalogShard(env, account, lane, now, part) {
  if (part != null) {
    const shard = await env.DB.prepare(
      `SELECT * FROM pose_catalog WHERE lane=? ORDER BY ${catalogOrderSql()} LIMIT 1 OFFSET ?`
    ).bind(lane, part - 1).first();
    if (!shard) return { error: "invalid_part" };
    const claimed = await claimShard(env, account, lane, shard, now);
    if (!claimed) {
      if ((shard.next_row || 0) >= (shard.row_count || 0)) {
        return assignCatalogShard(env, account, lane, now, null);
      }
      if (shard.assignee && shard.assignee !== account) return { error: "part_taken" };
      return null;
    }
    return claimed;
  }
  const existing = await env.DB.prepare(
    `SELECT * FROM pose_catalog WHERE lane=? AND assignee=? AND next_row < row_count AND COALESCE(held, 0)=0 ORDER BY ${catalogOrderSql()} LIMIT 1`
  ).bind(lane, account).first();
  if (existing) return existing;
  const candidates = (await env.DB.prepare(
    `SELECT * FROM pose_catalog WHERE lane=? AND next_row < row_count AND COALESCE(held, 0)=0 ORDER BY ${catalogOrderSql()}`
  ).bind(lane).all()).results || [];
  for (const shard of candidates) {
    const claimed = await claimShard(env, account, lane, shard, now);
    if (claimed) return claimed;
  }
  return null;
}

async function pendingForShard(env, lane, shardId, now, count) {
  return (await env.DB.prepare(
    `SELECT id, asset_id, capture, lane, model, generation, attribution, lat, lon, heading, pitch, zoom, country, camera_generation, catalog_shard, state, lease_until
     FROM locations WHERE lane=? AND catalog_shard=? AND COALESCE(queue_state,'pending')='pending'
       AND asset_id NOT LIKE 'Prototype%' AND asset_id NOT LIKE 'synthetic:%' AND asset_id NOT LIKE 'CommunityPano%'
       AND (state='pending' OR (state='leased' AND lease_until<=?))
       AND (lane!='object' OR (${officialGen4Coverage("locations")}))
     ORDER BY id LIMIT ?`
  ).bind(lane, shardId, now, count).all()).results || [];
}

async function pendingShared(env, lane, now, count) {
  return (await env.DB.prepare(
    `SELECT id, asset_id, capture, lane, model, generation, attribution, lat, lon, heading, pitch, zoom, country, camera_generation, catalog_shard, state, lease_until
     FROM locations WHERE lane=? AND COALESCE(queue_state,'pending')='pending'
       AND asset_id NOT LIKE 'Prototype%' AND asset_id NOT LIKE 'synthetic:%' AND asset_id NOT LIKE 'CommunityPano%'
       AND (state='pending' OR (state='leased' AND lease_until<=?))
       AND (lane!='object' OR (${officialGen4Coverage("locations")}))
     ORDER BY id LIMIT ?`
  ).bind(lane, now, count).all()).results || [];
}

async function materializeCatalog(env, lane, count, now, shard) {
  const claimed = [];
  const shardId = shard.shard_id;
  for (let attempt = 0; attempt < 32 && claimed.length < count; attempt += 1) {
    const current = await env.DB.prepare(
      "SELECT * FROM pose_catalog WHERE lane=? AND shard_id=?"
    ).bind(lane, shardId).first();
    if (!current || current.next_row >= current.row_count) break;
    const needed = count - claimed.length;
    const slice = await readCatalogSlice(env, current, needed);
    if (!slice.consumed) {
      await env.DB.prepare(
        "UPDATE pose_catalog SET next_row=row_count, next_byte=bytes WHERE lane=? AND shard_id=?"
      ).bind(lane, shardId).run();
      await releaseExhaustedShard(env, lane, shardId);
      break;
    }
    const moved = await env.DB.prepare(
      "UPDATE pose_catalog SET next_byte=next_byte+?, next_row=next_row+? WHERE lane=? AND shard_id=? AND next_byte=?"
    ).bind(slice.consumed, slice.jobs.length, lane, shardId, current.next_byte).run();
    if (!moved.meta || moved.meta.changes !== 1) continue;
    await releaseExhaustedShard(env, lane, shardId);
    for (const job of slice.jobs) {
      await env.DB.prepare(
        `INSERT OR IGNORE INTO locations
          (asset_id, capture, lane, model, label, source, rights, attribution, lat, lon, heading, pitch, zoom, country, camera_generation, queue_state, catalog_shard)
         VALUES (?, ?, ?, ?, '', 'street-metadata', 'metadata-only-no-imagery', 'Panorama metadata only. Imagery is not stored.', ?, ?, ?, ?, ?, ?, ?, 'pending', ?)`
      ).bind(
        job.assetId, job.capture, job.lane, job.model,
        job.lat, job.lon, job.heading, job.pitch, job.zoom, job.country, job.cameraGeneration, shardId
      ).run();
      await env.DB.prepare(
        `UPDATE locations SET catalog_shard=?
         WHERE asset_id=? AND capture=? AND lane=? AND model=? AND catalog_shard IS NULL`
      ).bind(shardId, job.assetId, job.capture, job.lane, job.model).run();
      const row = await env.DB.prepare(
        `SELECT id, asset_id, capture, lane, model, generation, attribution, lat, lon, heading, pitch, zoom, country, camera_generation, catalog_shard, state, lease_until, queue_state
         FROM locations WHERE asset_id=? AND capture=? AND lane=? AND model=?`
      ).bind(job.assetId, job.capture, job.lane, job.model).first();
      if (!row || row.state === "published" || row.queue_state === "skipped") continue;
      if (row.state === "leased" && row.lease_until && row.lease_until > now) continue;
      claimed.push(row);
      if (claimed.length >= count) break;
    }
  }
  return claimed;
}

async function createAccount(env, request) {
  const token = randomToken(32);
  const account = randomHex(16);
  const recovery = randomToken(18);
  const tokenHash = await sha256Hex(encodeUtf8(token));
  const recoveryHash = await sha256Hex(encodeUtf8(`${RECOVERY_PEPPER}\n${recovery}`));
  await env.DB.prepare("INSERT INTO accounts (id, token_hash, recovery_hash) VALUES (?, ?, ?)").bind(account, tokenHash, recoveryHash).run();
  return json({ accountId: account, recoveryCode: recovery }, 201, { "set-cookie": cookie(token, request) });
}

async function recover(env, request, body) {
  const code = body.recoveryCode;
  if (typeof code !== "string" || code.length < 16 || code.length > 80) return error("invalid_recovery", 401);
  const recoveryHash = await sha256Hex(encodeUtf8(`${RECOVERY_PEPPER}\n${code}`));
  const row = await env.DB.prepare("SELECT id FROM accounts WHERE recovery_hash=? AND deleted_at IS NULL").bind(recoveryHash).first();
  if (!row) return error("invalid_recovery", 401);
  const token = randomToken(32);
  const tokenHash = await sha256Hex(encodeUtf8(token));
  const recovered = await env.DB.prepare("UPDATE accounts SET token_hash=? WHERE id=? AND recovery_hash=? AND deleted_at IS NULL")
    .bind(tokenHash, row.id, recoveryHash).run();
  if (recovered.meta?.changes !== 1) return error("invalid_recovery", 401);
  return json({ accountId: row.id }, 200, { "set-cookie": cookie(token, request) });
}

async function leaseItemFromRow(row, generation) {
  const item = {
    locationId: row.id,
    assetId: row.asset_id,
    panoId: row.asset_id,
    capture: row.capture,
    lane: row.lane,
    model: row.model,
    generation,
    attribution: row.attribution,
    lat: row.lat,
    lng: row.lon,
    heading: row.heading || 0,
    pitch: row.pitch || 0,
    zoom: row.zoom || 0,
    country: row.country || "",
    cameraGeneration: row.camera_generation || "",
    persistImagery: false,
  };
  if (usesStreetViews(row.asset_id)) item.viewStrategy = "vision-pano-v1";
  else {
    const faces = renderFacesFromSeed(await seedBytes(row.asset_id, row.capture, row.lane, row.model));
    item.facesSha256 = await sha256Hex(faces);
  }
  return item;
}

async function lease(env, account, body, objectPrototype = false) {
  const lane = body.lane;
  if (lane === "object" && !objectPrototype) return error("object_verification_unavailable", 503);
  const pace = body.pace || "medium";
  if (!UNITS[lane] || typeof body.count !== "number" || body.count < 1 || body.count > MAX_LEASE) return error("invalid_lease_request");
  const references = lane === "scene" ? await loadSceneReferences(env) : null;
  if (lane === "scene" && !references && !verifierConfigured(env)) return error("scene_verification_unavailable", 503);
  const qualification = lane === "scene" && verifierConfigured(env)
    ? await activeQualification(env, account, Math.floor(Date.now() / 1000), null, body.profileId || null)
    : null;
  if (!["slow", "medium", "max"].includes(pace)) return error("invalid_pace");
  const requestedPart = parsePart(body.part);
  if (requestedPart === undefined) return error("invalid_part");
  const client = body.client === "cli" ? "cli" : "browser";
  const count = Math.min(body.count, leaseCap(lane, pace, client), qualification ? auditBatchLimit(env) : MAX_LEASE);
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare("UPDATE leases SET state='expired' WHERE state='active' AND expires_at<=?").bind(now).run();
  const existing = await env.DB.prepare(
    "SELECT * FROM leases WHERE account_id=? AND lane=? AND state='active' AND expires_at>? ORDER BY expires_at DESC LIMIT 1"
  ).bind(account, lane, now).first();
  if (existing) {
    const held = (await env.DB.prepare(
      `SELECT l.* FROM locations l JOIN lease_items i ON i.location_id=l.id WHERE i.lease_id=? ORDER BY l.id`
    ).bind(existing.id).all()).results || [];
    if (lane === "object" && !await objectCoverageComplete(env.DB, held)) return error("object_coverage_required", 409);
    if (references && held.some((row) => !references.covers(row))) return error("scene_reference_not_approved", 409);
    if (qualification && existing.scene_qualification_id !== qualification.id) return error("scene_qualification_changed", 409);
    const payload = [];
    for (const row of held) payload.push(await leaseItemFromRow(row, row.generation || 1));
    const work = await workStatus(env, account, lane);
    return json({
      leaseId: existing.id,
      expiresAt: existing.expires_at,
      pace: existing.pace || pace,
      resourceBudget: qualification ? "qualified-runtime" : { slow: 1, medium: "cpu/2", max: "all-cores" }[existing.pace || pace],
      items: payload,
      resumed: true,
      work,
    });
  }
  const remaining = lane === "object" ? null : await env.DB.prepare(
    "SELECT 1 AS ok FROM pose_catalog WHERE lane=? AND next_row < row_count LIMIT 1"
  ).bind(lane).first();
  // Catalog materialization advances a cursor outside a transaction. Until a
  // trusted audit service exists, only an operator-prepared approved pool runs.
  if (references && remaining) return error("scene_reference_pool_unprepared", 409);
  let items = [];
  let activeShard = null;
  if (remaining) {
    for (let hops = 0; hops < 32 && items.length < count; hops += 1) {
      const assigned = await assignCatalogShard(env, account, lane, now, hops === 0 ? requestedPart : null);
      if (assigned && assigned.error) return error(assigned.error, assigned.error === "part_taken" ? 409 : 400);
      if (!assigned) break;
      activeShard = assigned;
      const need = count - items.length;
      let chunk = await pendingForShard(env, lane, assigned.shard_id, now, need);
      if (chunk.length < need) {
        const extra = await materializeCatalog(env, lane, need - chunk.length, now, assigned);
        const seen = new Set(chunk.map((row) => row.id));
        chunk = chunk.concat(extra.filter((row) => !seen.has(row.id)));
      }
      if (!chunk.length) {
        await releaseExhaustedShard(env, lane, assigned.shard_id);
        continue;
      }
      const seen = new Set(items.map((row) => row.id));
      for (const row of chunk) {
        if (seen.has(row.id)) continue;
        items.push(row);
        seen.add(row.id);
        if (items.length >= count) break;
      }
      const current = await env.DB.prepare(
        "SELECT * FROM pose_catalog WHERE lane=? AND shard_id=?"
      ).bind(lane, assigned.shard_id).first();
      if (current) activeShard = current;
    }
  } else {
    items = await pendingShared(env, lane, now, count);
  }
  if (!items.length) return error("no_available_work", 409);
  if (references && items.some((row) => !references.covers(row))) return error("scene_reference_not_approved", 409);
  const leaseId = randomHex(16);
  const expires = now + (client === "cli" ? 6 * 60 * 60 : LEASE_SECONDS);
  const statements = [
    env.DB.prepare("INSERT INTO leases (id, account_id, lane, expires_at, state, generation, pace, scene_qualification_id) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)").bind(
      leaseId, account, lane, expires, (items[0].generation || 0) + 1, pace, qualification?.id || null
    ),
  ];
  const payload = [];
  for (const row of items) {
    const generation = (row.generation || 0) + 1;
    statements.push(env.DB.prepare("INSERT INTO lease_items (lease_id, location_id) VALUES (?, ?)").bind(leaseId, row.id));
    statements.push(env.DB.prepare("UPDATE locations SET state='leased', active_lease=?, lease_until=?, generation=? WHERE id=?").bind(leaseId, expires, generation, row.id));
    payload.push(await leaseItemFromRow(row, generation));
  }
  await env.DB.batch(statements);
  const work = activeShard
    ? await workFromShard(env, lane, activeShard)
    : await workStatus(env, account, lane);
  return json({
    leaseId,
    expiresAt: expires,
    pace,
    resourceBudget: qualification ? "qualified-runtime" : { slow: 1, medium: "cpu/2", max: "all-cores" }[pace],
    items: payload,
    work,
  });
}

function locationsToRecompute(items) {
  const audit = new Set();
  let streetAudit = null;
  for (const row of items) {
    if (usesStreetViews(row.asset_id)) {
      if (streetAudit == null) streetAudit = row.id;
    } else {
      audit.add(row.id);
    }
  }
  if (streetAudit != null) audit.add(streetAudit);
  return audit;
}

async function releaseLease(env, account, body) {
  const leaseId = body.leaseId;
  if (typeof leaseId !== "string" || !leaseId) return error("invalid_lease_request");
  const leaseRow = await env.DB.prepare("SELECT * FROM leases WHERE id=? AND account_id=?").bind(leaseId, account).first();
  if (!leaseRow) return error("unknown_lease", 404);
  if (leaseRow.state === "submitted") return json({ released: 0, alreadySubmitted: true, leaseId });
  const skip = body.skip === true;
  const released = skip
    ? await env.DB.prepare(
      "UPDATE locations SET state='pending', active_lease=NULL, lease_until=NULL, queue_state='skipped' WHERE active_lease=? AND state='leased'"
    ).bind(leaseId).run()
    : await env.DB.prepare(
      "UPDATE locations SET state='pending', active_lease=NULL, lease_until=NULL WHERE active_lease=? AND state='leased'"
    ).bind(leaseId).run();
  await env.DB.prepare("UPDATE leases SET state='expired' WHERE id=? AND state='active'").bind(leaseId).run();
  return json({ released: released?.meta?.changes || 0, leaseId, skipped: skip });
}

async function renewLease(env, account, body) {
  const leaseId = body.leaseId;
  if (typeof leaseId !== "string" || !leaseId) return error("invalid_lease_request");
  const now = Math.floor(Date.now() / 1000);
  const leaseRow = await env.DB.prepare("SELECT * FROM leases WHERE id=? AND account_id=?").bind(leaseId, account).first();
  if (!leaseRow) return error("unknown_lease", 404);
  if (leaseRow.state === "submitted") return json({ renewed: false, alreadySubmitted: true, leaseId });
  const held = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM locations WHERE active_lease=? AND state!='published'"
  ).bind(leaseId).first();
  if (!held || !held.n) return error("expired_lease", 409);
  const expires = now + 6 * 60 * 60;
  await env.DB.batch([
    env.DB.prepare("UPDATE leases SET state='active', expires_at=? WHERE id=?").bind(expires, leaseId),
    env.DB.prepare(
      "UPDATE locations SET state='leased', lease_until=? WHERE active_lease=? AND state!='published'"
    ).bind(expires, leaseId),
  ]);
  return json({ renewed: true, expiresAt: expires, leaseId });
}

async function submitFourView(env, account, leaseId, items, supplied, now) {
  if (verifierConfigured(env)) {
    const verified = [];
    for (const row of items) {
      if (row.lane !== "scene" || row.state !== "leased" || row.active_lease !== leaseId) return error("lease_lost", 409);
      const payload = supplied.get(row.id);
      if (!payload || !validFourViewRecord(payload.embedding)) return error("verification_failed", 422);
      const digest = await sha256Hex(payload.embedding);
      if (!equalHex(payload.digest, digest)) return error("verification_failed", 422);
      verified.push({ row, embedding: payload.embedding, digest });
    }
    return json(await stageScene(env, account, leaseId, verified, now));
  }
  const references = await loadSceneReferences(env);
  if (!references) return error("scene_verification_unavailable", 503);
  if (!env.INDEX) return error("index_unavailable", 503);
  const verified = [];
  for (const row of items) {
    if (row.lane !== "scene") return error("verification_failed", 422);
    if (row.state !== "leased" || row.active_lease !== leaseId) return error("lease_lost", 409);
    const payload = supplied.get(row.id);
    const embedding = payload.embedding;
    if (!validFourViewRecord(embedding)) return error("verification_failed", 422);
    const digest = await sha256Hex(embedding);
    if (!equalHex(payload.digest, digest)) return error("verification_failed", 422);
    if (!references.verify(row, digest)) return error("scene_reference_not_approved", 422);
    if (payload.embeddingSha256 && !equalHex(payload.embeddingSha256, digest)) return error("verification_failed", 422);
    verified.push({ row, embedding, digest });
  }
  const blob = new Uint8Array(verified.length * FOUR_VIEW_BYTES);
  verified.forEach((item, index) => blob.set(item.embedding, index * FOUR_VIEW_BYTES));
  const key = `four-view-v4/${leaseId}.i8`;
  await writeSceneArtifact(env, account, leaseId, key, blob, now);
  const earned = items.reduce((sum, row) => sum + UNITS[row.lane], 0);
  const statements = [
    env.DB.prepare("UPDATE leases SET state='submitted' WHERE id=?").bind(leaseId),
    env.DB.prepare("UPDATE accounts SET units=units+? WHERE id=?").bind(earned, account),
    env.DB.prepare("INSERT INTO ledger (account_id, units, reason, reference) VALUES (?, ?, 'verified_work', ?)").bind(account, earned, `lease:${leaseId}`),
  ];
  for (const item of verified) {
    statements.push(env.DB.prepare(
      "UPDATE locations SET state='published', active_lease=NULL, lease_until=NULL, output_sha256=?, contributor_id=? WHERE id=?"
    ).bind(item.digest, account, item.row.id));
    statements.push(env.DB.prepare(
      `INSERT INTO published_index
        (location_id, index_text, output_sha256, published_at, embedding, four_view_sha256, four_view_key)
       VALUES (?, '', ?, ?, NULL, ?, ?)`
    ).bind(item.row.id, item.digest, now, item.digest, key));
  }
  await env.DB.batch(statements);
  return json({ accepted: items.length, unitsEarned: earned, replayed: false, segments: [] });
}

async function submitObjectIndex(env, account, leaseId, items, supplied, objectIndex, now, objectPrototype = false) {
  if (!objectPrototype) return error("object_verification_unavailable", 503);
  if (!env.INDEX) return error("index_unavailable", 503);
  if (!objectIndex || typeof objectIndex !== "object") return error("object_index_required", 422);
  if (items.some((row) => row.lane !== "object" || row.state !== "leased" || row.active_lease !== leaseId)) {
    return error("lease_lost", 409);
  }
  if (!await objectCoverageComplete(env.DB, items)) return error("object_coverage_required", 409);
  let sourceTsv;
  try {
    sourceTsv = base64ToBytes(objectIndex.sourceTsv);
  } catch {
    return error("verification_failed", 422);
  }
  const encoded = objectIndex.files;
  if (!(sourceTsv instanceof Uint8Array) || !encoded || typeof encoded !== "object") return error("verification_failed", 422);
  const files = {};
  let totalBytes = 0;
  for (const [name, value] of Object.entries(encoded)) {
    let bytes;
    try {
      bytes = base64ToBytes(value);
    } catch {
      return error("verification_failed", 422);
    }
    totalBytes += bytes.length;
    if (totalBytes > 32000000) return error("verification_failed", 422);
    files[name] = bytes;
  }
  const leaseItems = items.map((row) => ({
    locationId: row.id,
    panoId: row.asset_id,
    lat: row.lat,
    lng: row.lon,
  }));
  let expected;
  try {
    expected = await validateObjectIndex(objectIndex.manifest, files, sourceTsv, leaseItems, leaseId);
  } catch {
    return error("verification_failed", 422);
  }
  if (expected.length !== items.length) return error("incomplete_submission");
  for (const item of expected) {
    const payload = supplied.get(item.locationId);
    if (!payload || payload.model !== OBJECT_INDEX_MODEL || !equalHex(payload.digest, item.outputSha256)) {
      return error("verification_failed", 422);
    }
  }
  const prefix = `object-index-v4/${leaseId}/`;
  await env.INDEX.put(`${prefix}manifest.json`, JSON.stringify({ ...objectIndex.manifest, sourceTsv: "locations.tsv" }));
  await env.INDEX.put(`${prefix}locations.tsv`, sourceTsv);
  for (const [name, bytes] of Object.entries(files)) {
    await env.INDEX.put(`${prefix}${name}`, bytes);
  }
  const earned = items.reduce((sum, row) => sum + UNITS[row.lane], 0);
  const statements = [
    env.DB.prepare("UPDATE leases SET state='submitted' WHERE id=?").bind(leaseId),
    env.DB.prepare("UPDATE accounts SET units=units+? WHERE id=?").bind(earned, account),
    env.DB.prepare("INSERT INTO ledger (account_id, units, reason, reference) VALUES (?, ?, 'verified_work', ?)").bind(account, earned, `lease:${leaseId}`),
  ];
  for (const item of expected) {
    statements.push(env.DB.prepare(
      "UPDATE locations SET state='published', active_lease=NULL, lease_until=NULL, output_sha256=?, contributor_id=? WHERE id=?"
    ).bind(item.outputSha256, account, item.locationId));
    statements.push(env.DB.prepare(
      `INSERT INTO published_index
        (location_id, index_text, output_sha256, published_at, embedding, object_index_sha256, object_index_key)
       VALUES (?, '', ?, ?, NULL, ?, ?)`
    ).bind(item.locationId, item.outputSha256, now, objectIndex.manifest.sourceSha256, prefix));
  }
  await env.DB.batch(statements);
  return json({ accepted: items.length, unitsEarned: earned, replayed: false, segments: [] });
}

async function submit(env, account, body, objectPrototype = false) {
  const leaseId = body.leaseId;
  const outputs = body.outputs;
  if (typeof leaseId !== "string" || !Array.isArray(outputs) || outputs.length > MAX_LEASE) return error("invalid_submission");
  const now = Math.floor(Date.now() / 1000);
  const leaseRow = await env.DB.prepare("SELECT * FROM leases WHERE id=? AND account_id=?").bind(leaseId, account).first();
  if (!leaseRow) return error("unknown_lease", 404);
  if (leaseRow.state === "submitted") {
    const accepted = await env.DB.prepare("SELECT COUNT(*) AS n FROM lease_items WHERE lease_id=?").bind(leaseId).first();
    return json({ accepted: accepted?.n || 0, unitsEarned: 0, replayed: true });
  }
  if (leaseRow.state !== "active" || leaseRow.expires_at <= now) return error("expired_lease", 409);
  const items = (await env.DB.prepare(
    `SELECT l.* FROM locations l JOIN lease_items i ON i.location_id=l.id WHERE i.lease_id=? ORDER BY l.id`
  ).bind(leaseId).all()).results || [];
  const supplied = new Map();
  for (const output of outputs) {
    if (!output || typeof output.locationId !== "number") return error("invalid_submission");
    const digest = output.outputSha256;
    if (supplied.has(output.locationId) || typeof digest !== "string" || digest.length !== 64) return error("invalid_submission");
    let embedding = output.embedding;
    if (typeof embedding === "string") embedding = base64ToBytes(embedding);
    supplied.set(output.locationId, { digest, embedding, embeddingSha256: output.embeddingSha256, model: output.model });
  }
  if (supplied.size !== items.length || items.some((row) => !supplied.has(row.id))) return error("incomplete_submission");
  if (leaseRow.lane === "object" || items.some((row) => row.lane === "object")) {
    return submitObjectIndex(env, account, leaseId, items, supplied, body.objectIndex, now, objectPrototype);
  }
  const suppliedModels = [...supplied.values()].map((item) => item.model);
  if (suppliedModels.includes(FOUR_VIEW_MODEL)) {
    if (!suppliedModels.every((model) => model === FOUR_VIEW_MODEL)) return error("invalid_submission");
    return submitFourView(env, account, leaseId, items, supplied, now);
  }
  // Public scene work cannot downgrade to the prototype extractor to bypass
  // independently approved reference verification.
  if (items.some((row) => row.lane === "scene")) return error("unsupported_model", 422);
  const audit = locationsToRecompute(items);
  const verified = [];
  for (const row of items) {
    if (row.state !== "leased" || row.active_lease !== leaseId) return error("lease_lost", 409);
    const payload = supplied.get(row.id);
    const recompute = audit.has(row.id);
    let embedding;
    if (recompute) {
      let faces;
      try {
        faces = await locationFaces({
          panoId: row.asset_id,
          assetId: row.asset_id,
          capture: row.capture,
          lane: row.lane,
          model: row.model,
          heading: row.heading || 0,
          pitch: row.pitch || 0,
          zoom: row.zoom || 0,
        });
      } catch (err) {
        return viewFailure(err) || error("verification_failed", 422);
      }
      embedding = embeddingFor(row.lane, faces);
    } else {
      embedding = payload.embedding;
      if (!embedding || embedding.length !== (row.lane === "object" ? OBJECT_PROPOSALS * OBJECT_DIM : SCENE_DIM)) return error("verification_failed", 422);
    }
    const digest = await outputDigest(row.asset_id, row.capture, row.lane, row.model, embedding);
    if (!equalHex(payload.digest, digest)) return error("verification_failed", 422);
    if (payload.embeddingSha256 && !equalHex(payload.embeddingSha256, await sha256Hex(embedding))) return error("verification_failed", 422);
    if (recompute && payload.embedding && bytesToHex(payload.embedding) !== bytesToHex(embedding)) return error("verification_failed", 422);
    verified.push({ row, embedding, digest });
  }
  const earned = items.reduce((sum, row) => sum + UNITS[row.lane], 0);
  const statements = [
    env.DB.prepare("UPDATE leases SET state='submitted' WHERE id=?").bind(leaseId),
    env.DB.prepare("UPDATE accounts SET units=units+? WHERE id=?").bind(earned, account),
    env.DB.prepare("INSERT INTO ledger (account_id, units, reason, reference) VALUES (?, ?, 'verified_work', ?)").bind(account, earned, `lease:${leaseId}`),
  ];
  for (const item of verified) {
    statements.push(env.DB.prepare(
      "UPDATE locations SET state='published', active_lease=NULL, lease_until=NULL, output_sha256=?, contributor_id=? WHERE id=?"
    ).bind(item.digest, account, item.row.id));
    statements.push(env.DB.prepare(
      "INSERT INTO published_index (location_id, index_text, output_sha256, published_at, embedding) VALUES (?, '', ?, ?, ?)"
    ).bind(item.row.id, item.digest, now, bytesToHex(item.embedding)));
  }
  await env.DB.batch(statements);
  try {
    await sealSearchShard(env, leaseId, leaseRow.lane, verified);
  } catch {
    // Index files are for local search. A failed copy must not un-publish credited work.
  }
  return json({ accepted: items.length, unitsEarned: earned, replayed: false, segments: [] });
}

function canonicalizeCountry(name) {
  if (name === "United States" || name === "United States of America") return "USA";
  return name;
}

function padBytes(text, size) {
  const out = new Uint8Array(size);
  out.set(encodeUtf8(String(text || "")).subarray(0, size));
  return out;
}

function packPose(row) {
  const bytes = new Uint8Array(176);
  const view = new DataView(bytes.buffer);
  view.setBigUint64(0, BigInt(row.id || 0), true);
  view.setFloat64(8, Number(row.lat || 0), true);
  view.setFloat64(16, Number(row.lon || 0), true);
  view.setFloat64(24, Number(row.heading || 0), true);
  view.setFloat64(32, Number(row.pitch || 0), true);
  view.setFloat64(40, Number(row.zoom || 0), true);
  bytes.set(padBytes(row.asset_id, 64), 48);
  bytes.set(padBytes(row.capture, 16), 112);
  bytes.set(padBytes(canonicalizeCountry(row.country || ""), 32), 128);
  bytes.set(padBytes(row.camera_generation || "", 16), 160);
  return bytes;
}

async function sealSearchShard(env, leaseId, lane, verified) {
  if (!env.INDEX || !verified.length) return;
  const embedSize = lane === "object" ? OBJECT_PROPOSALS * OBJECT_DIM : SCENE_DIM;
  const recordSize = 176 + embedSize;
  const bytes = new Uint8Array(16 + verified.length * recordSize);
  const view = new DataView(bytes.buffer);
  bytes.set(encodeUtf8("VCIDX001").subarray(0, 8), 0);
  view.setUint32(8, verified.length, true);
  view.setUint32(12, embedSize, true);
  let offset = 16;
  for (const item of verified) {
    bytes.set(packPose(item.row), offset);
    bytes.set(item.embedding, offset + 176);
    offset += recordSize;
  }
  const key = `search-index/${lane}/${leaseId}.bin`;
  await env.INDEX.put(key, bytes);
  await env.DB.prepare(
    "INSERT OR REPLACE INTO index_shards (r2_key, lane, location_count, bytes, sha256, created_at) VALUES (?, ?, ?, ?, ?, ?)"
  ).bind(key, lane, verified.length, bytes.length, await sha256Hex(bytes), Math.floor(Date.now() / 1000)).run();
}


function normalizeFilters(body) {
  const allGenerations = ["badcam", "gen1", "gen2", "gen3", "gen4", "trekker"];
  let mode = ["all", "include", "exclude"].includes(body.countryFilterMode) ? body.countryFilterMode : "all";
  const countries = Array.isArray(body.countries)
    ? [...new Set(body.countries.filter((item) => typeof item === "string" && item.trim()).map((item) => canonicalizeCountry(item.trim())))].sort()
    : [];
  let generations = Array.isArray(body.cameraGenerations)
    ? [...new Set(body.cameraGenerations.filter((item) => allGenerations.includes(item)))]
    : [];
  if (!generations.length || generations.length === allGenerations.length) generations = [];
  if (mode !== "include" && (mode === "all" || !countries.length)) {
    mode = "all";
  }
  return { mode, countries, generations };
}


function parseExcludeMap(map) {
  if (map == null) return [];
  if (typeof map !== "object") return { error: "invalid_mma_map" };
  const coordinates = Array.isArray(map)
    ? map
    : Array.isArray(map?.customCoordinates)
      ? map.customCoordinates
      : Array.isArray(map?.locations)
        ? map.locations
        : Array.isArray(map?.coordinates)
          ? map.coordinates
          : [];
  const points = [];
  for (const row of coordinates) {
    if (!row || typeof row !== "object") continue;
    const panoId = String(row.panoId || row.pano_id || row.pano || "").trim();
    if (panoId.includes("maps.googleapis.com") || panoId.startsWith("http")) return { error: "imagery_url_forbidden" };
    const lat = Number(row.lat);
    const lng = Number(row.lng ?? row.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    points.push({ lat, lng, panoId });
    if (points.length >= 10000) break;
  }
  return points;
}

function haversineMeters(lat1, lon1, lat2, lon2) {
  const radius = 6371000;
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dphi = ((lat2 - lat1) * Math.PI) / 180;
  const dlmb = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dphi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dlmb / 2) ** 2;
  return 2 * radius * Math.asin(Math.min(1, Math.sqrt(a)));
}

function evenlySample(values, limit) {
  if (values.length <= limit) return values;
  if (limit <= 1) return values.slice(0, 1);
  return Array.from({ length: limit }, (_, index) => {
    const fraction = index / (limit - 1);
    return values[Math.round(fraction * (values.length - 1))];
  });
}

function parseQueryMap(map) {
  const coordinates = Array.isArray(map?.customCoordinates)
    ? map.customCoordinates
    : Array.isArray(map?.locations)
      ? map.locations
      : Array.isArray(map?.coordinates)
        ? map.coordinates
        : Array.isArray(map)
          ? map
          : [];
  if (!coordinates.length) return null;
  const examples = [];
  const seen = new Set();
  for (const row of coordinates) {
    if (!row || typeof row !== "object") continue;
    const panoId = String(row.panoId || row.pano_id || row.pano || "").trim();
    if (!panoId) continue;
    if (panoId.includes("maps.googleapis.com") || panoId.startsWith("http")) return { error: "imagery_url_forbidden" };
    const heading = Number(row.heading) || 0;
    const pitch = Number(row.pitch) || 0;
    const zoom = Number(row.zoom) || 0;
    const key = `${panoId}|${heading}|${pitch}|${zoom}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const extra = row.extra && typeof row.extra === "object" ? row.extra : {};
    examples.push({
      panoId,
      lat: Number(row.lat) || 0,
      lng: Number(row.lng ?? row.lon) || 0,
      heading,
      pitch,
      zoom,
      capture: typeof extra.panoDate === "string" && extra.panoDate ? extra.panoDate : "unknown",
    });
  }
  const sampled = evenlySample(examples, 100);
  if (!sampled.length) return null;
  return sampled;
}


async function views(request) {
  const url = new URL(request.url);
  const pano = (url.searchParams.get("pano") || url.searchParams.get("panoId") || "").trim();
  if (pano.length < 4 || pano.length > 80) return error("invalid_pano_id");
  if (pano.includes("maps.googleapis.com") || pano.startsWith("http")) return error("imagery_url_forbidden");
  const lane = url.searchParams.get("lane") || "scene";
  if (!UNITS[lane]) return error("invalid_lane");
  const heading = Number(url.searchParams.get("heading") || 0);
  const pitch = Number(url.searchParams.get("pitch") || 0);
  const zoom = Number(url.searchParams.get("zoom") || 0);
  if (![heading, pitch, zoom].every(Number.isFinite)) return error("invalid_pose");
  const capture = url.searchParams.get("capture") || "unknown";
  try {
    const faces = await locationFaces({
      panoId: pano,
      assetId: pano,
      capture,
      lane,
      model: MODEL_ID,
      heading,
      pitch,
      zoom,
    });
    return json({
      faces: bytesToBase64(faces),
      persistImagery: false,
      viewStrategy: usesStreetViews(pano) ? "vision-pano-v1" : "identity-seed",
    });
  } catch (err) {
    return viewFailure(err) || error("view_unavailable", 422);
  }
}


async function search(env, account, body, objectPrototype = false) {
  if (body.accountId !== account) return error("account_changed", 409);
  if (body.execute === "local") return error("online_search_required", 410);
  if (body.lane !== undefined && !["scene", "object"].includes(body.lane)) return error("invalid_query");
  const lane = body.lane || "scene";
  const prompt = parsePrompt(body.prompt);
  if (prompt === null) return error("invalid_query");
  const parsed = body.queryMap == null ? null : parseQueryMap(body.queryMap);
  if (parsed?.error) return error(parsed.error);
  const examples = Array.isArray(parsed) ? parsed : [];
  if ((!examples.length && !prompt) || (lane === "object" && examples.length)) return error("invalid_query");
  if (examples.some(item => !usesStreetViews(item.panoId)
      || ![item.lat, item.lng, item.heading, item.pitch, item.zoom].every(Number.isFinite)
      || Math.abs(item.lat) > 90 || Math.abs(item.lng) > 180 || Math.abs(item.pitch) > 90
      || item.zoom < 0 || item.zoom > 5)) return error("invalid_query");
  const excluded = parseExcludeMap(body.excludeMap);
  if (excluded?.error) return error(excluded.error);
  if (excluded.some(item => Math.abs(item.lat) > 90 || Math.abs(item.lng) > 180)) return error("invalid_query");
  const filters = normalizeFilters(body);
  filters.generations.sort();
  if (filters.mode === "all") filters.countries = [];
  if (filters.mode === "include" && !filters.countries.length) return error("invalid_country_filter");
  if (lane === "object") {
    if (filters.generations.length && !filters.generations.includes("gen4")) return error("invalid_camera_filter");
    filters.generations = ["gen4"];
  }
  if (body.minimumGlobalLocation != null
      && (!Number.isSafeInteger(body.minimumGlobalLocation) || body.minimumGlobalLocation < 0))
    return error("invalid_query");
  const queryName = typeof body.outputName === "string" && body.outputName.trim()
    ? body.outputName.trim() : (typeof body.queryMap?.name === "string" && body.queryMap.name.trim()
      ? body.queryMap.name.trim() : prompt || "VISION Community");
  if (queryName.length > 200) return error("invalid_query");
  const query = {
    lane, prompt, examples, excluded, queryName,
    descriptionWeight: snapDescriptionWeight(body.descriptionWeight, examples.length > 0, Boolean(prompt)),
    viewDirection: normalizeViewDirection(body.viewDirection, lane),
    resultCount: Math.min(10000, Math.max(1, Number.isInteger(body.resultCount) ? body.resultCount : 200)),
    maxPerCountry: Math.min(10000, Math.max(1, Number.isInteger(body.maxPerCountry) ? body.maxPerCountry : 25)),
    filters, objectConfidence: ["balanced", "precise", "highRecall"].includes(body.objectConfidence) ? body.objectConfidence : "balanced",
    rejectRoadNames: body.rejectRoadNames === true, minimumGlobalLocation: body.minimumGlobalLocation ?? null,
  };
  try { return json(await onlineSearch(env, account, body.idempotencyKey, query,
    { allowNew: lane !== "object" || objectPrototype })); }
  catch (failure) {
    if (failure instanceof SearchError) return error(failure.code, failure.status);
    throw failure;
  }
}


const API_METHODS = new Map([
  ["/api/capabilities","GET"],["/api/status","GET"],["/api/me","GET"],["/api/views","GET"],
  ["/api/scene-qualifications","GET,POST"],["/api/object-qualifications","GET,POST"],["/api/accounts","POST"],["/api/recovery","POST"],
  ["/api/account/delete","POST"],["/api/scene-audits","POST"],["/api/leases/release","POST"],
  ["/api/leases/renew","POST"],["/api/leases","POST"],["/api/submissions","POST"],["/api/searches","POST"]
]);
export default {
  async scheduled(_event, env) {
    if (env.RESTORE_MAINTENANCE !== undefined && env.RESTORE_MAINTENANCE !== "0") return;
    if (!env.DB || !env.INDEX) return;
    // No request or scheduled handler installs/upgrades database structures.
    await requireSchema(env);
    await cleanupAccountArtifacts(env, null, 64);
    await archiveAccountDeletionReceipts(env);
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/") && env.RESTORE_MAINTENANCE !== undefined
        && env.RESTORE_MAINTENANCE !== "0") return error("service_maintenance", 503, { "retry-after": "60" });
    if (INDEX_DOWNLOAD_ROUTES.has(url.pathname)) return error("online_search_required", 410);
    if (!url.pathname.startsWith("/api/")) {
      const response = await env.ASSETS.fetch(request);
      const headers = new Headers(response.headers);
      headers.set("x-content-type-options", "nosniff");
      headers.set("referrer-policy", "no-referrer");
      headers.set("x-frame-options", "DENY");
      headers.set("x-robots-tag", "noindex, nofollow");
      headers.set("permissions-policy", "camera=(), microphone=(), geolocation=()");
      headers.set("content-security-policy", HEADERS["content-security-policy"]);
      return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
    }
    // Reject unsupported routes/methods before touching a database or body.
    if (!API_METHODS.get(url.pathname)?.split(",").includes(request.method)) return error("not_found",404);
    if (!sameOrigin(request)) return error("cross_origin_request",403);
    try {
      await ingressLimit(env,request);
      const anonymous=["/api/capabilities","/api/status","/api/accounts","/api/recovery"].includes(url.pathname);
      if (anonymous) await accountLimit(env,request,null);
      if (!env.DB) return error("control_plane_unprovisioned",503);
      await requireSchema(env);
      if (url.pathname === "/api/capabilities") {
        const scene=verifierConfigured(env) ? pipelineCapabilities(env) : sceneCapabilities(await loadSceneReferences(env));
        return json({...scene,...objectCapabilities()});
      }
      if (url.pathname === "/api/status") return json(await status(env));
      const account=anonymous ? null : await accountId(env,request);
      // Deleted accounts may still replay their own saved deletion receipt.
      if (!anonymous && !account && url.pathname!=="/api/account/delete") return error("unauthorized",401);
      if (!anonymous) await accountLimit(env,request,account);
      if (url.pathname === "/api/object-qualifications") {
        // This contract is recognized but has no trusted native provider yet.
        // Refuse before reading canary bytes or touching qualification state.
        if (request.body) void request.body.cancel().catch(() => {});
        return error("object_verification_unavailable",503,{"retry-after":"1800"});
      }
      if (url.pathname === "/api/me") return json(await status(env, account, { lite: url.searchParams.get("lite") === "1" }));
      if (url.pathname === "/api/scene-qualifications" && request.method==="GET") {
        if (!verifierConfigured(env)) return error("scene_verification_unavailable",503);
        return json(await qualificationStatus(env,account,url.searchParams.get("profileId")));
      }
      if (url.pathname === "/api/views") {
        await viewLimit(env,account);
        return views(request);
      }
      const body=await readRequestJson(request);
      if (url.pathname === "/api/accounts") return await createAccount(env,request);
      if (url.pathname === "/api/recovery") return await recover(env,request,body);
      if (url.pathname === "/api/account/delete") {
        const result=await deleteAccount(env,account,body);
        await cleanupAccountArtifacts(env,body.accountId);
        return json(result,200,{"set-cookie":cookie("",request)+"; Max-Age=0"});
      }
      if (url.pathname === "/api/scene-qualifications") {
        if (!verifierConfigured(env)) return error("scene_verification_unavailable",503);
        return json(await qualifyDevice(env,account,body,validFourViewRecord));
      }
      if (url.pathname === "/api/scene-audits") return json(await auditScene(env,account,body.submissionId));
      if (url.pathname === "/api/leases/release") return await releaseLease(env,account,body);
      if (url.pathname === "/api/leases/renew") return await renewLease(env,account,body);
      const objectPrototype=localObjectPrototype(request,env);
      if (url.pathname === "/api/leases") return await lease(env,account,body,objectPrototype);
      if (url.pathname === "/api/submissions") return await submit(env,account,body,objectPrototype);
      if (url.pathname === "/api/searches") return await search(env,account,body,objectPrototype);
      return error("not_found",404);
    } catch(err) {
      if (err instanceof ApiLimitError) return error(err.message,err.status,{"retry-after":"60"});
      if (err?.message==="schema_update_required") return error("schema_update_required",503,{"retry-after":"60"});
      return viewFailure(err) || error("internal_error",500);
    }
  }
};
