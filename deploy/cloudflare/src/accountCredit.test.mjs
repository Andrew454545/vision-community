import assert from 'node:assert/strict';
import test from 'node:test';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import worker from './worker.js';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {queueSearch,searchCredit,cancelQueuedSearch,SEARCH_JOB_SECONDS} from './searchQueue.js';

const ACCOUNT='a'.repeat(32),OTHER='b'.repeat(32),token='fixture-token';
const hash=value=>createHash('sha256').update(value).digest('hex');
function d1(sql, reads) {
  return {prepare(query){
    const statement=(args=[])=>({bind:(...values)=>statement(values),
      first:async()=>{reads.push(query);return sql.prepare(query).get(...args)||null;},
      all:async()=>{reads.push(query);return {results:sql.prepare(query).all(...args)};},
      run:async()=>({success:true,meta:{changes:Number(sql.prepare(query).run(...args).changes)}})});
    return statement();
  },async batch(statements){
    sql.exec('BEGIN IMMEDIATE');
    try{const values=[];for(const statement of statements)values.push(await statement.run());sql.exec('COMMIT');return values;}
    catch(error){sql.exec('ROLLBACK');throw error;}
  }};
}
async function fixture(t) {
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());const reads=[];
  const env={DB:d1(sql,reads),SEARCH_COST_UNITS:'2',INDEX:{head(){throw Error('No storage access');}}};
  await prepareDatabase(env.DB);
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES(?,?,?)').run(ACCOUNT,hash(token),10);
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES(?,?,?)').run(OTHER,hash('other-token'),999);
  sql.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES(?,10,'contribution','fixture')").run(ACCOUNT);
  reads.length=0;
  const request=(path='me?credit=1',credential=token)=>worker.fetch(new Request('https://fixture.test/api/'+path,
    {headers:{authorization:'Bearer '+credential}}),env);
  return {sql,env,reads,request};
}

test('explicit credit refresh reads only schema/auth/own balance, without corpus/R2 statistics',async t=>{
  const f=await fixture(t),reply=await f.request();assert.equal(reply.status,200);
  assert.deepEqual(await reply.json(),{creditContractVersion:1,accountId:ACCOUNT,units:10,searchCost:2,searchesAvailable:5});
  assert.equal(f.reads.length,3);
  assert.ok(f.reads.every(query=>!/(locations|published_index|pose_catalog|lease_items)/i.test(query)));
});

test('credit refresh cannot choose another account or read revoked accounts',async t=>{
  const f=await fixture(t);
  assert.equal((await (await f.request('me?credit=1&accountId='+OTHER)).json()).accountId,ACCOUNT);
  assert.equal((await f.request('me?credit=1','wrong-token')).status,401);
  f.sql.prepare('UPDATE accounts SET deleted_at=1 WHERE id=?').run(ACCOUNT);
  assert.equal((await f.request()).status,401);
});

test('credit refresh keeps disabled prices and zero balances closed to spending',async t=>{
  const f=await fixture(t);f.env.SEARCH_COST_UNITS='invalid';
  assert.deepEqual(await (await f.request()).json(),{creditContractVersion:1,accountId:ACCOUNT,units:10,searchCost:null,searchesAvailable:0});
  f.env.SEARCH_COST_UNITS='2';f.sql.prepare('UPDATE accounts SET units=0 WHERE id=?').run(ACCOUNT);
  assert.equal((await (await f.request()).json()).searchesAvailable,0);
});

test('queued credit uses reserved balances and expiry without spending or touching corpus tables',async t=>{
  const f=await fixture(t);f.sql.exec(readFileSync(new URL('../search-queue.sql',import.meta.url),'utf8'));
  f.sql.exec(`INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,country,camera_generation)
    VALUES(1,'synthetic-pano','2026-01','scene','fixture','published','contributor',10,20,90,'Italy','gen4');
    INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_key)
    VALUES(1,'','${'c'.repeat(64)}',0,'four-view-v4/fixture.i8');`);
  Object.assign(f.env,{SEARCH_DELIVERY:'queued-v1',SEARCH_POLICY_ID:'offline-fixture',
    SEARCH_RUNTIME_SHA256:'d'.repeat(64),SEARCH_SNAPSHOT_SHA256:'e'.repeat(64),SEARCH_AGENT_SECRET:'f'.repeat(64)});
  const now=Math.floor(Date.now()/1000),key=`q1.${now}.${'1'.repeat(32)}`;
  const query={lane:'scene',prompt:'road',examples:[],excluded:[],queryName:'fixture',descriptionWeight:100,
    viewDirection:'bestOfFour',resultCount:1,maxPerCountry:1,filters:{mode:'all',countries:[],generations:[]},
    objectConfidence:'balanced',rejectRoadNames:false,minimumGlobalLocation:null};
  await queueSearch(f.env,ACCOUNT,key,query,{now,maxCostUnits:2});
  f.reads.length=0;
  let value=await (await f.request()).json();
  assert.deepEqual(value,{creditContractVersion:1,accountId:ACCOUNT,bankedUnits:10,reservedUnits:2,units:8,searchCost:2,searchesAvailable:4});
  assert.ok(f.reads.every(query=>!/(locations|published_index|pose_catalog|lease_items)/i.test(query)));
  const past=now-SEARCH_JOB_SECONDS-1,old=await queueSearch(f.env,ACCOUNT,`q1.${past}.${'2'.repeat(32)}`,query,
    {now:past,maxCostUnits:2});
  assert.equal((await searchCredit(f.env.DB,ACCOUNT)).reservedUnits,4);
  value=await (await f.request()).json();assert.equal(value.reservedUnits,2);assert.equal(value.units,8);
  assert.equal(f.sql.prepare('SELECT state FROM search_jobs WHERE id=?').get(old.jobId).state,'expired');
  await cancelQueuedSearch(f.env,ACCOUNT,key);
  value=await (await f.request()).json();assert.equal(value.reservedUnits,0);assert.equal(value.units,10);
  assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM ledger').get().n,1);
  assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM searches').get().n,0);
});

test('queued credit fails closed without reservation schema rather than returning total banked credit',async t=>{
  const f=await fixture(t);f.env.SEARCH_DELIVERY='queued-v1';
  const reply=await f.request();assert.equal(reply.status,503);
  assert.equal((await reply.json()).error,'schema_update_required');
});
