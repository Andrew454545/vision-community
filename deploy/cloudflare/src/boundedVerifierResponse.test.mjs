import assert from 'node:assert/strict';
import test from 'node:test';
import { readVerifierJson } from './scenePipeline.js';

test('small private verifier replies decode correctly across split UTF-8 chunks', async () => {
  const bytes = new TextEncoder().encode('{"approved":false,"message":"é"}');
  const body = new ReadableStream({ start(controller) {
    for (const value of bytes) controller.enqueue(Uint8Array.of(value));
    controller.close();
  } });
  assert.deepEqual(await readVerifierJson(new Response(body, {headers:{'content-type':'application/json; charset=utf-8'}})),
    {approved:false,message:'é'});
});

test('the exact decision-response boundary is accepted and the next byte rejected', async () => {
  assert.deepEqual(await readVerifierJson(new Response('{}'+' '.repeat(65534), {headers:{'content-type':'application/json'}})), {});
  await assert.rejects(readVerifierJson(new Response('{}'+' '.repeat(65535), {headers:{'content-type':'application/json'}})), /budget/);
});

test('oversized declared replies are cancelled before reading', async () => {
  let cancelled = false;
  const response = new Response(new ReadableStream({ cancel() {cancelled=true;} }),
    {headers:{'content-type':'application/json','content-length':'65537'}});
  await assert.rejects(readVerifierJson(response), /invalid_verifier_response/);
  assert.equal(cancelled,true);
});

test('missing length does not allow a stream to exceed the byte budget', async () => {
  let cancelled = false;
  const response = new Response(new ReadableStream({start(controller) {
    controller.enqueue(new Uint8Array(64000));controller.enqueue(new Uint8Array(2000));
  },cancel() {cancelled=true;} }),{headers:{'content-type':'application/json'}});
  await assert.rejects(readVerifierJson(response), /budget/);
  assert.equal(cancelled,true);
});

test('malformed JSON, invalid UTF-8, wrong content type and invalid declared lengths fail', async () => {
  for (const [body,headers] of [['not-json',{'content-type':'application/json'}],
    [Uint8Array.of(0xff),{'content-type':'application/json'}],['{}',{'content-type':'text/html'}],
    ['{}',{'content-type':'application/json','content-length':'-1'}],['{}',{'content-type':'application/json','content-length':'1, 2'}]]) {
    await assert.rejects(readVerifierJson(new Response(body,{headers})));
  }
});

test('a stalled response has a deadline and cancellation cannot extend it', async () => {
  let cancelled = false;
  const response = new Response(new ReadableStream({cancel() {cancelled=true;return new Promise(()=>{});} }),
    {headers:{'content-type':'application/json'}});
  await assert.rejects(readVerifierJson(response,20),/timeout/);
  assert.equal(cancelled,true);
});

test('empty chunks cannot starve the deadline forever or grow a chunk list', async () => {
  let reads = 0, cancelled = false;
  const response = new Response(new ReadableStream({pull(controller) {reads++;controller.enqueue(new Uint8Array());},
    cancel() {cancelled=true;} }),{headers:{'content-type':'application/json'}});
  await assert.rejects(readVerifierJson(response),/read_budget/);
  assert.ok(reads<=65539);
  assert.equal(cancelled,true);
});

test('invalid timeout options fail before acquiring a reader', async () => {
  for (const timeout of [0,10001,1.5,NaN]) {
    await assert.rejects(readVerifierJson(Response.json({approved:true}),timeout),/invalid_verifier_response/);
  }
});

test('valid JSON primitives and arrays cannot masquerade as decision objects', async () => {
  for (const value of [null,true,'approved',[],1]) await assert.rejects(readVerifierJson(Response.json(value)),/invalid_verifier_response/);
});
