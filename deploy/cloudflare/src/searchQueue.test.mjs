import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { queueSearch, queuedSearchStatus, cancelQueuedSearch, claimQueuedSearch, renewQueuedSearch,
  failQueuedSearch, completeQueuedSearch, searchCredit, maintainSearchQueue, requireSearchAgent,
  queuedSearchConfigured, requireSearchQueue, recoverSearch, SEARCH_CLAIM_SECONDS, SEARCH_JOB_SECONDS } from './searchQueue.js';
import { onlineSearch, searchDigest } from './onlineSearch.js';
import { settleSearch } from './searchLedger.js';
import { deleteAccount, migrateAccountPrivacy } from './accountPrivacy.js';
import { prepareDatabase } from '../tools/initialize-schema.mjs';
import { sha256Hex, encodeUtf8 } from './model.js';
import worker from './worker.js';
import { checkSearchQueue } from '../tools/check-search-queue.mjs';

const ACCOUNT = 'a'.repeat(32), OTHER = 'b'.repeat(32), NOW = 2000000000;
const keyFor = (label, now = NOW) => `q1.${now}.${createHash('sha256').update(label).digest('hex').slice(0, 32)}`;
const SCHEMA = readFileSync(new URL('../schema.sql', import.meta.url), 'utf8');
const QUEUE = readFileSync(new URL('../search-queue.sql', import.meta.url), 'utf8');
function d1(sql) {
  return { prepare(query) {
    const statement = (args = []) => ({ bind: (...bound) => statement(bound),
      first: async () => sql.prepare(query).get(...args) || null,
      all: async () => ({ results: sql.prepare(query).all(...args) }),
      run: async () => statement(args).execute(),
      execute: () => ({ success: true, meta: { changes: Number(sql.prepare(query).run(...args).changes) } }),
    }); return statement();
  }, async batch(statements) {
    sql.exec('BEGIN IMMEDIATE');
    try { const rows = statements.map(s => s.execute()); sql.exec('COMMIT'); return rows; }
    catch (error) { sql.exec('ROLLBACK'); throw error; }
  } };
}
async function fixture(t, { units = 200, file = ':memory:', migrate = true } = {}) {
  const sql = new DatabaseSync(file); t.after(() => { if (sql.isOpen) sql.close(); }); sql.exec(SCHEMA);
  sql.exec('ALTER TABLE pose_catalog ADD COLUMN assignee TEXT; ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER;');
  await migrateAccountPrivacy({ DB: d1(sql) });
  if (migrate) sql.exec(QUEUE);
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES(?,?,?)').run(ACCOUNT, 'account-token', units);
  sql.prepare('INSERT INTO ledger(account_id,units,reason,reference) VALUES(?,?,?,?)').run(ACCOUNT, units, 'contribution', 'accepted');
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES(?,?,200)').run(OTHER, 'other-token');
  sql.exec(`INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,country,camera_generation)
    VALUES(1,'abcdefghijklmnopqrstuv','2026-01','scene','scene-model','published','contributor',10,20,90,'Italy','gen4');
    INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_key)
    VALUES(1,'','${'c'.repeat(64)}',0,'four-view-v4/test.i8');`);
  const env = { DB: d1(sql), SEARCH_DELIVERY: 'queued-v1', SEARCH_POLICY_ID: 'offline-fixture',
    SEARCH_RUNTIME_SHA256: 'd'.repeat(64), SEARCH_SNAPSHOT_SHA256: 'e'.repeat(64),
    SEARCH_AGENT_SECRET: 'f'.repeat(64), SEARCH_COST_UNITS: '100',
    SEARCH_ENGINE: { fetch() { throw Error('No cloud or model calls allowed'); } } };
  const query = { lane: 'scene', prompt: 'red door', examples: [], excluded: [], queryName: 'My map',
    descriptionWeight: 100, viewDirection: 'bestOfFour', resultCount: 200, maxPerCountry: 25,
    filters: { mode: 'all', countries: [], generations: [] }, objectConfidence: 'balanced',
    rejectRoadNames: false, minimumGlobalLocation: null };
  const enqueue = (key = 'saved-request-key', changes = {}, options = {}) =>
    queueSearch(env, ACCOUNT, keyFor(key), { ...query, ...changes }, { now: NOW, maxCostUnits: 100, ...options });
  const balance = () => sql.prepare('SELECT units FROM accounts WHERE id=?').get(ACCOUNT).units;
  const debits = () => sql.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='search'").get().n;
  return { sql, env, query, enqueue, balance, debits };
}
function computed(job) {
  const { query, ...head } = JSON.parse(job.requestJson);
  return { ...head, processedLocations: 1,
    hits: [{ locationId: 1, outputSha256: 'c'.repeat(64), sourceIndex: 0, score: 0.8, viewOffset: 1 }] };
}
const code = wanted => error => error.code === wanted;

test('offline owner reserves without a debit; concurrent different searches cannot overbook', async t => {
  const f = await fixture(t, { units: 150 });
  const results = await Promise.allSettled([f.enqueue('first-request'), f.enqueue('second-request')]);
  assert.equal(results.filter(x => x.status === 'fulfilled').length, 1);
  assert.equal(results.find(x => x.status === 'rejected').reason.code, 'insufficient_credit');
  assert.deepEqual(await searchCredit(f.env.DB, ACCOUNT), { bankedUnits: 150, reservedUnits: 100, units: 50 });
  assert.equal(f.balance(), 150); assert.equal(f.debits(), 0);
});

test('concurrent retries reserve once, while changed queries conflict', async t => {
  const f = await fixture(t);
  const jobs = await Promise.all([f.enqueue(), f.enqueue(), f.enqueue()]);
  assert.equal(new Set(jobs.map(x => x.jobId)).size, 1);
  await assert.rejects(f.enqueue(undefined, { prompt: 'different' }), code('idempotency_conflict'));
  assert.equal((await searchCredit(f.env.DB, ACCOUNT)).reservedUnits, 100);
});

test('legacy synchronous writer cannot spend reserved credits after mode rollback', async t => {
  const f = await fixture(t, { units: 100 }); await f.enqueue();
  delete f.env.SEARCH_DELIVERY;
  f.env.SEARCH_ENGINE.fetch = async request => {
    const { query, ...head } = await request.json();
    return Response.json({ ...head, processedLocations: 1, hits: computed({ requestJson: JSON.stringify({ ...head, query }) }).hits });
  };
  await assert.rejects(onlineSearch(f.env, ACCOUNT, 'legacy-concurrent-search', f.query, { maxCostUnits: 100 }), code('insufficient_credit'));
  assert.equal(f.balance(), 100); assert.equal(f.debits(), 0);
  assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM searches').get().n, 0);
});

test('claim renewal and restart reclaim fence the old owner, retaining exact query bytes', async t => {
  const f = await fixture(t); await f.enqueue(undefined, { excluded: [{ lat: 1e-7, lng: 2, panoId: 'excluded' }] });
  const { job: first } = await claimQueuedSearch(f.env, NOW);
  assert.match(first.requestJson, /"lat":1e-7/);
  assert.equal((await claimQueuedSearch(f.env, NOW + 1)).job, null);
  assert.equal((await renewQueuedSearch(f.env, first.jobId, first.claimToken, NOW + 100)).claimUntil, NOW + 100 + SEARCH_CLAIM_SECONDS);
  await assert.rejects(renewQueuedSearch(f.env, first.jobId, first.claimToken, NOW + 401), code('search_claim_lost'));
  const { job: replacement } = await claimQueuedSearch(f.env, NOW + 401);
  assert.equal(replacement.jobId, first.jobId); assert.notEqual(replacement.claimToken, first.claimToken);
  await assert.rejects(completeQueuedSearch(f.env, first.jobId, first.claimToken, computed(first), NOW + 402), code('search_claim_lost'));
  await completeQueuedSearch(f.env, replacement.jobId, replacement.claimToken, computed(replacement), NOW + 402);
  assert.equal(f.balance(), 100); assert.equal(f.debits(), 1);
});

test('lost completion reply and simultaneous owner retries charge exactly once; paid recovery survives closure', async t => {
  const f = await fixture(t); const queued = await f.enqueue(); const { job } = await claimQueuedSearch(f.env, NOW);
  const replies = await Promise.all(Array.from({ length: 4 }, () => completeQueuedSearch(f.env, job.jobId, job.claimToken, computed(job), NOW + 1)));
  assert.equal(new Set(replies.map(x => x.searchId)).size, 1);
  const paid = await queuedSearchStatus(f.env, ACCOUNT, queued.jobId, NOW + 2);
  assert.equal(paid.map.customCoordinates.length, 1); assert.equal(f.balance(), 100); assert.equal(f.debits(), 1);
  assert.equal(f.sql.prepare('SELECT query_json FROM search_jobs').get().query_json, null);
  delete f.env.SEARCH_AGENT_SECRET; f.env.SCENE_COHORT_ACCOUNTS = '[]'; f.env.SEARCH_COST_UNITS = '999';
  assert.deepEqual(await f.enqueue(), paid);
  assert.equal(f.balance(), 100);
});

test('cancellation releases credits and a completed search wins a late cancel without a refund/debit', async t => {
  const f = await fixture(t); await f.enqueue(); const { job } = await claimQueuedSearch(f.env, NOW);
  assert.equal((await cancelQueuedSearch(f.env, ACCOUNT, keyFor('saved-request-key'), NOW + 1)).state, 'cancelled');
  await assert.rejects(completeQueuedSearch(f.env, job.jobId, job.claimToken, computed(job), NOW + 2), code('search_claim_lost'));
  assert.equal((await searchCredit(f.env.DB, ACCOUNT)).reservedUnits, 0);
  await f.enqueue('next-request'); const next = (await claimQueuedSearch(f.env, NOW + 3)).job;
  await completeQueuedSearch(f.env, next.jobId, next.claimToken, computed(next), NOW + 4);
  const late = await cancelQueuedSearch(f.env, ACCOUNT, keyFor('next-request'), NOW + 5);
  assert.equal(late.searchId, next.jobId); assert.equal(f.debits(), 1);
});

test('offline deadline and three abandoned claims release holds with no charge and erase queries', async t => {
  const f = await fixture(t); await f.enqueue();
  for (let n = 0; n < 3; n++) assert.ok((await claimQueuedSearch(f.env, NOW + n * 301)).job);
  assert.equal((await claimQueuedSearch(f.env, NOW + 903)).job, null);
  assert.equal((await f.enqueue()).state, 'failed');
  const next = await f.enqueue('deadline-request');
  assert.equal((await queuedSearchStatus(f.env, ACCOUNT, next.jobId, NOW + SEARCH_JOB_SECONDS)).state, 'expired');
  assert.equal((await searchCredit(f.env.DB, ACCOUNT)).reservedUnits, 0);
  assert.equal(f.debits(), 0); assert.equal(f.balance(), 200);
  assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM search_jobs WHERE query_json IS NOT NULL').get().n, 0);
});

test('owner-reported failure uses a fixed code, releases the hold and cannot later complete', async t => {
  const f = await fixture(t); await f.enqueue(); const { job } = await claimQueuedSearch(f.env, NOW);
  assert.deepEqual(await failQueuedSearch(f.env, job.jobId, job.claimToken, NOW + 1), { failed: true, charged: false });
  await assert.rejects(completeQueuedSearch(f.env, job.jobId, job.claimToken, computed(job), NOW + 2), code('search_claim_lost'));
  assert.equal((await searchCredit(f.env.DB, ACCOUNT)).units, 200);
});

test('partial settlement failure rolls back the result, debit, ledger and released reservation', async t => {
  const f = await fixture(t); await f.enqueue(); const { job } = await claimQueuedSearch(f.env, NOW);
  f.sql.exec("CREATE TRIGGER injected_failure BEFORE INSERT ON searches BEGIN SELECT RAISE(ABORT,'simulated disk/SQL failure'); END;");
  await assert.rejects(completeQueuedSearch(f.env, job.jobId, job.claimToken, computed(job), NOW + 1), /simulated disk\/SQL failure/);
  assert.equal(f.debits(), 0); assert.equal(f.balance(), 200);
  assert.equal((await searchCredit(f.env.DB, ACCOUNT)).reservedUnits, 100);
  assert.equal(f.sql.prepare('SELECT state,claim_token FROM search_jobs').get().claim_token, job.claimToken);
  f.sql.exec('DROP TRIGGER injected_failure');
  await completeQueuedSearch(f.env, job.jobId, job.claimToken, computed(job), NOW + 2);
  assert.equal(f.debits(), 1); assert.equal(f.balance(), 100);
});

test('wrong fingerprints, unpublished membership and configuration changes never settle', async t => {
  const f = await fixture(t); await f.enqueue(); const { job } = await claimQueuedSearch(f.env, NOW);
  const good = computed(job);
  for (const changed of [{ policyId: 'wrong' }, { runtimeSha256: '0'.repeat(64) }, { snapshotSha256: '0'.repeat(64) },
    { requestSha256: '0'.repeat(64) }, { contractVersion: 1 }, { processedLocations: 0 },
    { hits: [{ ...good.hits[0], score: 2 }] }]) {
    await assert.rejects(completeQueuedSearch(f.env, job.jobId, job.claimToken, { ...good, ...changed }, NOW + 1), code('search_unavailable'));
  }
  f.sql.exec("UPDATE locations SET contributor_id=NULL WHERE id=1");
  await assert.rejects(completeQueuedSearch(f.env, job.jobId, job.claimToken, good, NOW + 1), code('search_unavailable'));
  f.env.SEARCH_SNAPSHOT_SHA256 = '0'.repeat(64);
  await assert.rejects(completeQueuedSearch(f.env, job.jobId, job.claimToken, good, NOW + 1), code('search_unavailable'));
  assert.equal((await claimQueuedSearch(f.env, NOW + 301)).job, null);
  await maintainSearchQueue(f.env.DB, NOW + SEARCH_JOB_SECONDS);
  assert.equal((await searchCredit(f.env.DB, ACCOUNT)).reservedUnits, 0); assert.equal(f.debits(), 0);
});

test('other accounts cannot read or cancel a queued or completed result', async t => {
  const f = await fixture(t); const queued = await f.enqueue();
  await assert.rejects(queuedSearchStatus(f.env, OTHER, queued.jobId, NOW), code('search_not_found'));
  await assert.rejects(cancelQueuedSearch(f.env, OTHER, keyFor('saved-request-key'), NOW), code('search_not_found'));
  const { job } = await claimQueuedSearch(f.env, NOW);
  await completeQueuedSearch(f.env, job.jobId, job.claimToken, computed(job), NOW + 1);
  await assert.rejects(queuedSearchStatus(f.env, OTHER, queued.jobId, NOW + 2), code('search_not_found'));
});

test('account deletion removes claimed queries, preserves contributions and fences a late result', async t => {
  const f = await fixture(t); await f.enqueue(); const { job } = await claimQueuedSearch(f.env, NOW);
  const deletion = { accountId: ACCOUNT, confirmation: 'DELETE', idempotencyKey: '0'.repeat(64) };
  const receipt = await deleteAccount(f.env, ACCOUNT, deletion, NOW + 1);
  assert.equal(receipt.unitsForfeited, 200);
  assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM search_jobs').get().n, 0);
  assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM published_index').get().n, 1);
  await assert.rejects(completeQueuedSearch(f.env, job.jobId, job.claimToken, computed(job), NOW + 2), code('search_claim_lost'));
  await assert.rejects(f.enqueue('after-deletion'), code('unauthorized'));
  assert.equal(f.debits(), 0);
});

test('deletion between result validation and settlement still prevents charge and private-data resurrection', async t => {
  const f = await fixture(t); await f.enqueue(); const { job } = await claimQueuedSearch(f.env, NOW);
  const original = f.env.DB.batch.bind(f.env.DB);
  f.env.DB.batch = async statements => {
    f.sql.prepare('UPDATE accounts SET deleted_at=?,units=0 WHERE id=?').run(NOW + 1, ACCOUNT);
    return original(statements);
  };
  await assert.rejects(completeQueuedSearch(f.env, job.jobId, job.claimToken, computed(job), NOW + 2), code('search_claim_lost'));
  assert.equal(f.debits(), 0); assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM searches').get().n, 0);
});

test('reopening a saved SQLite database retains reservations and paid replies; terminal pruning preserves payment', async t => {
  const directory = mkdtempSync(join(tmpdir(), 'vision-search-queue-'));
  const file = join(directory, 'queue.sqlite'); const f = await fixture(t, { file }); await f.enqueue();
  f.sql.close();
  const reopened = new DatabaseSync(file); t.after(() => reopened.close()); const env = { ...f.env, DB: d1(reopened) };
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  assert.equal((await searchCredit(env.DB, ACCOUNT)).reservedUnits, 100);
  const { job } = await claimQueuedSearch(env, NOW + 1);
  await completeQueuedSearch(env, job.jobId, job.claimToken, computed(job), NOW + 2);
  const saved = await queuedSearchStatus(env, ACCOUNT, job.jobId, NOW + 3);
  await maintainSearchQueue(env.DB, NOW + SEARCH_JOB_SECONDS + 86401);
  assert.equal(reopened.prepare('SELECT COUNT(*) AS n FROM search_jobs').get().n, 0);
  assert.deepEqual(await queueSearch(env, ACCOUNT, keyFor('saved-request-key'), f.query), saved);
  assert.equal(reopened.prepare('SELECT units FROM accounts WHERE id=?').get(ACCOUNT).units, 100);
  assert.equal(reopened.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='search'").get().n, 1);
});

test('queue is off by default and refuses missing schema, dynamic pins, huge queries and unapproved prices/lanes', async t => {
  const f = await fixture(t, { migrate: false });
  await assert.rejects(requireSearchQueue(f.env.DB), code('schema_update_required'));
  f.sql.exec(QUEUE);
  const off = { ...f.env }; delete off.SEARCH_DELIVERY;
  assert.equal(queuedSearchConfigured(off), false);
  assert.equal(queuedSearchConfigured({ ...f.env, SEARCH_DYNAMIC_SNAPSHOT: '1' }), false);
  await assert.rejects(f.enqueue(undefined, { prompt: 'x'.repeat(65537) }), code('search_query_too_large'));
  await assert.rejects(f.enqueue(undefined, { resultCount: 1001 }), code('search_query_too_large'));
  await assert.rejects(f.enqueue(undefined, {}, { maxCostUnits: 99 }), code('search_price_changed'));
  await assert.rejects(f.enqueue(undefined, { lane: 'object' }, { allowNew: false }), code('object_verification_unavailable'));
  assert.equal((await searchCredit(f.env.DB, ACCOUNT)).reservedUnits, 0);
});

test('separate owner authentication rejects user tokens and wrong secrets', async t => {
  const f = await fixture(t);
  for (const authorization of ['', 'Bearer account-token', `Bearer ${'0'.repeat(64)}`])
    await assert.rejects(requireSearchAgent(f.env, new Request('https://fixture.invalid', { headers: { authorization } })), code('unauthorized'));
  await requireSearchAgent(f.env, new Request('https://fixture.invalid', { headers: { authorization: `Bearer ${f.env.SEARCH_AGENT_SECRET}` } }));
});

test('bounded active slots reject excess work without trapping credit; cancellation frees a slot', async t => {
  const f = await fixture(t, { units: 1000 });
  for (let n = 0; n < 3; n++) await f.enqueue(`request-number-${n}`);
  await assert.rejects(f.enqueue('fourth-request'), code('search_queue_full'));
  await cancelQueuedSearch(f.env, ACCOUNT, keyFor('request-number-0'), NOW);
  await f.enqueue('fourth-request'); assert.equal((await searchCredit(f.env.DB, ACCOUNT)).reservedUnits, 300);
});

test('HTTP enqueue, credit display, owner delivery and browser recovery agree without any engine binding', async t => {
  const f = await fixture(t); await prepareDatabase(f.env.DB);
  delete f.env.SEARCH_ENGINE;
  f.sql.prepare('UPDATE accounts SET token_hash=? WHERE id=?').run(await sha256Hex(encodeUtf8('user-token')), ACCOUNT);
  f.sql.prepare('UPDATE accounts SET token_hash=? WHERE id=?').run(await sha256Hex(encodeUtf8('other-token')), OTHER);
  const request = (path, body, secret = 'user-token', method = 'POST') => new Request('https://fixture.invalid' + path, {
    method, headers: { authorization: `Bearer ${secret}`, 'content-type': 'application/json' },
    ...(method === 'POST' ? { body: JSON.stringify(body) } : {}),
  });
  const body = { accountId: ACCOUNT, idempotencyKey: keyFor('http-browser-request', Math.floor(Date.now()/1000)), lane: 'scene', prompt: 'red door', maxCostUnits: 100 };
  const pending = await worker.fetch(request('/api/searches', body), f.env);
  assert.equal(pending.status, 202); const queued = await pending.json();
  const status = await worker.fetch(request('/api/me?lite=1', null, 'user-token', 'GET'), f.env);
  assert.equal(status.status, 200); const credit = await status.json();
  assert.equal(credit.bankedUnits, 200); assert.equal(credit.reservedUnits, 100); assert.equal(credit.units, 100);
  assert.equal(credit.searchDelivery, 'queued'); assert.equal(credit.searchReady, true);
  const forbidden = await worker.fetch(request('/api/search-agent/claim', {}), f.env);
  assert.equal(forbidden.status, 401);
  const claim = await worker.fetch(request('/api/search-agent/claim', { lanes: ['scene'] }, f.env.SEARCH_AGENT_SECRET), f.env);
  assert.equal(claim.status, 200); const { job } = await claim.json(); assert.equal(job.jobId, queued.jobId);
  const done = await worker.fetch(request('/api/search-agent/complete', {
    jobId: job.jobId, claimToken: job.claimToken, result: computed(job),
  }, f.env.SEARCH_AGENT_SECRET), f.env);
  assert.equal(done.status, 200);
  const recovered = await worker.fetch(request('/api/searches', body), f.env);
  assert.equal(recovered.status, 200); assert.equal((await recovered.json()).map.customCoordinates.length, 1);
  const smallRecovery = await worker.fetch(request(`/api/searches/recover?idempotencyKey=${encodeURIComponent(body.idempotencyKey)}`, null, 'user-token', 'GET'), f.env);
  assert.equal(smallRecovery.status, 200); assert.equal((await smallRecovery.json()).searchId, job.jobId);
  assert.equal(f.balance(), 100); assert.equal(f.debits(), 1);
  const other = await worker.fetch(request(`/api/search-jobs?jobId=${job.jobId}`, null, 'other-token', 'GET'), f.env);
  assert.equal(other.status, 404);
  f.env.RESTORE_MAINTENANCE = '1';
  assert.equal((await worker.fetch(request('/api/search-agent/claim', {}, f.env.SEARCH_AGENT_SECRET), f.env)).status, 503);
});

test('owner routes refuse account credentials before database/body access and enforce small streaming bounds', async t => {
  const f = await fixture(t); const noDatabase = { ...f.env, DB: { prepare() { throw Error('database must not be touched'); } } };
  const bad = new Request('https://fixture.invalid/api/search-agent/claim', { method: 'POST', headers: { authorization: 'Bearer user-token' }, body: '{}' });
  assert.equal((await worker.fetch(bad, noDatabase)).status, 401);
  await prepareDatabase(f.env.DB);
  const huge = new Request('https://fixture.invalid/api/search-agent/claim', { method: 'POST',
    headers: { authorization: `Bearer ${f.env.SEARCH_AGENT_SECRET}`, 'content-type': 'application/json' }, body: JSON.stringify({ data: 'x'.repeat(4096) }) });
  assert.equal((await worker.fetch(huge, f.env)).status, 413);
  assert.equal(f.debits(), 0);
});

test('a Scene-only owner never claims Objects; queued Object settlement retains strict official Gen4 authority', async t => {
  const f = await fixture(t);
  await f.enqueue(undefined, { lane: 'object', filters: { mode: 'all', countries: [], generations: ['gen4'] } });
  assert.equal((await claimQueuedSearch(f.env, NOW)).job, null);
  const { job } = await claimQueuedSearch(f.env, NOW, ['object']); const result = computed(job);
  result.hits[0] = { ...result.hits[0], viewOffset: 0, heading: 45, pitch: 5, zoom: 1,
    object: { lane: 'common', className: 'car', classId: 3, confidence: 0.8, supportCount: 2, bboxArea: 0.1 } };
  f.sql.exec("UPDATE locations SET lane='object'; UPDATE published_index SET object_index_key='object-index-v4/test/';");
  await assert.rejects(completeQueuedSearch(f.env, job.jobId, job.claimToken, result, NOW + 1), code('search_unavailable'));
  f.sql.exec(`INSERT INTO object_coverage VALUES(1,'official-gen4-historical-v2-exact-pano','${'0'.repeat(64)}',0); UPDATE locations SET camera_generation='gen3';`);
  await assert.rejects(completeQueuedSearch(f.env, job.jobId, job.claimToken, result, NOW + 1), code('search_unavailable'));
  f.sql.exec("UPDATE locations SET camera_generation='gen4'");
  await completeQueuedSearch(f.env, job.jobId, job.claimToken, result, NOW + 1);
  assert.equal(f.debits(), 1);
});

test('closing cohort before claim releases the hold without giving the query to the owner', async t => {
  const f = await fixture(t); await f.enqueue(); f.env.SCENE_COHORT_ACCOUNTS = '[]';
  assert.equal((await claimQueuedSearch(f.env, NOW)).job, null);
  assert.equal((await searchCredit(f.env.DB, ACCOUNT)).reservedUnits, 0); assert.equal(f.debits(), 0);
});

test('global active and retained-row bounds reject new work and prune only old terminal jobs', async t => {
  const f = await fixture(t, { units: 1000 });
  const row = f.sql.prepare(`INSERT INTO search_jobs
    (id,account_id,idempotency_key,query_digest,query_json,lane,binding_json,cost_units,state,created_at,expires_at)
    VALUES(?,?,?,'sha256:fixture','{}','scene','{}',1,'queued',?,?)`);
  for (let n = 0; n < 128; n++) {
    const account = `capacity-${Math.floor(n / 3)}`;
    f.sql.prepare('INSERT OR IGNORE INTO accounts(id,token_hash,units) VALUES(?,?,1000)').run(account, account);
    row.run(n.toString(16).padStart(32, '0'), account, `fixture-${n}`, NOW, NOW + 3600);
  }
  await assert.rejects(f.enqueue(), code('search_queue_full'));
  f.sql.exec("UPDATE search_jobs SET state='cancelled',query_json=NULL");
  for (let n = 128; n < 512; n++) {
    row.run(n.toString(16).padStart(32, '0'), ACCOUNT, `fixture-${n}`, NOW, NOW + 3600);
    f.sql.prepare("UPDATE search_jobs SET state='cancelled',query_json=NULL WHERE id=?").run(n.toString(16).padStart(32, '0'));
  }
  await assert.rejects(f.enqueue(), code('search_queue_full'));
  await maintainSearchQueue(f.env.DB, NOW + SEARCH_JOB_SECONDS + 86401);
  assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM search_jobs').get().n, 448);
  assert.equal((await f.enqueue()).state, 'queued'); assert.equal(f.balance(), 1000);
});

test('pruning a failed/cancelled request can never silently re-enqueue that old recovery key', async t => {
  const f = await fixture(t); await f.enqueue();
  await cancelQueuedSearch(f.env, ACCOUNT, keyFor('saved-request-key'), NOW + 1);
  await maintainSearchQueue(f.env.DB, NOW + SEARCH_JOB_SECONDS + 86401);
  assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM search_jobs').get().n, 0);
  await assert.rejects(f.enqueue(undefined, {}, { now: NOW + SEARCH_JOB_SECONDS + 86402 }), code('search_request_expired'));
  await assert.rejects(queueSearch(f.env, ACCOUNT, keyFor('future', NOW + 301), f.query, { now: NOW }), code('search_request_expired'));
  assert.equal(f.balance(), 200); assert.equal(f.debits(), 0);
});

test('pre-migration paid keys replay unchanged even with no enabled queue, owner secret or valid new-request timestamp', async t => {
  const f = await fixture(t);
  const paid = { searchId: '1'.repeat(32), costUnits: 100, map: { name: 'Historical exact reply', customCoordinates: [] } };
  await settleSearch(f.env.DB, ACCOUNT, 'historical-key', await searchDigest(f.query), paid, 100);
  delete f.env.SEARCH_AGENT_SECRET; delete f.env.SEARCH_DELIVERY;
  assert.deepEqual(await queueSearch(f.env, ACCOUNT, 'historical-key', f.query), paid);
  assert.equal(f.balance(), 100); assert.equal(f.debits(), 1);
});

test('optional schema migration rolls back without changing old data; preflight detects removed or weakened guards', async t => {
  const f = await fixture(t, { migrate: false });
  const original = JSON.stringify(f.sql.prepare('SELECT * FROM accounts ORDER BY id').all());
  f.sql.exec('BEGIN IMMEDIATE'); f.sql.exec(QUEUE); f.sql.exec('ROLLBACK');
  await assert.rejects(requireSearchQueue(f.env.DB), code('schema_update_required'));
  assert.equal(JSON.stringify(f.sql.prepare('SELECT * FROM accounts ORDER BY id').all()), original);
  f.sql.exec('BEGIN IMMEDIATE'); f.sql.exec(QUEUE); f.sql.exec('COMMIT');
  await f.enqueue();
  assert.deepEqual(checkSearchQueue(f.sql), { passed: true, revision: 1, jobs: 1, active: 1, offline: true, liveReady: false });
  f.sql.exec('DROP TRIGGER search_jobs_credit_guard');
  assert.throws(() => checkSearchQueue(f.sql), /search_queue_schema_mismatch/);
  f.sql.exec('CREATE TRIGGER search_jobs_credit_guard BEFORE UPDATE OF units ON accounts BEGIN SELECT 1; END');
  assert.throws(() => checkSearchQueue(f.sql), /search_queue_schema_mismatch/);
  assert.equal(JSON.stringify(f.sql.prepare('SELECT * FROM accounts ORDER BY id').all()), original);
});

test('read-only recovery returns old large-map paid replies without needing the queue schema or original query upload', async t => {
  const f = await fixture(t, { migrate: false });
  const historicalQuery = { ...f.query, excluded: Array.from({ length: 3000 }, (_, n) => ({ lat: n / 100, lng: 2, panoId: `old-example-${n}` })) };
  assert.ok(encodeUtf8(JSON.stringify(historicalQuery)).length > 65536);
  const paid = { searchId: '2'.repeat(32), costUnits: 100, map: { name: 'Historical map', customCoordinates: [] } };
  await settleSearch(f.env.DB, ACCOUNT, 'large-historical-query', await searchDigest(historicalQuery), paid, 100);
  assert.deepEqual(await recoverSearch(f.env, ACCOUNT, 'large-historical-query', NOW), paid);
  delete f.env.SEARCH_DELIVERY;
  await assert.rejects(recoverSearch(f.env, OTHER, 'large-historical-query', NOW), code('search_not_found'));
  assert.equal(f.balance(), 100); assert.equal(f.debits(), 1);
});

test('rollback to synchronous delivery cannot execute a pruned unpaid request; old paid timestamped keys still replay', async t => {
  const f = await fixture(t);
  await f.enqueue('cancelled-before-rollback');
  await cancelQueuedSearch(f.env, ACCOUNT, keyFor('cancelled-before-rollback'), NOW + 1);
  await f.enqueue('paid-before-rollback');
  const { job } = await claimQueuedSearch(f.env, NOW + 1);
  await completeQueuedSearch(f.env, job.jobId, job.claimToken, computed(job), NOW + 2);
  await maintainSearchQueue(f.env.DB, NOW + 90001);
  assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM search_jobs').get().n, 0);
  t.mock.method(Date, 'now', () => (NOW + 90001) * 1000);
  delete f.env.SEARCH_DELIVERY;
  // The fixture engine throws if contacted: expired recovery must fail before
  // any computation, and paid recovery must return without new computation.
  await assert.rejects(onlineSearch(f.env, ACCOUNT, keyFor('cancelled-before-rollback'), f.query), code('search_request_expired'));
  assert.equal((await onlineSearch(f.env, ACCOUNT, keyFor('paid-before-rollback'), f.query)).searchId, job.jobId);
  assert.equal(f.balance(), 100); assert.equal(f.debits(), 1);
});
