import assert from 'node:assert/strict';
import test from 'node:test';
import bridge, {handleObjectAuditJobs, MAX_REQUEST} from './worker.js';

const env = {NATIVE_OBJECT_VERIFIER_ORIGIN:'https://trusted-object.example.test',
  NATIVE_OBJECT_VERIFIER_SECRET:'synthetic-only-private-transport-secret'};
const body = {version:1,leaseId:'a'.repeat(32),profileId:'b'.repeat(64),policyId:'staging.synthetic',
  assignmentSha256:'c'.repeat(64),submissionSha256:'d'.repeat(64),objectIndex:{synthetic:true}};
const receipt = {version:1,jobId:'e'.repeat(32),leaseId:body.leaseId,profileId:body.profileId,policyId:body.policyId,
  assignmentSha256:body.assignmentSha256,submissionSha256:body.submissionSha256,candidateManifestSha256:'f'.repeat(64),
  state:'queued',decision:'pending',attempts:0,retryAt:0,receiptSha256:null,serverAuthorization:false,
  productionQualified:false,acceptedContributions:0,searchCreditsCreated:0};
const start = (options={}) => new Request('https://object-verifier.internal/object-audits',
  {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body),...options});
const status = (tail='', method='GET') => new Request('https://object-verifier.internal/object-audits/'+receipt.jobId+tail,
  {method,...(method === 'POST' ? {headers:{'content-type':'application/json'},body:'{}'} : {})});

test('start acknowledges a pending saved job without waiting for native inference', async () => {
  const raw = JSON.stringify(body);
  const response = await handleObjectAuditJobs(start({headers:{'content-type':'application/json',
    authorization:'Bearer caller',cookie:'private'}}),env,async (url, init) => {
    assert.equal(url,env.NATIVE_OBJECT_VERIFIER_ORIGIN+'/object-audits');
    assert.equal(new TextDecoder().decode(init.body),raw);
    assert.equal(init.headers.authorization,'Bearer '+env.NATIVE_OBJECT_VERIFIER_SECRET);
    assert.equal(init.headers.cookie,undefined);
    assert.equal(init.headers['content-length'],undefined);
    assert.equal(init.redirect,'manual');
    return Response.json(receipt,{headers:{'set-cookie':'private','x-private-path':'hidden'}});
  });
  assert.equal(response.status,200);
  assert.deepEqual(await response.json(),receipt);
  assert.equal(response.headers.get('set-cookie'),null);
  assert.equal(response.headers.get('x-private-path'),null);
});

test('status, cancellation and explicit bounded retry use exact private paths', async () => {
  for (const [tail, method] of [['','GET'],['/cancel','POST'],['/retry','POST']]) {
    const response = await handleObjectAuditJobs(status(tail,method),env,async (url,init) => {
      assert.equal(url,env.NATIVE_OBJECT_VERIFIER_ORIGIN+'/object-audits/'+receipt.jobId+tail);
      assert.equal(init.method,method);
      return Response.json(tail === '/cancel' ? {...receipt,state:'cancelled'} : receipt);
    });
    assert.equal(response.status,200);
  }
});

test('only correlated native decisions with a durable receipt can complete', async () => {
  const approved = {...receipt,state:'approved',decision:'approved',attempts:1,receiptSha256:'1'.repeat(64)};
  assert.equal((await handleObjectAuditJobs(status(),env,()=>Response.json(approved))).status,200);
  for (const changes of [{jobId:'1'.repeat(32)},{decision:'approved'},{state:'approved',decision:'approved'},
    {productionQualified:true},{serverAuthorization:true},{searchCreditsCreated:10},{acceptedContributions:1},
    {receiptSha256:'private path'}, {attempts:4},{privateLog:'secret'},{jobId:[receipt.jobId]}]) {
    const response = await handleObjectAuditJobs(status(),env,()=>Response.json({...receipt,...changes}));
    assert.equal(response.status,503,JSON.stringify(changes));
    assert.deepEqual(await response.json(),{error:'object_verifier_unavailable'});
  }
  for (const field of ['leaseId','profileId','policyId','assignmentSha256','submissionSha256']) {
    assert.equal((await handleObjectAuditJobs(start(),env,()=>Response.json({...receipt,[field]:'1'.repeat(64)}))).status,503);
  }
});

test('unavailable, conflict and retry bounds remain distinct without private diagnostics', async () => {
  for (const [error, code] of [['object_job_conflict',409],['object_job_retry_limited',429],
    ['object_job_capacity_reached',503],['unknown_object_job',404]]) {
    const response = await handleObjectAuditJobs(status(),env,()=>Response.json({error},{status:code}));
    assert.equal(response.status,code);
    assert.deepEqual(await response.json(),{error});
  }
  for (const response of [Response.json({error:'private path or token'},{status:503}),
    Response.json({error:'object_job_conflict',private:'secret'},{status:409}),
    new Response('private',{status:302,headers:{location:'https://other.test'}})]) {
    assert.deepEqual(await (await handleObjectAuditJobs(status(),env,()=>response)).json(),{error:'object_verifier_unavailable'});
  }
});

test('missing configuration and wrong routes never contact a host', async () => {
  for (const changes of [{NATIVE_OBJECT_VERIFIER_SECRET:'short'},{NATIVE_OBJECT_VERIFIER_ORIGIN:'http://host'},
    {NATIVE_OBJECT_VERIFIER_ORIGIN:'https://user:secret@host'},{NATIVE_OBJECT_VERIFIER_ORIGIN:'https://host/path'},
    {NATIVE_OBJECT_VERIFIER_ORIGIN:'https://host/?query=private'}]) {
    assert.equal((await handleObjectAuditJobs(start(),{...env,...changes},()=>assert.fail('forwarded'))).status,503);
  }
  for (const [url, method] of [['/qualify','POST'],['/object-audits','GET'],['/object-audits/'+receipt.jobId+'?secret=x','GET'],
    ['/object-audits/../anything','POST'],['/object-audits/'+receipt.jobId+'/retry','GET']]) {
    assert.equal((await handleObjectAuditJobs(new Request('https://object.internal'+url,{method}),env,
      ()=>assert.fail('forwarded'))).status,404);
  }
});

test('malformed, oversized and partial request framing prevents jobs', async () => {
  for (const request of [start({body:'not json'}),start({body:new Uint8Array(MAX_REQUEST+1)}),
    start({headers:{'content-type':'application/json','content-length':'1'}}),
    new Request(status('/cancel','POST'),{body:'{"path":"private"}'})]) {
    assert.equal((await handleObjectAuditJobs(request,env,()=>assert.fail('forwarded'))).status,400);
  }
});

test('deadlines cover stalled request, stalled response and fetch ignoring abort', async () => {
  const stalled = () => new ReadableStream({pull(){return new Promise(()=>{});}});
  const request = start({body:stalled(),duplex:'half'});
  const before = Date.now();
  assert.equal((await handleObjectAuditJobs(request,env,()=>assert.fail('forwarded'),10)).status,400);
  assert.equal((await handleObjectAuditJobs(status(),env,()=>new Response(stalled(),
    {headers:{'content-type':'application/json'}}),10)).status,503);
  assert.equal((await handleObjectAuditJobs(status(),env,()=>new Promise(()=>{}),10)).status,503);
  assert(Date.now()-before < 1000);
});

test('oversized or truncated upstream replies and endless empty chunks cannot approve', async () => {
  for (const response of [new Response(new Uint8Array(65537),{headers:{'content-type':'application/json'}}),
    Response.json(receipt,{headers:{'content-length':'1'}}),
    new Response(new ReadableStream({pull(controller){controller.enqueue(new Uint8Array());}}),
      {headers:{'content-type':'application/json'}})]) {
    assert.equal((await handleObjectAuditJobs(status(),env,()=>response)).status,503);
  }
});

test('Worker execution context is not mistaken for the fetch implementation', async t => {
  t.mock.method(globalThis,'fetch',()=>Response.json(receipt));
  assert.equal((await bridge.fetch(start(),env,{waitUntil(){}})).status,200);
});

test('cancellation requires acknowledgement of revocation and late fetch bodies are discarded', async () => {
  assert.equal((await handleObjectAuditJobs(status('/cancel','POST'),env,()=>Response.json(receipt))).status,503);
  let resolve, cancelled = false;
  const pending = handleObjectAuditJobs(status(),env,()=>new Promise(done => {resolve=done;}),5);
  assert.equal((await pending).status,503);
  resolve(new Response(new ReadableStream({cancel(){cancelled=true;}}),{headers:{'content-type':'application/json'}}));
  await new Promise(done => setTimeout(done,5));
  assert.equal(cancelled,true);
});

test('private erasure acknowledgement stays pending until files are confirmed erased', async () => {
  for (const state of ['erasing','erased']) {
    const tombstone = {...receipt,state};
    const response = await handleObjectAuditJobs(status('/erase','POST'),env,async (url,init) => {
      assert.equal(url,env.NATIVE_OBJECT_VERIFIER_ORIGIN+'/object-audits/'+receipt.jobId+'/erase');
      assert.equal(new TextDecoder().decode(init.body),'{}');
      return Response.json(tombstone);
    });
    assert.equal(response.status,200);
    assert.deepEqual(await response.json(),tombstone);
    assert.equal((await handleObjectAuditJobs(status('/cancel','POST'),env,()=>Response.json(tombstone))).status,200);
  }
  for (const value of [receipt,{...receipt,state:'cancelled'},
    {...receipt,state:'erasing',receiptSha256:'1'.repeat(64)},{...receipt,state:'erased',retryAt:1},
    {...receipt,state:'approved',decision:'approved',attempts:1,receiptSha256:'1'.repeat(64)}]) {
    assert.equal((await handleObjectAuditJobs(status('/erase','POST'),env,()=>Response.json(value))).status,503);
  }
  assert.equal((await handleObjectAuditJobs(status(),env,
    ()=>Response.json({...receipt,state:'erased',receiptSha256:'1'.repeat(64)}))).status,503);
});
