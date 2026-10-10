import { randomHex, sha256Hex, encodeUtf8, SEARCH_COST, viewOffsetsFor, wrapHeading } from "./model.js";
import { replaySearch, settleSearch, SearchError } from "./searchLedger.js";
import { SEARCH_CONTRACT_VERSION, querySemantics, validHitObject, exportSearchMap } from "./searchExport.js";
import { officialGen4Coverage } from "./objectCoverage.js";
import { searchCost, validSearchQuote } from "./searchPricing.js";
import { sceneCohortAllows } from "./sceneCohort.js";

const HEX = /^[0-9a-f]{64}$/;
const RESPONSE_LIMIT = 4 * 1024 * 1024;
export const INDEX_DOWNLOAD_ROUTES = new Set([
  "/api/published-snapshot", "/api/index-manifest", "/api/index-shard",
  "/api/scene-indexes", "/api/scene-index-file", "/api/object-indexes", "/api/object-index-file",
]);

export function onlineSearchConfigured(env) {
  return !!(env.SEARCH_ENGINE?.fetch && typeof env.SEARCH_POLICY_ID === "string" && env.SEARCH_POLICY_ID
    && HEX.test(env.SEARCH_RUNTIME_SHA256 || "") && HEX.test(env.SEARCH_SNAPSHOT_SHA256 || "")
    && [undefined, '0', '1'].includes(env.SEARCH_DYNAMIC_SNAPSHOT));
}

async function snapshotIdentity(env) {
  if (env.SEARCH_DYNAMIC_SNAPSHOT !== '1') return env.SEARCH_SNAPSHOT_SHA256;
  try {
    const response = await env.SEARCH_ENGINE.fetch(new Request('https://search.internal/snapshot', {
      signal: AbortSignal.timeout(10000),
    }));
    if (!response.ok || !response.body) throw Error();
    const reader = response.body.getReader();
    const chunks = []; let size = 0;
    try {
      while (true) {
        const {done, value} = await reader.read(); if (done) break;
        size += value.byteLength; if (size > 4096) { await reader.cancel(); throw Error(); }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const head = JSON.parse(new TextDecoder().decode(bytes));
    if (!head || Object.keys(head).sort().join(',') !== 'bundleSha256,policyId,runtimeSha256,snapshotSha256'
        || head.policyId !== env.SEARCH_POLICY_ID || head.runtimeSha256 !== env.SEARCH_RUNTIME_SHA256
        || !HEX.test(head.snapshotSha256 || '') || !HEX.test(head.bundleSha256 || '')) throw Error();
    return head.snapshotSha256;
  } catch { throw new SearchError('search_unavailable'); }
}

export async function searchDigest(query) {
  // query is a normalized, allowlisted object, with a stable field order. Store
  // this fingerprint rather than raw prompts/reference maps in the ledger key.
  return `sha256:${await sha256Hex(encodeUtf8(JSON.stringify(query)))}`;
}

async function engineResult(env, query, digest) {
  if (!onlineSearchConfigured(env)) throw new SearchError("search_unavailable");
  const snapshotSha256 = await snapshotIdentity(env);
  let response;
  try {
    response = await env.SEARCH_ENGINE.fetch(new Request("https://search.internal/search", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ contractVersion: SEARCH_CONTRACT_VERSION, policyId: env.SEARCH_POLICY_ID,
        runtimeSha256: env.SEARCH_RUNTIME_SHA256, snapshotSha256,
        requestSha256: digest.slice(7), query }), signal: AbortSignal.timeout(120000),
    }));
  } catch { throw new SearchError("search_unavailable"); }
  if (!response.ok || !response.body) throw new SearchError("search_unavailable");
  const reader = response.body.getReader();
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > RESPONSE_LIMIT) { await reader.cancel(); throw new SearchError("search_unavailable"); }
      chunks.push(value);
    }
  } catch { throw new SearchError("search_unavailable"); }
  const bytes = new Uint8Array(length);
  let position = 0;
  for (const chunk of chunks) { bytes.set(chunk, position); position += chunk.byteLength; }
  let result;
  try { result = JSON.parse(new TextDecoder().decode(bytes)); } catch { throw new SearchError("search_unavailable"); }
  if (result?.contractVersion !== SEARCH_CONTRACT_VERSION || result.policyId !== env.SEARCH_POLICY_ID
      || result.runtimeSha256 !== env.SEARCH_RUNTIME_SHA256 || result.snapshotSha256 !== snapshotSha256
      || result.requestSha256 !== digest.slice(7) || !Array.isArray(result.hits)
      || result.hits.length > query.resultCount || !Number.isSafeInteger(result.processedLocations)
      || result.processedLocations < result.hits.length) throw new SearchError("search_unavailable");
  return result;
}

function distance(a, b) {
  const rad = Math.PI / 180;
  const value = Math.sin((b.lat - a.lat) * rad / 2) ** 2
    + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin((b.lng - a.lng) * rad / 2) ** 2;
  return 12742000 * Math.asin(Math.min(1, Math.sqrt(value)));
}

async function verifiedHits(db, query, hits, processedLocations) {
  const { minimumScore } = querySemantics(query);
  if (!Number.isFinite(minimumScore)) throw new SearchError("search_unavailable");
  if (hits.some(hit => !hit || typeof hit !== "object" || Array.isArray(hit))) throw new SearchError("search_unavailable");
  const ids = hits.map(hit => hit.locationId);
  if (ids.some(id => !Number.isSafeInteger(id) || id < 1) || new Set(ids).size !== ids.length)
    throw new SearchError("search_unavailable");
  const rows = (await db.prepare(`SELECT l.id,l.asset_id,l.lat,l.lon,l.heading,l.pitch,l.zoom,l.country,l.camera_generation,
      i.output_sha256 FROM published_index i JOIN locations l ON l.id=i.location_id
      WHERE l.id IN (SELECT value FROM json_each(?)) AND l.lane=? AND l.state='published'
        AND l.contributor_id IS NOT NULL AND l.contributor_id!=''
        AND ((?='scene' AND i.four_view_key IS NOT NULL)
          OR (?='object' AND i.object_index_key IS NOT NULL AND (${officialGen4Coverage("l")})))`)
    .bind(JSON.stringify(ids), query.lane, query.lane, query.lane).all()).results || [];
  const byId = new Map(rows.map(row => [row.id, row]));
  const countries = new Map();
  const panos = new Set();
  const ordinals = new Set();
  const verified = [];
  const offsets = query.lane === "object" ? [0, 1, 2, 3, 4, 5] : viewOffsetsFor(query.viewDirection, query.lane);
  for (const hit of hits) {
    const row = byId.get(hit.locationId);
    if (!row || hit.outputSha256 !== row.output_sha256 || !HEX.test(hit.outputSha256)
        || !Number.isFinite(hit.score) || hit.score < minimumScore || hit.score > 1
        || !Number.isSafeInteger(hit.sourceIndex) || hit.sourceIndex < 0 || hit.sourceIndex >= processedLocations
        || ordinals.has(hit.sourceIndex)
        || (query.minimumGlobalLocation !== null && hit.sourceIndex < query.minimumGlobalLocation)
        || !Number.isInteger(hit.viewOffset) || !offsets.includes(hit.viewOffset)
        || !Number.isFinite(row.lat) || !Number.isFinite(row.lon) || !row.asset_id
        || Math.abs(row.lat) > 90 || Math.abs(row.lon) > 180 || panos.has(row.asset_id)
        || ![row.heading, row.pitch, row.zoom].every(Number.isFinite)
        || Math.abs(row.pitch) > 90 || row.zoom < 0 || row.zoom > 5)
      throw new SearchError("search_unavailable");
    const prior = verified.at(-1);
    if (prior && (hit.score > prior.score || (hit.score === prior.score && hit.sourceIndex < prior.sourceIndex)))
      throw new SearchError("search_unavailable");
    const country = row.country || "";
    const count = (countries.get(country) || 0) + 1;
    const pose = { lat: row.lat, lng: row.lon };
    if (count > query.maxPerCountry
        || (query.filters.mode === "include" && !query.filters.countries.includes(country))
        || (query.filters.mode === "exclude" && query.filters.countries.includes(country))
        || (query.filters.generations.length && !query.filters.generations.includes(row.camera_generation))
        || query.excluded.some(point => point.panoId === row.asset_id || distance(pose, point) < 25)
        || verified.some(point => distance(pose, point.pose) < 100)) throw new SearchError("search_unavailable");
    countries.set(country, count);
    panos.add(row.asset_id);
    ordinals.add(hit.sourceIndex);
    let heading = wrapHeading(row.heading + hit.viewOffset * 90), pitch = row.pitch, zoom = row.zoom;
    if (query.lane === "object") {
      if (!validHitObject(hit.object, minimumScore)
          || ![hit.heading, hit.pitch, hit.zoom].every(Number.isFinite) || hit.heading < 0 || hit.heading >= 360
          || hit.pitch < -90 || hit.pitch > 90 || hit.zoom < 0 || hit.zoom > 5)
        throw new SearchError("search_unavailable");
      ({ heading, pitch, zoom } = hit);
    }
    verified.push({ locationId: row.id, lane: query.lane, score: hit.score, viewOffset: hit.viewOffset, sourceIndex: hit.sourceIndex,
      ...(query.lane === "object" ? { object: { lane: hit.object.lane, className: hit.object.className,
        classId: hit.object.classId ?? null, confidence: hit.object.confidence,
        supportCount: hit.object.supportCount, bboxArea: hit.object.bboxArea } } : {}),
      pose: { ...pose, heading, pitch, zoom, panoId: row.asset_id, country, cameraGeneration: row.camera_generation } });
  }
  return verified;
}

export async function onlineSearch(env, account, key, query, { allowNew = true, maxCostUnits } = {}) {
  if (typeof key !== "string" || key.length < 8 || key.length > 100) throw new SearchError("invalid_idempotency_key", 400);
  const digest = await searchDigest(query);
  const replay = await replaySearch(env.DB, account, key, digest);
  if (replay) return replay;
  // Expired/removed invitations cannot incur new work or debit, but must not
  // hide a reply that this account already paid for.
  if (!await sceneCohortAllows(env, account)) throw new SearchError("search_unavailable");
  // Closing an unqualified lane must not hide an already paid saved result.
  // New execution/debits remain forbidden, before checking engine availability.
  if (!allowNew) throw new SearchError("object_verification_unavailable");
  const cost = searchCost(env);
  if (cost === null) throw new SearchError("search_unavailable");
  // A saved paid result is replayed above, regardless of today's price/quote.
  // Old clients knew the historical price; they cannot authorize a higher one.
  const maximum = maxCostUnits === undefined ? SEARCH_COST : maxCostUnits;
  if (!validSearchQuote(maximum)) throw new SearchError("invalid_search_quote", 400);
  if (cost > maximum) throw new SearchError("search_price_changed", 409);
  const owner = await env.DB.prepare("SELECT units FROM accounts WHERE id=? AND deleted_at IS NULL").bind(account).first();
  if (!owner) throw new SearchError("unauthorized", 401);
  if (owner.units < cost) throw new SearchError("insufficient_credit", 402);
  const computed = await engineResult(env, query, digest);
  const hits = await verifiedHits(env.DB, query, computed.hits, computed.processedLocations);
  return settleSearch(env.DB, account, key, digest, {
    searchId: randomHex(16), query: query.queryName, lane: query.lane, results: hits, costUnits: cost,
    demo: false, persistImagery: false, local: false,
    map: exportSearchMap(query, hits, computed.processedLocations),
  }, cost);
}
