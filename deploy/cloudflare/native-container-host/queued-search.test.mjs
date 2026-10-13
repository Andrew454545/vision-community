// Actual SQLite and Worker queue routes; fake container transport, never inference.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {NativeController} from './controller.js';
import {QUEUED_KEY} from './queued-search.js';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareSearchHybrid} from '../tools/prepare-search-hybrid.mjs';
import {queueSearch,claimQueuedSearch,recoverSearch} from '../src/searchQueue.js';
import worker from '../src/worker.js';

const sha=v=>createHash('sha256').update(v).digest('hex');
const account='a'.repeat(32),runtime='d'.repeat(64),snapshot='e'.repeat(64);
const image=`registry.cloudflare.com/272760294910ef0b246980278aeb36e2/vision-community-native-scene@sha256:${'2'.repeat(64)}`;
const sample=new TextEncoder().encode('fictional operator bundle, no models or records');
const bundle={version:1,sha256:sha(sample),bytes:sample.length,key:`native-host/bundles/${sha(sample)}.zip`};
const key=at=>`q1.${at}.${'4'.repeat(32)}`;
function d1(sql){return {prepare(query){const bind=(args=[])=>({bind:(...v)=>bind(v),
  first:async()=>sql.prepare(query).get(...args)||null,all:async()=>({results:sql.prepare(query).all(...args)}),
  run:async()=>bind(args).execute(),execute:()=>({meta:{changes:Number(sql.prepare(query).run(...args).changes)}})});return bind();},
  async batch(statements){sql.exec('BEGIN IMMEDIATE');try{const out=statements.map(s=>s.execute());sql.exec('COMMIT');return out;}
    catch(error){sql.exec('ROLLBACK');throw error;}}};}
async function fixture(t,{seconds=120}={}){
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const at=Math.floor(Date.now()/1000),values=new Map(),control={starts:0,searches:0,destroys:0,uploads:0,reads:0,
    coordinator:[],at,now:()=>Date.now(),alarm:null};
  const queueEnv={DB:d1(sql),SEARCH_DELIVERY:'queued-v1',SEARCH_AGENT_SECRET:'f'.repeat(64),SEARCH_CLOUD_AGENT_SECRET:'9'.repeat(64),
    SEARCH_POLICY_ID:'offline-fixture',SEARCH_RUNTIME_SHA256:runtime,SEARCH_SNAPSHOT_SHA256:snapshot,SEARCH_COST_UNITS:'100',
    SEARCH_HYBRID_POLICY:JSON.stringify({version:1,limitCents:12,openingCents:0,sceneCents:6,objectCents:8,
      cloudGraceSeconds:30,maxExecutionSeconds:seconds}),SEARCH_ENGINE:{fetch(){throw Error('real inference forbidden');}},
    SEARCH_CLOUD_EXECUTION_MODE:'native-host-one-shot-v1',DEPLOYMENT_ENVIRONMENT:'staging',
    INDEX_BUCKET_NAME:'vision-community-staging',DELETION_ARCHIVE_DB_ID:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',RATE_LIMITS_REQUIRED:'1',
    ...Object.fromEntries(['API_RATE_LIMITER','API_INGRESS_LIMITER','API_VIEW_LIMITER'].map(k=>[k,{async limit(){return {success:true};}}]))};
  await prepareDatabase(queueEnv.DB);sql.exec(readFileSync(new URL('../search-queue.sql',import.meta.url),'utf8'));
  await prepareSearchHybrid(queueEnv.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'fixture',1000)").run(account);
  sql.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES (?,1000,'contribution','synthetic')").run(account);
  sql.exec(`INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,country,camera_generation)
    VALUES(1,'abcdefghijklmnopqrstuv','2026-01','scene','scene-model','published','fixture',10,20,90,'Italy','gen4');
    INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_key)
    VALUES(1,'','${'c'.repeat(64)}',0,'four-view-v4/test.i8');`);
  const query={lane:'scene',prompt:'red door',examples:[],excluded:[],queryName:'My map',descriptionWeight:100,
    viewDirection:'bestOfFour',resultCount:20,maxPerCountry:25,filters:{mode:'all',countries:[],generations:[]},
    objectConfidence:'balanced',rejectRoadNames:false,minimumGlobalLocation:null};
  const enqueue=()=>queueSearch(queueEnv,account,key(at),query,{now:at,maxCostUnits:100});
  let transaction=Promise.resolve();
  const storage={async get(k){return structuredClone(values.get(k));},async put(k,v){values.set(k,structuredClone(v));},
    async delete(k){values.delete(k);},async sync(){if(control.failSync)throw Error('synthetic write failure');},
    async setAlarm(v){if(control.failAlarm)throw Error('synthetic alarm failure');control.alarm=v;},
    async deleteAlarm(){control.alarm=null;},
    transaction(callback){const work=transaction.then(async()=>{const before=structuredClone([...values]);
      try{return await callback(this);}catch(error){values.clear();for(const [k,v] of before)values.set(k,v);throw error;}});
      transaction=work.catch(()=>{});return work;}};
  const health=()=>({status:'native_host_available',runtimeSha256:runtime,identityOnly:!control.active,
    auditReady:!!control.active,searchReady:!!control.active,activeNativeProcessesMaximum:1});
  const container={running:false,images:{native:image},
    start(){assert.equal(values.get(QUEUED_KEY)?.phase,'running');assert.ok(control.alarm);
      this.running=true;control.active=false;control.starts++;},
    async destroy(){control.destroys++;if(control.failDestroy)throw Error('private failure credentials');
      this.running=false;control.active=false;control.releaseSearch?.();},
    async inspect(){return this.running||control.staleInspect?{image}:null;},
    async setInactivityTimeout(v){assert.equal(v,180000);},monitor(){return new Promise(()=>{});},
    getTcpPort(){return {fetch:async(url,init)=>{
      const path=new URL(url).pathname;
      if(path==='/health')return Response.json(health());
      if(path==='/operator/bundle'){assert.equal(sha(new Uint8Array(await new Response(init.body).arrayBuffer())),bundle.sha256);
        control.active=true;control.uploads++;return Response.json(health());}
      assert.equal(path,'/search');assert.equal(this.running,true);control.searches++;
      if(control.hangSearch)await new Promise(resolve=>{control.releaseSearch=resolve;control.onSearch?.();});
      if(!this.running)return Response.json({error:'native_search_failed'},{status:503});
      if(control.searchError)return Response.json({error:'native_search_failed'},{status:503});
      const {query,...head}=JSON.parse(new TextDecoder().decode(init.body));
      return Response.json(control.result??{...head,processedLocations:1,
        hits:[{locationId:1,outputSha256:'c'.repeat(64),sourceIndex:0,score:.8,viewOffset:1}],...control.resultPatch});
    }};}};
  const ctx={storage,container,waitUntil(promise){void promise.catch(()=>{});}};
  const env={VISION_HOST_SECRET:'a'.repeat(64),VISION_HOST_OPERATOR_SECRET:'b'.repeat(64),
    NATIVE_DAILY_COMPUTE_REQUESTS:'10',NATIVE_DAILY_CONTAINER_STARTS:'10',
    NATIVE_MONTHLY_COMPUTE_POLICY:JSON.stringify({limitCents:12,openingCents:0,requestCents:1,startCents:1}),
    NATIVE_IMAGE:image,NATIVE_RUNTIME_SHA256:runtime,OPERATOR_BUCKET_NAME:'vision-community-staging',
    NATIVE_QUEUED_SEARCH_MODE:'cloud-scene-v1',SEARCH_CLOUD_AGENT_SECRET:queueEnv.SEARCH_CLOUD_AGENT_SECRET,
    OPERATOR_BUNDLES:{async get(k){control.reads++;assert.equal(k,bundle.key);
      if(control.holdRead)await control.holdRead;
      return {size:sample.length,body:new ReadableStream({start(c){c.enqueue(sample);c.close();}})};}},
    QUEUED_SEARCH_COORDINATOR:{async fetch(request){const action=new URL(request.url).pathname.split('/').at(-1);
      control.coordinator.push(action);await control.beforeCoordinator?.(action);
      const response=await worker.fetch(request,queueEnv);
      control.lastReply={status:response.status,body:await response.clone().text()};
      if(control.drop===action){control.drop=null;throw Error('synthetic lost response');}
      return response;}}};
  values.set('activeBundle',bundle);values.set('searchHead',{bundleSha256:bundle.sha256,policyId:queueEnv.SEARCH_POLICY_ID,
    runtimeSha256:runtime,snapshotSha256:snapshot});
  const options={fixedStream:()=>new TransformStream(),wait:async()=>{},now:()=>control.now()};
  const reopen=()=>new NativeController(ctx,env,options),host=reopen();
  const debits=()=>sql.prepare("SELECT count(*) n FROM ledger WHERE reason='search'").get().n;
  const cost=()=>{const raw=sql.prepare('SELECT document FROM search_cloud_budget').get().document;
    return raw==='uninitialized-v1'?0:JSON.parse(raw).monthly.reservedCents;};
  const step=async(h=host)=>{const run=h.queued.runOnce.bind(h.queued);
    h.queued.runOnce=async()=>{try{return await run();}catch(error){control.failure=error.stack;throw error;}};
    const response=await h.queuedStep();return {status:response.status,body:await response.json()};};
  return {sql,control,env,queueEnv,ctx,values,host,reopen,enqueue,debits,cost,step,at};
}

test('one finite Scene search stops before delivery and settles once through actual Worker routes',async t=>{
  const f=await fixture(t);await f.enqueue();
  f.control.beforeCoordinator=async action=>{if(['complete','stopped'].includes(action)){
    assert.equal(f.ctx.container.running,false);assert.equal(f.values.get(QUEUED_KEY).phase,'stopped');}};
  const result=await f.step();assert.deepEqual(result,{status:200,body:{status:'completed'}},
    f.control.failure+' '+JSON.stringify(f.control.lastReply));
  assert.equal(f.control.starts,1);assert.equal(f.control.searches,1);assert.equal(f.cost(),6);assert.equal(f.debits(),1);
  assert.equal(f.values.has(QUEUED_KEY),false);assert.equal(f.control.alarm,null);
  assert.equal([...f.values.keys()].some(k=>k.startsWith('nativeQueuedResult:')),false);
  assert.equal(f.values.get('lastNativeQueuedReceipt').status,'completed');
  assert.deepEqual(await f.step(f.reopen()),{status:200,body:{status:'idle'}});
  assert.equal(f.control.starts,1);assert.equal(f.cost(),6);assert.equal(f.debits(),1);
});

test('mode/zero allowance refuse before coordinator, bundle reads, starts or new budget',async t=>{
  for(const mode of ['paused','zero','wrong-resource','missing-monthly']){
    const f=await fixture(t);await f.enqueue();
    if(mode==='paused')delete f.env.NATIVE_QUEUED_SEARCH_MODE;
    if(mode==='zero')f.env.NATIVE_DAILY_COMPUTE_REQUESTS='0';
    if(mode==='wrong-resource')f.env.OPERATOR_BUCKET_NAME='other';
    if(mode==='missing-monthly')delete f.env.NATIVE_MONTHLY_COMPUTE_POLICY;
    const result=await f.step();assert.equal(result.status,['zero','missing-monthly'].includes(mode)?503:200);
    assert.equal(f.control.coordinator.length,0);assert.equal(f.control.reads,0);assert.equal(f.control.starts,0);
    assert.equal(f.cost(),0);assert.equal(f.debits(),0);
  }
});

test('lost claim acknowledgement resumes the durable nonce without another reservation',async t=>{
  const f=await fixture(t);await f.enqueue();f.control.drop='claim';
  assert.equal((await f.step()).status,503);assert.equal(f.values.get(QUEUED_KEY).phase,'claiming');
  const token=f.values.get(QUEUED_KEY).nonce;assert.equal(f.cost(),6);assert.equal(f.control.starts,0);
  assert.equal((await f.step(f.reopen())).body.status,'completed');
  assert.equal(f.sql.prepare('SELECT attempts FROM search_jobs').get().attempts,1);
  assert.equal(f.cost(),6);assert.equal(f.control.searches,1);
  assert.equal(f.sql.prepare('SELECT cloud_token FROM search_hybrid_claims').get().cloud_token,token);
});

test('lost completion and shutdown acknowledgements replay from saved bytes with no new models or charge',async t=>{
  for(const drop of ['complete','stopped']){
    const f=await fixture(t);await f.enqueue();f.control.drop=drop;
    assert.equal((await f.step()).status,503);assert.equal(f.debits(),1);assert.equal(f.ctx.container.running,false);
    const saved=f.values.get(QUEUED_KEY),receipt=saved.stopSha256;
    assert.equal(saved.phase,'stopped');assert.ok(saved.resultBytes);assert.equal(JSON.stringify(saved).includes('red door'),false);
    f.env.OPERATOR_BUNDLES.get=()=>{throw Error('recovery must not read models');};
    assert.equal((await f.step(f.reopen())).body.status,'completed');assert.equal(f.debits(),1);
    assert.equal(f.control.searches,1);assert.equal(f.control.starts,1);
    assert.equal(f.values.get('lastNativeQueuedReceipt').stopSha256,receipt);
    assert.equal((await recoverSearch(f.queueEnv,account,key(f.at),f.at+1)).searchId,
      f.values.get('lastNativeQueuedReceipt').jobId);
  }
});

test('changed resource authority and rejected native replies stop without debit then release the same request locally',async t=>{
  for(const failure of ['resource','native','result']){
    const f=await fixture(t);await f.enqueue();
    if(failure==='resource')f.control.beforeCoordinator=async action=>{if(action==='authorize')f.queueEnv.INDEX_BUCKET_NAME='other';};
    if(failure==='native')f.control.searchError=true;
    if(failure==='result')f.control.result={privateQuery:'must not persist'};
    const result=await f.step();assert.equal(result.body.status,'local_fallback');
    assert.equal(f.ctx.container.running,false);assert.equal(f.debits(),0);assert.equal(f.cost(),6);
    if(failure==='resource'){assert.equal(f.control.starts,0);assert.equal(f.control.reads,0);}
    const local=await claimQueuedSearch(f.queueEnv,f.at+1,['scene'],undefined,'local');assert.ok(local.job);
    assert.equal(local.job.jobId,f.values.get('lastNativeQueuedReceipt').jobId);
    assert.equal([...f.values.values()].some(v=>JSON.stringify(v).includes('must not persist')),false);
  }
});

test('unconfirmed shutdown blocks completion and local reuse until the same saved attempt can stop',async t=>{
  for(const failure of ['destroy','inspect']){
    const f=await fixture(t);await f.enqueue();
    if(failure==='destroy')f.control.failDestroy=true;else f.control.staleInspect=true;
    assert.equal((await f.step()).status,503);assert.equal(f.values.get(QUEUED_KEY).phase,'stopping');
    assert.ok(f.control.alarm);assert.equal(f.debits(),0);
    assert.equal((await claimQueuedSearch(f.queueEnv,f.at+121,['scene'],undefined,'local')).job,null);
    f.control.failDestroy=false;f.control.staleInspect=false;
    assert.equal((await f.step(f.reopen())).body.status,'completed');
    assert.equal(f.control.searches,1);assert.equal(f.cost(),6);assert.equal(f.debits(),1);
  }
});

test('restart of uncertain running attempt stops without rerunning even when execution is paused',async t=>{
  const f=await fixture(t);await f.enqueue();f.control.drop='claim';await f.step();
  const row=f.sql.prepare('SELECT * FROM search_jobs').get(),value=f.values.get(QUEUED_KEY);
  f.values.set(QUEUED_KEY,{...value,phase:'running',job:{jobId:row.id,claimToken:row.claim_token,claimUntil:row.claim_until,
    executionDeadline:row.claim_until,expiresAt:row.expires_at,reservedCents:6,requestBodySha256:'1'.repeat(64)}});
  f.ctx.container.running=true;delete f.env.NATIVE_QUEUED_SEARCH_MODE;
  assert.equal((await f.step(f.reopen())).body.status,'paused');
  assert.equal(f.ctx.container.running,false);assert.equal(f.values.get(QUEUED_KEY).phase,'stopped');
  assert.equal(f.control.searches,0);assert.equal(f.debits(),0);
  f.env.NATIVE_QUEUED_SEARCH_MODE='cloud-scene-v1';
  assert.equal((await f.step(f.reopen())).body.status,'local_fallback');assert.equal(f.control.starts,0);
});

test('durable deadline alarm interrupts a busy hung search and preserves the original failure',async t=>{
  const f=await fixture(t);await f.enqueue();f.control.hangSearch=true;
  const started=new Promise(resolve=>{f.control.onSearch=resolve;});const work=f.step();
  await Promise.race([started,work.then(r=>assert.fail('search did not start: '+JSON.stringify(r)))]);
  assert.equal(f.host.busy,true);const deadline=f.values.get(QUEUED_KEY).job.executionDeadline;
  f.control.now=()=>deadline*1000-40000;await f.host.alarm();
  assert.equal(f.ctx.container.running,false);assert.equal(f.control.alarm,null);
  assert.equal((await work).body.status,'local_fallback');assert.equal(f.debits(),0);
  assert.ok(f.values.get('nativeQueuedFailure:queued_execution_deadline'));
  assert.equal(f.control.starts,1);assert.equal(f.control.searches,1);
});

test('late bundle fetch cannot start or publish native work after a deadline stop',async t=>{
  const f=await fixture(t);await f.enqueue();let release;
  f.control.holdRead=new Promise(resolve=>{release=resolve;});const work=f.step();
  for(let i=0;i<1000&&!f.control.reads;i++)await new Promise(resolve=>setTimeout(resolve,1));
  assert.ok(f.control.reads,'bounded bundle wait');
  f.control.now=()=>f.values.get(QUEUED_KEY).job.executionDeadline*1000-40000;
  await f.host.alarm();release();assert.equal((await work).body.status,'local_fallback');
  assert.equal(f.ctx.container.running,false);assert.equal(f.control.starts,1);assert.equal(f.control.uploads,0);
  assert.equal(f.control.searches,0);assert.equal(f.debits(),0);
});

test('damaged durable result is retained and cannot cause execution, debit or false shutdown acknowledgement',async t=>{
  const f=await fixture(t);await f.enqueue();f.control.drop='complete';await f.step();
  const bytes=f.values.get('nativeQueuedResult:0');bytes[0]^=1;f.values.set('nativeQueuedResult:0',bytes);
  const calls=f.control.coordinator.length;assert.equal((await f.step(f.reopen())).status,503);
  assert.ok(f.values.has(QUEUED_KEY));assert.equal(f.control.coordinator.length,calls);
  assert.equal(f.control.starts,1);assert.equal(f.control.searches,1);assert.equal(f.debits(),1);
});

test('saved delivery blocks legacy compute and operator status does not disclose query, token or result',async t=>{
  const f=await fixture(t);await f.enqueue();f.control.drop='complete';await f.step();
  const reopened=f.reopen();assert.equal((await (await reopened.health()).json()).error,'native_queued_delivery_pending');
  const status=await (await reopened.status()).json();assert.equal(status.queuedDeliveryPending,true);
  assert.equal(JSON.stringify(status).includes(f.values.get(QUEUED_KEY).nonce),false);
  assert.equal(JSON.stringify(status).includes('red door'),false);assert.equal(f.control.starts,1);
});

test('native membership proof field is preserved while echoed queries and invalid hit fields are refused',async t=>{
  const f=await fixture(t);await f.enqueue();f.control.drop='complete';
  f.control.resultPatch={membership:[{memberJson:'{"synthetic":true}',siblings:[]}]};
  assert.equal((await f.step()).status,503);
  const result=await f.host.queued.result(f.values.get(QUEUED_KEY));assert.deepEqual(result.membership,f.control.resultPatch.membership);
  // The gateway still validates real proof authority when that mode is enabled;
  // this fixture proves transport, never authentic contributor membership.
  for(const patch of [{query:'private query'},{hits:[{locationId:1,outputSha256:'c'.repeat(64),sourceIndex:0,
    score:.8,viewOffset:1,privatePrompt:'private query'}]},{membership:[{memberJson:'x',siblings:['bad']}]}]){
    const broken=await fixture(t);await broken.enqueue();broken.control.resultPatch=patch;
    assert.equal((await broken.step()).body.status,'local_fallback');assert.equal(broken.debits(),0);
    assert.ok(broken.values.get('nativeQueuedFailure:queued_result_invalid'));
  }
});

test('failed durable alarm setup cannot start native work or debit and a short execution window refuses work',async t=>{
  for(const scenario of ['alarm','window']){
    const f=await fixture(t,{seconds:scenario==='window'?40:120});await f.enqueue();
    if(scenario==='alarm')f.control.beforeCoordinator=async action=>{if(action==='claim')f.control.failAlarm=true;};
    const result=await f.step();assert.equal(f.control.starts,0);assert.equal(f.control.reads,0);assert.equal(f.debits(),0);
    if(scenario==='alarm'){
      // A confirmed stop permits safe local handoff even if alarm setup failed.
      assert.equal(result.status,200);assert.equal(result.body.status,'local_fallback');
      assert.equal(f.ctx.container.running,false);
    }else assert.equal(result.body.status,'local_fallback');
    assert.equal(f.cost(),6);
  }
});

test('queued whole-job estimate cannot undercut sealed rolling native costs',async t=>{
  const f=await fixture(t);await f.enqueue();const before=Date.now()-1000;
  f.values.set('nativeRollingComputeBudgetV1',{version:1,lastAt:before,limitCents:12,openingCents:1,
    requestCents:4,startCents:4,reservations:[{at:before,cents:1}]});
  assert.equal((await f.step()).body.status,'local_fallback');assert.equal(f.control.starts,0);assert.equal(f.control.reads,0);
  assert.equal(f.debits(),0);assert.equal(f.cost(),6);
  assert.ok(f.values.get('nativeQueuedFailure:queued_native_allowance_unavailable'));
});

test('corrupt running journal still stops owned compute without erasing evidence or acknowledging fallback',async t=>{
  for(const path of ['request','alarm']){
    const f=await fixture(t);await f.enqueue();f.control.drop='complete';await f.step();
    const damaged={...f.values.get(QUEUED_KEY),phase:'corrupt'};f.values.set(QUEUED_KEY,damaged);
    f.ctx.container.running=true;const calls=f.control.coordinator.length;
    const reopened=f.reopen();
    if(path==='alarm')await reopened.alarm();else assert.equal((await f.step(reopened)).status,503);
    assert.equal(f.ctx.container.running,false);assert.deepEqual(f.values.get(QUEUED_KEY),damaged);
    assert.equal(f.control.coordinator.length,calls);assert.equal(f.control.searches,1);
    assert.ok(f.values.get('nativeQueuedFailure:queued_outbox_invalid'));
  }
});

test('shutdown inspection is bounded even if the provider never answers',async t=>{
  const f=await fixture(t);let entered;
  const inspected=new Promise(resolve=>{entered=resolve;});
  f.ctx.container.inspect=()=>{entered();return new Promise(()=>{});};
  t.mock.timers.enable({apis:['setTimeout']});
  const stopping=f.host.queued.destroyConfirmed();
  const rejected=assert.rejects(stopping,error=>error.code==='queued_shutdown_unconfirmed');
  await inspected;t.mock.timers.tick(10000);await rejected;
});
