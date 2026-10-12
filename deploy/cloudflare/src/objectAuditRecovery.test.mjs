// Real SQLite and recovery transactions; native inference explicitly synthetic.
import assert from 'node:assert/strict';
import test from 'node:test';
import {DatabaseSync} from 'node:sqlite';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareObjectAuditDispatch} from '../tools/prepare-object-audit-dispatch.mjs';
import {prepareObjectAuditRecovery} from '../tools/prepare-object-audit-recovery.mjs';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {stageObjectAudit,advanceObjectAudit} from './objectAuditDispatch.js';
import {recoverObjectAudit} from './objectAuditRecovery.js';
import {syntheticR2} from './syntheticR2.mjs';
import {sha256Hex,encodeUtf8} from './model.js';
import {deleteAccount} from './accountPrivacy.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
const account='a'.repeat(32),lease='b'.repeat(32),job='c'.repeat(32),other='d'.repeat(32),now=100000;
const index={manifest:{synthetic:true},files:{'synthetic.bin':''},sourceTsv:btoa('synthetic source\n')};
const key=n=>n.toString(16).padStart(64,'0');
async function setup(t,install=true) {
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());const r2=syntheticR2(new Map());
  const env={DB:sqliteD1(sql),INDEX:{...r2,async get(k){const v=await r2.get(k);return v?{...v,body:new Response(await v.arrayBuffer()).body}:null;}}};
  await prepareDatabase(env.DB);await prepareObjectAuditDispatch(env.DB);
  if(install)await prepareObjectAuditRecovery(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic',10)").run(account);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-other',10)").run(other);
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',101000)").run(lease,account);
  sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (1,'synthetic','fixture','object','synthetic','leased',?,'gen4')").run(lease);
  sql.prepare('INSERT INTO lease_items VALUES (?,1)').run(lease);
  sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,?)').run(1,COVERAGE_VALIDATOR,'f'.repeat(64),now);
  const authority={leaseId:lease,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),
    sourceSha256:await sha256Hex(encodeUtf8('synthetic source\n'))};
  await stageObjectAudit(env,account,authority,index,now);
  const row=()=>sql.prepare('SELECT * FROM object_audit_candidates').get();
  const histories=()=>sql.prepare('SELECT * FROM object_audit_recoveries ORDER BY created_at,request_id').all();
  const failed=()=>sql.prepare("UPDATE object_audit_candidates SET native_state='failed',native_attempts=1,job_id=?,candidate_manifest_sha256=?,receipt_sha256=?,next_attempt=?").run(job,'3'.repeat(64),'4'.repeat(64),now+60);
  const paused=()=>sql.prepare("UPDATE object_audit_candidates SET transport_failures=8,next_attempt=?,last_error='object_audit_transport_unavailable'").run(now+900);
  const reply=(changes={})=>({version:1,jobId:job,leaseId:lease,profileId:authority.profileId,policyId:authority.policyId,
    assignmentSha256:authority.assignmentSha256,submissionSha256:row().submission_sha256,candidateManifestSha256:'3'.repeat(64),
    state:'queued',decision:'pending',attempts:1,retryAt:0,receiptSha256:'4'.repeat(64),serverAuthorization:false,
    productionQualified:false,acceptedContributions:0,searchCreditsCreated:0,...changes});
  const recover=(action='resume-transport',requestId=key(1),at=now,timeout=20000)=>recoverObjectAudit(env,account,lease,{action,requestId},at,timeout);
  const noCredit=()=>{assert.equal(sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
    assert.equal(sql.prepare('SELECT count(*) AS n FROM published_index').get().n,0);
    assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,10);};
  return {sql,env,authority,row,histories,failed,paused,reply,recover,noCredit};
}
test('recovery requires explicit complete schema and refuses altered or future contracts',async t=>{
  const s=await setup(t,false);s.paused();
  await assert.rejects(s.recover(),{message:'object_recovery_setup_required',status:503});
  assert.equal(s.sql.prepare("SELECT count(*) AS n FROM sqlite_master WHERE name='object_audit_recoveries'").get().n,0);
  await prepareObjectAuditRecovery(s.env.DB);await prepareObjectAuditRecovery(s.env.DB);
  s.sql.exec('DROP TRIGGER object_recovery_immutable; CREATE TRIGGER object_recovery_immutable BEFORE UPDATE ON object_audit_recoveries BEGIN SELECT 1; END');
  await assert.rejects(prepareObjectAuditRecovery(s.env.DB));
  s.sql.exec("UPDATE object_recovery_revision SET contract='future'");
  await assert.rejects(s.recover(),{message:'object_recovery_setup_required'});
  assert.equal(s.sql.prepare('SELECT contract FROM object_recovery_revision').get().contract,'future');
});
test('explicit transport resume preserves the failure and replay cannot reset another failure',async t=>{
  const s=await setup(t);s.paused();const original=s.row();
  const result=await s.recover();assert.equal(result.recoveryState,'applied');assert.equal(result.freshAuditReply,false);
  assert.equal(s.row().transport_failures,0);assert.equal(s.row().next_attempt,now);
  const h=s.histories()[0];assert.equal(h.prior_failures,8);assert.equal(h.prior_retry_at,original.next_attempt);
  assert.equal(h.prior_error,original.last_error);assert.equal(h.expected_attempts,0);assert.equal(h.prior_receipt,null);
  s.paused();await s.recover();assert.equal(s.row().transport_failures,8);assert.equal(s.histories().length,1);s.noCredit();
  assert.throws(()=>s.sql.exec("UPDATE object_audit_recoveries SET prior_error='rewritten'"),/object_recovery_immutable/);
});

test('an explicitly authorized native retry keeps its one nonce while the queue drains',async t=>{
  const s=await setup(t);s.failed();let calls=0;
  s.sql.prepare('UPDATE leases SET expires_at=?').run(now+20000);
  s.env.OBJECT_VERIFIER={async fetch(request){calls++;assert.deepEqual(await request.json(),{requestId:key(1),expectedAttempts:1});
    return Response.json({error:'object_job_queue_full'},{status:503});}};
  for(let i=0;i<10;i++){
    const at=now+i*900,result=await s.recover('retry-native',key(1),at);
    assert.equal(result.recoveryState,'pending');assert.equal(result.recoveryNeedsAttention,false);
    assert.equal(result.recoveryRetryAt,at+900);assert.equal(s.histories().length,1);
    assert.equal(s.histories()[0].transport_failures,0);assert.equal(s.row().native_attempts,1);
    await s.recover('retry-native',key(1),at+1);assert.equal(calls,i+1);s.noCredit();
  }
  s.env.OBJECT_VERIFIER={async fetch(request){assert.deepEqual(await request.json(),{requestId:key(1),expectedAttempts:1});return Response.json(s.reply());}};
  const resumed=await s.recover('retry-native',key(1),s.histories()[0].next_attempt);
  assert.equal(resumed.recoveryState,'applied');assert.equal(s.histories().length,1);s.noCredit();
});
test('transport resume allowance is finite and each paused episode requires a new explicit nonce',async t=>{
  const s=await setup(t);
  for(let i=1;i<=4;i++){s.paused();await s.recover('resume-transport',key(i),now+i);}
  s.paused();await assert.rejects(s.recover('resume-transport',key(5),now+5),{message:'object_recovery_limited',status:429});
  assert.equal(s.row().transport_failures,8);assert.equal(s.histories().length,4);s.noCredit();
});
test('recovery never silently starts work or authorizes a fourth native attempt',async t=>{
  const s=await setup(t);
  await assert.rejects(s.recover(),{message:'object_recovery_not_needed'});
  await assert.rejects(s.recover('retry-native'),{message:'object_recovery_not_needed'});
  s.failed();s.sql.exec('UPDATE object_audit_candidates SET native_attempts=3');
  await assert.rejects(s.recover('retry-native'),{message:'object_recovery_not_needed'});
  assert.equal(s.histories().length,0);s.noCredit();
});
test('native retry intent is durable before transmission and replay cannot repeat a completed retry',async t=>{
  const s=await setup(t);s.failed();let calls=0;
  s.env.OBJECT_VERIFIER={async fetch(request){calls++;assert.equal(s.histories()[0].state,'pending');
    assert.equal(request.url,`https://object-verifier.internal/object-audits/${job}/retry`);
    assert.deepEqual(await request.json(),{requestId:key(1),expectedAttempts:1});return Response.json(s.reply());}};
  const result=await s.recover('retry-native');assert.equal(result.recoveryState,'applied');assert.equal(result.accepted,0);
  assert.equal(s.row().native_attempts,1);assert.equal(s.row().native_state,'queued');
  s.sql.exec("UPDATE object_audit_candidates SET native_state='failed',native_attempts=2");
  await s.recover('retry-native');assert.equal(calls,1);assert.equal(s.row().native_state,'failed');
  assert.equal(s.histories()[0].prior_native_state,'failed');assert.equal(s.histories()[0].prior_receipt,'4'.repeat(64));s.noCredit();
});
test('lost retry acknowledgement repeats one immutable nonce and observes the later failed attempt',async t=>{
  const s=await setup(t);s.failed();let calls=0,body;
  s.env.OBJECT_VERIFIER={async fetch(request){calls++;const next=await request.text();if(body)assert.equal(next,body);body=next;
    if(calls===1)throw Error('synthetic lost retry acknowledgement');
    return Response.json(s.reply({state:'failed',attempts:2,retryAt:now+90,receiptSha256:null}));}};
  const first=await s.recover('retry-native');assert.equal(first.recoveryState,'pending');assert.equal(first.recoveryRetryAt,now+30);
  await s.recover('retry-native',key(1),now+29);assert.equal(calls,1);
  const second=await s.recover('retry-native',key(1),now+30);assert.equal(second.recoveryState,'applied');
  assert.equal(s.row().native_attempts,2);assert.equal(s.row().native_state,'failed');
  await s.recover('retry-native',key(1),now+60);assert.equal(calls,2);s.noCredit();
});
test('normal saved-job observation of a newer attempt settles an uncertain retry without another POST',async t=>{
  const s=await setup(t);s.failed();s.env.OBJECT_VERIFIER={fetch(){throw Error('synthetic lost ack');}};
  await s.recover('retry-native');
  s.env.OBJECT_VERIFIER={fetch(request){assert.equal(request.method,'GET');return Response.json(s.reply({state:'approved',decision:'approved',attempts:2,receiptSha256:'5'.repeat(64)}));}};
  await advanceObjectAudit(s.env,account,lease,now+60);
  s.env.OBJECT_VERIFIER={fetch(){assert.fail('repeated retry');}};
  const result=await s.recover('retry-native',key(1),now+90);assert.equal(result.recoveryState,'applied');
  assert.equal(result.freshAuditReply,false);assert.equal(result.auditState,'approved');s.noCredit();
});
test('concurrent recovery requests share a saved claim and late replies cannot change it',async t=>{
  const s=await setup(t);s.failed();let complete,calls=0;
  s.env.OBJECT_VERIFIER={fetch(){calls++;return new Promise(resolve=>{complete=resolve;});}};
  const first=s.recover('retry-native');while(!complete)await new Promise(resolve=>setTimeout(resolve,1));
  assert.equal((await s.recover('retry-native')).freshAuditReply,false);assert.equal(calls,1);
  await assert.rejects(s.recover('retry-native',key(2)),{message:'object_recovery_busy'});
  complete(Response.json(s.reply()));await first;assert.equal(s.row().claim_token,null);s.noCredit();
});
test('deletion and lease revocation win over a delayed native retry approval',async t=>{
  for(const deleted of [false,true]){
    const s=await setup(t);s.failed();
    s.env.OBJECT_VERIFIER={async fetch(){
      if(deleted)await deleteAccount(s.env,account,{accountId:account,confirmation:'DELETE',idempotencyKey:key(8)},now+1);
      else s.sql.exec("UPDATE leases SET state='expired'");
      return Response.json(s.reply({state:'approved',decision:'approved',attempts:2,receiptSha256:'5'.repeat(64)}));}};
    if(deleted)await assert.rejects(s.recover('retry-native'),{message:'account_not_active',status:401});
    else assert.equal((await s.recover('retry-native')).freshAuditReply,false);
    assert.equal(s.row().state,'cancelled');assert.equal(s.row().receipt_sha256,null);assert.equal(s.histories()[0].state,'pending');
    assert.equal(s.histories()[0].prior_receipt,'4'.repeat(64));
    assert.equal(s.sql.prepare('SELECT active_lease FROM locations').get().active_lease,null);
  }
});
test('malformed, old-attempt and mismatched replies cannot clear a recovery intent',async t=>{
  for(const changed of [{jobId:'e'.repeat(32)},{candidateManifestSha256:'9'.repeat(64)},
    {state:'failed',attempts:1},{productionQualified:true},{acceptedContributions:1}]){
    const s=await setup(t);s.failed();s.env.OBJECT_VERIFIER={fetch:()=>Response.json(s.reply(changed))};
    const result=await s.recover('retry-native');assert.equal(result.freshAuditReply,false);assert.equal(result.recoveryState,'pending');
    assert.equal(s.row().native_state,'failed');assert.equal(s.histories()[0].transport_failures,1);s.noCredit();
  }
});
test('deadline covers stalled and late control replies without retaining private error text',async t=>{
  const s=await setup(t);s.failed();let complete,cancelled=false;
  s.env.OBJECT_VERIFIER={fetch:()=>new Promise(resolve=>{complete=resolve;})};
  assert.equal((await s.recover('retry-native',key(1),now,5)).recoveryState,'pending');
  complete(new Response(new ReadableStream({cancel(){cancelled=true;}}),{headers:{'content-type':'application/json'}}));
  await new Promise(resolve=>setTimeout(resolve,5));assert.equal(cancelled,true);
  assert.equal(s.row().claim_token,null);assert.equal(s.histories()[0].transport_failures,1);s.noCredit();
});
test('late transaction failure rolls back the recovery receipt and candidate reset together',async t=>{
  const s=await setup(t);s.paused();
  s.sql.exec("CREATE TRIGGER injected BEFORE UPDATE ON object_audit_recoveries WHEN NEW.state='applied' BEGIN SELECT RAISE(ABORT,'synthetic_late_failure'); END");
  await assert.rejects(s.recover(),/synthetic_late_failure/);assert.equal(s.histories().length,0);
  assert.equal(s.row().transport_failures,8);assert.equal(s.row().last_error,'object_audit_transport_unavailable');s.noCredit();
});
test('reusing a nonce for another action, owner or assignment is a conflict',async t=>{
  const s=await setup(t);s.paused();await s.recover();s.failed();
  await assert.rejects(s.recover('retry-native'),{message:'object_recovery_conflict'});
  await assert.rejects(recoverObjectAudit(s.env,other,lease,{action:'resume-transport',requestId:key(1)},now),{message:'unknown_object_candidate'});
  assert.equal(s.histories().length,1);s.noCredit();
});
test('invalid identity, action, request nonce and timing fail before mutation or transport',async t=>{
  const s=await setup(t);s.failed();s.env.OBJECT_VERIFIER={fetch(){assert.fail('invalid recovery forwarded');}};
  for(const [owner,assignment,request,at] of [[Symbol('invalid'),lease,{action:'retry-native',requestId:key(1)},now],
    [account,lease,{action:'retry-native',requestId:'bad'},now],[account,lease,{action:'cancel',requestId:key(1)},now],
    [account,lease,{action:'retry-native',requestId:key(1),extra:1},now],
    [account,lease,{action:'retry-native',requestId:key(1)},Number.MAX_SAFE_INTEGER]]){
    await assert.rejects(recoverObjectAudit(s.env,owner,assignment,request,at),{message:'invalid_object_recovery',status:400});
  }
  assert.equal(s.histories().length,0);s.noCredit();
});
