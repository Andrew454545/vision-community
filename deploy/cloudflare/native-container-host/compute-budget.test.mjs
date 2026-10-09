import assert from 'node:assert/strict';
import test from 'node:test';
import {BUDGET_KEY,ComputeBudgetError,reserveCompute,computeBudgetStatus} from './compute-budget.js';

const NOW=Date.UTC(2026,9,9,12),DAY=86400000;
const env={NATIVE_DAILY_COMPUTE_REQUESTS:'4',NATIVE_DAILY_CONTAINER_STARTS:'2'};
function fixture(){
  const values=new Map();let tail=Promise.resolve();
  const storage={writes:0,syncs:0,
    async get(key){return structuredClone(values.get(key));},
    async put(key,value){if(this.failWrite)throw Error('private storage details');this.writes++;values.set(key,structuredClone(value));},
    async sync(){this.syncs++;if(this.failSync)throw Error('private storage details');},
    transaction(callback){
      const pending=tail.then(async()=>{
        const before=structuredClone([...values]);
        try{return await callback(this);}catch(error){values.clear();for(const pair of before)values.set(...pair);throw error;}
      });
      tail=pending.catch(()=>{});return pending;
    }};
  return {storage,values};
}
const unavailable={message:'native_compute_budget_unavailable'};
const exhausted={message:'native_compute_budget_exhausted'};

test('missing, zero, malformed or excessive limits never grant an allowance',async()=>{
  for(const value of [undefined,null,0,4,'0','-1','04','1.0','1e2',' 4','10001','Infinity']){
    const {storage,values}=fixture();
    await assert.rejects(reserveCompute(storage,{...env,NATIVE_DAILY_COMPUTE_REQUESTS:value},'request',NOW),unavailable);
    assert.equal(values.size,0);assert.equal(storage.syncs,0);
  }
  const {storage}=fixture();
  await assert.rejects(reserveCompute(storage,{...env,NATIVE_DAILY_CONTAINER_STARTS:'1001'},'request',NOW),unavailable);
  await assert.rejects(reserveCompute(storage,env,'unknown',NOW),unavailable);
});

test('requests and container starts share one bounded durable UTC-day record',async()=>{
  const {storage,values}=fixture();
  for(let i=0;i<4;i++)await reserveCompute(storage,env,'request',NOW);
  await assert.rejects(reserveCompute(storage,env,'request',NOW),error=>
    error instanceof ComputeBudgetError&&error.message===exhausted.message&&error.retryAfter===43200);
  for(let i=0;i<2;i++)await reserveCompute(storage,env,'start',NOW);
  await assert.rejects(reserveCompute(storage,env,'start',NOW),exhausted);
  assert.equal(values.size,1);assert.equal(values.get(BUDGET_KEY).requests,4);assert.equal(values.get(BUDGET_KEY).starts,2);
  assert.equal(storage.writes,6);assert.equal(storage.syncs,8);
});

test('reopening keeps spent allowance, midnight resets it and clock rollback stays closed',async()=>{
  const {storage,values}=fixture();
  const single={...env,NATIVE_DAILY_COMPUTE_REQUESTS:'1'};
  await reserveCompute(storage,single,'request',NOW);
  const reopened={...storage,transaction:storage.transaction.bind(storage),sync:storage.sync.bind(storage)};
  await assert.rejects(reserveCompute(reopened,single,'request',NOW+1),exhausted);
  await reserveCompute(reopened,single,'request',NOW+DAY);
  assert.equal(values.get(BUDGET_KEY).day,Math.floor((NOW+DAY)/DAY));
  assert.equal(values.get(BUDGET_KEY).requests,1);
  await assert.rejects(reserveCompute(reopened,single,'request',NOW),unavailable);
});

test('limits cannot be raised after a redeploy and a lowering below usage remains sealed',async()=>{
  const {storage,values}=fixture();
  await reserveCompute(storage,env,'request',NOW);
  await reserveCompute(storage,env,'request',NOW);
  const lowered={...env,NATIVE_DAILY_COMPUTE_REQUESTS:'1'};
  await assert.rejects(reserveCompute(storage,lowered,'request',NOW),exhausted);
  assert.equal(values.get(BUDGET_KEY).requestLimit,1);
  const raised={...env,NATIVE_DAILY_COMPUTE_REQUESTS:'8'};
  await assert.rejects(reserveCompute(storage,raised,'request',NOW),exhausted);
  assert.equal(values.get(BUDGET_KEY).requests,2);
  await reserveCompute(storage,raised,'request',NOW+DAY);
  assert.equal(values.get(BUDGET_KEY).requestLimit,8);
});

test('concurrent reservations never oversubscribe the transaction allowance',async()=>{
  const {storage,values}=fixture();
  const results=await Promise.allSettled(Array.from({length:20},()=>reserveCompute(storage,env,'request',NOW)));
  assert.equal(results.filter(result=>result.status==='fulfilled').length,4);
  assert.ok(results.filter(result=>result.status==='rejected').every(result=>result.reason.message===exhausted.message));
  assert.equal(values.get(BUDGET_KEY).requests,4);
});

test('failed writes roll back and an unconfirmed reservation never grants work',async()=>{
  const {storage,values}=fixture();storage.failWrite=true;
  await assert.rejects(reserveCompute(storage,env,'request',NOW),unavailable);
  assert.equal(values.size,0);
  storage.failWrite=false;storage.failSync=true;
  await assert.rejects(reserveCompute(storage,env,'request',NOW),unavailable);
  assert.equal(values.get(BUDGET_KEY).requests,1);
  storage.failSync=false;
  await reserveCompute(storage,env,'request',NOW);
  assert.equal(values.get(BUDGET_KEY).requests,2);
});

test('corrupted records and bad clocks fail closed even after a day boundary',async()=>{
  const {storage,values}=fixture();await reserveCompute(storage,env,'request',NOW);
  const saved=structuredClone(values.get(BUDGET_KEY));
  for(const changed of [null,[],{}, {...saved,version:2},{...saved,requests:NaN},
    {...saved,starts:-1},{...saved,day:true},{...saved,day:saved.day+2},
    {...saved,requestLimit:0},{...saved,requests:10001},{...saved,extra:'private'}]){
    values.set(BUDGET_KEY,changed);
    await assert.rejects(reserveCompute(storage,env,'request',NOW+DAY),unavailable);
    assert.deepEqual(values.get(BUDGET_KEY),changed);
  }
  values.set(BUDGET_KEY,saved);
  for(const now of [-1,NaN,Infinity,1.5,8640000000000001])await assert.rejects(reserveCompute(storage,env,'request',now),unavailable);
});

test('status is aggregate-only and never writes, refunds or grants a request',async()=>{
  const {storage,values}=fixture();await reserveCompute(storage,env,'request',NOW);
  const before=structuredClone([...values]),writes=storage.writes;
  assert.equal((await computeBudgetStatus(storage,env,NOW)).requestsRemaining,3);
  assert.deepEqual(await computeBudgetStatus(storage,{},NOW),{configured:false,reason:unavailable.message});
  assert.deepEqual([...values],before);assert.equal(storage.writes,writes);
});
