import assert from 'node:assert/strict';
import test from 'node:test';
import {qualifiedFixture,ACCOUNT,SCENE_ACCOUNT,LEASE} from './qualifiedObject.fixture.mjs';
import {stageQualifiedObjectUpload,settleQualifiedObjectUpload} from './qualifiedObjectPublication.js';
import {prepareQualifiedObject,bindQualifiedObjectPolicy} from '../tools/prepare-qualified-object.mjs';
import {revokeObjectQualification} from './objectQualification.js';
import {stageObjectAudit} from './objectAuditDispatch.js';
import {settleObjectAudit} from './objectSettlement.js';
import {deleteAccount} from './accountPrivacy.js';
import {objectCapabilities} from './objectAdmission.js';

test('prepared qualified staging and atomic publication use distinct provenance and exactly one award',async t=>{
  const f=await qualifiedFixture(t);
  assert.equal((await f.stage()).pending,true);
  assert.deepEqual(f.counts(),{candidates:1,acceptances:0,publications:0,awards:0,units:0});
  const result=await f.settle();assert.equal(result.accepted,2);assert.equal(result.unitsEarned,20);assert.equal(result.independentlyRecomputed,false);
  assert.deepEqual(f.counts(),{candidates:1,acceptances:1,publications:2,awards:1,units:20});
  assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM object_audit_candidates').get().n,0);
  assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM object_dispatch_slots').get().n,0);
  assert.equal(f.sql.prepare("SELECT reason FROM ledger WHERE units>0").get().reason,'qualified_device_work');
  const manifest=JSON.parse(new TextDecoder().decode(f.objects.get(`object-index-v4/${LEASE}/manifest.json`)));
  assert.equal(JSON.stringify(manifest).includes('SYNTHETIC-PRIVATE'),false);
  assert.equal(objectCapabilities().objectContributions.ready,false);
});

test('optional exact migration and policy binding are explicit and idempotent',async t=>{
  const f=await qualifiedFixture(t);await prepareQualifiedObject(f.env.DB);
  const row=f.sql.prepare('SELECT * FROM qualified_object_policy').get();
  await bindQualifiedObjectPolicy(f.env.DB,row.eligibility_sha256,row.qualification_authority_sha256);
  await assert.rejects(bindQualifiedObjectPolicy(f.env.DB,'0'.repeat(64),row.qualification_authority_sha256));
  f.sql.exec('DROP TRIGGER qualified_object_acceptance_immutable');
  f.sql.exec('CREATE TRIGGER qualified_object_acceptance_immutable BEFORE UPDATE ON qualified_object_acceptances BEGIN SELECT 1; END');
  await assert.rejects(prepareQualifiedObject(f.env.DB));
});

test('staging cannot use old audited namespace or client-chosen untrusted source/profile authority',async t=>{
  const f=await qualifiedFixture(t);
  for(const changes of [{profileId:'0'.repeat(64)},{assignmentSha256:'0'.repeat(64)},{sourceSha256:'0'.repeat(64)},
    {policyId:'other'},{approved:true}]){
    // The synthetic private producer is made independent of the caller pins.
    f.env.OBJECT_ELIGIBILITY={fetch:async request=>{
      const v=f.proof(await request.json());v.assignmentSha256=f.authority.assignmentSha256;return Response.json(v);
    }};
    await assert.rejects(stageQualifiedObjectUpload(f.env,ACCOUNT,{...f.authority,...changes},f.index,f.now));
  }
  await f.stage();
  await assert.rejects(stageObjectAudit(f.env,ACCOUNT,f.authority,f.index,f.now));
  await assert.rejects(settleObjectAudit(f.env,ACCOUNT,LEASE,f.now));
  assert.equal(f.counts().awards,0);
});

test('duplicates and concurrent settlement recover the same award without another debit',async t=>{
  const f=await qualifiedFixture(t);await f.stage();assert.equal((await f.stage()).replayed,true);
  const outcomes=await Promise.allSettled([f.settle(),f.settle()]);assert(outcomes.some(r=>r.status==='fulfilled'));
  const before=f.protectionCalls(),ack=await f.settle();assert.equal(ack.unitsEarned,0);assert.equal(ack.replayed,true);
  assert.equal(f.protectionCalls(),before);assert.equal(f.counts().awards,1);assert.equal(f.counts().units,20);
});

test('a lost stage or acceptance database reply preserves the immutable retry identity',async t=>{
  const f=await qualifiedFixture(t);const batch=f.env.DB.batch;let lost=true;
  f.env.DB.batch=async statements=>{const r=await batch(statements);if(lost){lost=false;throw Error('synthetic lost stage reply');}return r;};
  await assert.rejects(f.stage());assert.equal((await f.stage()).replayed,true);
  lost=true;await assert.rejects(f.settle());const count=f.protectionCalls();
  assert.equal((await f.settle()).unitsEarned,0);assert.equal(f.protectionCalls(),count);assert.equal(f.counts().units,20);
});

test('changed saved submission conflicts and an expired qualification cannot be silently rebound',async t=>{
  const f=await qualifiedFixture(t);await f.stage();f.index.manifest.privateExtension='changed';await assert.rejects(f.stage());
  await revokeObjectQualification(f.env,ACCOUNT,{operationId:'7'.repeat(32),profileId:f.authority.profileId},f.now);
  await assert.rejects(f.settle());assert.equal(f.counts().awards,0);
  assert.throws(()=>f.sql.exec("UPDATE qualified_object_candidates SET qualification_id='other'"),/immutable/);
});

test('final staging transaction fences revocation, Scene deletion, pose and policy authority changes',async t=>{
  for(const change of ['revocation','scene-delete','object-delete','pose','generation','policy']){
    const f=await qualifiedFixture(t),batch=f.env.DB.batch;let once=true;
    f.env.DB.batch=async statements=>{if(once){once=false;
      if(change==='revocation')await revokeObjectQualification({...f.env,DB:{...f.env.DB,batch}},ACCOUNT,{operationId:'7'.repeat(32),profileId:f.authority.profileId},f.now);
      if(change==='scene-delete')f.sql.prepare('UPDATE accounts SET deleted_at=?,units=0 WHERE id=?').run(f.now,SCENE_ACCOUNT);
      if(change==='object-delete')f.sql.prepare('UPDATE accounts SET deleted_at=?,units=0 WHERE id=?').run(f.now,ACCOUNT);
      if(change==='pose')f.sql.exec("UPDATE locations SET heading=heading+1 WHERE lane='object'");
      if(change==='generation')f.sql.exec('UPDATE leases SET generation=generation+1');
      if(change==='policy')f.sql.exec("UPDATE qualified_object_policy SET generation=generation+1,eligibility_sha256='"+'0'.repeat(64)+"'");
    }return batch(statements);};
    await assert.rejects(f.stage());assert.equal(f.counts().candidates,0);assert.equal(f.counts().awards,0);
  }
});

test('final publication transaction fences current authority, fresh evidence, files and membership',async t=>{
  for(const change of ['revocation','scene-delete','object-delete','coverage','pose','generation','policy','artifact','expired']){
    const f=await qualifiedFixture(t);await f.stage();const batch=f.env.DB.batch;let once=true;
    f.env.DB.batch=async statements=>{if(once){once=false;
      if(change==='revocation')await revokeObjectQualification({...f.env,DB:{...f.env.DB,batch}},ACCOUNT,{operationId:'7'.repeat(32),profileId:f.authority.profileId},f.now);
      if(change==='scene-delete')f.sql.prepare('UPDATE accounts SET deleted_at=?,units=0 WHERE id=?').run(f.now,SCENE_ACCOUNT);
      if(change==='object-delete')f.sql.prepare('UPDATE accounts SET deleted_at=?,units=0 WHERE id=?').run(f.now,ACCOUNT);
      if(change==='coverage')f.sql.exec('UPDATE object_coverage SET validated_at=validated_at-1');
      if(change==='pose')f.sql.exec("UPDATE locations SET lat=lat+0.000001 WHERE lane='object'");
      if(change==='generation')f.sql.exec('UPDATE leases SET generation=generation+1');
      if(change==='policy')f.sql.exec("UPDATE qualified_object_policy SET generation=generation+1,eligibility_sha256='"+'0'.repeat(64)+"'");
      if(change==='artifact')f.sql.exec("DELETE FROM account_artifact_writes WHERE artifact_key LIKE 'object-index-v4/%'");
      if(change==='expired')f.sql.prepare("UPDATE leases SET state='expired' WHERE id=?").run(LEASE);
    }return batch(statements);};
    await assert.rejects(f.settle());assert.equal(f.counts().acceptances,0);assert.equal(f.counts().publications,0);assert.equal(f.counts().awards,0);
  }
});

test('a failure in a later publication statement rolls back acceptance and the entire award',async t=>{
  const f=await qualifiedFixture(t);await f.stage();
  f.sql.exec("CREATE TRIGGER synthetic_publication_failure BEFORE INSERT ON published_index WHEN NEW.object_index_key IS NOT NULL BEGIN SELECT RAISE(ABORT,'synthetic rollback'); END");
  await assert.rejects(f.settle());assert.deepEqual(f.counts(),{candidates:1,acceptances:0,publications:0,awards:0,units:0});
  f.sql.exec('DROP TRIGGER synthetic_publication_failure');assert.equal((await f.settle()).unitsEarned,20);
});

test('account deletion cancels staged work and retains published acceptance and forfeited credit history',async t=>{
  for(const published of [false,true]){
    const f=await qualifiedFixture(t);await f.stage();if(published)await f.settle();
    await deleteAccount(f.env,ACCOUNT,{accountId:ACCOUNT,idempotencyKey:'8'.repeat(64),confirmation:'DELETE'},f.now+2);
    await assert.rejects(f.settle(),{message:'account_not_active'});
    assert.equal(f.counts().units,0);assert.equal(f.counts().acceptances,published?1:0);assert.equal(f.counts().publications,published?2:0);
    if(!published)assert.equal(f.sql.prepare('SELECT state FROM qualified_object_candidates').get().state,'cancelled');
  }
});

test('saved acceptance stays recoverable after policy removal and profile revocation without private work',async t=>{
  const f=await qualifiedFixture(t);await f.stage();await f.settle();
  await revokeObjectQualification(f.env,ACCOUNT,{operationId:'7'.repeat(32),profileId:f.authority.profileId},f.now);
  delete f.env.OBJECT_ELIGIBILITY;delete f.env.OBJECT_ELIGIBILITY_POLICY;delete f.env.OBJECT_QUALIFIED_UPLOAD_MODE;
  const count=f.protectionCalls();assert.equal((await f.settle(f.now+100000)).unitsEarned,0);assert.equal(f.protectionCalls(),count);
  assert.throws(()=>f.sql.exec('DELETE FROM qualified_object_acceptances'),/retained/);
  assert.throws(()=>f.sql.exec('UPDATE qualified_object_acceptances SET units=0'),/immutable/);
});

test('missing optional schema, policy authority and invalid requests cannot create work',async t=>{
  const f=await qualifiedFixture(t,{install:false});await assert.rejects(f.stage());
  for(const args of [[{},'bad',LEASE,f.now,20],[{},ACCOUNT,'bad',f.now,20],[{},ACCOUNT,LEASE,NaN,20],[{},ACCOUNT,LEASE,f.now,0]])
    await assert.rejects(settleQualifiedObjectUpload(...args));
});

test('retained work cannot silently reconstruct lost revision or policy authority',async t=>{
  const f=await qualifiedFixture(t);await f.stage();
  f.sql.exec('DELETE FROM qualified_object_revision');await assert.rejects(prepareQualifiedObject(f.env.DB));
  const g=await qualifiedFixture(t);await g.stage();
  const p=g.sql.prepare('SELECT * FROM qualified_object_policy').get();
  g.sql.exec('DROP TRIGGER qualified_object_policy_retained; DELETE FROM qualified_object_policy');
  await assert.rejects(bindQualifiedObjectPolicy(g.env.DB,p.eligibility_sha256,p.qualification_authority_sha256),/recovery_required/);
  assert.equal(g.counts().awards,0);
});

test('unresponsive private protection times out without staging or credit',async t=>{
  const f=await qualifiedFixture(t);f.env.OBJECT_ELIGIBILITY={fetch:()=>new Promise(()=>{})};
  await assert.rejects(f.stage(f.now,50));assert.equal(f.counts().candidates,0);assert.equal(f.counts().units,0);
});

test('the independent qualified staging namespace has a bounded eight-candidate queue',async t=>{
  const f=await qualifiedFixture(t);await f.stage();
  const original=f.sql.prepare('SELECT * FROM qualified_object_candidates').get(),columns=Object.keys(original);
  const insert=f.sql.prepare(`INSERT INTO qualified_object_candidates(${columns.join(',')}) VALUES (${columns.map(()=>'?').join(',')})`);
  for(let i=1;i<=8;i++){
    const lease=i.toString(16).padStart(32,'0');
    f.sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at,generation) VALUES (?,?,'object','active',?,1)").run(lease,ACCOUNT,f.now+1000);
    const candidate={...original,lease_id:lease,artifact_key:`object-quarantine/${lease}/${original.submission_sha256}.json`};
    if(i<8)insert.run(...columns.map(k=>candidate[k]));
    else assert.throws(()=>insert.run(...columns.map(k=>candidate[k])),/candidate_unavailable/);
  }
  assert.equal(f.counts().candidates,8);assert.equal((await f.stage()).replayed,true);assert.equal(f.counts().units,0);
});
