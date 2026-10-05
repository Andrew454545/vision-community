import assert from 'node:assert/strict';
import test from 'node:test';
import { readRequestJson, MAX_JSON_BODY_BYTES } from './requestBody.js';

function request(body, headers = {}) {
  return new Request('https://community.test/api/accounts', { method:'POST', body, headers, duplex:'half' });
}
test('split UTF-8, exact byte boundary and valid object JSON are accepted', async () => {
  const value = new TextEncoder().encode('{"text":"é"}');
  const stream = new ReadableStream({start(controller) {
    for (const byte of value) controller.enqueue(Uint8Array.of(byte));
    controller.close();
  }});
  assert.deepEqual(await readRequestJson(request(stream)), {text:'é'});
  assert.deepEqual(await readRequestJson(request('{}'+' '.repeat(MAX_JSON_BODY_BYTES-2))), {});
});
test('oversized/malformed declared lengths are rejected and cancelled before reading', async () => {
  for (const declared of [String(MAX_JSON_BODY_BYTES+1), '-1', '1, 2']) {
    let cancelled = false;
    const body = new ReadableStream({cancel() {cancelled=true;}}, {highWaterMark:0});
    await assert.rejects(readRequestJson(request(body, {'content-length':declared})), {status:413});
    assert.equal(cancelled,true);
  }
});
test('missing or dishonest length cannot let the stream exceed the memory budget', async () => {
  for (const headers of [{}, {'content-length':'2'}]) {
    let cancelled=false;
    const body=new ReadableStream({start(controller) {
      controller.enqueue(new Uint8Array(MAX_JSON_BODY_BYTES));controller.enqueue(Uint8Array.of(32));
    },cancel() {cancelled=true;}});
    await assert.rejects(readRequestJson(request(body,headers)),{status:413});
    assert.equal(cancelled,true);
  }
});
test('invalid UTF-8, JSON shapes and mismatched lengths are not accepted', async () => {
  for (const body of ['[]','null','"text"','{',Uint8Array.of(255)])
    await assert.rejects(readRequestJson(request(body)),{status:400});
  await assert.rejects(readRequestJson(request('{}',{'content-length':'1'})),{status:400});
});
test('stalled reads have a deadline even when cancellation never finishes', async () => {
  let cancelled=false;
  const body=new ReadableStream({cancel() {cancelled=true;return new Promise(()=>{});}});
  await assert.rejects(readRequestJson(request(body),20),{status:408});
  assert.equal(cancelled,true);
});
test('empty chunks cannot indefinitely starve the deadline or allocate a chunk list', async () => {
  let reads=0,cancelled=false;
  const body=new ReadableStream({pull(controller) {reads++;controller.enqueue(new Uint8Array());},
    cancel() {cancelled=true;}});
  await assert.rejects(readRequestJson(request(body)),{status:408});
  assert.ok(reads<=65538);assert.equal(cancelled,true);
});
