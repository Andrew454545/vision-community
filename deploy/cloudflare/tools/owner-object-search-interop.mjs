// Offline fixture consumer: actual Python adapter packets -> actual SQLite
// queue/gateway/ledger. It neither executes a model nor connects to a service.
import assert from 'node:assert/strict';
import {readFileSync, statSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {queueSearch, claimQueuedSearch, completeQueuedSearch, recoverSearch, searchCredit} from '../src/searchQueue.js';
import {migrateAccountPrivacy} from '../src/accountPrivacy.js';
import {searchDigest} from '../src/onlineSearch.js';

const inputPath = process.argv[2];
assert.ok(inputPath && statSync(inputPath).isFile() && statSync(inputPath).size <= 4*1024*1024);
const input = JSON.parse(readFileSync(inputPath, 'utf8'));
assert.equal(input.scope, 'synthetic-owner-object-search-interop');
assert.equal(input.members.length, 3);
assert.equal(input.cases.length, 3);
const account = 'a'.repeat(32), now = 2000000000;
const sql = new DatabaseSync(':memory:');
const db = {prepare(query) {
  const statement = (args=[]) => ({bind:(...bound)=>statement(bound),
    first:async()=>sql.prepare(query).get(...args)||null,
    all:async()=>({results:sql.prepare(query).all(...args)}),
    run:async()=>statement(args).execute(),
    execute:()=>({success:true,meta:{changes:Number(sql.prepare(query).run(...args).changes)}})});
  return statement();
},async batch(statements) {
  sql.exec('BEGIN IMMEDIATE');
  try {const result=statements.map(s=>s.execute());sql.exec('COMMIT');return result;}
  catch(error) {sql.exec('ROLLBACK');throw error;}
}};
try {
  sql.exec(readFileSync(new URL('../schema.sql', import.meta.url), 'utf8'));
  sql.exec('ALTER TABLE pose_catalog ADD COLUMN assignee TEXT; ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER;');
  await migrateAccountPrivacy({DB:db});
  sql.exec(readFileSync(new URL('../search-queue.sql', import.meta.url), 'utf8'));
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES(?,?,60)').run(account,'synthetic-token-hash');
  sql.prepare('INSERT INTO ledger(account_id,units,reason,reference) VALUES(?,60,?,?)')
    .run(account,'synthetic_test_balance','synthetic-only-not-earned-work');
  for(const member of input.members) {
    const p=member.pose;
    sql.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,
      lat,lon,heading,pitch,zoom,country,camera_generation) VALUES(?,?,?,'object','synthetic','published',?,?,?,?,?,?,?,?)`)
      .run(member.locationId,p.panoId,p.capture,'synthetic-contributor',p.lat,p.lng,p.heading,p.pitch,p.zoom,p.country,p.cameraGeneration);
    sql.prepare(`INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key)
      VALUES(?,'',?,0,?)`).run(member.locationId,member.outputSha256,'object-index-v4/synthetic/');
    sql.prepare('INSERT INTO object_coverage VALUES(?,?,?,0)')
      .run(member.locationId,'official-gen4-historical-v2-exact-pano',member.coverageEvidenceSha256);
  }
  const balance=()=>sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units;
  const debits=()=>sql.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='search'").get().n;
  let denied=0;
  for(const [index,entry] of input.cases.entries()) {
    const packet=entry.result;
    const env={DB:db,SEARCH_DELIVERY:'queued-v1',SEARCH_POLICY_ID:packet.policyId,
      SEARCH_RUNTIME_SHA256:packet.runtimeSha256,SEARCH_SNAPSHOT_SHA256:packet.snapshotSha256,
      SEARCH_AGENT_SECRET:'f'.repeat(64),SEARCH_COST_UNITS:'10'};
    const key=`q1.${now}.${String(index+1).padStart(32,'0')}`;
    assert.equal(packet.requestSha256,(await searchDigest(entry.query)).slice(7));
    const units=balance();
    await queueSearch(env,account,key,entry.query,{now,maxCostUnits:10});
    assert.equal(balance(),units);
    assert.equal((await searchCredit(db,account)).reservedUnits,10);
    assert.equal((await claimQueuedSearch(env,now,['scene'])).job,null);
    const {job}=await claimQueuedSearch(env,now,['object']);
    assert.equal(JSON.parse(job.requestJson).requestSha256,packet.requestSha256);
    const id=packet.hits[0].locationId;
    // Live authority can disappear after the owner has computed. No saved
    // snapshot/model result may replace current publication/Gen4 membership.
    const invalidators=[
      ["UPDATE locations SET camera_generation='gen3' WHERE id=?","UPDATE locations SET camera_generation='gen4' WHERE id=?"],
      ["UPDATE locations SET contributor_id='' WHERE id=?","UPDATE locations SET contributor_id='synthetic-contributor' WHERE id=?"],
      ["UPDATE object_coverage SET validator='official-gen4-historical-v1' WHERE location_id=?",
       "UPDATE object_coverage SET validator='official-gen4-historical-v2-exact-pano' WHERE location_id=?"],
    ];
    for(const [breakSql,restoreSql] of invalidators) {
      sql.prepare(breakSql).run(id);
      await assert.rejects(completeQueuedSearch(env,job.jobId,job.claimToken,packet,now+1), e=>e.code==='search_unavailable');
      assert.equal(balance(),units);assert.equal(debits(),index);
      sql.prepare(restoreSql).run(id);denied++;
    }
    const ack=await completeQueuedSearch(env,job.jobId,job.claimToken,packet,now+1);
    assert.equal(ack.completed,true);assert.equal(balance(),units-10);assert.equal(debits(),index+1);
    assert.deepEqual(await completeQueuedSearch(env,job.jobId,job.claimToken,packet,now+2),ack);
    const saved=await recoverSearch(env,account,key,{now:now+3});
    assert.equal(saved.results.length,3);assert.equal(saved.results[0].object.lane,entry.route);
    assert.deepEqual(saved.results.map(h=>h.sourceIndex),[0,1,2]);
    assert.equal(saved.map.customCoordinates[0].heading,45);
    const offline={DB:db};
    assert.deepEqual(await recoverSearch(offline,account,key,{now:now+4}),saved);
    assert.equal(balance(),units-10);assert.equal(debits(),index+1);
  }
  assert.equal(balance(),30);assert.equal(debits(),3);
  assert.equal((await searchCredit(db,account)).reservedUnits,0);
  process.stdout.write(JSON.stringify({status:'OWNER_OBJECT_SEARCH_INTEROP_PASSED',routes:3,
    staleAuthorityRefusals:denied,onceOnlyDebits:3,synthetic:true,liveReady:false})+'\n');
} finally {sql.close();}
