import assert from 'node:assert/strict';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';
import { sceneCohortAllows } from './sceneCohort.js';
import { encodeUtf8, sha256Hex } from './model.js';
import worker from './worker.js';
import { prepareDatabase } from '../tools/initialize-schema.mjs';

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
