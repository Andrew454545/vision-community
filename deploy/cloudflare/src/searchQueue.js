// Owner-outbound search delivery. D1 owns reservations and once-only payment;
// the owner never writes balances and the gateway never runs model inference.
import { randomHex, encodeUtf8, SEARCH_COST } from './model.js';
import { SearchError, replaySearch, requireFreshSearchRequest, SEARCH_REQUEST_SECONDS } from './searchLedger.js';
import { searchDigest, verifiedSearchResult } from './onlineSearch.js';
import { SEARCH_CONTRACT_VERSION } from './searchExport.js';
import { searchCost, validSearchQuote } from './searchPricing.js';
import { sceneCohortAllows } from './sceneCohort.js';
import { sceneMembershipBinding, MAX_SEALED_SCENE_HITS } from './sceneMembership.js';

export const SEARCH_QUEUE_CONTRACT = 'vision-search-queue-v1-20261012';
export const SEARCH_JOB_SECONDS = SEARCH_REQUEST_SECONDS;
export const SEARCH_CLAIM_SECONDS = 300;
export const SEARCH_QUEUE_RESULT_BYTES = 1024 * 1024;
const HEX = /^[0-9a-f]{64}$/;
const ID = /^[0-9a-f]{32}$/;
const ACTIVE = "state IN ('queued','claimed')";
const clock = () => Math.floor(Date.now() / 1000);

function canonicalBinding(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || Object.keys(value).sort().join(',') !== 'contractVersion,policyId,runtimeSha256,snapshotSha256'
      || value.contractVersion !== SEARCH_CONTRACT_VERSION
      || typeof value.policyId !== 'string' || !/^[A-Za-z0-9_.-]{1,128}$/.test(value.policyId)
      || typeof value.runtimeSha256 !== 'string' || typeof value.snapshotSha256 !== 'string'
      || !HEX.test(value.runtimeSha256) || !HEX.test(value.snapshotSha256))
    throw new SearchError('invalid_search_binding', 400);
  return { contractVersion: SEARCH_CONTRACT_VERSION, policyId: value.policyId,
    runtimeSha256: value.runtimeSha256, snapshotSha256: value.snapshotSha256 };
}

function bindings(env) {
  if (env.SEARCH_DELIVERY !== 'queued-v1' || env.SEARCH_DYNAMIC_SNAPSHOT === '1'
      || ![undefined, '0'].includes(env.SEARCH_DYNAMIC_SNAPSHOT)
      || !HEX.test(env.SEARCH_AGENT_SECRET || '')) throw new SearchError('search_unavailable');
  if (env.SEARCH_QUEUE_BINDINGS !== undefined) {
    try {
      // Explicit lane pins cannot coexist with legacy global pins: rollback or
      // a partial edit must not silently select a different engine/catalog.
      if (typeof env.SEARCH_QUEUE_BINDINGS !== 'string' || env.SEARCH_QUEUE_BINDINGS.length > 2048
          || [env.SEARCH_POLICY_ID, env.SEARCH_RUNTIME_SHA256, env.SEARCH_SNAPSHOT_SHA256].some(v => v !== undefined)) throw Error();
      const value = JSON.parse(env.SEARCH_QUEUE_BINDINGS);
      if (!value || Object.keys(value).sort().join(',') !== 'lanes,version' || value.version !== 1
          || !value.lanes || typeof value.lanes !== 'object' || Array.isArray(value.lanes)
          || !Object.keys(value.lanes).length || Object.keys(value.lanes).some(lane => !['scene', 'object'].includes(lane))) throw Error();
      return Object.fromEntries(Object.entries(value.lanes).map(([lane, pin]) => [lane, canonicalBinding(pin)]));
    } catch { throw new SearchError('search_unavailable'); }
  }
  // Preserve historical single-binding requests and saved rows unchanged.
  if (typeof env.SEARCH_POLICY_ID !== 'string' || !env.SEARCH_POLICY_ID || env.SEARCH_POLICY_ID.length > 200
      || !HEX.test(env.SEARCH_RUNTIME_SHA256 || '') || !HEX.test(env.SEARCH_SNAPSHOT_SHA256 || ''))
    throw new SearchError('search_unavailable');
  const pin = { contractVersion: SEARCH_CONTRACT_VERSION, policyId: env.SEARCH_POLICY_ID,
    runtimeSha256: env.SEARCH_RUNTIME_SHA256, snapshotSha256: env.SEARCH_SNAPSHOT_SHA256 };
  return { scene: pin, object: pin };
}

function binding(env, lane) {
  if (!['scene', 'object'].includes(lane)) throw new SearchError('search_unavailable');
  const pin = bindings(env)[lane];
  if (!pin) throw new SearchError('search_unavailable');
  if (lane === 'scene') sceneMembershipBinding(env, pin);
  return pin;
}

export function queuedSearchConfigured(env, lane) {
  try { return lane === undefined ? !!bindings(env) : !!binding(env, lane); } catch { return false; }
}

export async function requireSearchAgent(env, request) {
  if (!queuedSearchConfigured(env)) throw new SearchError('search_unavailable');
  const auth = request.headers.get('authorization') || '';
  if (!/^Bearer [0-9a-f]{64}$/.test(auth)) throw new SearchError('unauthorized', 401);
  // Web Crypto verifies the MAC without a secret string comparison. No token
  // or private query is logged, and browser account credentials cannot claim.
  const key = await crypto.subtle.importKey('raw', encodeUtf8(env.SEARCH_AGENT_SECRET),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
  const expected = await crypto.subtle.sign('HMAC', key, encodeUtf8(`Bearer ${env.SEARCH_AGENT_SECRET}`));
  if (!await crypto.subtle.verify('HMAC', key, expected, encodeUtf8(auth))) throw new SearchError('unauthorized', 401);
}

export async function requireSearchQueue(db) {
  let row;
  try { row = await db.prepare('SELECT revision,contract FROM search_queue_revision WHERE slot=1').first(); }
  catch { throw new SearchError('schema_update_required'); }
  if (row?.revision !== 1 || row.contract !== SEARCH_QUEUE_CONTRACT) throw new SearchError('schema_update_required');
}

function validTime(now) {
  if (!Number.isSafeInteger(now) || now < 0 || now > Number.MAX_SAFE_INTEGER - SEARCH_JOB_SECONDS)
    throw new SearchError('invalid_search_time', 400);
}

export async function maintainSearchQueue(db, now = clock()) {
  validTime(now);
  // At most 128 active rows and 64 old terminal rows, enforced by the insert
  // trigger. No timer/cron or paid queue is required to release holds.
  await db.batch([
    db.prepare(`UPDATE search_jobs SET state=CASE WHEN expires_at<=? THEN 'expired' ELSE 'failed' END,
      error_code=CASE WHEN expires_at<=? THEN 'search_expired' ELSE 'search_failed' END,
      query_json=NULL,claim_token=NULL,claim_until=NULL
      WHERE ${ACTIVE} AND (expires_at<=? OR (state='claimed' AND claim_until<=? AND attempts>=3))`)
      .bind(now, now, now, now),
    db.prepare(`DELETE FROM search_jobs WHERE id IN (SELECT id FROM search_jobs
      WHERE state IN ('settled','failed','cancelled','expired') AND expires_at<? ORDER BY expires_at,id LIMIT 64)`)
      .bind(now - 86400),
  ]);
}

export async function searchCredit(db, account) {
  const row = await db.prepare(`SELECT units,COALESCE((SELECT SUM(cost_units) FROM search_jobs
    WHERE account_id=a.id AND ${ACTIVE}),0) AS reserved FROM accounts a WHERE id=? AND deleted_at IS NULL`)
    .bind(account).first();
  if (!row) throw new SearchError('unauthorized', 401);
  return { bankedUnits: row.units, reservedUnits: row.reserved, units: row.units - row.reserved };
}

function receipt(row) {
  return { queued: true, jobId: row.id, state: row.state, reservedUnits: ['queued', 'claimed'].includes(row.state) ? row.cost_units : 0,
    costUnits: row.cost_units, expiresAt: row.expires_at, retryAfterSeconds: 30,
    ...(row.error_code ? { error: row.error_code } : {}) };
}

function queueError(error) {
  if (String(error.message).includes('search_credit_reserved')) return new SearchError('insufficient_credit', 402);
  if (String(error.message).includes('search_queue_full')) return new SearchError('search_queue_full', 429);
  if (String(error.message).includes('account_not_active')) return new SearchError('unauthorized', 401);
  return error;
}

export async function queueSearch(env, account, key, query, { allowNew = true, maxCostUnits, now = clock() } = {}) {
  validTime(now);
  if (typeof key !== 'string' || key.length < 8 || key.length > 100) throw new SearchError('invalid_idempotency_key', 400);
  const digest = await searchDigest(query);
  // Historical paid replies need neither a running owner nor queue configuration.
  const paid = await replaySearch(env.DB, account, key, digest);
  if (paid) return paid;
  await requireSearchQueue(env.DB);
  await maintainSearchQueue(env.DB, now);
  const previous = await env.DB.prepare(`SELECT j.* FROM search_jobs j JOIN accounts a ON a.id=j.account_id
    WHERE j.account_id=? AND j.idempotency_key=? AND a.deleted_at IS NULL`).bind(account, key).first();
  if (previous) {
    if (previous.query_digest !== digest) throw new SearchError('idempotency_conflict', 409);
    if (previous.state === 'settled') return await replaySearch(env.DB, account, key, digest) || receipt(previous);
    return receipt(previous);
  }
  // Terminal job metadata is finite. An expired key can still replay a paid
  // result above, but can never silently become new work after pruning.
  requireFreshSearchRequest(key, now);
  const identity = binding(env, query.lane);
  if (query.lane === 'scene' && env.SEARCH_SCENE_MEMBERSHIP !== undefined
      && query.resultCount > MAX_SEALED_SCENE_HITS) throw new SearchError('search_result_count_limit', 400);
  if (!await sceneCohortAllows(env, account)) throw new SearchError('search_unavailable');
  if (!allowNew) throw new SearchError('object_verification_unavailable');
  const cost = searchCost(env), maximum = maxCostUnits === undefined ? SEARCH_COST : maxCostUnits;
  if (cost === null) throw new SearchError('search_unavailable');
  if (!validSearchQuote(maximum)) throw new SearchError('invalid_search_quote', 400);
  if (cost > maximum) throw new SearchError('search_price_changed', 409);
  const raw = JSON.stringify(query);
  if (encodeUtf8(raw).length > 65536 || query.resultCount > 1000) throw new SearchError('search_query_too_large', 413);
  let failure;
  try {
    await env.DB.prepare(`INSERT INTO search_jobs
      (id,account_id,idempotency_key,query_digest,query_json,lane,binding_json,cost_units,state,created_at,expires_at)
      VALUES(?,?,?,?,?,?,?,?,'queued',?,?)`)
      .bind(randomHex(16), account, key, digest, raw, query.lane, JSON.stringify(identity), cost, now, now + SEARCH_JOB_SECONDS).run();
  } catch (error) { failure = queueError(error); }
  // Concurrent retry can lose the unique-key race; return its exact saved job.
  const saved = await env.DB.prepare('SELECT * FROM search_jobs WHERE account_id=? AND idempotency_key=?')
    .bind(account, key).first();
  if (saved) {
    if (saved.query_digest !== digest) throw new SearchError('idempotency_conflict', 409);
    return receipt(saved);
  }
  const concurrentPaid = await replaySearch(env.DB, account, key, digest);
  if (concurrentPaid) return concurrentPaid;
  throw failure || new SearchError('search_unavailable');
}

export async function queuedSearchStatus(env, account, id, now = clock()) {
  if (!ID.test(id || '')) throw new SearchError('search_not_found', 404);
  await requireSearchQueue(env.DB);
  await maintainSearchQueue(env.DB, now);
  const paid = await env.DB.prepare(`SELECT s.result_json FROM searches s JOIN accounts a ON a.id=s.account_id
    WHERE s.id=? AND s.account_id=? AND a.deleted_at IS NULL`).bind(id, account).first();
  if (paid) return JSON.parse(paid.result_json);
  const row = await env.DB.prepare(`SELECT j.* FROM search_jobs j JOIN accounts a ON a.id=j.account_id
    WHERE j.id=? AND j.account_id=? AND a.deleted_at IS NULL`).bind(id, account).first();
  if (!row) throw new SearchError('search_not_found', 404);
  return receipt(row);
}

export async function recoverSearch(env, account, key, now = clock()) {
  if (typeof key !== 'string' || key.length < 8 || key.length > 100) throw new SearchError('invalid_idempotency_key', 400);
  // Recovery never enqueues, runs inference or charges. Historical large query
  // maps need not be re-uploaded under the new small-input queue policy.
  const paid = await env.DB.prepare(`SELECT s.result_json FROM searches s JOIN accounts a ON a.id=s.account_id
    WHERE s.account_id=? AND s.idempotency_key=? AND a.deleted_at IS NULL`).bind(account, key).first();
  if (paid) return JSON.parse(paid.result_json);
  try { await requireSearchQueue(env.DB); }
  catch (failure) {
    if (failure.code === 'schema_update_required' && env.SEARCH_DELIVERY === undefined) throw new SearchError('search_not_found', 404);
    throw failure;
  }
  await maintainSearchQueue(env.DB, now);
  const row = await env.DB.prepare(`SELECT j.* FROM search_jobs j JOIN accounts a ON a.id=j.account_id
    WHERE j.account_id=? AND j.idempotency_key=? AND a.deleted_at IS NULL`).bind(account, key).first();
  if (!row) throw new SearchError('search_not_found', 404);
  return receipt(row);
}

export async function cancelQueuedSearch(env, account, key, now = clock()) {
  await requireSearchQueue(env.DB);
  await maintainSearchQueue(env.DB, now);
  await env.DB.prepare(`UPDATE search_jobs SET state='cancelled',query_json=NULL,claim_token=NULL,claim_until=NULL,
    error_code='search_cancelled' WHERE account_id=? AND idempotency_key=? AND ${ACTIVE}
    AND EXISTS(SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL)`).bind(account, key, account).run();
  const row = await env.DB.prepare('SELECT id FROM search_jobs WHERE account_id=? AND idempotency_key=?').bind(account, key).first();
  if (!row) throw new SearchError('search_not_found', 404);
  return queuedSearchStatus(env, account, row.id, now);
}

export async function claimQueuedSearch(env, now = clock(), lanes = ['scene'], capabilities) {
  if (!Array.isArray(lanes) || !lanes.length || lanes.length > 2 || new Set(lanes).size !== lanes.length
      || lanes.some(lane => !['scene', 'object'].includes(lane))) throw new SearchError('invalid_search_lane', 400);
  const configured = bindings(env), supported = {};
  let invalidScene = false;
  if (configured.scene && lanes.includes('scene')) {
    try { sceneMembershipBinding(env, configured.scene); }
    catch { invalidScene = true; delete configured.scene; }
  }
  if (capabilities !== undefined) {
    if (!capabilities || typeof capabilities !== 'object' || Array.isArray(capabilities)
        || Object.keys(capabilities).sort().join(',') !== [...lanes].sort().join(','))
      throw new SearchError('invalid_search_binding', 400);
    for (const lane of lanes) {
      const advertised = JSON.stringify(canonicalBinding(capabilities[lane]));
      if (configured[lane] && advertised === JSON.stringify(configured[lane])) supported[lane] = advertised;
    }
    if (!Object.keys(supported).length && (invalidScene || lanes.some(lane => configured[lane])))
      throw new SearchError('search_binding_changed', 409);
  } else {
    // Old agents advertise only lane names. They cannot safely consume a new
    // deployment with independent runtime pins, so never receive its queries.
    if (env.SEARCH_QUEUE_BINDINGS !== undefined) throw new SearchError('search_binding_required', 409);
    for (const lane of lanes) supported[lane] = JSON.stringify(configured[lane]);
    if (invalidScene && !Object.keys(supported).some(lane => supported[lane] !== undefined))
      throw new SearchError('search_binding_changed', 409);
  }
  validTime(now);
  await requireSearchQueue(env.DB);
  await maintainSearchQueue(env.DB, now);
  // One SQL write chooses and fences the claim; two agents cannot own it.
  const job = await env.DB.prepare(`UPDATE search_jobs SET state='claimed',claim_token=?,claim_until=MIN(?,expires_at),attempts=attempts+1
    WHERE id=(SELECT j.id FROM search_jobs j JOIN accounts a ON a.id=j.account_id WHERE a.deleted_at IS NULL
      AND j.binding_json=json_extract(?, '$.' || j.lane) AND j.expires_at>? AND j.attempts<3
      AND (j.state='queued' OR (j.state='claimed' AND j.claim_until<=?)) ORDER BY j.created_at,j.id LIMIT 1)
    RETURNING id,account_id,query_json,query_digest,binding_json,claim_token,claim_until,expires_at`)
    .bind(randomHex(32), now + SEARCH_CLAIM_SECONDS, JSON.stringify(supported), now, now).first();
  if (!job) return { job: null, retryAfterSeconds: 30 };
  if (!await sceneCohortAllows(env, job.account_id)) {
    await failQueuedSearch(env, job.id, job.claim_token, now);
    return { job: null, retryAfterSeconds: 30 };
  }
  // Preserve the gateway's original JSON number spellings for native digest
  // validation; Python must not re-serialize the query before hashing it.
  const head = JSON.stringify({ ...JSON.parse(job.binding_json), requestSha256: job.query_digest.slice(7) });
  return { job: { jobId: job.id, claimToken: job.claim_token, claimUntil: job.claim_until,
    expiresAt: job.expires_at, requestJson: `${head.slice(0, -1)},"query":${job.query_json}}` } };
}

function validClaim(id, token) {
  if (!ID.test(id || '') || !HEX.test(token || '')) throw new SearchError('invalid_search_claim', 400);
}

export async function renewQueuedSearch(env, id, token, now = clock()) {
  validClaim(id, token); validTime(now);
  const identities = Object.fromEntries(Object.entries(bindings(env)).map(([lane, pin]) => [lane, JSON.stringify(pin)]));
  await requireSearchQueue(env.DB);
  const saved = await env.DB.prepare(`UPDATE search_jobs SET claim_until=MIN(?,expires_at)
    WHERE id=? AND claim_token=? AND state='claimed' AND claim_until>? AND expires_at>?
      AND binding_json=json_extract(?, '$.' || lane)
    RETURNING claim_until`).bind(now + SEARCH_CLAIM_SECONDS, id, token, now, now, JSON.stringify(identities)).first();
  if (!saved) throw new SearchError('search_claim_lost', 409);
  return { claimUntil: saved.claim_until };
}

export async function failQueuedSearch(env, id, token, now = clock()) {
  validClaim(id, token); validTime(now);
  await requireSearchQueue(env.DB);
  // Fixed public code only; never store arbitrary owner stderr or query content.
  const saved = await env.DB.prepare(`UPDATE search_jobs SET state='failed',error_code='search_failed',query_json=NULL,
    claim_token=NULL,claim_until=NULL WHERE id=? AND claim_token=? AND state='claimed' AND claim_until>? AND expires_at>?
    RETURNING id`).bind(id, token, now, now).first();
  if (!saved) throw new SearchError('search_claim_lost', 409);
  return { failed: true, charged: false };
}

export async function completeQueuedSearch(env, id, token, computed, now) {
  const startedAt = now ?? clock();
  validClaim(id, token); validTime(startedAt);
  await requireSearchQueue(env.DB);
  const job = await env.DB.prepare(`SELECT j.* FROM search_jobs j JOIN accounts a ON a.id=j.account_id
    WHERE j.id=? AND a.deleted_at IS NULL`).bind(id).first();
  if (!job) throw new SearchError('search_claim_lost', 409);
  const paid = await replaySearch(env.DB, job.account_id, job.idempotency_key, job.query_digest);
  if (paid) return { completed: true, searchId: paid.searchId };
  if (job.state !== 'claimed' || job.claim_token !== token || job.claim_until <= startedAt || job.expires_at <= startedAt)
    throw new SearchError('search_claim_lost', 409);
  const identity = binding(env, job.lane);
  if (job.binding_json !== JSON.stringify(identity) || !await sceneCohortAllows(env, job.account_id))
    throw new SearchError('search_unavailable');
  const query = JSON.parse(job.query_json);
  if (query.lane !== job.lane) throw new SearchError('search_unavailable');
  const result = await verifiedSearchResult({ ...env, SEARCH_POLICY_ID: identity.policyId,
    SEARCH_RUNTIME_SHA256: identity.runtimeSha256 }, query, job.query_digest, computed, identity.snapshotSha256, id, job.cost_units);
  if (encodeUtf8(JSON.stringify(result)).length > SEARCH_QUEUE_RESULT_BYTES) throw new SearchError('search_result_too_large', 413);
  const nonce = randomHex(32), reference = `search:${id}`;
  const settledAt = now ?? clock();
  // Fresh completion nonce gates EVERY financial statement. Concurrent/lost
  // replies cannot re-use a prior successful transaction to debit again.
  await env.DB.batch([
    env.DB.prepare(`UPDATE search_jobs SET state='settled',query_json=NULL,claim_token=NULL,claim_until=NULL,completion_nonce=?
      WHERE id=? AND state='claimed' AND claim_token=? AND claim_until>? AND expires_at>? AND binding_json=?`)
      .bind(nonce, id, token, settledAt, settledAt, job.binding_json),
    env.DB.prepare(`INSERT INTO ledger(account_id,units,reason,reference)
      SELECT j.account_id,-j.cost_units,'search',? FROM search_jobs j JOIN accounts a ON a.id=j.account_id
      WHERE j.id=? AND j.completion_nonce=? AND a.deleted_at IS NULL`).bind(reference, id, nonce),
    env.DB.prepare(`INSERT INTO searches(id,account_id,idempotency_key,query,result_json)
      SELECT id,account_id,idempotency_key,query_digest,? FROM search_jobs WHERE id=? AND completion_nonce=?`)
      .bind(JSON.stringify(result), id, nonce),
    env.DB.prepare(`UPDATE accounts SET units=units-? WHERE id=? AND deleted_at IS NULL
      AND EXISTS(SELECT 1 FROM search_jobs WHERE id=? AND completion_nonce=?)`).bind(job.cost_units, job.account_id, id, nonce),
  ]);
  const saved = await replaySearch(env.DB, job.account_id, job.idempotency_key, job.query_digest);
  if (!saved) throw new SearchError('search_claim_lost', 409);
  return { completed: true, searchId: saved.searchId };
}
