// Finite synthetic actual workerd/D1/R2 checks. No provider login or live imagery.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {resolve,dirname} from 'node:path';
import {pathToFileURL} from 'node:url';
import {prepareDatabase} from './initialize-schema.mjs';
import {localRateLimits} from './local-api-bindings.mjs';
import {RETIRED_CATALOG_PREFIXES, freshLeaseItemSql} from '../src/catalogAllocation.js';

const [runtime,bundle]=process.argv.slice(2);
const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(runtime)).href);
const digest=value=>createHash('sha256').update(value).digest('hex');
let fixtures=0;
async function instance(references=false) {
  const scriptPath=resolve(bundle);
  const policy=JSON.stringify({version:1,policyId:'offline-catalog-only',inputModel:'fixture-model',outputModel:'vision-four-view-v4',
    references:Array.from({length:12},(_,i)=>({assetId:'a'.repeat(20)+String(i+1).padStart(2,'0'),capture:'unknown',lat:10,lng:20,heading:0,pitch:0,zoom:0,approvedSha256:['a'.repeat(64)]}))});
  const options={modules:true,scriptPath,modulesRoot:dirname(scriptPath),compatibilityDate:'2026-09-19',
    compatibilityFlags:['nodejs_compat'],d1Databases:['DB'],r2Buckets:['INDEX','SCENE_REFERENCES'],
    ratelimits:localRateLimits(),bindings:references?{SCENE_REFERENCE_KEY:'policy.json',SCENE_REFERENCE_SHA256:digest(policy)}:{SCENE_POLICY_ID:'offline-catalog-only'},
    serviceBindings:{ASSETS:()=>new Response('offline fixture'),SCENE_VERIFIER:()=>Response.json({error:'must_not_call'},{status:503})}};
  const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
  const db=await mf.getD1Database('DB');await prepareDatabase(db);
  if(references) await (await mf.getR2Bucket('SCENE_REFERENCES')).put('policy.json',policy);
  const token='offline-saved-token';
  for(const id of ['account','existing']) {
    await db.prepare('INSERT INTO accounts(id,token_hash,units) VALUES(?,?,17)').bind(id,digest(token+id)).run();
    await db.prepare('INSERT INTO scene_qualifications(id,account_id,profile_id,policy_id,canary_sha256,expires_at,created_at) VALUES(?,?,?,?,?,?,0)')
      .bind('q-'+id,id,'b'.repeat(64),'offline-catalog-only','c'.repeat(64),Math.floor(Date.now()/1000)+7200).run();
  }
  const post=(body,id='account')=>mf.dispatchFetch('https://community.test/api/leases',{method:'POST',
    headers:{authorization:'Bearer '+token+id,'content-type':'application/json'},body:JSON.stringify({lane:'scene',pace:'max',client:'cli',count:8,...body})});
  async function catalog(id,key,{held=0,remaining=0,assignee=null}={}) {
    await db.prepare('INSERT INTO pose_catalog(lane,shard_id,r2_key,row_start,row_count,bytes,sha256,next_row,held,assignee) VALUES(?,?,?,0,1,1,?,?,?,?)')
      .bind('scene',id,key,'a'.repeat(64),remaining?0:1,held,assignee).run();
  }
  async function location(id,shard) {
    await db.prepare('INSERT INTO locations(id,asset_id,capture,lane,model,catalog_shard,lat,lon) VALUES(?,?,?,\'scene\',?,?,10,20)')
      .bind(id,'a'.repeat(20)+String(id).padStart(2,'0'),'unknown','fixture-model',shard).run();
  }
  fixtures++;return {mf,db,post,catalog,location};
}

{
  const {mf,db,post,catalog,location}=await instance(true);
  try {
    for(let i=0;i<3;i++) {await catalog(i+1,RETIRED_CATALOG_PREFIXES[i]+'old.tsv',{remaining:1});await location(i+1,i+1);}
    await catalog(4,'catalog/official-remaining-v1/fixture/held.tsv',{held:1,remaining:1});await location(4,4);
    await location(5,999); // Removed/missing registration cannot bypass the hold.
    await catalog(6,'catalog/official-remaining-v1/fixture/complete.tsv');await location(6,6);await location(7,null);
    const response=await post({});assert.equal(response.status,200);
    const first=await response.json();assert.deepEqual(first.items.map(r=>r.locationId),[6,7]);
    const again=await post({});assert.equal(again.status,200);assert.equal((await again.json()).leaseId,first.leaseId);
    // A valid lease issued before retirement may finish/resume; fresh assignments may not.
    const now=Math.floor(Date.now()/1000);
    await db.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state,pace,scene_qualification_id) VALUES('saved','existing','scene',?,'active','medium','q-existing')").bind(now+1000).run();
    await db.prepare("INSERT INTO lease_items(lease_id,location_id) VALUES('saved',1)").run();
    await db.prepare("UPDATE locations SET state='leased',active_lease='saved',lease_until=? WHERE id=1").bind(now+1000).run();
    const resumed=await post({},'existing');assert.equal(resumed.status,200);
    const saved=await resumed.json();assert.equal(saved.resumed,true);assert.deepEqual(saved.items.map(r=>r.locationId),[1]);
    await mf.dispatchFetch('https://community.test/api/leases/release',{method:'POST',headers:{authorization:'Bearer offline-saved-tokenexisting','content-type':'application/json'},body:JSON.stringify({leaseId:'saved'})});
    const refused=await post({},'existing');assert.equal(refused.status,409);assert.equal((await refused.json()).error,'no_available_work');
    for(const id of ['account','existing']) assert.equal((await db.prepare('SELECT units FROM accounts WHERE id=?').bind(id).first()).units,17);
    for(const table of ['ledger','published_index','searches']) assert.equal((await db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).first()).n,0);
    assert.equal((await db.prepare('SELECT SUM(next_row) AS n FROM pose_catalog WHERE shard_id<=3').first()).n,0);
  } finally {await mf.dispose();}
}
{
  const {mf,db,post,catalog}=await instance();
  try {
    for(let i=0;i<3;i++) await catalog(i+1,RETIRED_CATALOG_PREFIXES[i]+'unreadable.tsv',{remaining:1,assignee:'account'});
    const key='catalog/official-remaining-v1/fixture/new.tsv';
    const tsv='map\t1\t10\t20\t0\t0\t0\taaaaaaaaaaaaaaaaaaaa09\tunknown\tunknown\tfalse\n';
    await catalog(4,key,{remaining:1});
    await db.prepare('UPDATE pose_catalog SET bytes=?,sha256=? WHERE shard_id=4').bind(Buffer.byteLength(tsv),digest(tsv)).run();
    await (await mf.getR2Bucket('INDEX')).put(key,tsv);
    const response=await post({part:1,count:1});assert.equal(response.status,200);
    const lease=await response.json();assert.equal(lease.items.length,1);assert.equal(lease.work.shardId,4);assert.equal(lease.work.partCount,1);
    assert.equal(lease.work.family,'new-places');assert.equal(lease.items[0].cameraGeneration,'unknown');
    assert.equal((await db.prepare('SELECT catalog_shard FROM locations').first()).catalog_shard,4);
    assert.equal((await db.prepare('SELECT SUM(next_row) AS n FROM pose_catalog WHERE shard_id<=3').first()).n,0);
    const objects=await post({lane:'object'});assert.equal(objects.status,503);assert.equal((await objects.json()).error,'object_verification_unavailable');
    // Exercise the same final guard against actual D1's transactional rollback.
    const location=lease.items[0].locationId;
    await db.prepare("UPDATE locations SET state='pending',active_lease=NULL,lease_until=NULL WHERE id=?").bind(location).run();
    await db.prepare('UPDATE pose_catalog SET held=1 WHERE shard_id=4').run();
    await assert.rejects(db.batch([
      db.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES('late','account','scene',9999999999,'active')"),
      db.prepare(freshLeaseItemSql()).bind('late',location,Math.floor(Date.now()/1000))
    ]),/NOT NULL constraint failed/);
    assert.equal(await db.prepare("SELECT id FROM leases WHERE id='late'").first(),null);
  }finally{await mf.dispose();}
}
{
  const {mf,db,post,location}=await instance();
  try {
    await location(1,null);
    const responses=await Promise.all([post({count:1}),post({count:1},'existing')]);
    assert.deepEqual(responses.map(r=>r.status).sort(),[200,409]);
    const rejected=responses.find(r=>r.status===409);
    assert.equal((await rejected.json()).error,'no_available_work');
    for(const table of ['leases','lease_items']) assert.equal((await db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).first()).n,1);
    assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM locations WHERE state='leased'").first()).n,1);
    assert.equal((await db.prepare('SELECT SUM(units) AS n FROM accounts').first()).n,34);
  }finally{await mf.dispose();}
}
console.log(JSON.stringify({status:'ACTUAL_WORKERD_CATALOG_ALLOCATION_PASSED',fixtures,retiredFamilies:3,
  queuedFallbackClosed:true,newCatalogMaterialized:true,missingRegistrationClosed:true,
  existingLeaseResumed:true,actualD1LateHoldRolledBack:true,competingClaimsAtomic:true,objectAdmissionClosed:true,
  liveImageryRetrieved:false,cloudResourcesAccessed:false,creditsChanged:0,productionQualified:false}));
