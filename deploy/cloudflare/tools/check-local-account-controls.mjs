// Actual local workerd/D1/R2/rate limits. Synthetic accounts and pool only.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve,dirname,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {runInNewContext} from 'node:vm';
import {prepareDatabase} from './initialize-schema.mjs';
import {localRateLimits} from './local-api-bindings.mjs';
import {deleteAccount} from '../src/accountPrivacy.js';
const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(process.argv[2])).href);
const path=resolve(process.argv[3]),hash=v=>createHash('sha256').update(v).digest('hex');
const account='a'.repeat(32),token='synthetic-browser-controls',scope={AbortSignal};
runInNewContext(readFileSync(new URL('../../../community/web/service-readiness.js',import.meta.url),'utf8'),scope);
let nativeCalls=0,checks=0;const requests=[];
const options={modules:true,scriptPath:path,modulesRoot:dirname(path),compatibilityDate:'2026-09-19',
  compatibilityFlags:['nodejs_compat'],resourcePersistencePath:mkdtempSync(join(tmpdir(),'browser-controls-')),
  d1Databases:['DB'],r2Buckets:['INDEX'],ratelimits:localRateLimits(),bindings:{RATE_LIMITS_REQUIRED:'1',
    DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',
    SCENE_ADMISSION_MODE:'qualified-device-v1',SCENE_POLICY_ID:'staging.fixture',SCENE_AUDIT_MAX_LOCATIONS:'2',
    SEARCH_COST_UNITS:'2',SEARCH_POLICY_ID:'fixture',SEARCH_RUNTIME_SHA256:'b'.repeat(64),SEARCH_SNAPSHOT_SHA256:'c'.repeat(64)},
  serviceBindings:{SEARCH_ENGINE:()=>{nativeCalls++;throw Error('No native calls permitted');}}};
const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
async function call(route,credential=token){
  const response=await mf.dispatchFetch('https://fixture.test/api/'+route,{headers:{authorization:'Bearer '+credential}});
  const usage={};for(const [key,suffix]of Object.entries({read:'rows-read',written:'rows-written',puts:'r2-puts',bytes:'r2-bytes'}))
    usage[key]=Number(response.headers.get('x-vision-trial-'+suffix));
  const r2=Number(response.headers.get('x-controls-fixture-r2-calls'));
  requests.push({path:'/api/'+route,status:response.status,usage,r2Calls:r2});return response;
}
try{
  const db=await mf.getD1Database('DB');await prepareDatabase(db);
  await db.prepare('INSERT INTO accounts(id,token_hash,recovery_hash,units) VALUES(?,?,?,10)')
    .bind(account,hash(token),'synthetic-recovery-hash').run();
  await db.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES(?,10,'contribution','fixture')").bind(account).run();
  await db.prepare(`WITH RECURSIVE n(x) AS(VALUES(1000) UNION ALL SELECT x+1 FROM n WHERE x<2023)
    INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,country,camera_generation)
    SELECT x,'synthetic-'||x,'fixture','scene','fixture','published',?,'Italy','gen4' FROM n`).bind(account).run();
  await db.prepare(`INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_key)
    SELECT id,'',?,0,'four-view-v4/synthetic-fixture.i8' FROM locations`).bind('d'.repeat(64)).run();
  let response=await call('me?controls=1');assert.equal(response.status,200);
  const controls=await response.json();assert.equal(controls.units,10);assert.equal(controls.searchesAvailable,5);checks++;
  assert.equal(controls.accountControlVersion,1);assert.equal(controls.searchReady,true);checks++;
  assert.deepEqual(requests.at(-1).usage,{read:3,written:0,puts:0,bytes:0});assert.equal(requests.at(-1).r2Calls,0);checks++;
  const merged=scope.VisionServiceReadiness.mergeAccountControls({accountId:account,countries:['Italy']},controls);
  assert.equal(merged.units,10);assert.equal(merged.countries[0],'Italy');checks++;
  response=await call('capabilities');assert.equal(response.status,200);const capabilities=await response.json();
  assert.equal(capabilities.sceneContributions.admissionMode,'qualified-device-v1');
  assert.equal(capabilities.objectContributions.ready,false);assert.equal(requests.at(-1).usage.read,1);checks++;
  response=await call('me?controls=1');assert.deepEqual(await response.json(),controls);checks++;
  const dashboard=await call('me?lite=1');assert.equal(dashboard.status,200);const full=await dashboard.json();
  for(const key of ['searchReady','searchOnSite','searchCost','searchBackend','searchDelivery','searchResultLimits','indexDownloads','accountDeletionAvailable'])
    assert.deepEqual(controls[key],full[key]);checks++;
  assert.ok(requests.at(-1).usage.read>1024);assert.equal(requests.at(-1).r2Calls,0);checks++;
  response=await call('status?controls=1');assert.equal(response.status,200);
  const anonymous=await response.json();assert.equal(anonymous.accountId,null);assert.equal(anonymous.units,0);
  assert.equal(anonymous.accountDeletionAvailable,true);assert.equal(requests.at(-1).usage.read,1);checks++;
  scope.VisionServiceReadiness.mergeAccountControls(merged,anonymous);checks++;
  assert.equal((await call('me?controls=1','wrong')).status,401);checks++;
  assert.equal((await db.prepare('SELECT units FROM accounts WHERE id=?').bind(account).first()).units,10);
  assert.equal((await db.prepare('SELECT COUNT(*) n FROM ledger').first()).n,1);
  assert.equal((await db.prepare('SELECT COUNT(*) n FROM searches').first()).n,0);checks++;
  await deleteAccount({DB:db},account,{accountId:account,confirmation:'DELETE',idempotencyKey:'9'.repeat(64)});
  assert.equal((await call('me?controls=1')).status,401);checks++;
  assert.equal((await db.prepare('SELECT units FROM accounts WHERE id=?').bind(account).first()).units,0);
  assert.equal((await db.prepare('SELECT COUNT(*) n FROM published_index').first()).n,1024);checks++;
  assert.equal(nativeCalls,0);assert.ok(requests.every(r=>r.r2Calls===0&&r.usage.written===0));checks++;
  console.log(JSON.stringify({status:'LOCAL_BROWSER_ACCOUNT_CONTROLS_PASS',checks,requests,nativeCalls,
    syntheticPublishedLocations:1024,accountAndPoolSynthetic:true,actualLocalWorkerdD1R2AndRateLimits:true,
    cloudResourcesAccessed:false,nativeInference:false,productionQualified:false}));
}finally{await mf.dispose();}
