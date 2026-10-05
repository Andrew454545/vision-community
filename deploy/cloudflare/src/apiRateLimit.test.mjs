import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import test from 'node:test';
import worker from './worker.js';
import {ingressLimit,accountLimit,viewLimit} from './apiRateLimit.js';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
const allow=()=>({limit:async()=>({success:true})});
const env=()=>({RATE_LIMITS_REQUIRED:'1',API_INGRESS_LIMITER:allow(),API_RATE_LIMITER:allow(),API_VIEW_LIMITER:allow()});
const request=(path='/api/status')=>new Request('https://community.test'+path,{headers:{'CF-Connecting-IP':'192.0.2.123'}});

test('missing, malformed and failing required limiters stop before database or body work',async()=>{
  for(const modify of [e=>delete e.API_RATE_LIMITER,e=>e.RATE_LIMITS_REQUIRED='mistyped',
    e=>{e.DEPLOYMENT_ENVIRONMENT='staging';delete e.RATE_LIMITS_REQUIRED;},
    e=>{e.INDEX_BUCKET_NAME='vision-community';e.RATE_LIMITS_REQUIRED='0';},
    e=>e.API_INGRESS_LIMITER={limit:async()=>{throw Error('PRIVATE provider exception');}},
    e=>e.API_INGRESS_LIMITER={limit:async()=>({success:'true'})},
    e=>e.API_INGRESS_LIMITER={limit:async()=>({success:false})}]) {
    const e=env();let touched=0;e.DB={prepare(){touched++;throw Error('must not execute');}};modify(e);
    const r={url:'https://community.test/api/accounts',method:'POST',headers:new Headers({'content-type':'application/json'}),get body(){touched++;throw Error('must not read');}};
    const response=await worker.fetch(r,e);assert.ok([429,503].includes(response.status));assert.equal(touched,0);
    assert.equal(response.headers.get('retry-after'),'60');assert.doesNotMatch(await response.text(),/PRIVATE|provider/);
  }
});
test('counter keys contain no raw address, token, recovery code or query and cannot be rotated by path',async()=>{
  const e=env(),keys=[];e.API_INGRESS_LIMITER={limit:async({key})=>{keys.push(key);return {success:true};}};
  await ingressLimit(e,request());await ingressLimit(e,request('/api/me?secret=private-prompt'));
  assert.equal(keys[0],keys[1]);assert.match(keys[0],/^ingress:local:[0-9a-f]{64}$/);assert.doesNotMatch(keys[0],/192\.0\.2|private/);
  const accounts=[];e.API_RATE_LIMITER={limit:async({key})=>{accounts.push(key);return {success:true};}};
  await accountLimit(e,request(),'same-account');await accountLimit(e,request('/api/searches'),'same-account');
  assert.deepEqual(accounts,['account:same-account','account:same-account']);
});
test('a stalled configured limiter returns a retryable failure after a bounded wait',async()=>{
  const e=env();e.API_INGRESS_LIMITER={limit:()=>new Promise(()=>{})};
  await assert.rejects(ingressLimit(e,request()),{message:'rate_limit_unavailable',status:503});
});
test('view and account budgets reject before imagery or upload reads and preserve balances',async t=>{
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());const calls=[];const db=sqliteD1(sql,q=>calls.push(q));
  await prepareDatabase(db);const e={...env(),DB:db};
  const created=await worker.fetch(new Request('https://community.test/api/accounts',{method:'POST',headers:{'content-type':'application/json'},body:'{}'}),e);
  assert.equal(created.status,201);
  const account=await created.json();const session=created.headers.get('set-cookie').split(';')[0];
  sql.prepare('UPDATE accounts SET units=100000 WHERE id=?').run(account.accountId);
  e.API_VIEW_LIMITER={limit:async()=>({success:false})};
  let external=0;const original=globalThis.fetch;globalThis.fetch=async()=>{external++;throw Error('must not retrieve imagery');};t.after(()=>{globalThis.fetch=original;});
  const preview=await worker.fetch(new Request('https://community.test/api/views?pano=abcdefghijklmnopqrstuv',{headers:{cookie:session}}),e);
  assert.equal(preview.status,429);assert.equal(external,0);
  e.API_RATE_LIMITER={limit:async()=>({success:false})};
  let bodyReads=0;const upload={url:'https://community.test/api/submissions',method:'POST',headers:new Headers({cookie:session,'content-type':'application/json'}),get body(){bodyReads++;throw Error('must not read');}};
  const refused=await worker.fetch(upload,e);assert.equal(refused.status,429);assert.equal(bodyReads,0);
  assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(account.accountId).units,100000);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM ledger').get().n,0);
});
test('unknown routes, wrong methods and foreign origins cannot cause schema or account reads',async()=>{
  const e=env();e.DB={prepare(){throw Error('must not access database');}};
  for(const r of [new Request('https://community.test/api/unknown'),new Request('https://community.test/api/accounts'),
    new Request('https://community.test/api/me',{headers:{origin:'https://foreign.test'}})]) {
    const response=await worker.fetch(r,e);assert.ok([403,404].includes(response.status));
  }
});
