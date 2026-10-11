import assert from 'node:assert/strict';
import test from 'node:test';
import {eraseObjectAssignment,objectAuditCleanupLease,objectAuditCleanupKey} from './objectAuditPrivacy.js';

const lease = 'a'.repeat(32);
const erased = {version:1,leaseId:lease,policyId:'staging.synthetic',assignmentSha256:'b'.repeat(64),
  state:'erased',serverAuthorization:false,productionQualified:false};

test('logical cleanup identities cannot address an R2 object or arbitrary native path', () => {
  assert.equal(objectAuditCleanupLease(objectAuditCleanupKey(lease)),lease);
  for (const key of ['object-audit-jobs/../outside','object-audit-jobs/'+lease+'/erase','scene-quarantine/'+lease,null])
    assert.equal(objectAuditCleanupLease(key),null);
});

test('only exact completed assignment revocation acknowledges native erasure', async () => {
  const env = {OBJECT_VERIFIER:{async fetch(request) {
    assert.equal(request.url,`https://object-verifier.internal/object-assignments/${lease}/erase`);
    assert.equal(request.method,'POST');
    assert.equal(await request.text(),'{}');
    assert.equal(request.headers.get('authorization'),null);
    assert.equal(request.headers.get('cookie'),null);
    return Response.json(erased);
  }}};
  assert.equal(await eraseObjectAssignment(env,lease),true);
  for (const changes of [{state:'erasing'},{leaseId:'c'.repeat(32)},{private:'path'},
    {productionQualified:true},{serverAuthorization:true},{assignmentSha256:'invalid'}]) {
    assert.equal(await eraseObjectAssignment({OBJECT_VERIFIER:{fetch:()=>Response.json({...erased,...changes})}},lease),false);
  }
  assert.equal(await eraseObjectAssignment({},lease),false);
  assert.equal(await eraseObjectAssignment(env,'../outside'),false);
});

test('unavailable, oversized, stalled and late native replies never erase the durable outbox item', async () => {
  const stalled = () => new ReadableStream({pull(){return new Promise(()=>{});}});
  for (const fetch of [()=>Response.json({error:'unknown_object_assignment'},{status:403}),
    ()=>new Response(new Uint8Array(65537),{headers:{'content-type':'application/json'}}),
    ()=>new Response(stalled(),{headers:{'content-type':'application/json'}}),
    ()=>new Promise(()=>{}),()=>{throw Error('private token and paths');}]) {
    assert.equal(await eraseObjectAssignment({OBJECT_VERIFIER:{fetch}},lease,10),false);
  }
  let complete, cancelled = false;
  const promise = eraseObjectAssignment({OBJECT_VERIFIER:{fetch:()=>new Promise(resolve=>{complete=resolve;})}},lease,5);
  assert.equal(await promise,false);
  complete(new Response(new ReadableStream({cancel(){cancelled=true;}}),{headers:{'content-type':'application/json'}}));
  await new Promise(resolve=>setTimeout(resolve,5));
  assert.equal(cancelled,true);
});

test('optional expected assignment pins are exact and invalid expectations cannot contact the native host', async () => {
  const expected={policyId:erased.policyId,assignmentSha256:erased.assignmentSha256};let calls=0;
  const env={OBJECT_VERIFIER:{fetch(){calls++;return Response.json(erased);}}};
  assert.equal(await eraseObjectAssignment(env,lease,100,expected),true);assert.equal(calls,1);
  for(const mismatch of [{...expected,policyId:'wrong'},{...expected,assignmentSha256:'c'.repeat(64)}])
    assert.equal(await eraseObjectAssignment(env,lease,100,mismatch),false);
  const before=calls;
  for(const invalid of [{},{...expected,extra:true},{...expected,policyId:'../outside'},
    {...expected,assignmentSha256:'invalid'},[],false])
    assert.equal(await eraseObjectAssignment(env,lease,100,invalid),false);
  assert.equal(await eraseObjectAssignment(env,Symbol('bad-lease'),100,expected),false);
  assert.equal(calls,before);
});
