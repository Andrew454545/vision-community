// Finite actual workerd/D1 check. Explicit synthetic account/publication/credit.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve,dirname,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {prepareDatabase} from './initialize-schema.mjs';
import {localRateLimits} from './local-api-bindings.mjs';
const [runtime,bundle]=process.argv.slice(2);
const dynamic=process.argv[4]==='dynamic';
let snapshot='c'.repeat(64),headAvailable=true;
const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(runtime)).href);
const root=mkdtempSync(join(tmpdir(),'vision-cohort-'));
const hash=value=>createHash('sha256').update(value).digest('hex');
const account='a'.repeat(32),token='synthetic-cohort-account',other='b'.repeat(32);
let calls=0,mf,db;
async function start(deadline) {
  await mf?.dispose();
  const scriptPath=resolve(bundle);
  const options={modules:true,scriptPath,modulesRoot:dirname(scriptPath),compatibilityDate:'2026-09-19',
    compatibilityFlags:['nodejs_compat'],resourcePersistencePath:root,d1Databases:['DB'],r2Buckets:['INDEX'],
    ratelimits:localRateLimits(),bindings:{RATE_LIMITS_REQUIRED:'1',DEPLOYMENT_ENVIRONMENT:'staging',
      INDEX_BUCKET_NAME:'vision-community-staging',DELETION_ARCHIVE_DB_ID:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',
      SCENE_POLICY_ID:'staging.synthetic-cohort',SCENE_COHORT_ACCOUNTS:JSON.stringify([hash(account)]),
      SCENE_COHORT_UNTIL:String(deadline),SEARCH_COST_UNITS:'8',SEARCH_POLICY_ID:'synthetic',
      SEARCH_RUNTIME_SHA256:'b'.repeat(64),SEARCH_SNAPSHOT_SHA256:'c'.repeat(64),...(dynamic?{SEARCH_DYNAMIC_SNAPSHOT:'1'}:{})},
    serviceBindings:{ASSETS:()=>new Response('offline fixture'),
      SCENE_VERIFIER:()=>{throw Error('unexpected verifier work');},
      SEARCH_ENGINE:async request=>{
        if(new URL(request.url).pathname==='/snapshot')return headAvailable?Response.json({policyId:'synthetic',
          runtimeSha256:'b'.repeat(64),snapshotSha256:snapshot,bundleSha256:'f'.repeat(64)}):Response.json({error:'unavailable'},{status:503});
        calls++;const body=await request.json();assert.equal(body.snapshotSha256,dynamic?snapshot:'c'.repeat(64));
        return Response.json({...body,processedLocations:1,
          hits:[{locationId:1,outputSha256:'a'.repeat(64),sourceIndex:0,score:.8,viewOffset:1}]});
      }}};
  mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
  db=await mf.getD1Database('DB');
}
function call(path, credential, body) {
  return mf.dispatchFetch('https://community.test/api/'+path,{
    method:body===undefined?'GET':'POST',headers:{'content-type':'application/json',
      ...(credential?{authorization:'Bearer '+credential}:{})},
    ...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(10000)});
}
const balance=async()=> (await db.prepare('SELECT units FROM accounts WHERE id=?').bind(account).first()).units;
let cases=0;
try {
  await start(Date.now()+3600000);await prepareDatabase(db);
  for(const [id,credential] of [[account,token],[other,'other-token']])
    await db.prepare('INSERT INTO accounts(id,token_hash,units) VALUES(?,?,16)').bind(id,hash(credential)).run();
  await db.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,country,camera_generation)
    VALUES(1,'abcdefghijklmnopqrstuv','2026-01','scene','synthetic','published','synthetic-contributor',10,20,90,'Italy','gen4')`).run();
  await db.prepare('INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_key) VALUES(1,?,?,0,?)')
    .bind('','a'.repeat(64),'four-view-v4/synthetic.i8').run();
  for(const [credential,ready] of [[undefined,false],['forged',false],['other-token',false],[token,true]]) {
    const response=await call('capabilities',credential);assert.equal(response.status,200);
    const result=await response.json();assert.equal(result.sceneContributions.ready,ready);
    assert.equal(result.objectContributions.ready,false);cases++;
  }
  for(const path of ['scene-qualifications','scene-audits','leases','submissions']) {
    const response=await call(path,'other-token',{});assert.equal(response.status,503);
    assert.equal((await response.json()).error,'scene_verification_unavailable');cases++;
  }
  assert.equal((await (await call('status')).json()).searchReady,false);cases++;
  const body={accountId:account,prompt:'a street',resultCount:1,idempotencyKey:'paid-before-cohort-expiry',maxCostUnits:8};
  const paidResponse=await call('searches',token,body);assert.equal(paidResponse.status,200);
  const paid=await paidResponse.json();assert.equal(paid.costUnits,8);assert.equal(await balance(),8);
  assert.equal(calls,1);cases++;
  let expectedBalance=8,expectedCalls=1;
  if(dynamic){
    headAvailable=false;
    const saved=await call('searches',token,body);assert.equal(saved.status,200);assert.deepEqual(await saved.json(),paid);
    assert.equal(await balance(),8);assert.equal(calls,1);cases++;
    const missing=await call('searches',token,{...body,idempotencyKey:'new-without-head'});
    assert.equal(missing.status,503);assert.equal(await balance(),8);assert.equal(calls,1);cases++;
    headAvailable=true;snapshot='e'.repeat(64);
    const refreshed=await call('searches',token,{...body,idempotencyKey:'paid-after-refresh'});
    assert.equal(refreshed.status,200);assert.equal((await refreshed.json()).costUnits,8);
    assert.equal(await balance(),0);assert.equal(calls,2);expectedBalance=0;expectedCalls=2;cases++;
    headAvailable=false;
  }
  await start(Date.now()-1000);
  const replay=await call('searches',token,body);assert.equal(replay.status,200);
  assert.deepEqual(await replay.json(),paid);assert.equal(await balance(),expectedBalance);assert.equal(calls,expectedCalls);cases++;
  const refused=await call('searches',token,{...body,idempotencyKey:'new-after-cohort-expiry'});
  assert.equal(refused.status,503);assert.equal((await refused.json()).error,'search_unavailable');
  assert.equal(await balance(),expectedBalance);assert.equal(calls,expectedCalls);cases++;
  const expired=await call('capabilities',token);assert.equal((await expired.json()).sceneContributions.ready,false);cases++;
  const deleted=await call('account/delete',token,{accountId:account,confirmation:'DELETE',idempotencyKey:hash('delete-expired-cohort-account')});assert.equal(deleted.status,200);
  assert.equal((await deleted.json()).deleted,true);cases++;
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_FINITE_SCENE_COHORT_PASSED',cases,
    syntheticFixture:true,dynamicSnapshot:dynamic,realContributions:0,realCredits:0,privateNativeCalls:0,syntheticSearchCalls:calls}));
} finally {await mf?.dispose();}
