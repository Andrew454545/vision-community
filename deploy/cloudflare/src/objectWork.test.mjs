import assert from 'node:assert/strict';
import test from 'node:test';
import {objectWorkFixture} from './objectWork.fixture.mjs';
import {ACCOUNT,SCENE_ACCOUNT,LEASE} from './qualifiedObject.fixture.mjs';
import {requestQualifiedObjectWork,cancelQualifiedObjectWork} from './objectWork.js';
import {prepareObjectWorkPool} from './objectWorkSchema.js';
import {importObjectWorkPool} from '../tools/import-object-work-pool.mjs';
import {sha256Hex,encodeUtf8} from './model.js';
import {qualifyObjectDevice,revokeObjectQualification} from './objectQualification.js';
import {deleteAccount} from './accountPrivacy.js';
import {objectCapabilities} from './objectAdmission.js';

test('automatic prepared allocation delivers stable source and flows to distinct atomic qualified publication',async t=>{
 const f=await objectWorkFixture(t),work=await f.claim();assert.equal(work.items.length,2);assert.equal(work.leaseId,LEASE);
 assert.equal(work.unitsEarned,0);assert.equal(work.independentlyRecomputed,false);
 assert.deepEqual(work.authority,f.authority);assert.equal(await sha256Hex(encodeUtf8(work.sourceTsv)),f.authority.sourceSha256);
 assert.equal(JSON.stringify(work).includes('synthetic-object-owner'),false);
 const calls=f.protectionCalls();assert.deepEqual(await f.claim(),work);assert.equal(f.protectionCalls(),calls);
 await f.stage();assert.equal((await f.settle()).unitsEarned,20);
 assert.equal((await f.claim()).alreadySubmitted,true);assert.equal(f.counts().awards,1);
 assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM object_audit_candidates').get().n,0);
 assert.equal(objectCapabilities().objectContributions.ready,false);
});

test('operator import is pinned, idempotent and cannot rewrite retained prepared identities or grant approval',async t=>{
 const f=await objectWorkFixture(t),raw=JSON.stringify(f.doc),pin=await sha256Hex(encodeUtf8(raw));
 const r=await importObjectWorkPool(f.env,raw,pin,f.now);assert.equal(r.imported,0);assert.equal(r.eligibilityGranted,false);
 await assert.rejects(importObjectWorkPool(f.env,raw,'0'.repeat(64),f.now));
 const changed=structuredClone(f.doc);changed.entries[0].assignmentSha256='0'.repeat(64);const bytes=JSON.stringify(changed);
 await assert.rejects(importObjectWorkPool(f.env,bytes,await sha256Hex(encodeUtf8(bytes)),f.now));
 assert.equal(f.counts().awards,0);
});

test('same work cannot be assigned to two qualified accounts during concurrent claims',async t=>{
 const f=await objectWorkFixture(t),other='c'.repeat(32);
 f.sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'other-synthetic-owner',0)").run(other);
 await qualifyObjectDevice(f.env,other,{requestId:'4'.repeat(32),profileId:f.body.profileId,artifactSetSha256:'8'.repeat(64)},f.now);
 const outcomes=await Promise.allSettled([f.claim(),requestQualifiedObjectWork(f.env,other,{...f.body,requestKey:'6'.repeat(32)},f.now)]);
 assert.equal(outcomes.filter(r=>r.status==='fulfilled').length,1);
 assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM leases').get().n,1);
 assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM object_work_requests').get().n,1);
 assert.equal(f.counts().awards,0);
});

test('one account cannot open another active assignment and request identity cannot silently change',async t=>{
 const f=await objectWorkFixture(t);await f.claim();
 for(const change of [{count:4},{pace:'max'},{profileId:'0'.repeat(64)}])
   await assert.rejects(f.claim({...f.body,...change}),/conflict/);
 await assert.rejects(f.claim({...f.body,requestKey:'6'.repeat(32)}));
 assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM leases').get().n,1);
});

test('private outage preserves the reserved request and a retry resumes without allocating new work',async t=>{
 const f=await objectWorkFixture(t),service=f.env.OBJECT_ELIGIBILITY;
 f.env.OBJECT_ELIGIBILITY={fetch:()=>new Promise(()=>{})};await assert.rejects(f.claim(f.body,f.now,50));
 assert.equal(f.sql.prepare('SELECT state FROM object_work_requests').get().state,'preparing');
 f.env.OBJECT_ELIGIBILITY=service;assert.equal((await f.claim()).leaseId,LEASE);
 assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM leases').get().n,1);assert.equal(f.counts().awards,0);
});

test('a lost reservation reply recovers the committed identity',async t=>{
 const f=await objectWorkFixture(t),batch=f.env.DB.batch;let lost=true;
 f.env.DB.batch=async s=>{const r=await batch(s);if(lost){lost=false;throw Error('synthetic lost reservation reply');}return r;};
 assert.equal((await f.claim()).leaseId,LEASE);assert.equal((await f.claim()).leaseId,LEASE);
 assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM object_work_requests').get().n,1);
});

test('fresh official Gen4 coverage, exact Scene membership and the complete qualified profile are required',async t=>{
 for(const change of ['gen3','stale','source','scene','revoked']){
   const f=await objectWorkFixture(t);
   if(change==='gen3')f.sql.exec("UPDATE locations SET camera_generation='gen3' WHERE lane='object'");
   if(change==='stale')f.sql.exec('UPDATE object_coverage SET validated_at=validated_at-86400');
   if(change==='source')f.sql.exec("UPDATE locations SET lat=lat+1 WHERE lane='object'");
   if(change==='scene')f.sql.prepare('UPDATE accounts SET deleted_at=? WHERE id=?').run(f.now,SCENE_ACCOUNT);
   if(change==='revoked')await revokeObjectQualification(f.env,ACCOUNT,{operationId:'7'.repeat(32),profileId:f.body.profileId},f.now);
   await assert.rejects(f.claim());assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM leases').get().n,0);
 }
});

test('changes during the private reply invalidate delivery without granting work or credit',async t=>{
 for(const change of ['revoke','scene','coverage','pose','generation','delete','expire','policy']){
   const f=await objectWorkFixture(t),service=f.env.OBJECT_ELIGIBILITY;
   f.env.OBJECT_ELIGIBILITY={fetch:async request=>{
     const response=await service.fetch(request);
     if(change==='revoke')await revokeObjectQualification(f.env,ACCOUNT,{operationId:'7'.repeat(32),profileId:f.body.profileId},f.now);
     if(change==='scene')f.sql.prepare('UPDATE accounts SET deleted_at=? WHERE id=?').run(f.now,SCENE_ACCOUNT);
     if(change==='coverage')f.sql.exec('UPDATE object_coverage SET validated_at=validated_at-1');
     if(change==='pose')f.sql.exec("UPDATE locations SET lat=lat+1 WHERE lane='object'");
     if(change==='generation')f.sql.exec('UPDATE leases SET generation=generation+1');
     if(change==='delete')f.sql.prepare('UPDATE accounts SET deleted_at=? WHERE id=?').run(f.now,ACCOUNT);
     if(change==='expire')f.sql.exec("UPDATE leases SET state='expired'");
     if(change==='policy')f.env.OBJECT_ELIGIBILITY_POLICY_SHA256='0'.repeat(64);
     return response;}};
   await assert.rejects(f.claim());assert.equal(f.sql.prepare("SELECT COUNT(*) n FROM object_work_requests WHERE state='ready'").get().n,0);
   assert.equal(f.counts().awards,0);
 }
});

test('the final ready transaction repeats qualification, account, Scene, coverage and lease fences',async t=>{
 for(const change of ['revoke','scene','coverage','generation','delete','expire','policy']){
   const f=await objectWorkFixture(t),prepare=f.env.DB.prepare;let changed=false;
   f.env.DB.prepare=query=>{const s=prepare(query);if(!query.includes("UPDATE object_work_requests SET state='ready'"))return s;
     const bind=s.bind;s.bind=(...args)=>{const bound=bind(...args),run=bound.run;bound.run=async()=>{
       if(!changed){changed=true;
         if(change==='revoke')await revokeObjectQualification({...f.env,DB:{...f.env.DB,prepare}},ACCOUNT,{operationId:'7'.repeat(32),profileId:f.body.profileId},f.now);
         if(change==='scene')f.sql.prepare('UPDATE accounts SET deleted_at=? WHERE id=?').run(f.now,SCENE_ACCOUNT);
         if(change==='coverage')f.sql.exec('UPDATE object_coverage SET validated_at=validated_at-1');
         if(change==='generation')f.sql.exec('UPDATE leases SET generation=generation+1');
         if(change==='delete')f.sql.prepare('UPDATE accounts SET deleted_at=? WHERE id=?').run(f.now,ACCOUNT);
         if(change==='expire')f.sql.exec("UPDATE leases SET state='expired'");
         if(change==='policy')f.sql.exec("UPDATE qualified_object_policy SET generation=generation+1,eligibility_sha256='"+'0'.repeat(64)+"'");
       }return run();};return bound;};return s;};
   await assert.rejects(f.claim());assert.equal(changed,true);
   assert.equal(f.sql.prepare("SELECT COUNT(*) n FROM object_work_requests WHERE state='ready'").get().n,0);
 }
});

test('cancellation works without private service or active policy, releases locations and preserves the old request tombstone',async t=>{
 const f=await objectWorkFixture(t);await f.claim();delete f.env.OBJECT_ELIGIBILITY;delete f.env.OBJECT_ELIGIBILITY_POLICY;
 assert.equal((await cancelQualifiedObjectWork(f.env,ACCOUNT,f.body.requestKey,f.now)).cancelled,true);
 assert.equal(f.sql.prepare('SELECT state FROM object_work_requests').get().state,'cancelled');
 assert.equal(f.sql.prepare("SELECT COUNT(*) n FROM locations WHERE lane='object' AND active_lease IS NULL").get().n,2);
 assert.equal(f.sql.prepare('SELECT state FROM object_work_pool').get().state,'claimed');
 assert.equal((await cancelQualifiedObjectWork(f.env,ACCOUNT,f.body.requestKey,f.now)).cancelled,true);
});

test('account deletion cancels active allocation and cannot revive its assignment',async t=>{
 const f=await objectWorkFixture(t);await f.claim();
 await deleteAccount(f.env,ACCOUNT,{accountId:ACCOUNT,idempotencyKey:'8'.repeat(64),confirmation:'DELETE'},f.now);
 await assert.rejects(f.claim(),/account_not_active/);
 assert.equal(f.sql.prepare('SELECT state FROM object_work_requests').get().state,'cancelled');
 assert.equal(f.sql.prepare('SELECT state FROM leases').get().state,'expired');
 assert.equal(f.counts().units,0);
});

test('a submitted upload is not released or resubmitted by assignment cancellation',async t=>{
 const f=await objectWorkFixture(t);await f.claim();await f.stage();
 assert.equal((await cancelQualifiedObjectWork(f.env,ACCOUNT,f.body.requestKey,f.now)).alreadySubmitted,true);
 assert.equal((await f.settle()).unitsEarned,20);assert.equal((await f.claim()).alreadySubmitted,true);
});

test('pool revision, immutable histories and finite import windows fail closed',async t=>{
 const f=await objectWorkFixture(t);await prepareObjectWorkPool(f.env.DB);await f.claim();
 assert.throws(()=>f.sql.exec("UPDATE object_work_pool SET state='available'"),/immutable/);
 assert.throws(()=>f.sql.exec('DELETE FROM object_work_requests'),/retained/);
 assert.throws(()=>f.sql.exec('UPDATE object_work_requests SET qualification_id=qualification_id'),/immutable/);
 f.sql.exec('DELETE FROM object_work_revision');await assert.rejects(prepareObjectWorkPool(f.env.DB),/recovery_required/);
 await assert.rejects(f.claim());
});

test('expired assignments and cancelled request keys do not silently allocate replacement work',async t=>{
 const f=await objectWorkFixture(t);await f.claim();
 await assert.rejects(f.claim(f.body,f.now+1801));
 assert.equal(f.sql.prepare('SELECT state FROM object_work_requests').get().state,'cancelled');
 assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM leases').get().n,1);
});

test('reservation itself is atomic against stale qualification, Scene, account, pose and coverage',async t=>{
 for(const change of ['revoke','scene','delete','pose','coverage']){
   const f=await objectWorkFixture(t),batch=f.env.DB.batch;let once=true;
   f.env.DB.batch=async s=>{if(once){once=false;
     if(change==='revoke')await revokeObjectQualification({...f.env,DB:{...f.env.DB,batch}},ACCOUNT,{operationId:'7'.repeat(32),profileId:f.body.profileId},f.now);
     if(change==='scene')f.sql.prepare('UPDATE accounts SET deleted_at=? WHERE id=?').run(f.now,SCENE_ACCOUNT);
     if(change==='delete')f.sql.prepare('UPDATE accounts SET deleted_at=? WHERE id=?').run(f.now,ACCOUNT);
     if(change==='pose')f.sql.exec("UPDATE locations SET lat=lat+1 WHERE lane='object'");
     if(change==='coverage')f.sql.exec('UPDATE object_coverage SET validated_at=validated_at-1');
   }return batch(s);};
   await assert.rejects(f.claim());assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM leases').get().n,0);
 }
});

test('lost ready reply recovers without repeating private preparation',async t=>{
 const f=await objectWorkFixture(t),prepare=f.env.DB.prepare;let lost=true;
 f.env.DB.prepare=query=>{const s=prepare(query);if(!query.includes("UPDATE object_work_requests SET state='ready'"))return s;
   const bind=s.bind;s.bind=(...args)=>{const b=bind(...args),run=b.run;b.run=async()=>{const r=await run();
     if(lost){lost=false;throw Error('synthetic lost delivery reply');}return r;};return b;};return s;};
 await assert.rejects(f.claim());const calls=f.protectionCalls();assert.equal((await f.claim()).leaseId,LEASE);
 assert.equal(f.protectionCalls(),calls);
});

test('the prepared pool bounds pending metadata and cannot rewrite claimed rows',async t=>{
 const f=await objectWorkFixture(t),original=f.sql.prepare('SELECT * FROM object_work_pool').get(),keys=Object.keys(original);
 const insert=f.sql.prepare(`INSERT INTO object_work_pool(${keys.join(',')}) VALUES (${keys.map(()=>'?').join(',')})`);
 for(let i=1;i<=64;i++){
   const v={...original,lease_id:i.toString(16).padStart(32,'0')};
   if(i<64)insert.run(...keys.map(k=>v[k]));else assert.throws(()=>insert.run(...keys.map(k=>v[k])),/pool_unavailable/);
 }
 assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM object_work_pool').get().n,64);
});

test('upload cannot bypass unfinished delivery or silently switch to a newer qualification',async t=>{
 const f=await objectWorkFixture(t),service=f.env.OBJECT_ELIGIBILITY;
 f.env.OBJECT_ELIGIBILITY={fetch:()=>new Promise(()=>{})};await assert.rejects(f.claim(f.body,f.now,50));
 f.env.OBJECT_ELIGIBILITY=service;await assert.rejects(f.stage(),/assignment_changed/);
 await f.claim();
 await revokeObjectQualification(f.env,ACCOUNT,{operationId:'7'.repeat(32),profileId:f.body.profileId},f.now);
 await qualifyObjectDevice(f.env,ACCOUNT,{requestId:'6'.repeat(32),profileId:f.body.profileId,artifactSetSha256:'8'.repeat(64)},f.now);
 await assert.rejects(f.stage(),/assignment_changed/);assert.equal(f.counts().awards,0);
});

test('staging and publication final transactions cannot ignore changed allocation authority',async t=>{
 for(const stage of [true,false]){
   const f=await objectWorkFixture(t);await f.claim();if(!stage)await f.stage();
   const batch=f.env.DB.batch;let once=true;
   f.env.DB.batch=async statements=>{if(once){once=false;
     f.sql.prepare("UPDATE object_work_requests SET state='cancelled' WHERE account_id=?").run(ACCOUNT);
   }return batch(statements);};
   await assert.rejects(stage?f.stage():f.settle());assert.equal(f.counts().awards,0);assert.equal(f.counts().acceptances,0);
 }
});
