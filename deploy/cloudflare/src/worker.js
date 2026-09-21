import {
  MODEL_ID, SEARCH_COST, SITE_SEARCH_CAP, UNITS, LEASE_SECONDS, MAX_LEASE, RECOVERY_PEPPER, SCENE_DIM,
  OBJECT_PROPOSALS, OBJECT_DIM,
  sha256Hex, encodeUtf8, equalHex, seedBytes, renderFacesFromSeed, embeddingFor,
  outputDigest, maxRegionCosine, meanEmbeddings, base64ToBytes, bytesToHex,
  bytesToBase64, randomHex, randomToken, bestSceneView, normalizeViewDirection,
  viewOffsetsFor, wrapHeading,
} from "./model.js";
import {
  QUERY_VIEW_CAP, renderLocationFaces, leaseCap, usesStreetViews,
} from "./pano.js";
import { SEED_LOCATIONS } from "./seed.js";

const SCHEMA = `
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
  units INTEGER NOT NULL DEFAULT 0 CHECK (units >= 0), recovery_hash TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT NOT NULL, capture TEXT NOT NULL,
  lane TEXT NOT NULL, model TEXT NOT NULL, label TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'pending', active_lease TEXT, lease_until INTEGER,
  output_sha256 TEXT, contributor_id TEXT, source TEXT, rights TEXT, attribution TEXT,
  lat REAL, lon REAL, heading REAL NOT NULL DEFAULT 0, pitch REAL NOT NULL DEFAULT 0,
  zoom REAL NOT NULL DEFAULT 0, country TEXT, camera_generation TEXT,
  generation INTEGER NOT NULL DEFAULT 0, queue_state TEXT NOT NULL DEFAULT 'pending',
  UNIQUE (asset_id, capture, lane, model)
);
CREATE INDEX IF NOT EXISTS locations_queue ON locations (lane, state, lease_until, id);
CREATE TABLE IF NOT EXISTS leases (
  id TEXT PRIMARY KEY, account_id TEXT NOT NULL, lane TEXT NOT NULL,
  expires_at INTEGER NOT NULL, state TEXT NOT NULL, generation INTEGER, pace TEXT
);
CREATE TABLE IF NOT EXISTS lease_items (
  lease_id TEXT NOT NULL, location_id INTEGER NOT NULL, PRIMARY KEY (lease_id, location_id)
);
CREATE TABLE IF NOT EXISTS published_index (
  location_id INTEGER PRIMARY KEY, index_text TEXT NOT NULL, output_sha256 TEXT NOT NULL,
  published_at INTEGER NOT NULL, embedding TEXT, segment_id TEXT
);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL, units INTEGER NOT NULL,
  reason TEXT NOT NULL, reference TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS searches (
  id TEXT PRIMARY KEY, account_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
  query TEXT NOT NULL, result_json TEXT NOT NULL, UNIQUE (account_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS pose_catalog (
  lane TEXT NOT NULL, shard_id INTEGER NOT NULL, r2_key TEXT NOT NULL,
  row_start INTEGER NOT NULL, row_count INTEGER NOT NULL, bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL, next_byte INTEGER NOT NULL DEFAULT 0, next_row INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (lane, shard_id)
);
CREATE TABLE IF NOT EXISTS index_shards (
  r2_key TEXT PRIMARY KEY, lane TEXT NOT NULL, location_count INTEGER NOT NULL,
  bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at INTEGER NOT NULL
);
`;

const HEADERS = {
  "content-type": "application/json",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
  "x-frame-options": "DENY",
  "x-robots-tag": "noindex, nofollow",
  "permissions-policy": "camera=(), microphone=(), geolocation=()",
  "content-security-policy":
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'",
};

async function locationFaces(location) {
  return renderLocationFaces(location, async () =>
    renderFacesFromSeed(await seedBytes(location.assetId || location.panoId, location.capture, location.lane, location.model || MODEL_ID))
  );
}

function json(value, status = 200, extra = {}) {
  return new Response(JSON.stringify(value), { status, headers: { ...HEADERS, ...extra } });
}

function error(code, status = 400) {
  return json({ error: code }, status);
}

function viewFailure(err) {
  const code = err && err.message;
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

async function ready(env) {
  for (const statement of SCHEMA.split(";").map((item) => item.trim()).filter(Boolean)) {
    await env.DB.prepare(statement).run();
  }
  await migratePoseCatalog(env);
  const count = await env.DB.prepare("SELECT COUNT(*) AS n FROM locations").first();
  if (!count || count.n > 0) return;
  const statements = SEED_LOCATIONS.map((row) =>
    env.DB.prepare(
      `INSERT OR IGNORE INTO locations
        (asset_id, capture, lane, model, label, source, rights, attribution, lat, lon, heading, pitch, zoom, country, camera_generation, queue_state)
       VALUES (?, ?, ?, ?, '', 'street-metadata', 'metadata-only-no-imagery', 'Panorama metadata only. Imagery is not stored.', ?, ?, ?, ?, ?, ?, ?, 'pending')`
    ).bind(row.panoId, row.capture, row.lane, MODEL_ID, row.lat, row.lng, row.heading, row.pitch, row.zoom, row.country, row.cameraGeneration)
  );
  await env.DB.batch(statements);
}

async function migratePoseCatalog(env) {
  const row = await env.DB.prepare("SELECT sql FROM sqlite_master WHERE name='pose_catalog'").first();
  if (!row?.sql || !row.sql.includes("r2_key TEXT NOT NULL UNIQUE")) return;
  await env.DB.prepare(`CREATE TABLE pose_catalog_v2 (
    lane TEXT NOT NULL, shard_id INTEGER NOT NULL, r2_key TEXT NOT NULL,
    row_start INTEGER NOT NULL, row_count INTEGER NOT NULL, bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL, next_byte INTEGER NOT NULL DEFAULT 0, next_row INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (lane, shard_id)
  )`).run();
  await env.DB.prepare("INSERT OR IGNORE INTO pose_catalog_v2 SELECT * FROM pose_catalog").run();
  await env.DB.prepare("DROP TABLE pose_catalog").run();
  await env.DB.prepare("ALTER TABLE pose_catalog_v2 RENAME TO pose_catalog").run();
}

async function accountId(env, request) {
  const token = tokenFrom(request);
  if (!token || token.length > 100) return null;
  const tokenHash = await sha256Hex(encodeUtf8(token));
  const row = await env.DB.prepare("SELECT id, token_hash FROM accounts WHERE token_hash=?").bind(tokenHash).first();
  if (!row || !equalHex(row.token_hash, tokenHash)) return null;
  return row.id;
}

async function status(env, account) {
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
  const countryRows = await env.DB.prepare(
    "SELECT DISTINCT country FROM locations WHERE country IS NOT NULL AND country != '' ORDER BY country"
  ).all();
  const generationRows = await env.DB.prepare(
    "SELECT DISTINCT camera_generation FROM locations WHERE camera_generation IS NOT NULL AND camera_generation != '' ORDER BY camera_generation"
  ).all();
  const result = {
    operational: true,
    demo: false,
    publicCorpus: false,
    ownerBypass: false,
    persistImagery: false,
    r2: await r2Status(env),
    searchCost: SEARCH_COST,
    searchBackend: (visual?.n || 0) <= SITE_SEARCH_CAP ? "d1-prototype" : "local",
    searchOnSite: (visual?.n || 0) <= SITE_SEARCH_CAP,
    model: MODEL_ID,
    visualPublished: visual?.n || 0,
    countries: [...new Set((countryRows.results || []).map((row) => canonicalizeCountry(row.country)).filter(Boolean))].sort(),
    cameraGenerations: (generationRows.results || []).map((row) => row.camera_generation),
    output: "map-making.app JSON",
    prototype: true,
    counts,
  };
  if (account) {
    const row = await env.DB.prepare("SELECT units FROM accounts WHERE id=?").bind(account).first();
    result.accountId = account;
    result.units = row?.units || 0;
    result.searchesAvailable = Math.floor(result.units / SEARCH_COST);
  }
  return result;
}

async function r2Status(env) {
  const status = {
    provisioned: Boolean(env.INDEX),
    bucket: env.INDEX ? "vision-community" : null,
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

async function materializeCatalog(env, lane, count, now) {
  const claimed = [];
  for (let attempt = 0; attempt < 32 && claimed.length < count; attempt += 1) {
    const shard = await env.DB.prepare(
      "SELECT * FROM pose_catalog WHERE lane=? AND next_row < row_count ORDER BY shard_id LIMIT 1"
    ).bind(lane).first();
    if (!shard) break;
    const needed = count - claimed.length;
    const slice = await readCatalogSlice(env, shard, needed);
    if (!slice.consumed) {
      await env.DB.prepare(
        "UPDATE pose_catalog SET next_row=row_count, next_byte=bytes WHERE lane=? AND shard_id=?"
      ).bind(lane, shard.shard_id).run();
      continue;
    }
    const moved = await env.DB.prepare(
      "UPDATE pose_catalog SET next_byte=next_byte+?, next_row=next_row+? WHERE lane=? AND shard_id=? AND next_byte=?"
    ).bind(slice.consumed, slice.jobs.length, lane, shard.shard_id, shard.next_byte).run();
    if (!moved.meta || moved.meta.changes !== 1) continue;
    for (const job of slice.jobs) {
      await env.DB.prepare(
        `INSERT OR IGNORE INTO locations
          (asset_id, capture, lane, model, label, source, rights, attribution, lat, lon, heading, pitch, zoom, country, camera_generation, queue_state)
         VALUES (?, ?, ?, ?, '', 'street-metadata', 'metadata-only-no-imagery', 'Panorama metadata only. Imagery is not stored.', ?, ?, ?, ?, ?, ?, ?, 'pending')`
      ).bind(
        job.assetId, job.capture, job.lane, job.model,
        job.lat, job.lon, job.heading, job.pitch, job.zoom, job.country, job.cameraGeneration
      ).run();
      const row = await env.DB.prepare(
        `SELECT id, asset_id, capture, lane, model, generation, attribution, lat, lon, heading, pitch, zoom, country, camera_generation, state, lease_until
         FROM locations WHERE asset_id=? AND capture=? AND lane=? AND model=?`
      ).bind(job.assetId, job.capture, job.lane, job.model).first();
      if (!row || row.state === "published") continue;
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
  const row = await env.DB.prepare("SELECT id FROM accounts WHERE recovery_hash=?").bind(recoveryHash).first();
  if (!row) return error("invalid_recovery", 401);
  const token = randomToken(32);
  const tokenHash = await sha256Hex(encodeUtf8(token));
  await env.DB.prepare("UPDATE accounts SET token_hash=? WHERE id=?").bind(tokenHash, row.id).run();
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

async function lease(env, account, body) {
  const lane = body.lane;
  const pace = body.pace || "medium";
  if (!UNITS[lane] || typeof body.count !== "number" || body.count < 1 || body.count > MAX_LEASE) return error("invalid_lease_request");
  if (!["slow", "medium", "max"].includes(pace)) return error("invalid_pace");
  const client = body.client === "cli" ? "cli" : "browser";
  const count = Math.min(body.count, leaseCap(lane, pace, client));
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare("UPDATE leases SET state='expired' WHERE state='active' AND expires_at<=?").bind(now).run();
  const existing = await env.DB.prepare(
    "SELECT * FROM leases WHERE account_id=? AND lane=? AND state='active' AND expires_at>? ORDER BY expires_at DESC LIMIT 1"
  ).bind(account, lane, now).first();
  if (existing) {
    const held = (await env.DB.prepare(
      `SELECT l.* FROM locations l JOIN lease_items i ON i.location_id=l.id WHERE i.lease_id=? ORDER BY l.id`
    ).bind(existing.id).all()).results || [];
    const payload = [];
    for (const row of held) payload.push(await leaseItemFromRow(row, row.generation || 1));
    return json({
      leaseId: existing.id,
      expiresAt: existing.expires_at,
      pace: existing.pace || pace,
      resourceBudget: { slow: 1, medium: "cpu/2", max: "all-cores" }[existing.pace || pace],
      items: payload,
      resumed: true,
    });
  }
  const rows = await env.DB.prepare(
    `SELECT id, asset_id, capture, lane, model, generation, attribution, lat, lon, heading, pitch, zoom, country, camera_generation
     FROM locations WHERE lane=? AND COALESCE(queue_state,'pending')='pending'
       AND asset_id NOT LIKE 'Prototype%' AND asset_id NOT LIKE 'synthetic:%' AND asset_id NOT LIKE 'CommunityPano%'
       AND (state='pending' OR (state='leased' AND lease_until<=?))
     ORDER BY id LIMIT ?`
  ).bind(lane, now, count).all();
  let items = rows.results || [];
  if (items.length < count) {
    const extra = await materializeCatalog(env, lane, count - items.length, now);
    const seen = new Set(items.map((row) => row.id));
    items = items.concat(extra.filter((row) => !seen.has(row.id))).slice(0, count);
  }
  if (!items.length) return error("no_available_work", 409);
  const leaseId = randomHex(16);
  const expires = now + LEASE_SECONDS;
  const statements = [
    env.DB.prepare("INSERT INTO leases (id, account_id, lane, expires_at, state, generation, pace) VALUES (?, ?, ?, ?, 'active', ?, ?)").bind(
      leaseId, account, lane, expires, (items[0].generation || 0) + 1, pace
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
  return json({
    leaseId,
    expiresAt: expires,
    pace,
    resourceBudget: { slow: 1, medium: "cpu/2", max: "all-cores" }[pace],
    items: payload,
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
  const released = await env.DB.prepare(
    "UPDATE locations SET state='pending', active_lease=NULL, lease_until=NULL WHERE active_lease=? AND state='leased'"
  ).bind(leaseId).run();
  await env.DB.prepare("UPDATE leases SET state='expired' WHERE id=? AND state='active'").bind(leaseId).run();
  return json({ released: released?.meta?.changes || 0, leaseId });
}

async function submit(env, account, body) {
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

async function requirePaidSearch(env, account, searchId) {
  if (typeof searchId !== "string" || !searchId) return null;
  return env.DB.prepare("SELECT id FROM searches WHERE id=? AND account_id=?").bind(searchId, account).first();
}

async function publishedSnapshot(env, account, url) {
  const paid = await requirePaidSearch(env, account, url.searchParams.get("searchId") || "");
  if (!paid) return error("unknown_search", 404);
  const lane = url.searchParams.get("lane") === "object" ? "object" : "scene";
  const after = Math.max(0, Number(url.searchParams.get("after") || 0) || 0);
  const limit = Math.min(500, Math.max(1, Number(url.searchParams.get("limit") || 250) || 250));
  const rows = (await env.DB.prepare(
    `SELECT i.location_id, i.embedding, l.asset_id, l.lat, l.lon, l.heading, l.pitch, l.zoom, l.country, l.camera_generation
     FROM published_index i JOIN locations l ON l.id=i.location_id
     WHERE i.embedding IS NOT NULL AND l.lane=? AND i.location_id>?
     ORDER BY i.location_id LIMIT ?`
  ).bind(lane, after, limit + 1).all()).results || [];
  const page = rows.slice(0, limit);
  return json({
    lane,
    locations: page.map((row) => ({
      locationId: row.location_id,
      panoId: row.asset_id,
      lat: row.lat || 0,
      lng: row.lon || 0,
      heading: row.heading || 0,
      pitch: row.pitch || 0,
      zoom: row.zoom || 0,
      country: canonicalizeCountry(row.country || ""),
      cameraGeneration: row.camera_generation || "",
      embedding: row.embedding,
    })),
    nextAfter: rows.length > limit ? page[page.length - 1].location_id : null,
  });
}

async function indexManifest(env, account, url) {
  const paid = await requirePaidSearch(env, account, url.searchParams.get("searchId") || "");
  if (!paid) return error("unknown_search", 404);
  const lane = url.searchParams.get("lane") === "object" ? "object" : "scene";
  const rows = (await env.DB.prepare(
    "SELECT r2_key, location_count, bytes, sha256 FROM index_shards WHERE lane=? ORDER BY r2_key"
  ).bind(lane).all()).results || [];
  return json({
    shards: rows.map((row) => ({
      key: row.r2_key,
      locationCount: row.location_count,
      bytes: row.bytes,
      sha256: row.sha256,
    })),
  });
}

async function indexShard(env, account, url) {
  const paid = await requirePaidSearch(env, account, url.searchParams.get("searchId") || "");
  if (!paid) return error("unknown_search", 404);
  const key = url.searchParams.get("key") || "";
  if (!key.startsWith("search-index/") || key.includes("..")) return error("unknown_search", 404);
  const row = await env.DB.prepare("SELECT r2_key FROM index_shards WHERE r2_key=?").bind(key).first();
  if (!row || !env.INDEX) return error("unknown_search", 404);
  const object = await env.INDEX.get(key);
  if (!object) return error("unknown_search", 404);
  return new Response(object.body, {
    headers: { ...HEADERS, "content-type": "application/octet-stream" },
  });
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

function acceptsHit(hit, filters) {
  if (filters.generations.length && !filters.generations.includes(hit.cameraGeneration)) return false;
  if (filters.mode === "include") return filters.countries.includes(hit.country);
  if (filters.mode === "exclude") return !filters.countries.includes(hit.country);
  return true;
}

function pruneNearby(hits) {
  const out = [];
  const seen = new Set();
  for (const hit of hits) {
    const pano = hit.panoId || "";
    if (pano && seen.has(pano)) continue;
    const tooClose = out.some((prior) => haversineMeters(hit.lat, hit.lng, prior.lat, prior.lng) < 100);
    if (tooClose) continue;
    if (pano) seen.add(pano);
    out.push(hit);
  }
  return out;
}

function excludeUsed(hits, excluded) {
  if (!excluded.length) return hits;
  return hits.filter((hit) => {
    const pano = hit.panoId || "";
    return !excluded.some((prior) => (
      (pano && pano === prior.panoId)
      || haversineMeters(hit.lat, hit.lng, prior.lat, prior.lng) < 25
    ));
  });
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

function capCountries(hits, resultCount, maxPerCountry) {
  const counts = {};
  const out = [];
  for (const hit of hits) {
    const country = hit.country || "";
    if ((counts[country] || 0) >= maxPerCountry) continue;
    counts[country] = (counts[country] || 0) + 1;
    out.push(hit);
    if (out.length >= resultCount) break;
  }
  return out;
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

function locationRecord(hit, rank, queryName, lane, processed, minScore) {
  const extra = {
    tags: [canonicalizeCountry(hit.country || "")],
    visionCameraGeneration: hit.cameraGeneration || "unknown",
    visionScore: Number(hit.score.toFixed(7)),
    visionMinScore: Number(minScore.toFixed(7)),
    visionRank: rank,
    visionQuery: queryName,
    visionQueryMode: lane === "object" ? "objects" : "scene",
    visionHeadingOffset: hit.headingOffset || 0,
    visionSourceIndex: 0,
    visionProcessedLocations: processed,
    visionModel: MODEL_ID,
    visionPruneMeters: 100,
  };
  if (lane === "object") {
    extra.visionObjectLane = "object";
    extra.visionObjectConfidence = Number(hit.score.toFixed(7));
  }
  return {
    lat: hit.lat,
    lng: hit.lng,
    heading: hit.heading,
    pitch: hit.pitch,
    zoom: hit.zoom,
    panoId: hit.panoId,
    extra,
  };
}

async function search(env, account, body) {
  const key = body.idempotencyKey;
  if (typeof key !== "string" || key.length < 8 || key.length > 100) return error("invalid_idempotency_key");
  const lane = body.lane === "object" ? "object" : "scene";
  const viewDirection = normalizeViewDirection(body.viewDirection, lane);
  const offsets = viewOffsetsFor(viewDirection, lane);
  const excluded = parseExcludeMap(body.excludeMap);
  if (excluded?.error) return error(excluded.error);
  const resultCount = Math.min(10000, Math.max(1, Number.isInteger(body.resultCount) ? body.resultCount : 200));
  const maxPerCountry = Math.min(10000, Math.max(1, Number.isInteger(body.maxPerCountry) ? body.maxPerCountry : 25));
  const filters = normalizeFilters(body);
  if (filters.mode === "include" && !filters.countries.length) return error("invalid_country_filter");
  const map = body.queryMap;
  const parsed = parseQueryMap(map);
  if (parsed?.error) return error(parsed.error);
  if (!parsed) return error("invalid_mma_map");
  const examples = parsed;
  const queryName = typeof map?.name === "string" && map.name.trim() ? map.name.trim() : (body.outputName || "VISION Community");
  const excludeKey = excluded.length ? `:exclude:${excluded.length}:${excluded[0].panoId}` : "";
  const queryKey = `mma:${queryName}:${lane}:${viewDirection}:${examples.map((item) => item.panoId).join(",")}${excludeKey}`;
  const existing = await env.DB.prepare(
    "SELECT query, result_json FROM searches WHERE account_id=? AND idempotency_key=?"
  ).bind(account, key).first();
  if (existing) {
    if (existing.query !== queryKey) return error("idempotency_conflict", 409);
    return json(JSON.parse(existing.result_json));
  }
  const accountRow = await env.DB.prepare("SELECT units FROM accounts WHERE id=?").bind(account).first();
  if (!accountRow) return error("unauthorized", 401);
  if (accountRow.units < SEARCH_COST) return error("insufficient_credit", 402);
  if (body.execute === "local") {
    const debit = await env.DB.prepare("UPDATE accounts SET units=units-? WHERE id=? AND units>=?").bind(SEARCH_COST, account, SEARCH_COST).run();
    if (!debit.meta || debit.meta.changes !== 1) return error("insufficient_credit", 402);
    const published = await env.DB.prepare(
      "SELECT COUNT(*) AS n FROM published_index i JOIN locations l ON l.id=i.location_id WHERE i.embedding IS NOT NULL AND l.lane=?"
    ).bind(lane).first();
    const searchId = randomHex(16);
    const result = {
      searchId,
      query: queryName,
      local: true,
      lane,
      results: [],
      demo: false,
      persistImagery: false,
      map: null,
      published: published?.n || 0,
    };
    await env.DB.batch([
      env.DB.prepare("INSERT INTO searches (id, account_id, idempotency_key, query, result_json) VALUES (?, ?, ?, ?, ?)").bind(
        searchId, account, key, queryKey, JSON.stringify(result)
      ),
      env.DB.prepare("INSERT INTO ledger (account_id, units, reason, reference) VALUES (?, ?, 'search', ?)").bind(
        account, -SEARCH_COST, `search:${searchId}`
      ),
    ]);
    return json(result);
  }
  const publishedCount = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM published_index i JOIN locations l ON l.id=i.location_id WHERE i.embedding IS NOT NULL AND l.lane=?"
  ).bind(lane).first();
  if ((publishedCount?.n || 0) > SITE_SEARCH_CAP) return error("search_on_computer", 413);
  const vectors = [];
  const queryExamples = examples.some((item) => usesStreetViews(item.panoId))
    ? examples.slice(0, QUERY_VIEW_CAP)
    : examples;
  for (const example of queryExamples) {
    const indexed = await env.DB.prepare(
      `SELECT capture FROM locations WHERE asset_id=? AND lane=?
       ORDER BY CASE WHEN state='published' THEN 0 ELSE 1 END, id LIMIT 1`
    ).bind(example.panoId, lane).first();
    const capture = indexed?.capture || example.capture;
    let faces;
    try {
      faces = await locationFaces({
        panoId: example.panoId,
        assetId: example.panoId,
        capture,
        lane,
        model: MODEL_ID,
        heading: example.heading || 0,
        pitch: example.pitch || 0,
        zoom: example.zoom || 0,
      });
    } catch (err) {
      return viewFailure(err) || error("view_unavailable", 422);
    }
    vectors.push(embeddingFor(lane, faces));
  }
  const query = meanEmbeddings(vectors);
  const published = (await env.DB.prepare(
    `SELECT i.location_id, i.embedding, l.asset_id, l.lat, l.lon, l.heading, l.pitch, l.zoom, l.country, l.camera_generation
     FROM published_index i JOIN locations l ON l.id=i.location_id
     WHERE i.embedding IS NOT NULL AND l.lane=?`
  ).bind(lane).all()).results || [];
  const scored = published.map((row) => {
    const embedding = hexToQuery(row.embedding);
    let score;
    let viewOffset = 0;
    if (lane === "object") {
      score = maxRegionCosine(query, embedding);
    } else {
      const ranked = bestSceneView(query, embedding, offsets);
      score = ranked.score;
      viewOffset = ranked.offset;
    }
    return {
      locationId: row.location_id,
      score,
      panoId: row.asset_id,
      lat: row.lat || 0,
      lng: row.lon || 0,
      heading: wrapHeading((row.heading || 0) + viewOffset * 90),
      headingOffset: viewOffset * 90,
      viewOffset,
      pitch: row.pitch || 0,
      zoom: row.zoom || 0,
      country: canonicalizeCountry(row.country || ""),
      cameraGeneration: row.camera_generation || "",
    };
  }).filter((hit) => usesStreetViews(hit.panoId) && acceptsHit(hit, filters)).sort((a, b) => b.score - a.score || a.locationId - b.locationId);
  const capped = capCountries(pruneNearby(excludeUsed(scored, excluded)), resultCount, maxPerCountry);
  const minScore = capped.length ? capped[capped.length - 1].score : 0;
  const coordinates = capped.map((hit, index) => locationRecord(hit, index + 1, queryName, lane, published.length, minScore));
  const searchId = randomHex(16);
  const result = {
    searchId,
    query: queryName,
    results: capped.map((hit) => ({ locationId: hit.locationId, lane, score: Number(hit.score.toFixed(6)), pose: hit })),
    demo: false,
    persistImagery: false,
    map: { name: queryName, customCoordinates: coordinates },
  };
  const debit = await env.DB.prepare("UPDATE accounts SET units=units-? WHERE id=? AND units>=?").bind(SEARCH_COST, account, SEARCH_COST).run();
  if (!debit.meta || debit.meta.changes !== 1) return error("insufficient_credit", 402);
  await env.DB.batch([
    env.DB.prepare("INSERT INTO searches (id, account_id, idempotency_key, query, result_json) VALUES (?, ?, ?, ?, ?)").bind(
      searchId, account, key, queryKey, JSON.stringify(result)
    ),
    env.DB.prepare("INSERT INTO ledger (account_id, units, reason, reference) VALUES (?, ?, 'search', ?)").bind(
      account, -SEARCH_COST, `search:${searchId}`
    ),
  ]);
  return json(result);
}

function hexToQuery(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i += 1) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
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
    if (!env.DB) return error("control_plane_unprovisioned", 503);
    try {
      await ready(env);
      if (url.pathname === "/api/status" && request.method === "GET") return json(await status(env));
      if (url.pathname === "/api/me" && request.method === "GET") {
        const account = await accountId(env, request);
        if (!account) return error("unauthorized", 401);
        return json(await status(env, account));
      }
      if (url.pathname === "/api/views" && request.method === "GET") {
        if (!sameOrigin(request)) return error("cross_origin_request", 403);
        const account = await accountId(env, request);
        if (!account) return error("unauthorized", 401);
        return views(request);
      }
      if (url.pathname === "/api/published-snapshot" && request.method === "GET") {
        if (!sameOrigin(request)) return error("cross_origin_request", 403);
        const account = await accountId(env, request);
        if (!account) return error("unauthorized", 401);
        return publishedSnapshot(env, account, url);
      }
      if (url.pathname === "/api/index-manifest" && request.method === "GET") {
        if (!sameOrigin(request)) return error("cross_origin_request", 403);
        const account = await accountId(env, request);
        if (!account) return error("unauthorized", 401);
        return indexManifest(env, account, url);
      }
      if (url.pathname === "/api/index-shard" && request.method === "GET") {
        if (!sameOrigin(request)) return error("cross_origin_request", 403);
        const account = await accountId(env, request);
        if (!account) return error("unauthorized", 401);
        return indexShard(env, account, url);
      }
      if (request.method !== "POST") return error("not_found", 404);
      if (!sameOrigin(request)) return error("cross_origin_request", 403);
      const body = await request.json().catch(() => null);
      if (!body || typeof body !== "object") return error("invalid_json");
      if (url.pathname === "/api/accounts") return createAccount(env, request);
      if (url.pathname === "/api/recovery") return recover(env, request, body);
      const account = await accountId(env, request);
      if (!account) return error("unauthorized", 401);
      if (url.pathname === "/api/leases/release") return releaseLease(env, account, body);
      if (url.pathname === "/api/leases") return lease(env, account, body);
      if (url.pathname === "/api/submissions") return submit(env, account, body);
      if (url.pathname === "/api/searches") return search(env, account, body);
      return error("not_found", 404);
    } catch (err) {
      return viewFailure(err) || error("internal_error", 500);
    }
  },
};
