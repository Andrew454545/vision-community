import test from 'node:test';
import assert from 'node:assert/strict';
import {ownerFixture,ACCOUNT,LEASE,JOB,SECRET} from './ownerObjectAudit.fixture.mjs';
import {ownerObjectDelivery,ownerObjectBinding,requireOwnerObjectAgent,claimOwnerObjectAudit,ownerObjectCandidate,
  completeOwnerObjectAudit,failOwnerObjectAudit,OWNER_OBJECT_RESULT_BYTES} from './ownerObjectAudit.js';
import {advanceObjectContribution} from './objectAuditFlow.js';
import {deleteAccount} from './accountPrivacy.js';
import worker from './worker.js';
const zero=f=>assert.deepEqual(f.counts(),{publications:0,ledger:0,accepted:0,units:0});
const paid=f=>assert.deepEqual(f.counts(),{publications:2,ledger:1,accepted:1,units:20});
function request(action,body={},secret=SECRET,headers={}){
  return new Request('https://fixture.invalid/api/object-audit-agent/'+action,{method:'POST',
    headers:{authorization:'Bearer '+secret,'content-type':'application/json',...headers},body:JSON.stringify(body)});
}
function limits(env){env.RATE_LIMITS_REQUIRED='1';for(const n of ['API_RATE_LIMITER','API_INGRESS_LIMITER','API_VIEW_LIMITER'])env[n]={async limit(){return{success:true};}};}

test('optional owner path is closed by default and authenticates before body/database access',async()=>{
  assert.equal(ownerObjectDelivery({}),false);
  const env={OBJECT_AUDIT_DELIVERY:'owner-outbound-v1',OBJECT_AUDIT_AGENT_SECRET:SECRET,
    get DB(){throw Error('must not touch database');}};
  limits(env);
  const wrong=await worker.fetch(request('claim',{},'a'.repeat(64)),env);
  assert.equal(wrong.status,401);assert.deepEqual(await wrong.json(),{error:'unauthorized'});
  const off=await worker.fetch(request('claim'),{});assert.equal(off.status,503);
  await assert.rejects(requireOwnerObjectAgent(env,request('claim',{},'account-code')),/unauthorized/);
  await requireOwnerObjectAgent(env,request('claim'));
});
test('independent owner capability and confirmed resource are required without a hosted fallback',async t=>{
  const f=await ownerFixture(t),binding=ownerObjectBinding(f.env);
  for(const body of [{},{binding:{...binding,runtimeProfileSha256:'a'.repeat(64)}},{binding,extra:'private'}])
    await assert.rejects(claimOwnerObjectAudit(f.env,body,f.now),/owner_object_binding_required/);
  for(const env of [{...f.env,OBJECT_VERIFIER:{fetch(){throw Error('no hosted call');}}},
    {...f.env,DEPLOYMENT_ENVIRONMENT:'production'},{...f.env,OBJECT_AUDIT_DELIVERY:'unexpected'}])
    assert.throws(()=>ownerObjectBinding(env));
  assert.equal(f.row().claim_token,null);zero(f);
});
test('concurrent claims disclose one bounded metadata job without account credentials or candidate reads',async t=>{
  const f=await ownerFixture(t),before=f.reads(),claims=await Promise.all([f.claim(),f.claim()]);
  assert.equal(claims.filter(v=>v.job).length,1);assert.equal(f.reads(),before);
  const job=claims.find(v=>v.job).job;
  assert.equal(job.claimUntil,f.now+1200);assert.equal(job.locations,2);
  assert(!JSON.stringify(job).includes(ACCOUNT));assert(!JSON.stringify(job).includes('FICTIONAL-PRIVATE'));
  assert(!JSON.stringify(job).includes('objectIndex'));zero(f);
});
test('candidate is exact hash-bound quarantine data and a stale claim cannot retrieve it',async t=>{
  const f=await ownerFixture(t),{job}=await f.claim(),body={leaseId:LEASE,claimToken:job.claimToken};
  const raw=await ownerObjectCandidate(f.env,body,f.now),native=JSON.parse(raw);
  assert.equal(native.leaseId,LEASE);assert.deepEqual(native.objectIndex,f.index);
  assert.equal(native.submissionSha256,f.row().submission_sha256);
  await assert.rejects(ownerObjectCandidate(f.env,{...body,claimToken:'a'.repeat(32)},f.now),/claim_lost/);
  const key=f.row().artifact_key;f.objects.set(key,new TextEncoder().encode('{}'));
  await assert.rejects(ownerObjectCandidate(f.env,body,f.now),/candidate_unavailable/);zero(f);
});
test('bounded candidate transport times out an unresponsive storage reader',async t=>{
  const f=await ownerFixture(t),{job}=await f.claim();
  f.env.INDEX.get=()=>new Promise(()=>{});
  const start=Date.now();await assert.rejects(ownerObjectCandidate(f.env,{leaseId:LEASE,claimToken:job.claimToken},f.now,20),/candidate_unavailable/);
  assert(Date.now()-start<1000);zero(f);
});
test('fresh approved owner completion uses existing sanitized publication and awards exactly once',async t=>{
  const f=await ownerFixture(t),{job}=await f.claim(),body=f.body(job);
  assert.equal((await completeOwnerObjectAudit(f.env,body,f.now)).unitsEarned,20);paid(f);
  assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM object_dispatch_slots').get().n,0);
  const manifest=JSON.parse(new TextDecoder().decode(f.objects.get(`object-index-v4/${LEASE}/manifest.json`)));
  assert(!JSON.stringify(manifest).includes('FICTIONAL-PRIVATE'));
  f.env.OBJECT_SETTLEMENT_POLICY='broken after committed acceptance';body.evidence=null;
  const replay=await completeOwnerObjectAudit(f.env,body,f.now+1201);
  assert.equal(replay.unitsEarned,0);assert.equal(replay.replayed,true);paid(f);
});
test('lost committed database reply recovers accepted work without another award or source check',async t=>{
  const f=await ownerFixture(t),{job}=await f.claim(),body=f.body(job),batch=f.env.DB.batch.bind(f.env.DB);let lost=false;
  f.env.DB.batch=async statements=>{const reply=await batch(statements);if(!lost&&f.counts().accepted){lost=true;throw Error('lost committed reply');}return reply;};
  await assert.rejects(completeOwnerObjectAudit(f.env,body,f.now));paid(f);
  const reads=f.reads();assert.equal((await completeOwnerObjectAudit(f.env,body,f.now+40)).unitsEarned,0);
  assert.equal(f.reads(),reads);paid(f);
});
test('expired uncommitted evidence requests real protection refresh on the same claim without charging',async t=>{
  const f=await ownerFixture(t),{job}=await f.claim(),body=f.body(job);
  await assert.rejects(completeOwnerObjectAudit(f.env,body,f.now+31),/owner_object_evidence_refresh_required/);
  assert.equal(f.row().claim_token,job.claimToken);assert.equal(f.row().job_id,null);zero(f);
  body.evidence=f.evidence(f.now+31);
  assert.equal((await completeOwnerObjectAudit(f.env,body,f.now+31)).unitsEarned,20);paid(f);
});
test('interrupted artifact publication keeps the saved native job and retries with fresh evidence on a new claim',async t=>{
  const f=await ownerFixture(t),{job}=await f.claim(),put=f.env.INDEX.put.bind(f.env.INDEX);let failed=false;
  f.env.INDEX.put=async(...args)=>{if(args[0].startsWith('object-index-v4/')&&!failed){failed=true;throw Error('fictional storage outage');}return put(...args);};
  await assert.rejects(completeOwnerObjectAudit(f.env,f.body(job),f.now));zero(f);
  assert.equal(f.row().native_state,'approved');assert.equal(f.row().job_id,JOB);
  const next=(await f.claim(f.now+30)).job;assert.equal(next.jobId,JOB);
  assert.equal((await completeOwnerObjectAudit(f.env,f.body(next,f.now+30),f.now+30)).unitsEarned,20);paid(f);
});
test('a changed native identity cannot receive a saved acceptance acknowledgement',async t=>{
  const f=await ownerFixture(t),{job}=await f.claim(),body=f.body(job);
  await completeOwnerObjectAudit(f.env,body,f.now);body.audit.jobId='a'.repeat(32);
  await assert.rejects(completeOwnerObjectAudit(f.env,body,f.now+1),/invalid_owner_object_result/);paid(f);
});
test('saved pending native identity survives status polling without publication or a hosted request',async t=>{
  const f=await ownerFixture(t),{job}=await f.claim();
  await completeOwnerObjectAudit(f.env,{...f.body(job),audit:f.audit('queued',0),evidence:null},f.now);
  zero(f);assert.equal(f.row().job_id,JOB);
  const status=await advanceObjectContribution(f.env,ACCOUNT,LEASE,f.now+1);
  assert.equal(status.auditState,'queued');assert.equal(status.accepted,0);
  const again=await f.claim(f.now+30);assert.equal(again.job.jobId,JOB);assert.equal(again.job.nativeAttempts,0);
});
test('failed or rejected native work never earns credit or retries itself automatically',async t=>{
  for(const state of ['failed','rejected']){
    const f=await ownerFixture(t),{job}=await f.claim();
    await completeOwnerObjectAudit(f.env,{...f.body(job),audit:f.audit(state),evidence:null},f.now);
    zero(f);assert.equal((await f.claim(f.now+900)).job,null);
    const status=await advanceObjectContribution(f.env,ACCOUNT,LEASE,f.now);
    if(state==='failed')assert.equal(status.needsAttention,true);else assert.equal(status.rejected,true);
  }
});
test('malformed, expired or independently mismatched evidence cannot change an active claim or mint credit',async t=>{
  for(const change of [b=>b.audit.extra='PRIVATE',b=>b.audit.profileId='a'.repeat(64),b=>b.evidence=null,
    b=>b.evidence.protectedAuthoritySha256='a'.repeat(64),b=>b.evidence.resource.bucket='vision-community',
    b=>{b.evidence.issuedAt-=31;b.evidence.expiresAt-=31;},b=>b.audit.searchCreditsCreated=20]){
    const f=await ownerFixture(t),{job}=await f.claim(),body=f.body(job);change(body);
    await assert.rejects(completeOwnerObjectAudit(f.env,body,f.now));zero(f);assert.equal(f.row().claim_token,job.claimToken);
  }
});
test('account deletion, cancellation and replaced claims fence late owner results',async t=>{
  for(const kind of ['delete','expire','replace']){
    const f=await ownerFixture(t),{job}=await f.claim();
    if(kind==='delete')await deleteAccount(f.env,ACCOUNT,{accountId:ACCOUNT,idempotencyKey:'e'.repeat(64),confirmation:'DELETE'},f.now);
    if(kind==='expire')f.sql.prepare("UPDATE leases SET state='expired' WHERE id=?").run(LEASE);
    if(kind==='replace')f.sql.prepare('UPDATE object_audit_candidates SET claim_token=? WHERE lease_id=?').run('a'.repeat(32),LEASE);
    await assert.rejects(completeOwnerObjectAudit(f.env,f.body(job),f.now));zero(f);
  }
});
test('strict fresh official Gen4 and final pose/coverage guards survive owner delivery',async t=>{
  for(const stage of ['before-claim','before-completion']){
    const f=await ownerFixture(t);let job;
    if(stage==='before-completion')job=(await f.claim()).job;
    f.sql.prepare("UPDATE locations SET camera_generation='gen3'").run();
    if(stage==='before-claim')assert.equal((await f.claim()).job,null);
    else await assert.rejects(completeOwnerObjectAudit(f.env,f.body(job),f.now));
    zero(f);
  }
});
test('healthy busy backpressure preserves attempts while repeated transport failures stop after eight',async t=>{
  const f=await ownerFixture(t);let job=(await f.claim()).job;
  const busy=await failOwnerObjectAudit(f.env,{leaseId:LEASE,claimToken:job.claimToken,reason:'busy'},f.now);
  assert.equal(busy.charged,false);assert.equal(f.row().transport_failures,0);assert.equal(busy.retryAt,f.now+900);
  let at=f.now+900;
  for(let i=1;i<=8;i++){
    job=(await f.claim(at)).job;assert(job);
    const failed=await failOwnerObjectAudit(f.env,{leaseId:LEASE,claimToken:job.claimToken,reason:'unavailable'},at);
    assert.equal(f.row().transport_failures,i);assert.equal(failed.needsAttention,i===8);at=failed.retryAt;
  }
  assert.equal((await f.claim(at)).job,null);zero(f);
});
test('HTTP owner authentication, exact commands and body limits connect to once-only publication',async t=>{
  const f=await ownerFixture(t);limits(f.env);
  let response=await worker.fetch(request('claim',{binding:ownerObjectBinding(f.env)}),f.env);
  assert.equal(response.status,200);const {job}=await response.json();assert(job);
  response=await worker.fetch(request('candidate',{leaseId:LEASE,claimToken:job.claimToken}),f.env);
  assert.equal(response.status,200);assert.equal((await response.json()).leaseId,LEASE);
  const oversized=await worker.fetch(request('complete',{padding:'x'.repeat(OWNER_OBJECT_RESULT_BYTES+1)}),f.env);
  assert.equal(oversized.status,413);zero(f);
  response=await worker.fetch(request('complete',f.body(job)),f.env);assert.equal(response.status,200);
  assert.equal((await response.json()).unitsEarned,20);paid(f);
});
test('concurrent duplicate completions cannot multiply publications or credit',async t=>{
  const f=await ownerFixture(t),{job}=await f.claim(),body=f.body(job);
  const results=await Promise.allSettled([completeOwnerObjectAudit(f.env,body,f.now),completeOwnerObjectAudit(f.env,body,f.now)]);
  assert(results.some(v=>v.status==='fulfilled'));paid(f);
});
