import assert from 'node:assert/strict';
import test from 'node:test';
import {createFiniteSceneGateway,meterSceneBindings,FINITE_HEADERS} from './finite-scene-gateway.mjs';
import {sha256Hex,encodeUtf8} from '../src/model.js';

async function configuration(){const until=String(Date.now()+600000);return {
  DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',
  DELETION_ARCHIVE_DB_ID:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',FINITE_SCENE_ACCOUNT:'272760294910ef0b246980278aeb36e2',
  SCENE_ADMISSION_MODE:'qualified-device-v1',SCENE_AUDIT_MAX_LOCATIONS:'2',
  SCENE_COHORT_ACCOUNTS:JSON.stringify(['a'.repeat(64)]),SCENE_COHORT_UNTIL:until,FINITE_SCENE_UNTIL:until,
  FINITE_SCENE_TOKEN_SHA256:await sha256Hex(encodeUtf8('b'.repeat(64))),DB:{},INDEX:{},
};}
const request=(path='/api/me',token='b'.repeat(64),method='GET')=>new Request('https://staging.test'+path,
  {method,headers:{'x-vision-finite-cohort':token,'x-vision-trial-remaining-read':'2000',
    'x-vision-trial-remaining-written':'128','x-vision-trial-remaining-puts':'4','x-vision-trial-remaining-bytes':'524288'}});

test('finite gateway refuses missing/bad scope, expired/long deadlines and wrong token before any delegate',async()=>{
  let calls=0;const gateway=createFiniteSceneGateway({fetch(){calls++;throw Error('must not call');}});
  const env=await configuration();
  for(const patch of [{FINITE_SCENE_ACCOUNT:'other'},{DEPLOYMENT_ENVIRONMENT:'production'},
    {INDEX_BUCKET_NAME:'vision-community'},{SCENE_ADMISSION_MODE:'audited-v1'},
    {SCENE_COHORT_ACCOUNTS:'[]'},{SCENE_COHORT_UNTIL:'1'},
    {FINITE_SCENE_UNTIL:String(Date.now()-1)},{FINITE_SCENE_UNTIL:String(Date.now()+3600000)},
    {FINITE_SCENE_TOKEN_SHA256:undefined},{SCENE_AUDIT_MAX_LOCATIONS:'8'}])
    assert.equal((await gateway.fetch(request(),{...env,...patch})).status,503);
  assert.equal((await gateway.fetch(request('/api/me','c'.repeat(64)),env)).status,403);
  for(const path of ['/api/accounts','/api/searches','/api/scene-qualifications','/api/object-audits'])
    assert.equal((await gateway.fetch(request(path,undefined,'POST'),env)).status,404);
  assert.equal(calls,0);
});

function database({read=3,written=0,invalid=false}={}){
  let calls=0;const make=()=>({bind(){return make();},async all(){calls++;return {results:[{value:42}],
    meta:invalid?{}:{rows_read:read,rows_written:written}};},async run(){return this.all();}});
  return {prepare(){return make();},async batch(statements){const out=[];for(const s of statements)out.push(await s.run());return out;},get calls(){return calls;}};
}

test('meter preserves first/bind/batch results and native bindings cannot be used',async()=>{
  const DB=database(),INDEX={get(){return 'saved';},async put(){return 'stored';}};
  const m=meterSceneBindings({DB,INDEX,SCENE_VERIFIER:{fetch(){throw Error('native');}},SEARCH_ENGINE:{fetch(){throw Error('native');}}});
  assert.equal(await m.env.DB.prepare('read').bind('x').first('value'),42);
  assert.equal((await m.env.DB.batch([m.env.DB.prepare('write')]))[0].results[0].value,42);
  assert.equal(m.usage.read,6);assert.equal(m.env.SCENE_VERIFIER,undefined);assert.equal(m.env.SEARCH_ENGINE,undefined);
  assert.equal(m.env.INDEX.get(),'saved');assert.equal(await m.env.INDEX.put('key',new Uint8Array(3)),'stored');
  assert.equal(m.usage.puts,1);assert.equal(m.usage.bytes,3);
});

test('unknown SQL metadata and observed row overrun refuse further operations without refunding the first call',async()=>{
  const invalid=database({invalid:true}),m=meterSceneBindings({DB:invalid,INDEX:{}});
  await assert.rejects(m.env.DB.prepare('read').first(),/usage_unknown/);
  await assert.rejects(m.env.DB.prepare('again').run(),/usage_unknown/);
  assert.equal(invalid.calls,1);assert.equal(m.usage.complete,false);
  const large=database({read:2001}),n=meterSceneBindings({DB:large,INDEX:{}});
  await n.env.DB.prepare('read').all();assert.equal(n.usage.read,2001);
  await assert.rejects(n.env.DB.prepare('again').all(),/usage_limit/);assert.equal(large.calls,1);
});

test('R2 byte/write limits are checked before the next put, including rejected streaming bodies',async()=>{
  let puts=0;const make=()=>meterSceneBindings({DB:{},INDEX:{async put(){puts++;}}});
  const m=make();await m.env.INDEX.put('key',new Uint8Array(524288));
  await assert.rejects(m.env.INDEX.put('key2','x'),/upload_limit/);assert.equal(puts,1);
  const n=make();for(let i=0;i<4;i++)await n.env.INDEX.put('key'+i,'');
  await assert.rejects(n.env.INDEX.put('fifth',''),/upload_limit/);assert.equal(puts,5);
  await assert.rejects(make().env.INDEX.put('stream',new ReadableStream()),/upload_unbounded/);
});

test('actual request-scoped usage headers retain the original response and never share counters',async()=>{
  const env=await configuration();env.DB=database();env.INDEX={};
  const gateway=createFiniteSceneGateway({async fetch(_request,bindings){await bindings.DB.prepare('read').first();
    assert.equal(bindings.SCENE_VERIFIER,undefined);return Response.json({saved:true});}});
  for(let i=0;i<2;i++){
    const response=await gateway.fetch(request(),env);
    assert.equal(response.headers.get(FINITE_HEADERS.read),'3');
    assert.equal(response.headers.get('x-vision-trial-usage-complete'),'1');
    assert.deepEqual(await response.json(),{saved:true});
  }
});

test('remaining budget is required and repeated requests cannot exceed the prepared client put allowance',async()=>{
  const env=await configuration();let puts=0;env.INDEX={async put(){puts++;}};
  const gateway=createFiniteSceneGateway({async fetch(_request,bindings){
    await bindings.INDEX.put('first','x');await bindings.INDEX.put('second','x');return Response.json({saved:true});}});
  for(const remaining of [4,2]){
    const req=request();req.headers.set('x-vision-trial-remaining-puts',String(remaining));
    assert.equal((await gateway.fetch(req,env)).status,200);
  }
  const exhausted=request();exhausted.headers.set('x-vision-trial-remaining-puts','0');
  assert.equal((await gateway.fetch(exhausted,env)).status,503);assert.equal(puts,4);
  for(const invalid of ['', '-1','5','1.5']){
    const req=request();req.headers.set('x-vision-trial-remaining-puts',invalid);
    assert.equal((await gateway.fetch(req,env)).status,400);assert.equal(puts,4);
  }
});
