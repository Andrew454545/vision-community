// Actual isolated workerd/D1 gateway checks. Replies are synthetic; this
// cannot approve a real PC or contact an account, model, imagery or cloud store.
import assert from 'node:assert/strict';
import { prepareDatabase } from './initialize-schema.mjs';
import { localRateLimits } from './local-api-bindings.mjs';
import { createHash } from 'node:crypto';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const [runtime, bundle] = process.argv.slice(2);
if (!runtime || !bundle) throw Error('Specify the local Miniflare entry and Worker bundle.');
const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(runtime)).href);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const record = Buffer.alloc(3080);
for (let view = 0; view < 4; view++) record[view * 770 + 1] = 60;
const canary = { locations: 112, records: Array(112).fill(record.toString('base64')),
  outputSha256: sha(Buffer.concat(Array(112).fill(record))) };
let mode = 'exact-boundary';
const options = { modules: true, scriptPath: resolve(bundle), modulesRoot: dirname(resolve(bundle)),
  compatibilityDate: '2026-09-19', compatibilityFlags: ['nodejs_compat'],
  d1Databases: ['DB'], r2Buckets: ['INDEX'],
  bindings: { SCENE_POLICY_ID: 'synthetic-local-replies-only',
    DEPLOYMENT_ENVIRONMENT: 'staging', INDEX_BUCKET_NAME: 'vision-community-staging' },
  serviceBindings: { ASSETS: () => new Response('', { status: 404 }),
    SCENE_VERIFIER: async request => {
      const body = await request.json();
      const decision = { approved: true, policyId: body.policyId, profileId: body.profileId,
        canarySha256: body.canarySha256, expiresAt: Math.floor(Date.now() / 1000) + 3600 };
      if (mode === 'exact-boundary') {
        const text = JSON.stringify(decision);
        return new Response(text + ' '.repeat(65536 - Buffer.byteLength(text)),
          { headers: { 'content-type': 'application/json' } });
      }
      if (mode === 'malformed') return new Response('{', { headers: { 'content-type': 'application/json' } });
      if (mode === 'array') return Response.json([decision]);
      if (mode === 'content-type') return new Response(JSON.stringify(decision), { headers: { 'content-type': 'text/html' } });
      if (mode === 'profile') decision.profileId = '0'.repeat(64);
      if (mode === 'missing-decision') delete decision.approved;
      if (mode === 'expiry') decision.expiresAt = 0;
      if (mode === 'oversized') decision.padding = 'X'.repeat(65536);
      if (mode === 'oversized-stream') return new Response(new ReadableStream({ start(controller) {
        controller.enqueue(Buffer.from(JSON.stringify(decision)));
        controller.enqueue(Buffer.alloc(65536, 32)); controller.close();
      } }), { headers: { 'content-type': 'application/json' } });
      if (mode === 'negative-200') return Response.json({ approved: false });
      if (mode === 'negative-422') return Response.json({ error: 'scene_device_not_qualified' }, { status: 422 });
      if (mode === 'stalled') return new Response(new ReadableStream(), { headers: { 'content-type': 'application/json' } });
      return Response.json(decision);
    } } };
options.ratelimits=localRateLimits();options.bindings.RATE_LIMITS_REQUIRED='1';
const mf = new Miniflare(convertV4MiniflareOptions ? convertV4MiniflareOptions(options) : options);
try {
  const db = await mf.getD1Database('DB');
  await prepareDatabase(db);
  const created = await mf.dispatchFetch('https://community.test/api/accounts', { method: 'POST',
    headers: { 'content-type': 'application/json', origin: 'https://community.test' }, body: '{}' });
  assert.equal(created.status, 201);
  const account = (await created.json()).accountId;
  const cookie = created.headers.get('set-cookie').split(';')[0];
  const cases = [['exact-boundary', 200], ['malformed', 503], ['array', 503], ['content-type', 503],
    ['profile', 503], ['missing-decision', 503], ['expiry', 503], ['oversized', 503],
    ['oversized-stream', 503], ['negative-200', 422], ['negative-422', 422], ['stalled', 503], ['retry', 200]];
  let approvals = 0;
  for (const [kind, status] of cases) {
    mode = kind;
    const response = await mf.dispatchFetch('https://community.test/api/scene-qualifications', { method: 'POST',
      headers: { 'content-type': 'application/json', origin: 'https://community.test', cookie },
      body: JSON.stringify({ accountId: account, profileId: 'b'.repeat(64), canary }) });
    assert.equal(response.status, status, kind);
    const body = await response.json();
    if (status === 200) { assert.equal(body.qualified, true, kind); approvals++; }
    else assert.equal(body.error, status === 503 ? 'scene_verification_unavailable' : 'scene_device_not_qualified', kind);
    assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM scene_qualifications').first()).n, approvals, kind);
    assert.equal((await db.prepare('SELECT units FROM accounts WHERE id=?').bind(account).first()).units, 0, kind);
    assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM ledger').first()).n, 0, kind);
    assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM published_index').first()).n, 0, kind);
  }
  console.log(JSON.stringify({ status: 'BOUNDED_VERIFIER_GATEWAY_REPLIES_PASSED', actualWorkerdCases: cases.length,
    syntheticQualifications: approvals, creditsChanged: 0, realPcQualifications: 0, cloudResourcesAccessed: false }));
} finally { await mf.dispose(); }
