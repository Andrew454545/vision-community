// Actual local workerd/D1/R2. All account/qualification/feature inputs are fixtures.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve,dirname,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {prepareDatabase} from './initialize-schema.mjs';
import {localRateLimits} from './local-api-bindings.mjs';
const [runtime,bundle]=process.argv.slice(2);
const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(runtime)).href);
const hash=value=>createHash('sha256').update(value).digest('hex');
const account='a'.repeat(32),profile='b'.repeat(64),session='synthetic-finite-account',token='c'.repeat(64);
const deadline=String(Date.now()+600000),path=resolve(bundle);
const options={modules:true,scriptPath:path,modulesRoot:dirname(path),compatibilityDate:'2026-09-19',
  compatibilityFlags:['nodejs_compat'],resourcePersistencePath:mkdtempSync(join(tmpdir(),'finite-scene-')),
  d1Databases:['DB'],r2Buckets:['INDEX'],ratelimits:localRateLimits(),bindings:{
    DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',RATE_LIMITS_REQUIRED:'1',
    DELETION_ARCHIVE_DB_ID:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',
    FINITE_SCENE_ACCOUNT:'272760294910ef0b246980278aeb36e2',FINITE_SCENE_TOKEN_SHA256:hash(token),
    FINITE_SCENE_UNTIL:deadline,SCENE_COHORT_UNTIL:deadline,SCENE_COHORT_ACCOUNTS:JSON.stringify([hash(account)]),
    SCENE_POLICY_ID:'staging.synthetic-finite',SCENE_ADMISSION_MODE:'qualified-device-v1',SCENE_AUDIT_MAX_LOCATIONS:'2'}};
const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
let checks=0;const usage={read:0,written:0,puts:0,bytes:0},requests=[];
const scaled=process.argv.includes('--cost-fixture');
async function call(route,body,credential=token,meter=usage){
  const response=await mf.dispatchFetch('https://fixture.test/api/'+route,{method:body===undefined?'GET':'POST',
    headers:{'content-type':'application/json',authorization:'Bearer '+session,'x-vision-finite-cohort':credential,
      ...Object.fromEntries(Object.entries({read:2000,written:128,puts:4,bytes:524288}).map(([key,max])=>
        ['x-vision-trial-remaining-'+key,String(max-meter[key])]))},
    ...(body===undefined?{}:{body:JSON.stringify(body)})});
  const observed={read:0,written:0,puts:0,bytes:0};
  if(response.headers.get('x-vision-trial-usage-complete')==='1')for(const [key,suffix]of
    Object.entries({read:'rows-read',written:'rows-written',puts:'r2-puts',bytes:'r2-bytes'})){
    const value=Number(response.headers.get('x-vision-trial-'+suffix));assert.ok(Number.isSafeInteger(value)&&value>=0);
    meter[key]+=value;observed[key]=value;
  }
  requests.push({path:'/api/'+route.split('?')[0],creditOnly:route==='me?credit=1',status:response.status,observed});
  return response;
}
try{
  const db=await mf.getD1Database('DB');await prepareDatabase(db);
  const now=Math.floor(Date.now()/1000);
  await db.prepare('INSERT INTO accounts(id,token_hash,units) VALUES(?,?,0)').bind(account,hash(session)).run();
  await db.prepare('INSERT INTO scene_qualifications VALUES(?,?,?,?,?,?,?)')
    .bind('qualified-fixture',account,profile,'staging.synthetic-finite','d'.repeat(64),now+3600,now).run();
  for(let i=1;i<=2;i++)await db.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,lat,lon,heading,pitch,zoom,country,camera_generation)
    VALUES(?,?,'2026-09','scene','community-visual-v1','pending',10,20,90,0,0,?,'gen4')`)
    .bind(i,'synthetic-pano-'+i,i===1?'Italy':'Canada').run();
  let dashboardProbe;
  if(scaled){
    await db.prepare(`WITH RECURSIVE numbers(x) AS (VALUES(1000) UNION ALL SELECT x+1 FROM numbers WHERE x<2023)
      INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,lat,lon,country,camera_generation)
      SELECT x,'synthetic-old-'||x,'fixture','scene','fixture','published',?,0,0,'Italy','gen4' FROM numbers`).bind(account).run();
    await db.prepare(`INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_key)
      SELECT id,'',?,0,'four-view-v4/synthetic-old.i8' FROM locations WHERE id>=1000`).bind('f'.repeat(64)).run();
    dashboardProbe={read:0,written:0,puts:0,bytes:0};
    const full=await call('me',undefined,token,dashboardProbe);
    assert.equal(full.status,500);assert.ok(dashboardProbe.read>2000);checks++;
  }
  assert.equal((await call('capabilities',undefined,'e'.repeat(64))).status,403);checks++;
  assert.equal((await call('accounts',{})).status,404);checks++;
  const caps=await call('capabilities');assert.equal(caps.status,200);
  assert.equal((await caps.json()).sceneContributions.admissionMode,'qualified-device-v1');checks++;
  const q=await call('scene-qualifications?profileId='+profile);assert.equal(q.status,200);
  assert.equal((await q.json()).qualified,true);checks++;
  const before=await call('me?credit=1');assert.equal(before.status,200);
  assert.equal((await before.json()).units,0);checks++;
  const held=await call('leases',{lane:'scene',count:2,pace:'slow',client:'cli',profileId:profile});
  const lease=await held.json();assert.equal(held.status,200,JSON.stringify(lease));assert.equal(lease.items.length,2);checks++;
  const bytes=new Uint8Array(3080);for(let v=0;v<4;v++)bytes[v*770+1]=60;
  const output={model:'vision-four-view-v4',embedding:Buffer.from(bytes).toString('base64'),outputSha256:hash(bytes)};
  const submission={leaseId:lease.leaseId,outputs:lease.items.map(item=>({...output,locationId:item.locationId}))};
  const staged=await call('submissions',submission);assert.equal(staged.status,200);
  assert.equal((await staged.json()).pendingAudit,true);checks++;
  const accepted=await call('scene-audits',{submissionId:lease.leaseId});const receipt=await accepted.json();
  assert.equal(accepted.status,200,JSON.stringify(receipt));assert.equal(receipt.accepted,2);
  assert.equal(receipt.unitsEarned,2);assert.equal(receipt.admissionMode,'qualified-device-v1');checks++;
  const replay=await call('scene-audits',{submissionId:lease.leaseId});assert.equal(replay.status,200);
  assert.equal((await replay.json()).unitsEarned,0);checks++;
  const balance=await call('me?credit=1');assert.equal(balance.status,200);
  assert.equal((await balance.json()).units,2);checks++;
  assert.equal((await call('searches',{accountId:account,prompt:'red door'})).status,404);checks++;
  assert.equal((await db.prepare('SELECT units FROM accounts WHERE id=?').bind(account).first()).units,2);
  assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM ledger').first()).n,1);checks++;
  assert.ok(usage.read<=2000&&usage.written<=128&&usage.puts<=4&&usage.bytes<=524288);checks++;
  console.log(JSON.stringify({status:'LOCAL_FINITE_SCENE_PASS',checks,usage,requests,
    ...(scaled?{syntheticPublishedBackgroundRows:1024,dashboardProbe}:{}),actualLocalWorkerdD1R2:true,
    accountQualificationAndFeaturesSynthetic:true,cloudAccess:false,nativeInference:false,productionQualified:false}));
}catch(error){
  console.error(JSON.stringify({status:'LOCAL_FINITE_SCENE_INCOMPLETE',usage,requests,cloudAccess:false}));
  throw error;
}finally{await mf.dispose();}
