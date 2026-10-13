// Local workerd fixture only. Never deploy: fake container, synthetic data.
import {DurableObject} from 'cloudflare:workers';
import {createHash} from 'node:crypto';
import {NativeController} from '../../native-container-host/controller.js';
import {QUEUED_KEY} from '../../native-container-host/queued-search.js';
import coordinator from '../../src/worker.js';
const runtime='d'.repeat(64),sample=new TextEncoder().encode('local fixture without a model');
const digest=createHash('sha256').update(sample).digest('hex');
const bundle={version:1,sha256:digest,bytes:sample.length,key:`native-host/bundles/${digest}.zip`};
const image=`registry.cloudflare.com/272760294910ef0b246980278aeb36e2/vision-community-native-scene@sha256:${'2'.repeat(64)}`;

export class LocalQueuedFixture extends DurableObject {
  constructor(ctx,env){
    super(ctx,env);const fixture=this;
    const health=()=>({status:'native_host_available',runtimeSha256:runtime,identityOnly:!fixture.active,
      auditReady:!!fixture.active,searchReady:!!fixture.active,activeNativeProcessesMaximum:1});
    const count=async key=>ctx.storage.put(key,(await ctx.storage.get(key)||0)+1);
    this.synthetic={running:false,images:{native:image},
      start(){this.running=true;fixture.active=false;},
      async destroy(){this.running=false;fixture.active=false;await count('syntheticStops');fixture.release?.();},
      async inspect(){return this.running?{image}:null;},
      async setInactivityTimeout(){},monitor(){return new Promise(()=>{});},
      getTcpPort(){return {async fetch(url,init){
        const path=new URL(url).pathname;
        if(path==='/health')return Response.json(health());
        if(path==='/operator/bundle'){
          const received=new Uint8Array(await new Response(init.body).arrayBuffer());
          if(createHash('sha256').update(received).digest('hex')!==digest)throw Error('fixture checksum');
          fixture.active=true;return Response.json(health());
        }
        if(path!=='/search')throw Error('fixture unexpected native path');
        await count('syntheticSearches');
        if(await ctx.storage.get('hang')){
          // Advance only the fixture clock: the durable alarm must win before
          // the separate wall-clock timer, proving actual alarm delivery.
          fixture.offset=120000;await ctx.storage.setAlarm(Date.now()+25);
          await new Promise(resolve=>{fixture.release=resolve;});
        }
        if(!fixture.synthetic.running)return Response.json({error:'native_search_failed'},{status:503});
        const {query,...head}=JSON.parse(new TextDecoder().decode(init.body));
        // Valid trailing whitespace exercises multiple durable output chunks.
        return new Response(JSON.stringify({...head,processedLocations:1,
          hits:[{locationId:1,outputSha256:'c'.repeat(64),sourceIndex:0,score:.8,viewOffset:1}]})+' '.repeat(70000),
          {headers:{'content-type':'application/json'}});
      }};}};
    const hostEnv={...env,VISION_HOST_SECRET:'a'.repeat(64),VISION_HOST_OPERATOR_SECRET:'b'.repeat(64),
      NATIVE_DAILY_COMPUTE_REQUESTS:'10',NATIVE_DAILY_CONTAINER_STARTS:'10',NATIVE_IMAGE:image,NATIVE_RUNTIME_SHA256:runtime,
      NATIVE_MONTHLY_COMPUTE_POLICY:JSON.stringify({limitCents:12,openingCents:0,requestCents:1,startCents:1}),
      OPERATOR_BUCKET_NAME:'vision-community-staging',NATIVE_QUEUED_SEARCH_MODE:'cloud-scene-v1',
      OPERATOR_BUNDLES:{async get(){return {size:sample.length,body:new Response(sample).body};}},
      QUEUED_SEARCH_COORDINATOR:{async fetch(request){
        const response=await coordinator.fetch(request,env);
        if(new URL(request.url).pathname.endsWith('/complete')&&await ctx.storage.get('dropComplete')){
          await ctx.storage.delete('dropComplete');throw Error('synthetic lost completion acknowledgement');
        }
        return response;
      }}};
    this.controller=new NativeController({container:this.synthetic,storage:ctx.storage,waitUntil:p=>ctx.waitUntil(p)},hostEnv,
      {fixedStream:()=>new TransformStream(),now:()=>Date.now()+(fixture.offset||0)});
  }
  async seed(body){
    if(await this.ctx.storage.get(QUEUED_KEY))throw Error('pending delivery must be preserved');
    await this.ctx.storage.put('activeBundle',bundle);
    await this.ctx.storage.put('searchHead',{bundleSha256:digest,policyId:'offline-fixture',runtimeSha256:runtime,snapshotSha256:'e'.repeat(64)});
    await this.ctx.storage.put('dropComplete',!!body.dropComplete);await this.ctx.storage.put('hang',!!body.hang);
    return {seeded:true};
  }
  step(){return this.controller.queuedStep();}
  async status(){const saved=await this.ctx.storage.get(QUEUED_KEY);
    return {phase:saved?.phase??null,resultChunks:saved?.resultChunks??0,running:this.synthetic.running,
      stops:await this.ctx.storage.get('syntheticStops')||0,searches:await this.ctx.storage.get('syntheticSearches')||0,
      alarmCallbacks:await this.ctx.storage.get('alarmCallbacks')||0,last:await this.ctx.storage.get('lastNativeQueuedReceipt')??null,
      alarm:await this.ctx.storage.getAlarm(),deadlineFailure:!!await this.ctx.storage.get('nativeQueuedFailure:queued_execution_deadline')};}
  async alarm(){await this.controller.alarm();
    await this.ctx.storage.put('alarmCallbacks',(await this.ctx.storage.get('alarmCallbacks')||0)+1);}
}
export default {async fetch(request,env){const action=new URL(request.url).pathname,stub=env.FIXTURE.getByName('one-host');
  if(action==='/seed'&&request.method==='POST')return Response.json(await stub.seed(await request.json()));
  if(action==='/step'&&request.method==='POST')return stub.step();
  if(action==='/status'&&request.method==='GET')return Response.json(await stub.status());
  return new Response(null,{status:404});}};
