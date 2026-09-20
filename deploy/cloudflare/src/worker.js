import {
  MODEL_ID, SEARCH_COST, UNITS, LEASE_SECONDS, MAX_LEASE, RECOVERY_PEPPER,
  sha256Hex, encodeUtf8, equalHex, seedBytes, renderFacesFromSeed, embeddingFor,
  outputDigest, cosine, maxRegionCosine, meanEmbeddings, base64ToBytes, bytesToHex,
  randomHex, randomToken,
} from "./model.js";
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
`;

const HEADERS = {
  "content-type": "application/json",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
  "x-frame-options": "DENY",
  "content-security-policy":
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'",
};

function json(value, status = 200, extra = {}) {
  return new Response(JSON.stringify(value), { status, headers: { ...HEADERS, ...extra } });
}

function error(code, status = 400) {
  return json({ error: code }, status);
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
  const visual = await env.DB.prepare("SELECT COUNT(*) AS n FROM published_index WHERE embedding IS NOT NULL").first();
  const result = {
    operational: true,
    demo: false,
    publicCorpus: false,
    ownerBypass: false,
    persistImagery: false,
    r2: "not_created",
    searchCost: SEARCH_COST,
    searchBackend: "d1-prototype",
    model: MODEL_ID,
    visualPublished: visual?.n || 0,
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

async function lease(env, account, body) {
  const lane = body.lane;
  const count = body.count;
  const pace = body.pace || "medium";
  if (!UNITS[lane] || typeof count !== "number" || count < 1 || count > MAX_LEASE) return error("invalid_lease_request");
  if (!["slow", "medium", "max"].includes(pace)) return error("invalid_pace");
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare("UPDATE leases SET state='expired' WHERE state='active' AND expires_at<=?").bind(now).run();
  const rows = await env.DB.prepare(
    `SELECT id, asset_id, capture, lane, model, generation, attribution, lat, lon, heading, pitch, zoom, country, camera_generation
     FROM locations WHERE lane=? AND COALESCE(queue_state,'pending')='pending'
       AND (state='pending' OR (state='leased' AND lease_until<=?))
     ORDER BY id LIMIT ?`
  ).bind(lane, now, count).all();
  const items = rows.results || [];
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
    const faces = renderFacesFromSeed(await seedBytes(row.asset_id, row.capture, row.lane, row.model));
    payload.push({
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
      facesSha256: await sha256Hex(faces),
    });
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
  const verified = [];
  for (const row of items) {
    if (row.state !== "leased" || row.active_lease !== leaseId) return error("lease_lost", 409);
    const payload = supplied.get(row.id);
    const faces = renderFacesFromSeed(await seedBytes(row.asset_id, row.capture, row.lane, row.model));
    const embedding = embeddingFor(row.lane, faces);
    const digest = await outputDigest(row.asset_id, row.capture, row.lane, row.model, embedding);
    if (!equalHex(payload.digest, digest)) return error("verification_failed", 422);
    if (payload.embeddingSha256 && !equalHex(payload.embeddingSha256, await sha256Hex(embedding))) return error("verification_failed", 422);
    if (payload.embedding && bytesToHex(payload.embedding) !== bytesToHex(embedding)) return error("verification_failed", 422);
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
  return json({ accepted: items.length, unitsEarned: earned, replayed: false, segments: [] });
}

function capCountries(hits, maxPerCountry) {
  const counts = {};
  const out = [];
  for (const hit of hits) {
    const country = hit.country || "";
    if ((counts[country] || 0) >= maxPerCountry) continue;
    counts[country] = (counts[country] || 0) + 1;
    out.push(hit);
  }
  return out;
}

function locationRecord(hit, rank, queryName, lane, processed, minScore) {
  return {
    lat: hit.lat,
    lng: hit.lng,
    heading: hit.heading,
    pitch: hit.pitch,
    zoom: hit.zoom,
    panoId: hit.panoId,
    extra: {
      tags: [hit.country, lane].filter(Boolean),
      visionCameraGeneration: hit.cameraGeneration || "unknown",
      visionScore: Number(hit.score.toFixed(6)),
      visionMinScore: Number(minScore.toFixed(6)),
      visionRank: rank,
      visionQuery: queryName,
      visionQueryMode: lane,
      visionHeadingOffset: 0,
      visionSourceIndex: 0,
      visionProcessedLocations: processed,
      visionModel: MODEL_ID,
      visionPruneMeters: 25,
      visionObjectClass: null,
      visionObjectClassId: null,
      visionObjectLane: lane === "object" ? lane : null,
      visionObjectConfidence: lane === "object" ? Number(hit.score.toFixed(6)) : null,
      visionObjectSupport: null,
      visionObjectBoxArea: null,
    },
  };
}

async function search(env, account, body) {
  const key = body.idempotencyKey;
  if (typeof key !== "string" || key.length < 8 || key.length > 100) return error("invalid_idempotency_key");
  const lane = body.lane === "object" ? "object" : "scene";
  const resultCount = Math.min(200, Math.max(1, Number(body.resultCount) || 25));
  const maxPerCountry = Math.min(200, Math.max(1, Number(body.maxPerCountry) || 25));
  const map = body.queryMap;
  if (!map || !Array.isArray(map.customCoordinates) || !map.customCoordinates.length) return error("invalid_mma_map");
  if (map.customCoordinates.length > 100) return error("too_many_references");
  const queryName = typeof map.name === "string" && map.name.trim() ? map.name.trim() : (body.outputName || "VISION Community");
  const examples = [];
  for (const row of map.customCoordinates) {
    const panoId = row.panoId || row.pano_id;
    if (typeof panoId !== "string" || panoId.length < 4 || panoId.length > 80) return error("invalid_pano_id");
    const extra = row.extra && typeof row.extra === "object" ? row.extra : {};
    examples.push({
      panoId,
      capture: typeof extra.panoDate === "string" && extra.panoDate ? extra.panoDate : "unknown",
    });
  }
  const queryKey = `mma:${queryName}:${lane}:${examples.map((item) => item.panoId).join(",")}`;
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
  const vectors = [];
  for (const example of examples) {
    const indexed = await env.DB.prepare(
      `SELECT capture FROM locations WHERE asset_id=? AND lane=?
       ORDER BY CASE WHEN state='published' THEN 0 ELSE 1 END, id LIMIT 1`
    ).bind(example.panoId, lane).first();
    const capture = indexed?.capture || example.capture;
    const faces = renderFacesFromSeed(await seedBytes(example.panoId, capture, lane, MODEL_ID));
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
    const score = lane === "object" ? maxRegionCosine(query, embedding) : cosine(query, embedding);
    return {
      locationId: row.location_id,
      score,
      panoId: row.asset_id,
      lat: row.lat || 0,
      lng: row.lon || 0,
      heading: row.heading || 0,
      pitch: row.pitch || 0,
      zoom: row.zoom || 0,
      country: row.country || "",
      cameraGeneration: row.camera_generation || "",
    };
  }).sort((a, b) => b.score - a.score);
  const capped = capCountries(scored, maxPerCountry).slice(0, resultCount);
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
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    if (!env.DB) return error("control_plane_unprovisioned", 503);
    try {
      await ready(env);
      if (url.pathname === "/api/status" && request.method === "GET") return json(await status(env));
      if (url.pathname === "/api/me" && request.method === "GET") {
        const account = await accountId(env, request);
        if (!account) return error("unauthorized", 401);
        return json(await status(env, account));
      }
      if (request.method !== "POST") return error("not_found", 404);
      if (!sameOrigin(request)) return error("cross_origin_request", 403);
      const body = await request.json().catch(() => null);
      if (!body || typeof body !== "object") return error("invalid_json");
      if (url.pathname === "/api/accounts") return createAccount(env, request);
      if (url.pathname === "/api/recovery") return recover(env, request, body);
      const account = await accountId(env, request);
      if (!account) return error("unauthorized", 401);
      if (url.pathname === "/api/leases") return lease(env, account, body);
      if (url.pathname === "/api/submissions") return submit(env, account, body);
      if (url.pathname === "/api/searches") return search(env, account, body);
      return error("not_found", 404);
    } catch (err) {
      return error(err.message || "internal_error", 500);
    }
  },
};
