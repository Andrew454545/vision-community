// Actual local workerd/D1/R2, explicit synthetic publication; no inference/credit grants.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {prepareDatabase} from './initialize-schema.mjs';
import {capturePublications,artifactBytes,uploadBundle} from './scene-refresh-source.mjs';
const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(process.argv[2])));
const mf=new Miniflare(convertV4MiniflareOptions({modules:true,script:'export default {fetch(){return new Response("offline fixture")}}',
  compatibilityDate:'2026-10-02',compatibilityFlags:['nodejs_compat'],d1Databases:['DB'],r2Buckets:['INDEX']}));
const account='synthetic-owner',lease='b'.repeat(32),policy='staging.synthetic-refresh',key='four-view-v4/'+lease+'.i8';
let checks=0;
try {
  const db=await mf.getD1Database('DB'),bucket=await mf.getR2Bucket('INDEX');await prepareDatabase(db);
  await db.prepare('INSERT INTO accounts(id,token_hash,recovery_hash,units) VALUES(?,?,?,1)').bind(account,'private-token','private-recovery').run();
  await db.prepare(`INSERT INTO scene_qualifications(id,account_id,profile_id,policy_id,canary_sha256,created_at,expires_at)
    VALUES('q',?,?,?,'canary',90,200)`).bind(account,'c'.repeat(64),policy).run();
  await db.prepare(`INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES(?,?,'scene',200,'submitted')`).bind(lease,account).run();
  await db.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,lat,lon,output_sha256)
    VALUES(1,'synthetic-pano','2026-09','scene','synthetic-model','published',?,1,2,?)`).bind(account,'d'.repeat(64)).run();
  await db.prepare('INSERT INTO lease_items(lease_id,location_id) VALUES(?,1)').bind(lease).run();
  await db.prepare(`INSERT INTO scene_candidates(lease_id,account_id,qualification_id,policy_id,submission_sha256,artifact_key,records_json,created_at,state)
    VALUES(?,?,'q',?,'submission','quarantine','[]',100,'published')`).bind(lease,account,policy).run();
  await db.prepare(`INSERT INTO published_index(location_id,index_text,output_sha256,four_view_sha256,four_view_key,published_at)
    VALUES(1,'',?,?,?,100)`).bind('d'.repeat(64),'d'.repeat(64),key).run();
  await db.prepare(`INSERT INTO ledger(account_id,units,reason,reference) VALUES(?,1,'verified_work',?)`).bind(account,'lease:'+lease).run();
  let value=await capturePublications(db,[policy]);
  assert.equal(value.inventory.rows.length,1);assert.equal(value.control.candidates.length,1);
  assert.equal(value.control.qualifications.length,1);assert.equal(value.control.ledger[0].units,1);
  assert.deepEqual(value.control.accounts,[{id:account,deleted_at:null}]);
  assert.doesNotMatch(JSON.stringify(value),/private-token|private-recovery/);checks++;
  const empty=await capturePublications(db,['staging.other']);assert.equal(empty.inventory.rows.length,0);
  assert.equal(empty.control.candidates.length,0);checks++;
  await db.prepare('UPDATE scene_qualifications SET expires_at=0 WHERE id=\'q\'').run();
  await db.prepare(`INSERT INTO account_deletion_receipts(account_id,request_key,deleted_at,units_forfeited) VALUES(?,'synthetic-deletion',110,1)`).bind(account).run();
  await db.prepare(`UPDATE accounts SET deleted_at=110,units=0,token_hash='revoked',recovery_hash=NULL WHERE id=?`).bind(account).run();
  value=await capturePublications(db,[policy]);assert.deepEqual(value.control.deletions,[{account_id:account,deleted_at:110}]);
  assert.equal(value.inventory.rows.length,1);assert.equal(value.control.qualifications[0].expires_at,0);checks++;
  const blob=new Uint8Array(3080);await bucket.put(key,blob);
  assert.deepEqual(await artifactBytes(bucket,key),blob);checks++;
  const zip=new Uint8Array([80,75,3,4]),pin=createHash('sha256').update(zip).digest('hex');
  const descriptor={version:1,key:'native-host/bundles/'+pin+'.zip',sha256:pin,bytes:zip.length};
  assert.deepEqual(await uploadBundle(bucket,descriptor,zip),{uploaded:true});
  assert.deepEqual(await uploadBundle(bucket,descriptor,zip),{uploaded:false});checks++;
  await bucket.put(descriptor.key,new Uint8Array([4,3,2,1]));
  await assert.rejects(uploadBundle(bucket,descriptor,zip),/refresh_bundle_conflict/);checks++;
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_SCENE_REFRESH_SOURCE_PASSED',checks,
    syntheticInference:true,realCreditGranted:0,productionQualified:false}));
} finally {await mf.dispose();}
