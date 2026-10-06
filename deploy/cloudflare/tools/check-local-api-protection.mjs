// Finite actual workerd/D1/rate-limit checks. Synthetic data; no Cloudflare login.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {resolve,dirname} from 'node:path';
import {pathToFileURL} from 'node:url';
import {prepareDatabase} from './initialize-schema.mjs';
import {checkpointPlan,freshPlan} from './schema-plan.mjs';
const [runtime,bundle]=process.argv.slice(2);
const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(runtime)).href);
let sequence=0,rejected=0;
function instance(limits={},required=false) {
  const scriptPath=resolve(bundle),namespace=++sequence*10;
  const ratelimits=Object.fromEntries(Object.entries(limits).map(([name,limit],i)=>[name,{namespace_id:String(9000+namespace+i),simple:{limit,period:60}}]));
  const options={modules:true,scriptPath,modulesRoot:dirname(scriptPath),compatibilityDate:'2026-09-19',
    compatibilityFlags:['nodejs_compat'],d1Databases:['DB'],r2Buckets:['INDEX'],ratelimits,
    bindings:required?{RATE_LIMITS_REQUIRED:'1'}:{},
    serviceBindings:{ASSETS:()=>new Response('private offline guide')}};
  return new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
}
// workerd may lazily initialize its own _cf_METADATA on the first binding read.
const tables=async db=>(await db.prepare("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE '_cf_%' ORDER BY name").all()).results;
const base={API_INGRESS_LIMITER:1000,API_RATE_LIMITER:1000,API_VIEW_LIMITER:1000};
async function savedAccount(db) {
  const id='a'.repeat(32),token='synthetic-api-protection-token';
  await db.prepare('INSERT INTO accounts(id,token_hash,recovery_hash,units) VALUES(?,?,?,123456)')
    .bind(id,createHash('sha256').update(token).digest('hex'),'synthetic-saved-code').run();
  return {id,headers:{authorization:'Bearer '+token,'CF-Connecting-IP':'192.0.2.123'}};
}
async function unchanged(db,id) {
  assert.equal((await db.prepare('SELECT units FROM accounts WHERE id=?').bind(id).first()).units,123456);
  assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM ledger').first()).n,0);
  assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM searches').first()).n,0);
}
async function eventuallyLimited(mf,url,headers,initialStatus) {
  let received=0;
  for(let i=0;i<30;i++) {
    const response=await mf.dispatchFetch(url,{headers});
    if(response.status===429) {
      assert.deepEqual(await response.json(),{error:'rate_limited'});assert.equal(response.headers.get('retry-after'),'60');
      rejected++;return received;
    }
    assert.equal(response.status,initialStatus);received++;
  }
  throw Error('configured_counter_not_observed');
}
{
  const mf=instance({},true);
  try {
    const db=await mf.getD1Database('DB'),before=await tables(db);
    for(const route of ['status','capabilities','accounts']) {
      const response=await mf.dispatchFetch('https://community.test/api/'+route,{...(route==='accounts'?{method:'POST',body:'not JSON'}:{})});
      assert.equal(response.status,503);assert.deepEqual(await response.json(),{error:'rate_limit_unavailable'});
    }
    assert.deepEqual(await tables(db),before);
  }finally{await mf.dispose();}
}
{
  const mf=instance();
  try {
    const db=await mf.getD1Database('DB'),before=await tables(db);
    for(const route of ['status','capabilities','accounts']) {
      const response=await mf.dispatchFetch('https://community.test/api/'+route,{...(route==='accounts'?{method:'POST',body:'not JSON'}:{})});
      assert.equal(response.status,503);assert.deepEqual(await response.json(),{error:'schema_update_required'});
    }
    assert.deepEqual(await tables(db),before);
    const plan=await freshPlan();
    await db.batch(plan.map(q=>db.prepare(q)));
    assert.equal((await mf.dispatchFetch('https://community.test/api/status')).status,200);
    // Actual D1 checkpoint rejection must not advertise a damaged deletion fence.
    await db.prepare('DELETE FROM community_schema_revision').run();
    await db.prepare('DROP TRIGGER ledger_active_account_insert').run();
    await assert.rejects(db.batch(checkpointPlan().map(q=>db.prepare(q))));
    assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM community_schema_revision').first()).n,0);
    assert.equal((await mf.dispatchFetch('https://community.test/api/status')).status,503);
  }finally{await mf.dispose();}
}
{
  const mf=instance({...base,API_INGRESS_LIMITER:2},true);
  try {
    const db=await mf.getD1Database('DB');await prepareDatabase(db);
    let stopped=false;
    for(let i=0;i<30;i++) {
      const route=i%2?'me':'status';
      const response=await mf.dispatchFetch('https://community.test/api/'+route,{headers:{'CF-Connecting-IP':'192.0.2.123',authorization:'Bearer changing-invalid-token-'+i}});
      if(response.status===429){rejected++;stopped=true;break;}
      assert.ok([200,401].includes(response.status));
    }
    assert.equal(stopped,true);assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM accounts').first()).n,0);
  }finally{await mf.dispose();}
}
{
  const mf=instance({...base,API_RATE_LIMITER:2},true);
  try {
    const db=await mf.getD1Database('DB');await prepareDatabase(db);const a=await savedAccount(db);
    await eventuallyLimited(mf,'https://community.test/api/me?lite=1',a.headers,200);
    const upload=await mf.dispatchFetch('https://community.test/api/submissions',{method:'POST',headers:{...a.headers,'content-type':'application/json'},body:'not JSON'});
    assert.equal(upload.status,429);await unchanged(db,a.id);
  }finally{await mf.dispose();}
}
{
  const mf=instance({...base,API_VIEW_LIMITER:1},true);
  try {
    const db=await mf.getD1Database('DB');await prepareDatabase(db);const a=await savedAccount(db);
    // Invalid identity stops before imagery; repetitions still consume its preview budget.
    await eventuallyLimited(mf,'https://community.test/api/views?pano=x',a.headers,400);
    const me=await mf.dispatchFetch('https://community.test/api/me?lite=1',{headers:a.headers});
    assert.equal(me.status,200);await unchanged(db,a.id);
  }finally{await mf.dispose();}
}
{
  const mf=instance(base);
  try {
    const db=await mf.getD1Database('DB');await prepareDatabase(db);const a=await savedAccount(db);
    const capabilities=await mf.dispatchFetch('https://community.test/api/capabilities');
    assert.equal(capabilities.status,200);
    assert.deepEqual((await capabilities.json()).objectContributions,{
      ready:false,reason:'object_verification_unavailable',model:'vision-object-index-v4',
      deviceQualificationRequired:true,officialGen4Required:true});
    const before=await tables(db);
    for(const method of ['GET','POST']) {
      const response=await mf.dispatchFetch('https://community.test/api/object-qualifications?profileId='+'a'.repeat(64),
        {method,headers:{...a.headers,'content-type':'application/json'},...(method==='POST'?{body:'not JSON'}:{})});
      assert.equal(response.status,503);
      assert.deepEqual(await response.json(),{error:'object_verification_unavailable'});
      assert.equal(response.headers.get('retry-after'),'1800');
    }
    const unauthorized=await mf.dispatchFetch('https://community.test/api/object-qualifications');
    assert.equal(unauthorized.status,401);
    const unsupported=await mf.dispatchFetch('https://community.test/api/object-qualifications',{method:'PUT'});
    assert.equal(unsupported.status,404);
    await unchanged(db,a.id);assert.deepEqual(await tables(db),before);
    assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM scene_qualifications').first()).n,0);
  }finally{await mf.dispose();}
}
console.log(JSON.stringify({status:'ACTUAL_WORKERD_API_PROTECTION_PASSED',fixtures:sequence,
  limiterRejections:rejected,missingBindingsClosedBeforeDatabase:true,missingSchemaClosedWithoutMigration:true,
  explicitFreshSchemaAndCheckpointChecked:true,damagedFenceRefused:true,accountAndViewBudgetsIndependent:true,
  objectQualificationExplicitlyClosed:true,syntheticAccounts:3,creditsChanged:0,nativeCalls:0,imageryRetrieved:false,cloudResourcesAccessed:false,
  strictGlobalQuotaClaimed:false,productionQualified:false}));
