// Actual SQLite/R2 ownership and cancellation; native inference synthetic.
import assert from 'node:assert/strict';
import test from 'node:test';
import {DatabaseSync} from 'node:sqlite';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareObjectAuditDispatch} from '../tools/prepare-object-audit-dispatch.mjs';
import {prepareObjectAuditCancellation} from '../tools/prepare-object-audit-cancellation.mjs';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {stageObjectAudit,advanceObjectAudit} from './objectAuditDispatch.js';
import {cancelObjectAudit,advanceObjectCancellation} from './objectAuditCancellation.js';
import {syntheticR2} from './syntheticR2.mjs';
import {sha256Hex,encodeUtf8} from './model.js';
import {PRIVACY_FENCE,writeObjectArtifact} from './artifactWrites.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {deleteAccount,cleanupAccountArtifacts} from './accountPrivacy.js';
import {exportDeletionLedger,RESOURCE_PROFILES} from '../tools/account-restore.mjs';
import {exportObjectErasureAuthority} from '../tools/object-erasure-recovery.mjs';
const account='a'.repeat(32),lease='b'.repeat(32),other='c'.repeat(32),job='d'.repeat(32),now=100000;
const requestId='7'.repeat(64),source=encodeUtf8('synthetic source\n');
const index={manifest:{synthetic:true},files:{'synthetic.bin':''},sourceTsv:btoa('synthetic source\n')};
async function setup(t,install=true){
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());const objects=new Map(),r2=syntheticR2(objects);
  const env={DB:sqliteD1(sql),INDEX:{...r2,async get(key){const value=await r2.get(key);return value?{...value,body:new Response(await value.arrayBuffer()).body}:null;}}};
  await prepareDatabase(env.DB);await prepareObjectAuditDispatch(env.DB);if(install)await prepareObjectAuditCancellation(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-session',10)").run(account);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-other',10)").run(other);
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',101000)").run(lease,account);
  sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (1,'synthetic','fixture','object','synthetic','leased',?,'gen4')").run(lease);
  sql.prepare('INSERT INTO lease_items VALUES (?,1)').run(lease);
  sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,?)').run(1,COVERAGE_VALIDATOR,'f'.repeat(64),now);
  const authority={leaseId:lease,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),sourceSha256:await sha256Hex(source)};
  await stageObjectAudit(env,account,authority,index,now);
  const candidate=()=>sql.prepare('SELECT * FROM object_audit_candidates').get();
  const row=()=>sql.prepare('SELECT * FROM object_audit_cancellations').get();
  const erased=(changes={})=>({version:1,leaseId:lease,policyId:authority.policyId,assignmentSha256:authority.assignmentSha256,
    state:'erased',serverAuthorization:false,productionQualified:false,...changes});
  env.OBJECT_VERIFIER={fetch:()=>Response.json(erased())};
  const cancel=(at=now)=>cancelObjectAudit(env,account,lease,requestId,at);
  const advance=(at=now,timeout=20000)=>advanceObjectCancellation(env,account,lease,at,timeout);
  const approved=()=>({version:1,jobId:job,leaseId:lease,profileId:authority.profileId,policyId:authority.policyId,
    assignmentSha256:authority.assignmentSha256,submissionSha256:candidate().submission_sha256,candidateManifestSha256:'3'.repeat(64),
    state:'approved',decision:'approved',attempts:1,retryAt:0,receiptSha256:'4'.repeat(64),serverAuthorization:false,
    productionQualified:false,acceptedContributions:0,searchCreditsCreated:0});
  const noCredit=()=>{assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,10);
    assert.equal(sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);assert.equal(sql.prepare('SELECT count(*) AS n FROM published_index').get().n,0);};
  return {sql,env,objects,authority,candidate,row,erased,cancel,advance,approved,noCredit};
}
test('optional cancellation setup is explicit, exact and refuses future contracts or altered ownership fences',async t=>{
  const s=await setup(t,false);
  await assert.rejects(s.cancel(),{message:'object_cancel_setup_required',status:503});
  assert.equal(s.sql.prepare("SELECT count(*) AS n FROM sqlite_master WHERE name='object_audit_cancellations'").get().n,0);
  await prepareObjectAuditCancellation(s.env.DB);await prepareObjectAuditCancellation(s.env.DB);
  s.sql.exec('DROP TRIGGER object_cancel_authority; CREATE TRIGGER object_cancel_authority BEFORE INSERT ON object_audit_cancellations BEGIN SELECT 1; END');
  await assert.rejects(prepareObjectAuditCancellation(s.env.DB));
  s.sql.exec("UPDATE object_cancel_revision SET contract='future'");
  await assert.rejects(s.cancel(),{message:'object_cancel_setup_required'});
});
test('cancellation journals original evidence and revokes ownership atomically before any native or R2 cleanup',async t=>{
  const s=await setup(t);
  s.sql.prepare("UPDATE object_audit_candidates SET native_state='failed',native_attempts=1,receipt_sha256=?,transport_failures=8,last_error='object_audit_transport_unavailable',next_attempt=100900").run('4'.repeat(64));
  s.env.INDEX.put=()=>assert.fail('cleanup before cancellation receipt');s.env.OBJECT_VERIFIER.fetch=()=>assert.fail('cleanup before cancellation receipt');
  const result=await s.cancel();assert.equal(result.cleanupState,'pending');assert.equal(result.cancelled,true);assert.equal(result.accepted,0);
  assert.equal(s.candidate().state,'cancelled');assert.equal(s.candidate().receipt_sha256,null);assert.equal(s.candidate().claim_token,null);
  assert.equal(s.row().prior_receipt,'4'.repeat(64));assert.equal(s.row().prior_failures,8);assert.equal(s.row().prior_retry_at,100900);
  assert.equal(s.row().prior_error,'object_audit_transport_unavailable');assert.equal(s.row().prior_job_id,null);
  assert.equal(s.sql.prepare('SELECT state FROM leases').get().state,'expired');
  assert.deepEqual({...s.sql.prepare('SELECT state,queue_state,active_lease FROM locations').get()},{state:'pending',queue_state:'pending',active_lease:null});
  assert.deepEqual(await s.cancel(),result);s.noCredit();
  assert.throws(()=>s.sql.exec("UPDATE object_audit_cancellations SET prior_receipt=NULL"),/object_cancel_immutable/);
});
test('late cancellation transaction failure preserves the active assignment and leaves no receipt',async t=>{
  const s=await setup(t);
  s.sql.exec("CREATE TRIGGER fail_cancel BEFORE UPDATE ON leases WHEN NEW.state='expired' BEGIN SELECT RAISE(ABORT,'synthetic_late_failure'); END");
  await assert.rejects(s.cancel(),/synthetic_late_failure/);assert.equal(s.row(),undefined);assert.equal(s.candidate().state,'pending');
  assert.equal(s.sql.prepare('SELECT active_lease FROM locations').get().active_lease,lease);
  assert.equal(s.sql.prepare('SELECT state FROM leases').get().state,'submitted');s.noCredit();
});
test('unowned, changed, already published or unprepared candidates cannot be cancelled',async t=>{
  const s=await setup(t);
  await assert.rejects(cancelObjectAudit(s.env,other,lease,requestId,now),{message:'object_cancel_conflict'});
  assert.equal(s.row(),undefined);
  s.sql.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at) VALUES (1,'synthetic',?,100000)").run('f'.repeat(64));
  await assert.rejects(s.cancel(),/object_cancel_authority_lost/);assert.equal(s.row(),undefined);assert.equal(s.candidate().state,'pending');
});
test('exact active-owner cleanup erases native assignment by lease and confirms the permanent R2 fence',async t=>{
  const s=await setup(t);await s.cancel();let calls=0;
  s.env.OBJECT_VERIFIER={async fetch(request){calls++;assert.equal(request.url,`https://object-verifier.internal/object-assignments/${lease}/erase`);
    assert.equal(s.row().state,'pending');assert.equal(s.candidate().state,'cancelled');assert.equal(await request.text(),'{}');return Response.json(s.erased());}};
  const result=await s.advance();assert.equal(result.cleanupState,'erased');assert.equal(result.cleanupPending,false);assert.equal(calls,1);
  assert.equal(s.row().native_erased_at,now);assert.equal(s.row().r2_fenced_at,now);
  assert.equal(new TextDecoder().decode(s.objects.get(s.candidate().artifact_key)),PRIVACY_FENCE);
  await s.advance(now+30);assert.equal(calls,1);s.noCredit();
});
test('pending native erasure and outages still fence R2; retry preserves confirmed partial progress',async t=>{
  const s=await setup(t);await s.cancel();let puts=0;const put=s.env.INDEX.put;
  s.env.INDEX.put=(...args)=>{puts++;return put(...args);};
  s.env.OBJECT_VERIFIER={fetch:()=>Response.json(s.erased({state:'erasing'}))};
  const pending=await s.advance();assert.equal(pending.cleanupState,'pending');assert.equal(s.row().native_erased_at,null);
  assert.equal(s.row().r2_fenced_at,now);assert.equal(puts,1);assert.equal(pending.retryAt,now+30);
  s.env.OBJECT_VERIFIER={fetch:()=>Response.json(s.erased())};
  assert.equal((await s.advance(now+29)).cleanupState,'pending');
  assert.equal((await s.advance(now+30)).cleanupState,'erased');assert.equal(puts,1);s.noCredit();
});
test('R2 outage cannot prevent native revocation and can be repaired without repeating native work',async t=>{
  const s=await setup(t);await s.cancel();const put=s.env.INDEX.put;let calls=0;
  s.env.OBJECT_VERIFIER={fetch(){calls++;return Response.json(s.erased());}};
  s.env.INDEX.put=()=>{throw Error('private provider failure');};
  assert.equal((await s.advance()).cleanupState,'pending');assert.equal(s.row().native_erased_at,now);assert.equal(s.row().r2_fenced_at,null);
  assert.equal(s.row().last_error,'object_cancel_cleanup_pending');s.env.INDEX.put=put;
  assert.equal((await s.advance(now+30)).cleanupState,'erased');assert.equal(calls,1);s.noCredit();
});
test('wrong policy or assignment hash cannot acknowledge native cleanup',async t=>{
  for(const changes of [{policyId:'wrong'},{assignmentSha256:'9'.repeat(64)}]){
    const s=await setup(t);await s.cancel();s.env.OBJECT_VERIFIER={fetch:()=>Response.json(s.erased(changes))};
    assert.equal((await s.advance()).cleanupState,'pending');assert.equal(s.row().native_erased_at,null);
    assert.equal(s.row().r2_fenced_at,now);s.noCredit();
  }
});
test('storage acknowledgement and exact fence readback are both required',async t=>{
  for(const damage of [s=>{s.env.INDEX.put=async()=>null;},s=>{s.env.INDEX.get=async()=>null;},
    s=>{s.env.INDEX.get=async()=>({size:PRIVACY_FENCE.length,customMetadata:{visionPrivacyFence:'1'},body:new Response('x'.repeat(PRIVACY_FENCE.length)).body});}]){
    const s=await setup(t);await s.cancel();damage(s);assert.equal((await s.advance()).cleanupState,'pending');
    assert.equal(s.row().r2_fenced_at,null);assert.equal(s.row().native_erased_at,now);s.noCredit();
  }
});
test('damaged ownership and accepted publication refuse cleanup without touching storage or native service',async t=>{
  for(const damage of [s=>s.sql.exec('DELETE FROM account_artifact_writes'),s=>s.sql.prepare('UPDATE leases SET account_id=?').run(other),
    s=>s.sql.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at) VALUES (1,'synthetic',?,100000)").run('f'.repeat(64))]){
    const s=await setup(t);await s.cancel();damage(s);s.env.INDEX.put=()=>assert.fail('damaged authority wrote storage');
    s.env.OBJECT_VERIFIER.fetch=()=>assert.fail('damaged authority called native');
    const result=await s.advance();assert.equal(result.cleanupState,'needs_review');assert.equal(result.needsAttention,true);
    assert.equal(s.row().native_erased_at,null);assert.equal(s.row().r2_fenced_at,null);
  }
});
test('cancellation defeats a late approval even when the native start acknowledgement was lost',async t=>{
  const s=await setup(t);
  s.env.OBJECT_VERIFIER={async fetch(){const response=Response.json(s.approved());await s.cancel();return response;}};
  const result=await advanceObjectAudit(s.env,account,lease,now);
  assert.equal(result.freshAuditReply,false);assert.equal(result.cancelled,true);assert.equal(s.candidate().job_id,null);
  assert.equal(s.row().prior_job_id,null);assert.equal(s.row().prior_receipt,null);
  s.env.OBJECT_VERIFIER={fetch:()=>Response.json(s.erased())};assert.equal((await s.advance(now+30)).cleanupState,'erased');s.noCredit();
});
test('audit approval already received can be abandoned without publishing or changing banked credit',async t=>{
  const s=await setup(t);s.env.OBJECT_VERIFIER={fetch:()=>Response.json(s.approved())};
  await advanceObjectAudit(s.env,account,lease,now);await s.cancel();
  assert.equal(s.row().prior_job_id,job);assert.equal(s.row().prior_receipt,'4'.repeat(64));assert.equal(s.row().prior_native_state,'approved');
  s.env.OBJECT_VERIFIER={fetch:()=>Response.json(s.erased())};await s.advance();s.noCredit();
  assert.equal((await advanceObjectAudit(s.env,account,lease,now+30)).cancelled,true);
});
test('account deletion after cancellation shares cleanup safely and keeps its original cancellation evidence',async t=>{
  const s=await setup(t);await s.cancel();
  await deleteAccount(s.env,account,{accountId:account,confirmation:'DELETE',idempotencyKey:'8'.repeat(64)},now+1);
  await assert.rejects(s.cancel(),{message:'account_not_active',status:401});
  assert.equal((await s.advance(now+2)).cleanupState,'erased');await cleanupAccountArtifacts(s.env,account,64);
  assert.equal(s.sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,0);assert.equal(s.row().created_at,now);
  assert.equal(s.sql.prepare('SELECT state FROM account_cleanup WHERE artifact_key=?').get('object-audit-jobs/'+lease).state,'erased');
});
test('concurrent cancellation cleanup has one claim; interrupted and rolled-back clocks recover',async t=>{
  const s=await setup(t);await s.cancel();let complete,calls=0;
  s.env.OBJECT_VERIFIER={fetch(){calls++;return new Promise(resolve=>{complete=resolve;});}};
  const first=s.advance();while(!complete)await new Promise(resolve=>setTimeout(resolve,1));
  assert.equal((await s.advance()).cleanupState,'pending');assert.equal(calls,1);complete(Response.json(s.erased()));await first;
  assert.equal(s.row().state,'erased');s.noCredit();
  const another=await setup(t);await another.cancel();
  another.sql.prepare('UPDATE object_audit_cancellations SET claim_token=?,claim_until=?,next_attempt=?').run('9'.repeat(32),now+99999,now+99999);
  assert.equal((await another.advance()).cleanupState,'erased');
});
test('stalled native or R2 replies have a shared finite deadline and leave recoverable private cleanup',async t=>{
  for(const damage of [s=>{s.env.OBJECT_VERIFIER.fetch=()=>new Promise(()=>{});},s=>{s.env.INDEX.put=()=>new Promise(()=>{});},
    s=>{s.env.INDEX.get=async()=>({size:PRIVACY_FENCE.length,customMetadata:{visionPrivacyFence:'1'},body:new ReadableStream({pull(){return new Promise(()=>{});}})});}]){
    const s=await setup(t);await s.cancel();damage(s);assert.equal((await s.advance(now,20)).cleanupState,'pending');
    assert.equal(s.row().claim_token,null);assert.equal(s.row().transport_failures,1);assert.equal(s.row().last_error,'object_cancel_cleanup_pending');s.noCredit();
  }
});
test('wrong request nonce and invalid identities cannot alter cancellation; delayed writes cannot revive it',async t=>{
  const s=await setup(t);await s.cancel();
  await assert.rejects(cancelObjectAudit(s.env,account,lease,'9'.repeat(64),now),{message:'object_cancel_conflict'});
  await assert.rejects(cancelObjectAudit(s.env,Symbol('invalid'),lease,requestId,now),{message:'invalid_object_cancellation'});
  await s.advance();
  await assert.rejects(writeObjectArtifact(s.env,account,lease,s.candidate().artifact_key,encodeUtf8(JSON.stringify(index)),now+1),/fenced|lease_lost/);
  assert.equal(new TextDecoder().decode(s.objects.get(s.candidate().artifact_key)),PRIVACY_FENCE);s.noCredit();
});
test('a changed lease owner cannot acquire a cancellation receipt or release another owner\'s assignment',async t=>{
  const s=await setup(t);s.sql.prepare('UPDATE leases SET account_id=?').run(other);
  await assert.rejects(s.cancel(),/object_cancel_authority_lost/);assert.equal(s.row(),undefined);
  assert.equal(s.candidate().state,'pending');assert.equal(s.sql.prepare('SELECT active_lease FROM locations').get().active_lease,lease);s.noCredit();
});
test('account-deletion-only native recovery cannot certify current submission cancellation',async t=>{
  const s=await setup(t),raw=value=>Buffer.from(JSON.stringify(value)+'\n');
  const registryRaw=raw({version:1,scope:'private-object-audit-registry',policyId:s.authority.policyId,
    resource:RESOURCE_PROFILES.staging,assignments:[{leaseId:lease,assignment:{sha256:s.authority.assignmentSha256}}]});
  const deletionLedgerRaw=raw(exportDeletionLedger(s.sql,now,'staging'));
  const args={registryRaw,registrySha256:await sha256Hex(registryRaw),policySha256:'f'.repeat(64),
    deletionLedgerRaw,deletionLedgerSha256:await sha256Hex(deletionLedgerRaw),notBefore:now-1,now,environment:'staging'};
  assert.equal(exportObjectErasureAuthority(s.sql,args).revocations.length,0);
  await s.cancel();assert.throws(()=>exportObjectErasureAuthority(s.sql,args),/object_cancellation_recovery_required/);
  await s.advance();assert.throws(()=>exportObjectErasureAuthority(s.sql,args),/object_cancellation_recovery_required/);s.noCredit();
});

test('later publication from another lease cannot strand the cancelled owner\'s cleanup or erase the new bundle',async t=>{
  const s=await setup(t);await s.cancel();
  const prefix='object-index-v4/'+other+'/',newKey=prefix+'manifest.json',bytes=encodeUtf8('synthetic other-owner publication');
  s.objects.set(newKey,bytes);
  s.sql.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (1,'synthetic',?,100001,?)").run('f'.repeat(64),prefix);
  assert.equal((await s.advance(now+2)).cleanupState,'erased');assert.deepEqual(s.objects.get(newKey),bytes);
  assert.equal(s.sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,10);
  assert.equal(s.sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
});
