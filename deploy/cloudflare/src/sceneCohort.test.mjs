import assert from 'node:assert/strict';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { sceneCohortAllows } from './sceneCohort.js';
import { encodeUtf8, sha256Hex } from './model.js';
import worker from './worker.js';
import { prepareDatabase } from '../tools/initialize-schema.mjs';
import { syntheticR2 } from './syntheticR2.mjs';
import { queueSearch, claimQueuedSearch, completeQueuedSearch, recoverSearch } from './searchQueue.js';

async function invitation(account, now = Date.now()) {
  return {DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',
    DELETION_ARCHIVE_DB_ID:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',SCENE_POLICY_ID:'staging.test',
    SCENE_COHORT_ACCOUNTS:JSON.stringify([await sha256Hex(encodeUtf8(account))]),
    SCENE_COHORT_UNTIL:String(now+3600000)};
}

test('a staging invitation needs exact resources, a hashed account and a finite deadline', async () => {
  const now = Date.now(), env = await invitation('invited', now);
  assert.equal(await sceneCohortAllows({}, null), true);
  assert.equal(await sceneCohortAllows(env,'invited',now),true);
  assert.equal(await sceneCohortAllows(env,'another',now),false);
  assert.equal(await sceneCohortAllows(env,null,now),false);
  for (const patch of [
    {DEPLOYMENT_ENVIRONMENT:'production'},{INDEX_BUCKET_NAME:'vision-community'},
    {DELETION_ARCHIVE_DB_ID:'wrong'},{SCENE_POLICY_ID:'production.policy'},
    {SCENE_COHORT_UNTIL:String(now)},{SCENE_COHORT_UNTIL:String(now+9*86400000)},
    {SCENE_COHORT_UNTIL:undefined},{SCENE_COHORT_UNTIL:'Infinity'},
    {SCENE_COHORT_ACCOUNTS:undefined},{SCENE_COHORT_ACCOUNTS:'[]'},
    {SCENE_COHORT_ACCOUNTS:'{}'},{SCENE_COHORT_ACCOUNTS:'["invited"]'},
    {SCENE_COHORT_ACCOUNTS:'null'},{SCENE_COHORT_ACCOUNTS:'['},
    {SCENE_COHORT_ACCOUNTS:JSON.stringify(Array(17).fill('a'.repeat(64)))},
    {SCENE_COHORT_ACCOUNTS:JSON.stringify(Array(2).fill('a'.repeat(64)))},
  ]) assert.equal(await sceneCohortAllows({...env,...patch},'invited',now),false,JSON.stringify(patch));
});

function database(sql) {
  return {prepare(query) {
    const statement=(args=[])=>({bind:(...values)=>statement(values),
      first:async()=>sql.prepare(query).get(...args)||null,
      all:async()=>({results:sql.prepare(query).all(...args)}),
      run:async()=>({success:true,meta:{changes:Number(sql.prepare(query).run(...args).changes)}})});
    return statement();
  },async batch(statements) {
    sql.exec('BEGIN IMMEDIATE');
    try {const results=[];for(const statement of statements)results.push(await statement.run());sql.exec('COMMIT');return results;}
    catch(error){sql.exec('ROLLBACK');throw error;}
  }};
}
function request(path, token, body) {
  return new Request('https://community.test/api/'+path,{method:body===undefined?'GET':'POST',
    headers:{...(token?{authorization:'Bearer '+token}:{}),'content-type':'application/json'},
    ...(body===undefined?{}:{body:JSON.stringify(body)})});
}

test('qualified Scene router leases exclusive work and settles uploads without cloud inference',async t=>{
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const env={DB:database(sql),INDEX:syntheticR2(new Map()),SCENE_POLICY_ID:'test-policy',
    SCENE_ADMISSION_MODE:'qualified-device-v1'};
  await prepareDatabase(env.DB);
  const created=await worker.fetch(request('accounts',null,{}),env);
  assert.equal(created.status,201);
  const account=await created.json(),token=created.headers.get('set-cookie').match(/^vision_session=([^;]+)/)[1];
  const now=Math.floor(Date.now()/1000),profile='a'.repeat(64);
  sql.prepare('INSERT INTO scene_qualifications VALUES (?,?,?,?,?,?,?)')
    .run('qualified',account.accountId,profile,'test-policy','b'.repeat(64),now+3600,now);
  sql.exec("INSERT INTO locations (id,asset_id,capture,lane,model,state,lat,lon,heading,pitch,zoom,country,camera_generation) VALUES (1,'synthetic-pano','2026-09','scene','community-visual-v1','pending',10,20,90,0,0,'Italy','gen4')");
  const caps=await worker.fetch(request('capabilities',token),env);
  assert.equal((await caps.json()).sceneContributions.admissionMode,'qualified-device-v1');
  const status=await worker.fetch(request('scene-qualifications?profileId='+profile,token),env);
  assert.equal((await status.json()).qualified,true);
  const held=await worker.fetch(request('leases',token,{lane:'scene',count:1,pace:'medium',client:'cli',profileId:profile}),env);
  const lease=await held.json();assert.equal(held.status,200,JSON.stringify(lease));
  assert.equal(lease.items.length,1);
  const resumed=await worker.fetch(request('leases',token,{lane:'scene',count:1,pace:'medium',client:'cli',profileId:profile}),env);
  assert.equal((await resumed.json()).leaseId,lease.leaseId);
  const otherResponse=await worker.fetch(request('accounts',null,{}),env);
  const other=await otherResponse.json(),otherToken=otherResponse.headers.get('set-cookie').match(/^vision_session=([^;]+)/)[1];
  sql.prepare('INSERT INTO scene_qualifications VALUES (?,?,?,?,?,?,?)')
    .run('qualified-other',other.accountId,profile,'test-policy','b'.repeat(64),now+3600,now);
  const competing=await worker.fetch(request('leases',otherToken,{lane:'scene',count:1,pace:'medium',client:'cli',profileId:profile}),env);
  const competingLease=await competing.json();assert.equal(competing.status,409,JSON.stringify(competingLease));
  assert.equal(competingLease.error,'no_available_work');
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM leases WHERE state='active'").get().n,1);
  const bytes=new Uint8Array(3080);for(let v=0;v<4;v++)bytes[v*770+1]=60;
  const body={leaseId:lease.leaseId,outputs:[{locationId:1,model:'vision-four-view-v4',
    embedding:Buffer.from(bytes).toString('base64'),outputSha256:await sha256Hex(bytes)}]};
  const upload=await worker.fetch(request('submissions',token,body),env);
  assert.equal(upload.status,200);assert.equal((await upload.json()).pendingAudit,true);
  const settled=await worker.fetch(request('scene-audits',token,{submissionId:lease.leaseId}),env);
  const receipt=await settled.json();assert.equal(settled.status,200,JSON.stringify(receipt));
  assert.equal(receipt.accepted,1);assert.equal(receipt.admissionMode,'qualified-device-v1');
  const replay=await worker.fetch(request('submissions',token,body),env);
  assert.equal((await replay.json()).unitsEarned,0);
  assert.equal(sql.prepare('SELECT reason FROM ledger').get().reason,'qualified_device_work');
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM published_index').get().n,1);
  sql.exec(readFileSync(new URL('../search-queue.sql',import.meta.url),'utf8'));
  Object.assign(env,{SEARCH_DELIVERY:'queued-v1',SEARCH_POLICY_ID:'offline-fixture',
    SEARCH_RUNTIME_SHA256:'c'.repeat(64),SEARCH_SNAPSHOT_SHA256:'d'.repeat(64),
    SEARCH_AGENT_SECRET:'e'.repeat(64),SEARCH_COST_UNITS:'1',
    SEARCH_ENGINE:{fetch(){throw Error('test must not invoke cloud inference');}}});
  const query={lane:'scene',prompt:'red door',examples:[],excluded:[],queryName:'My map',
    descriptionWeight:100,viewDirection:'bestOfFour',resultCount:1,maxPerCountry:25,
    filters:{mode:'all',countries:[],generations:[]},objectConfidence:'balanced',
    rejectRoadNames:false,minimumGlobalLocation:null};
  const key=`q1.${now}.${'f'.repeat(32)}`;
  await queueSearch(env,account.accountId,key,query,{now,maxCostUnits:1});
  const {job}=await claimQueuedSearch(env,now);
  const {query:rawQuery,...head}=JSON.parse(job.requestJson);
  const result={...head,processedLocations:1,hits:[{locationId:1,outputSha256:await sha256Hex(bytes),
    sourceIndex:0,score:0.8,viewOffset:1}]};
  const paid=await completeQueuedSearch(env,job.jobId,job.claimToken,result,now+1);
  const recovered=await recoverSearch(env,account.accountId,key,now+2);
  assert.equal(recovered.searchId,paid.searchId);
  assert.equal(recovered.map.customCoordinates.length,1);
  await completeQueuedSearch(env,job.jobId,job.claimToken,result,now+2);
  assert.deepEqual((await recoverSearch(env,account.accountId,key,now+2)).map,recovered.map);
  assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(account.accountId).units,0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='search'").get().n,1);
});

test('the real router closes anonymous and other accounts, including direct processing routes',async t=>{
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const env={DB:database(sql),SCENE_VERIFIER:{fetch(){throw Error('unexpected private compute');}},
    SEARCH_ENGINE:{fetch(){throw Error('unexpected private search');}},
    SEARCH_POLICY_ID:'test',SEARCH_RUNTIME_SHA256:'b'.repeat(64),SEARCH_SNAPSHOT_SHA256:'c'.repeat(64)};
  await prepareDatabase(env.DB);
  const accounts=[];
  for(let i=0;i<2;i++) {
    const response=await worker.fetch(request('accounts',null,{}),env);
    assert.equal(response.status,201);
    accounts.push({...await response.json(),token:response.headers.get('set-cookie').match(/^vision_session=([^;]+)/)[1]});
  }
  Object.assign(env,await invitation(accounts[0].accountId));
  env.RATE_LIMITS_REQUIRED='1';
  for(const name of ['API_RATE_LIMITER','API_INGRESS_LIMITER','API_VIEW_LIMITER'])
    env[name]={async limit(){return {success:true};}};
  for(const token of [null,accounts[1].token,'forged']) {
    const caps=await worker.fetch(request('capabilities',token),env);
    assert.equal((await caps.json()).sceneContributions.ready,false);
  }
  const own=await worker.fetch(request('capabilities',accounts[0].token),env);
  assert.equal((await own.json()).sceneContributions.ready,true);
  for(const path of ['scene-qualifications','scene-audits','leases','submissions','views']) {
    const response=await worker.fetch(request(path,accounts[1].token,path==='views'?undefined:{}),env);
    assert.equal(response.status,503,path);
    assert.equal((await response.json()).error,'scene_verification_unavailable');
  }
  const publicStatus=await worker.fetch(request('status'),env);
  assert.equal((await publicStatus.json()).searchReady,false);
  const memberStatus=await worker.fetch(request('me?lite=1',accounts[0].token),env);
  assert.equal((await memberStatus.json()).searchReady,true);
  const otherStatus=await worker.fetch(request('me?lite=1',accounts[1].token),env);
  assert.equal((await otherStatus.json()).searchReady,false);
  const recovered=await worker.fetch(request('recovery',null,{recoveryCode:accounts[1].recoveryCode}),env);
  assert.equal(recovered.status,200);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM ledger').get().n,0);
});
