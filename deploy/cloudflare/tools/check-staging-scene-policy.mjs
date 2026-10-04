// Actual local workerd/D1: reserved staging admission IDs cannot open production.
import assert from 'node:assert/strict';
import { resolve, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
const [miniflarePath, bundlePath] = process.argv.slice(2);
const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(miniflarePath)).href);
let calls = 0;
const base = { DEPLOYMENT_ENVIRONMENT: 'staging', INDEX_BUCKET_NAME: 'vision-community-staging',
  SCENE_POLICY_ID: 'staging.measured-candidate' };
const cases = [{}, { DEPLOYMENT_ENVIRONMENT: 'production' }, { DEPLOYMENT_ENVIRONMENT: '' },
  { INDEX_BUCKET_NAME: 'vision-community' }, { INDEX_BUCKET_NAME: '' }];
for (const [index, change] of cases.entries()) {
  const options = { modules: true, scriptPath: resolve(bundlePath), modulesRoot: dirname(resolve(bundlePath)),
    compatibilityDate: '2026-09-19', compatibilityFlags: ['nodejs_compat'],
    d1Databases: ['DB'], r2Buckets: ['INDEX'], bindings: { ...base, ...change },
    serviceBindings: { ASSETS: () => new Response('', {status:404}),
      SCENE_VERIFIER: () => { calls++; return Response.json({error:'must_not_execute'}, {status:503}); } } };
  const mf = new Miniflare(convertV4MiniflareOptions ? convertV4MiniflareOptions(options) : options);
  try {
    const response = await mf.dispatchFetch('https://community.test/api/capabilities');
    assert.equal(response.status, 200);
    assert.equal((await response.json()).sceneContributions.ready, index === 0);
    const created = await mf.dispatchFetch('https://community.test/api/accounts', { method:'POST',
      headers:{'content-type':'application/json',origin:'https://community.test'},body:'{}' });
    assert.equal(created.status,201);
    const account = (await created.json()).accountId;
    const cookie = created.headers.get('set-cookie').split(';')[0];
    const qualified = await mf.dispatchFetch('https://community.test/api/scene-qualifications', {method:'POST',
      headers:{'content-type':'application/json',origin:'https://community.test',cookie},
      body:JSON.stringify({accountId:account})});
    assert.equal(qualified.status, index === 0 ? 400 : 503);
  } finally { await mf.dispose(); }
}
assert.equal(calls, 0);
console.log(JSON.stringify({status:'STAGING_SCENE_POLICY_ISOLATION_PASSED',actualWorkerdCases:cases.length,
  nativeCalls:0,productionChanged:false}));
