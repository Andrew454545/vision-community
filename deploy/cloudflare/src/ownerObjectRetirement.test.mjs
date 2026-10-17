// Fictional native/coverage/R2, real Worker handlers and local SQLite journals.
import test from 'node:test';
import assert from 'node:assert/strict';
import {ownerFixture,ACCOUNT,LEASE,SECRET} from './ownerObjectAudit.fixture.mjs';
import {prepareObjectAuditRetention} from '../tools/prepare-object-audit-retention.mjs';
import {ownerObjectBinding,completeOwnerObjectAudit} from './ownerObjectAudit.js';
import {claimOwnerObjectRetirement,acknowledgeOwnerObjectRetirement} from './ownerObjectRetirement.js';
import {deleteAccount} from './accountPrivacy.js';
import worker from './worker.js';

async function fixture(t,{accept=true,setup=true}={}){
  const f=await ownerFixture(t);
  if(setup)await prepareObjectAuditRetention(f.env.DB);
  if(accept){const claim=(await f.claim()).job;await completeOwnerObjectAudit(f.env,f.body(claim),f.now);}
  const binding=ownerObjectBinding(f.env);
  const claim=()=>claimOwnerObjectRetirement(f.env,{binding},f.now);
  const row=()=>f.sql.prepare('SELECT * FROM object_audit_retirements').get();
  const receipt=(state='retired')=>({...f.audit(),state,decision:'pending',receiptSha256:state==='erased'?null:f.audit().receiptSha256});
  return {...f,binding,retirement:claim,retentionRow:row,receipt};
}
const ack=(f,c,state)=>acknowledgeOwnerObjectRetirement(f.env,{command:c,audit:f.receipt(state)},f.now);
const paid=f=>assert.deepEqual(f.counts(),{publications:2,ledger:1,accepted:1,units:20});

test('owner retirement is authenticated and disabled before body/database access',async()=>{
  const env={OBJECT_AUDIT_DELIVERY:'owner-outbound-v1',OBJECT_AUDIT_AGENT_SECRET:SECRET,
    get DB(){throw Error('database must stay untouched');},RATE_LIMITS_REQUIRED:'1'};
  for(const name of ['API_RATE_LIMITER','API_INGRESS_LIMITER','API_VIEW_LIMITER'])env[name]={async limit(){return {success:true};}};
  const request=secret=>new Request('https://fixture.invalid/api/object-audit-agent/retirement',{
    method:'POST',headers:{authorization:'Bearer '+secret,'content-type':'application/json'},body:'not-json'});
  assert.equal((await worker.fetch(request('a'.repeat(64)),env)).status,401);
  assert.equal((await worker.fetch(request(SECRET),{})).status,503);
});
test('missing optional setup installs nothing and preserves accepted work',async t=>{
  const f=await fixture(t,{setup:false});
  await assert.rejects(f.retirement(),/owner_retirement_setup_required/);paid(f);
  assert.equal(f.sql.prepare("SELECT COUNT(*) n FROM sqlite_master WHERE name='object_audit_retirements'").get().n,0);
});
test('native approval without immutable acceptance/publication/credit cannot retire a job',async t=>{
  const f=await fixture(t,{accept:false});
  assert.deepEqual(await f.retirement(),{command:null,retryAfterSeconds:30});assert.equal(f.retentionRow(),undefined);
});
test('one exact accepted command reserves durable backoff without financial or storage changes',async t=>{
  const f=await fixture(t),reads=f.reads();const {command}=await f.retirement();
  assert.equal(command.leaseId,LEASE);assert.equal(command.body.assignmentSha256,f.authority.assignmentSha256);
  assert.equal(command.profileId,f.authority.profileId);assert.equal(command.requestSha256,f.retentionRow().request_sha256);
  assert.equal(f.retentionRow().next_attempt,f.now+60);assert.equal(f.retentionRow().failures,1);
  assert.deepEqual(await f.retirement(),{command:null,retryAfterSeconds:30});paid(f);assert.equal(f.reads(),reads);
  assert(!JSON.stringify(command).includes(ACCOUNT));assert(!JSON.stringify(command).includes('FICTIONAL-PRIVATE'));
});
test('concurrent owner polls cannot reserve the same retry twice',async t=>{
  const f=await fixture(t);const replies=await Promise.all([f.retirement(),f.retirement()]);
  assert.equal(replies.filter(r=>r.command).length,1);assert.equal(f.retentionRow().failures,1);paid(f);
});
test('retry reuses immutable command and increases reserved backoff after a lost handoff',async t=>{
  const f=await fixture(t);const first=await f.retirement();
  const next=await claimOwnerObjectRetirement(f.env,{binding:f.binding},f.now+60);
  assert.deepEqual(next.command,first.command);assert.equal(f.retentionRow().next_attempt,f.now+180);paid(f);
});
test('wrong independent bindings or mixed hosted mode cannot produce a cleanup command',async t=>{
  const f=await fixture(t);
  await assert.rejects(claimOwnerObjectRetirement(f.env,{binding:{...f.binding,policySha256:'0'.repeat(64)}}),/binding_required/);
  f.env.OBJECT_VERIFIER={};await assert.rejects(f.retirement(),/owner_object_unavailable/);paid(f);
});
test('only completed exact native cleanup is acknowledged; mutations preserve pending authority',async t=>{
  const f=await fixture(t);const {command}=await f.retirement();
  for(const change of [{state:'retiring'},{receiptSha256:'0'.repeat(64)},{jobId:'0'.repeat(32)},{private:'path'},
    {attempts:2},{serverAuthorization:true}]){
    await assert.rejects(acknowledgeOwnerObjectRetirement(f.env,{command,audit:{...f.receipt(),...change}},f.now));
    assert.equal(f.retentionRow().state,'pending');paid(f);
  }
  for(const changed of [{...command,profileId:'0'.repeat(64)},
    {...command,body:{...command.body,acceptanceSha256:'0'.repeat(64)}},
    {...command,body:{...command.body,extra:'PRIVATE'}},{...command,requestSha256:'0'.repeat(64)}])
    await assert.rejects(acknowledgeOwnerObjectRetirement(f.env,{command:changed,audit:f.receipt()},f.now));
  assert.equal(f.retentionRow().state,'pending');paid(f);
});
test('committed acknowledgement replay needs no current policy or native assets and changes no credit',async t=>{
  const f=await fixture(t);const {command}=await f.retirement();
  assert.deepEqual(await ack(f,command),{acknowledged:true,leaseId:LEASE,requestSha256:command.requestSha256,privacyPending:false});
  const saved=f.retentionRow();delete f.env.OBJECT_SETTLEMENT_POLICY;
  assert.equal((await ack(f,command)).acknowledged,true);assert.deepEqual(f.retentionRow(),saved);paid(f);
});
test('account deletion wins over in-flight retirement and its erasure outbox remains pending',async t=>{
  const f=await fixture(t);const {command}=await f.retirement();
  await deleteAccount(f.env,ACCOUNT,{accountId:ACCOUNT,confirmation:'DELETE',idempotencyKey:'e'.repeat(64)},f.now);
  assert.equal((await ack(f,command)).privacyPending,true);assert.equal(f.retentionRow().state,'privacy');
  assert.equal(f.sql.prepare('SELECT state FROM account_cleanup WHERE artifact_key=?').get('object-audit-jobs/'+LEASE).state,'pending');
  assert.equal(f.counts().publications,2);assert.equal(f.counts().ledger,1);assert.equal(f.counts().units,0);
});
test('old runtime-policy rows remain preserved and do not block a different policy poll',async t=>{
  const f=await fixture(t);await f.retirement();
  const newBinding={...f.binding,policySha256:'0'.repeat(64)};f.env.OBJECT_SETTLEMENT_POLICY=JSON.stringify(newBinding);
  assert.deepEqual(await claimOwnerObjectRetirement(f.env,{binding:newBinding},f.now+61),{command:null,retryAfterSeconds:30});
  assert.equal(f.retentionRow().state,'pending');paid(f);
});
test('actual private HTTP routes enforce body bounds and return the immutable acknowledgement',async t=>{
  const f=await fixture(t);f.env.RATE_LIMITS_REQUIRED='1';
  for(const name of ['API_RATE_LIMITER','API_INGRESS_LIMITER','API_VIEW_LIMITER'])f.env[name]={async limit(){return {success:true};}};
  const request=(action,body)=>new Request('https://fixture.invalid/api/object-audit-agent/'+action,{
    method:'POST',headers:{authorization:'Bearer '+SECRET,'content-type':'application/json'},body:JSON.stringify(body)});
  const reply=await worker.fetch(request('retirement',{binding:f.binding}),f.env);assert.equal(reply.status,200);
  const {command}=await reply.json();const done=await worker.fetch(request('retirement-ack',{command,audit:f.receipt()}),f.env);
  assert.equal(done.status,200);assert.equal((await done.json()).acknowledged,true);
  assert.equal((await worker.fetch(request('retirement-ack',{private:'x'.repeat(9000)}),f.env)).status,413);paid(f);
});
