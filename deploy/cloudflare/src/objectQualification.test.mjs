// Real local SQLite and Worker authentication; all numerical/native evidence is
// synthetic. This is not actual Mac/PC inference or production qualification.
import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareObjectQualification} from '../tools/prepare-object-qualification.mjs';
import {OBJECT_QUALIFICATION_CONTRACT} from './objectQualificationSchema.js';
import {qualifyObjectDevice,objectQualificationStatus,activeObjectQualification,revokeObjectQualification,
  objectQualificationConfigured} from './objectQualification.js';
import {sha256Hex,encodeUtf8} from './model.js';
import worker from './worker.js';
import {policy,evidence} from '../tools/fixtures/object-qualification-proof.mjs';

const account='a'.repeat(32),other='b'.repeat(32),profile='c'.repeat(64),settings='d'.repeat(64),token='synthetic-private-token';
const now=Math.floor(Date.now()/1000);
const body=(n=1)=>({requestId:n.toString(16).padStart(32,'0'),profileId:profile,artifactSetSha256:'e'.repeat(64)});
async function fixture(t,install=true) {
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const env={DB:sqliteD1(sql),DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',
    OBJECT_QUALIFICATION_MODE:'saved-sample-v1',OBJECT_QUALIFICATION_POLICY:JSON.stringify(policy()),
    RATE_LIMITS_REQUIRED:'1',API_RATE_LIMITER:{limit:async()=>({success:true})},API_INGRESS_LIMITER:{limit:async()=>({success:true})},
    API_VIEW_LIMITER:{limit:async()=>({success:true})}};
  await prepareDatabase(env.DB);if(install)await prepareObjectQualification(env.DB);
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES (?,?,0)').run(account,await sha256Hex(encodeUtf8(token)));
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'other-private',0)").run(other);
  const requests=[];
  env.OBJECT_QUALIFIER={async fetch(req){const request=await req.json();requests.push(request);return Response.json(evidence(request));}};
  const call=(path='/api/object-qualifications',data=body(),auth=token)=>worker.fetch(new Request('https://community.test'+path,{
    method:data===null?'GET':'POST',headers:{'content-type':'application/json',...(auth?{authorization:'Bearer '+auth}:{})},
    ...(data===null?{}:{body:JSON.stringify(data)})}),env,{});
  const qualify=(data=body(),at=now,timeout=70000)=>qualifyObjectDevice(env,account,data,at,timeout);
  const zero=()=>{assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,0);
    for(const table of ['ledger','published_index','leases'])assert.equal(sql.prepare(`SELECT COUNT(*) n FROM ${table}`).get().n,0);};
  return {sql,env,requests,qualify,call,zero,row:(n=1)=>sql.prepare('SELECT * FROM object_qualification_requests WHERE id=?').get(body(n).requestId)};
}

test('explicit migration is repeatable, checks exact fences and refuses a missing revision with retained data',async t=>{
  const f=await fixture(t,false);
  await assert.rejects(f.qualify(),/setup_required/);
  await prepareObjectQualification(f.env.DB);await prepareObjectQualification(f.env.DB);
  assert.equal(f.sql.prepare('SELECT contract FROM object_qualification_revision').get().contract,OBJECT_QUALIFICATION_CONTRACT);
  await f.qualify();
  f.sql.exec('DELETE FROM object_qualification_revision');
  await assert.rejects(prepareObjectQualification(f.env.DB));
  assert.equal(f.row().state,'qualified');f.zero();
});
test('weakened optional trigger is refused rather than repaired or used',async t=>{
  const f=await fixture(t);
  f.sql.exec('DROP TRIGGER object_qualification_request_immutable');
  f.sql.exec('CREATE TRIGGER object_qualification_request_immutable BEFORE UPDATE ON object_qualification_requests BEGIN SELECT 1; END');
  await assert.rejects(prepareObjectQualification(f.env.DB));f.zero();
});
test('same-profile saved full sample creates reusable expiring authority and preserves the numerical false qualification flags',async t=>{
  const f=await fixture(t),result=await f.qualify();
  assert.equal(result.qualified,true);assert.equal(result.qualificationId,body().requestId);
  assert.equal(result.verification,'trusted-reference-sample-comparison');
  assert.equal(result.independentlyRecomputedRoutineUploads,false);
  assert.equal(f.row().state,'qualified');assert.equal(f.requests.length,1);
  assert.equal(f.requests[0].accountId,account);assert.equal(f.requests[0].challenge,f.row().challenge);
  assert.equal((await objectQualificationStatus(f.env,account,profile,now+1)).qualified,true);
  assert.equal((await objectQualificationStatus(f.env,account,profile,now+3600)).qualified,false);
  assert.equal(f.row().proof_sha256,await sha256Hex(encodeUtf8(f.row().proof_json)));f.zero();
});
test('lost HTTP reply/restart replays the retained qualification without comparing or extending it again',async t=>{
  const f=await fixture(t),first=await f.qualify();
  delete f.env.OBJECT_QUALIFIER;
  const next=await f.qualify();
  assert.equal(next.qualificationId,first.qualificationId);assert.equal(next.expiresAt,first.expiresAt);
  assert.equal(next.replayed,true);assert.equal(f.requests.length,1);f.zero();
});
test('account, request and artifact identities cannot be exchanged on retry',async t=>{
  const f=await fixture(t);await f.qualify();
  for(const changed of [{...body(),artifactSetSha256:'f'.repeat(64)},{...body(),profileId:'f'.repeat(64)}])
    await assert.rejects(f.qualify(changed));
  await assert.rejects(qualifyObjectDevice(f.env,other,body(),now),/conflict/);
  assert.equal(await activeObjectQualification(f.env,other,profile,now),null);f.zero();
});
test('settings, fixture, policy and environment changes cannot reuse an earlier qualification',async t=>{
  const f=await fixture(t);await f.qualify();
  for(const update of [p=>p.profiles[profile]='f'.repeat(64),p=>p.fixtureSha256='f'.repeat(64),p=>p.validUntil-=1]) {
    const p=policy();update(p);f.env.OBJECT_QUALIFICATION_POLICY=JSON.stringify(p);
    assert.equal((await objectQualificationStatus(f.env,account,profile,now)).qualified,false);
  }
  f.env.OBJECT_QUALIFICATION_POLICY=JSON.stringify(policy());f.env.INDEX_BUCKET_NAME='vision-community';
  await assert.rejects(objectQualificationStatus(f.env,account,profile,now),/policy_required/);f.zero();
});
test('explicit revocation is idempotent and old saved approvals cannot resurrect it',async t=>{
  const f=await fixture(t);await f.qualify();
  const revoke={operationId:'f'.repeat(32),profileId:profile};
  await revokeObjectQualification(f.env,account,revoke,now+1);
  await revokeObjectQualification(f.env,account,revoke,now+2);
  assert.equal(f.sql.prepare('SELECT epoch FROM object_qualification_controls').get().epoch,1);
  assert.equal((await f.qualify()).qualified,false);assert.equal(f.row().state,'qualified');
  await f.qualify(body(2));
  await revokeObjectQualification(f.env,account,revoke,now+3);
  assert.equal((await objectQualificationStatus(f.env,account,profile,now+3)).qualified,true);f.zero();
});
test('a trusted incompatible sample revokes existing profile authority once, and replay cannot revoke a newer epoch',async t=>{
  const f=await fixture(t);await f.qualify();
  f.env.OBJECT_QUALIFIER={async fetch(req){return Response.json(evidence(await req.json(),policy(),false));}};
  const failed=await f.qualify(body(2));assert.equal(failed.reason,'object_sample_incompatible');
  assert.equal((await objectQualificationStatus(f.env,account,profile,now)).qualified,false);
  assert.equal(f.row(2).state,'incompatible');
  f.env.OBJECT_QUALIFIER={async fetch(req){return Response.json(evidence(await req.json()));}};
  await f.qualify(body(3));await f.qualify(body(2));
  assert.equal((await objectQualificationStatus(f.env,account,profile,now)).qualified,true);f.zero();
});
test('revocation during a pending comparison fences its late reply',async t=>{
  const f=await fixture(t);await f.qualify();
  f.env.OBJECT_QUALIFIER={async fetch(req){const request=await req.json();
    await revokeObjectQualification(f.env,account,{operationId:'f'.repeat(32),profileId:profile},now);
    return Response.json(evidence(request));}};
  await assert.rejects(f.qualify(body(2)));
  assert.equal((await objectQualificationStatus(f.env,account,profile,now)).qualified,false);
  assert.equal(f.row(2).state,'pending');f.zero();
});
test('account deletion during comparison cancels pending work and retains immutable history without awarding credit',async t=>{
  const f=await fixture(t);await f.qualify();
  f.env.OBJECT_QUALIFIER={async fetch(req){const request=await req.json();
    f.sql.prepare('UPDATE accounts SET deleted_at=? WHERE id=?').run(now,account);return Response.json(evidence(request));}};
  await assert.rejects(f.qualify(body(2)));
  assert.equal(f.row(2).state,'cancelled');assert.equal(f.row().state,'qualified');
  await assert.rejects(objectQualificationStatus(f.env,account,profile,now),/account_not_active/);f.zero();
});
test('malformed, detector-only, mismatched settings or stale proofs are service failures and do not revoke a device',async t=>{
  const f=await fixture(t);await f.qualify();
  const changes=[v=>v.accountId=other,v=>v.challenge='0'.repeat(32),v=>v.artifactSetSha256='0'.repeat(64),
    v=>v.artifacts.indexProfileId='0'.repeat(64),v=>v.artifacts.indexSettingsSha256='0'.repeat(64),
    v=>v.report.qualificationScope='fixed-input-detector-score-parity-only',v=>delete v.report.indexComparison,
    v=>v.report.indexComparison.semantic.differentCodeBytes=1,v=>v.report.indexComparison.viewQualityDifferences=1,
    v=>v.report.qualified=true,v=>v.expiresAt=now,v=>v.report.expiresAt=policy().validUntil+1,
    v=>{v.report.sampleCompatible=v.report.scoreCompatible=false;v.report.detectorComparison.maximumBoxDifference=null;},
    v=>{v.report.sampleCompatible=v.report.indexCompatible=false;v.report.indexComparison.semantic.maximumLogitScaleDifference=-1;}];
  for(const change of changes) {
    f.env.OBJECT_QUALIFIER={async fetch(req){const value=evidence(await req.json());change(value);return Response.json(value);}};
    await assert.rejects(f.qualify(body(2)),/unavailable/);
    assert.equal(f.row(2).state,'pending');
    assert.equal((await objectQualificationStatus(f.env,account,profile,now)).qualified,true);
  }
  f.zero();
});
test('an unresponsive or oversized verifier cannot approve, debit, revoke or silently resubmit a request',async t=>{
  const f=await fixture(t);await f.qualify();let signal;
  f.env.OBJECT_QUALIFIER={fetch(req){signal=req.signal;return new Promise(()=>{});}};
  const start=Date.now();await assert.rejects(f.qualify(body(2),now,20),/unavailable/);
  assert(Date.now()-start<1000);assert(signal.aborted);assert.equal(f.row(2).claim_token,null);
  f.env.OBJECT_QUALIFIER={fetch(){return new Response(' '.repeat(65537),{headers:{'content-type':'application/json'}});}};
  await assert.rejects(f.qualify(body(2)),/unavailable/);
  assert.equal((await objectQualificationStatus(f.env,account,profile,now)).qualified,true);f.zero();
});
test('worker requires account authentication, an explicit policy and small fixed request fields',async t=>{
  const f=await fixture(t);
  assert.equal((await f.call(undefined,body(),null)).status,401);
  const saved=f.env.OBJECT_QUALIFICATION_MODE;delete f.env.OBJECT_QUALIFICATION_MODE;
  assert.equal((await f.call()).status,503);assert.equal(f.requests.length,0);
  f.env.OBJECT_QUALIFICATION_MODE=saved;
  assert.equal((await f.call(undefined,{...body(),approved:true})).status,400);
  assert.equal((await f.call(undefined,{...body(),rawSample:'x'.repeat(5000)})).status,413);
  const response=await f.call();assert.equal(response.status,200);assert.equal((await response.json()).qualified,true);
  const status=await f.call('/api/object-qualifications?profileId='+profile,null);
  assert.equal((await status.json()).qualified,true);
  assert.equal((await f.call('/api/object-qualifications/revoke',{operationId:'f'.repeat(32),profileId:profile})).status,200);
  f.zero();
});
test('sample qualification does not open Object assignments, capability readiness or publication',async t=>{
  const f=await fixture(t);await f.qualify();
  const capabilities=await f.call('/api/capabilities',null);
  assert.equal((await capabilities.json()).objectContributions.ready,false);
  const lease=await f.call('/api/leases',{lane:'object',count:1,pace:'medium',client:'native'});
  assert.equal(lease.status,503);f.zero();
});
test('authority records are immutable and retained, and raw report paths never enter stored receipts',async t=>{
  const f=await fixture(t);
  f.env.OBJECT_QUALIFIER={async fetch(req){const value=evidence(await req.json());value.report.privatePath='SYNTHETIC-PRIVATE-PATH';return Response.json(value);}};
  await f.qualify();
  assert(!f.row().proof_json.includes('SYNTHETIC-PRIVATE-PATH'));
  assert.throws(()=>f.sql.exec("UPDATE object_qualification_requests SET profile_id='changed'"),/immutable|authority_lost/);
  assert.equal(f.row().profile_id,profile);
  assert.throws(()=>f.sql.exec('DELETE FROM object_qualification_requests'),/retained/);
  assert.throws(()=>f.sql.exec('UPDATE object_qualification_controls SET epoch=0'),/immutable/);f.zero();
});
test('configuration mutation during a comparison cannot publish the stale authority',async t=>{
  const f=await fixture(t);
  f.env.OBJECT_QUALIFIER={async fetch(req){const value=evidence(await req.json());
    f.env.OBJECT_QUALIFICATION_POLICY=JSON.stringify({...policy(),fixtureSha256:'f'.repeat(64)});return Response.json(value);}};
  await assert.rejects(f.qualify(),/unavailable/);assert.equal(f.row().state,'pending');f.zero();
});
test('four pending samples bound account queue size, and expired requests cannot be revived',async t=>{
  const f=await fixture(t);f.env.OBJECT_QUALIFIER={fetch(){throw Error('synthetic offline verifier');}};
  for(let n=1;n<=4;n++)await assert.rejects(f.qualify(body(n)));
  await assert.rejects(f.qualify(body(5)));
  assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM object_qualification_requests').get().n,4);
  await assert.rejects(f.qualify(body(1),now+600),/expired/);f.zero();
});
