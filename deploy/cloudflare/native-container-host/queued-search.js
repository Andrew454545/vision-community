// One finite Scene search, durable result/stop outbox, no implicit activation.
import {createHash} from 'node:crypto';
export const QUEUED_KEY='nativeQueuedSearchV1';
const CHUNK=32768,MAX_RESULT=1024*1024,HEX=/^[0-9a-f]{64}$/,ID=/^[0-9a-f]{32}$/;
const RESOURCE=Object.freeze({accountId:'272760294910ef0b246980278aeb36e2',databaseId:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',bucket:'vision-community-staging'});
const sha=v=>createHash('sha256').update(v).digest('hex');
const text=v=>new TextEncoder().encode(v);
const integer=(v,min,max)=>Number.isSafeInteger(v)&&v>=min&&v<=max;
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===keys;
class QueueError extends Error{constructor(code){super(code);this.code=code;}}
const fail=code=>{throw new QueueError(code);};
const chunkKey=i=>'nativeQueuedResult:'+i;
function sceneOutput(result,binding,r){
  if(!exact(result,'contractVersion,hits,policyId,processedLocations,requestSha256,runtimeSha256,snapshotSha256')
      &&!exact(result,'contractVersion,hits,membership,policyId,processedLocations,requestSha256,runtimeSha256,snapshotSha256'))fail('queued_result_invalid');
  if(Object.entries(binding).some(([k,v])=>result[k]!==v)||result.requestSha256!==r.requestSha256
      ||!integer(result.processedLocations,1,200000000)||!Array.isArray(result.hits)
      ||result.hits.length>Math.min(1000,r.query.resultCount)||result.hits.some(hit=>
        !exact(hit,'locationId,outputSha256,score,sourceIndex,viewOffset')||!integer(hit.locationId,1,Number.MAX_SAFE_INTEGER)
        ||!HEX.test(hit.outputSha256)||!Number.isFinite(hit.score)||hit.score< -1||hit.score>1
        ||!integer(hit.sourceIndex,0,result.processedLocations-1)||!integer(hit.viewOffset,0,3)))fail('queued_result_invalid');
  if(result.membership!==undefined&&(!Array.isArray(result.membership)||result.membership.length!==result.hits.length
      ||result.membership.some(proof=>!exact(proof,'memberJson,siblings')||typeof proof.memberJson!=='string'
        ||text(proof.memberJson).length>8192||!Array.isArray(proof.siblings)||proof.siblings.length>17
        ||proof.siblings.some(v=>!HEX.test(v)))))fail('queued_result_invalid');
}

function job(value){
  if(!exact(value,'claimToken,claimUntil,executionDeadline,expiresAt,jobId,requestJson,reservedCents')
      ||!ID.test(value.jobId)||!HEX.test(value.claimToken)||!integer(value.executionDeadline,1,8640000000000)
      ||value.claimUntil!==value.executionDeadline||!integer(value.expiresAt,value.claimUntil,8640000000000)
      ||!integer(value.reservedCents,1,300)||typeof value.requestJson!=='string'||text(value.requestJson).length>81920)
    fail('queued_job_invalid');
  return value;
}
function request(value){
  const r=JSON.parse(value.requestJson);
  if(!exact(r,'contractVersion,policyId,query,requestSha256,runtimeSha256,snapshotSha256')||r.contractVersion!==2
      ||typeof r.policyId!=='string'||!HEX.test(r.requestSha256)||!HEX.test(r.runtimeSha256)||!HEX.test(r.snapshotSha256)
      ||r.query?.lane!=='scene')fail('queued_job_invalid');
  return r;
}
function metadata(value){const {requestJson,...meta}=value;return {...meta,requestBodySha256:sha(text(requestJson))};}
function validateSaved(v){
  const allowed=['version','phase','nonce','createdAt','resource','job','resultBytes','resultChunks','resultSha256','stopReceipt','stopSha256','completion'];
  if(!v||typeof v!=='object'||Array.isArray(v)||Object.keys(v).some(k=>!allowed.includes(k))||v.version!==1
      ||!['claiming','prepared','running','result','stopping','stopped'].includes(v.phase)||!HEX.test(v.nonce)
      ||!integer(v.createdAt,0,8640000000000000)||JSON.stringify(v.resource)!==JSON.stringify(RESOURCE))fail('queued_outbox_invalid');
  if(v.phase!=='claiming'){
    if(!exact(v.job,'claimToken,claimUntil,executionDeadline,expiresAt,jobId,requestBodySha256,reservedCents')
        ||v.job.claimToken!==v.nonce||!ID.test(v.job.jobId)||!HEX.test(v.job.requestBodySha256)
        ||!integer(v.job.executionDeadline,1,8640000000000)||v.job.claimUntil!==v.job.executionDeadline
        ||!integer(v.job.expiresAt,v.job.claimUntil,8640000000000)||!integer(v.job.reservedCents,1,300))fail('queued_outbox_invalid');
  }
  if(['resultBytes','resultChunks','resultSha256'].some(k=>v[k]!==undefined)
      &&(!integer(v.resultBytes,1,MAX_RESULT)||v.resultChunks!==Math.ceil(v.resultBytes/CHUNK)||!HEX.test(v.resultSha256)))fail('queued_outbox_invalid');
  if(v.phase==='stopped'&&(!v.stopReceipt||sha(text(JSON.stringify(v.stopReceipt)))!==v.stopSha256
      ||!exact(v.stopReceipt,'claimTokenSha256,jobId,observedAt,scope,stopped,version')||v.stopReceipt.version!==1
      ||v.stopReceipt.scope!=='queued-native-container-stop-v1'||!integer(v.stopReceipt.observedAt,v.createdAt,8640000000000000)
      ||v.stopReceipt.jobId!==v.job.jobId||v.stopReceipt.claimTokenSha256!==sha(v.job.claimToken)
      ||v.stopReceipt.stopped!==true))fail('queued_outbox_invalid');
  if(v.completion!==undefined&&!['completed','claim_lost'].includes(v.completion))fail('queued_outbox_invalid');
  return v;
}

export class QueuedNativeSearch {
  constructor(host){this.host=host;this.storage=host.ctx.storage;this.cancelled=false;}
  now(){return this.host.now();}
  configured(){const e=this.host.env;return e.NATIVE_QUEUED_SEARCH_MODE==='cloud-scene-v1'
    &&e.OPERATOR_BUCKET_NAME===RESOURCE.bucket&&HEX.test(e.SEARCH_CLOUD_AGENT_SECRET||'')&&typeof e.QUEUED_SEARCH_COORDINATOR?.fetch==='function';}
  async saved(){const v=await this.storage.get(QUEUED_KEY);return v===undefined?null:validateSaved(v);}
  async report(code){
    // Preserve the first fixed classification per failure, without raw errors.
    const name='nativeQueuedFailure:'+code;
    if(!await this.storage.get(name))await this.storage.put(name,{code,at:this.now()});
  }
  async coordinator(action,body,maximum=196608){
    if(!this.configured())fail('queued_mode_paused');
    const abort=new AbortController();let timer;
    const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{abort.abort();reject(new QueueError('queued_delivery_unavailable'));},10000);});
    void deadline.catch(()=>{});
    try{
      const transfer=Promise.resolve().then(()=>this.host.env.QUEUED_SEARCH_COORDINATOR.fetch(new Request(
        'https://queued-coordinator.internal/api/search-cloud-agent/'+action,{method:'POST',redirect:'manual',signal:abort.signal,
          headers:{'content-type':'application/json',authorization:'Bearer '+this.host.env.SEARCH_CLOUD_AGENT_SECRET},body:JSON.stringify(body)})))
        .then(response=>{if(abort.signal.aborted){if(response.body)void response.body.cancel().catch(()=>{});fail('queued_delivery_unavailable');}return response;});
      const response=await Promise.race([transfer,deadline]);
      if(![200,409].includes(response.status)||response.headers.get('content-type')?.split(';')[0]!=='application/json'||!response.body){
        if(response.body)void response.body.cancel().catch(()=>{});fail('queued_delivery_unavailable');}
      const reader=response.body.getReader(),chunks=[];let size=0;
      try{for(let i=0;i<65536;i++){
        const next=await Promise.race([reader.read(),deadline]);if(next.done){
          const bytes=new Uint8Array(size);let at=0;for(const c of chunks){bytes.set(c,at);at+=c.length;}
          const document=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
          if(response.status===409){if(exact(document,'error')&&document.error==='search_claim_lost')return {lost:true};fail('queued_delivery_unavailable');}
          return document;}
        if(!(next.value instanceof Uint8Array)||size+next.value.length>maximum)fail('queued_delivery_unavailable');
        size+=next.value.length;chunks.push(next.value);
      }fail('queued_delivery_unavailable');}finally{void reader.cancel().catch(()=>{});reader.releaseLock();}
    }catch(error){if(error instanceof QueueError)throw error;fail('queued_delivery_unavailable');}
    finally{abort.abort();clearTimeout(timer);}
  }
  async save(value){validateSaved(value);await this.storage.put(QUEUED_KEY,value);await this.storage.sync();}
  guard(deadline){if(this.cancelled||this.now()>=deadline)fail('queued_execution_deadline');}
  async destroyConfirmed(){
    let timer;
    try{
      const observe=(async()=>{
        await this.host.ctx.container.destroy();
        if(this.host.ctx.container.running||await this.host.ctx.container.inspect()!==null)fail('queued_shutdown_unconfirmed');
        this.host.hydratedDigest=undefined;
      })();
      await Promise.race([observe,new Promise((_,reject)=>{
        timer=setTimeout(()=>reject(new QueueError('queued_shutdown_unconfirmed')),10000);
      })]);
    }finally{clearTimeout(timer);}
  }
  async stopCorrupt(){
    // Unreadable metadata cannot authorize work or disable owned shutdown.
    // Preserve the damaged journal; never manufacture a stop acknowledgement.
    this.cancelled=true;
    try{await this.destroyConfirmed();await this.storage.deleteAlarm();}
    catch(error){await this.storage.setAlarm(this.now()+30000);throw error;}
    await this.report('queued_outbox_invalid');
  }
  async stop(){
    this.cancelled=true;
    let value=await this.saved();if(!value||value.phase==='claiming')return value;
    if(value.phase==='stopped')return value;
    await this.save({...value,phase:'stopping'});
    try{
      await this.destroyConfirmed();
      const stopReceipt={version:1,scope:'queued-native-container-stop-v1',jobId:value.job.jobId,claimTokenSha256:sha(value.job.claimToken),
        stopped:true,observedAt:this.now()};
      await this.storage.transaction(async s=>{
        const current=validateSaved(await s.get(QUEUED_KEY));
        if(current.nonce!==value.nonce)fail('queued_outbox_invalid');
        if(current.phase!=='stopped')await s.put(QUEUED_KEY,{...current,phase:'stopped',stopReceipt,stopSha256:sha(text(JSON.stringify(stopReceipt)))});
      });
      await this.storage.sync();await this.storage.deleteAlarm();return this.saved();
    }catch(error){await this.storage.setAlarm(this.now()+30000);throw error;}
  }
  async alarm(){
    let value;try{value=await this.saved();}catch{await this.stopCorrupt();return true;}
    if(!value)return false;
    if(value.phase==='claiming'){
      // No model was started by this attempt; stop any previously idle owned
      // instance rather than erasing its only shutdown alarm during recovery.
      if(this.host.ctx.container.running)await this.host.ctx.container.destroy();
      this.host.hydratedDigest=undefined;await this.storage.deleteAlarm();return true;
    }
    if(value.phase==='stopped'){await this.storage.deleteAlarm();return true;}
    const deadline=value.job.executionDeadline*1000-40000;
    if(this.now()<deadline){await this.storage.setAlarm(deadline);return true;}
    await this.report('queued_execution_deadline');await this.stop();return true;
  }
  async clear(status){
    const value=await this.saved();
    await this.storage.transaction(async s=>{
      for(let i=0;i<(value?.resultChunks||0);i++)await s.delete(chunkKey(i));
      await s.put('lastNativeQueuedReceipt',{status,at:this.now(),jobId:value?.job?.jobId??null,
        stopSha256:value?.stopSha256??null,resultSha256:value?.resultSha256??null});
      await s.delete(QUEUED_KEY);
    });await this.storage.sync();return {status};
  }
  async result(value){
    const raw=new Uint8Array(value.resultBytes);let offset=0;
    for(let i=0;i<value.resultChunks;i++){
      const bytes=await this.storage.get(chunkKey(i));
      if(!(bytes instanceof Uint8Array)||bytes.length!==Math.min(CHUNK,value.resultBytes-offset))fail('queued_outbox_invalid');
      raw.set(bytes,offset);offset+=bytes.length;
    }
    if(sha(raw)!==value.resultSha256)fail('queued_outbox_invalid');
    return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
  }
  async deliver(){
    let value=await this.saved();if(value.phase!=='stopped')fail('queued_shutdown_unconfirmed');
    if(!this.configured())return {status:'paused'};
    const identity={jobId:value.job.jobId,claimToken:value.job.claimToken};
    if(value.resultBytes!==undefined&&!value.completion){
      const reply=await this.coordinator('complete',{...identity,result:await this.result(value)},4096);
      if(!reply.lost&&(!exact(reply,'completed,searchId')||reply.completed!==true||reply.searchId!==value.job.jobId))fail('queued_delivery_unavailable');
      await this.save({...value,completion:reply.lost?'claim_lost':'completed'});value=await this.saved();
    }
    const reply=await this.coordinator('stopped',{...identity,shutdownReceiptSha256:value.stopSha256},4096);
    if(!reply.lost&&(!exact(reply,'stopped')||reply.stopped!==true))fail('queued_delivery_unavailable');
    return this.clear(value.completion==='completed'?'completed':'local_fallback');
  }
  async runOnce(){
    let value;try{value=await this.saved();}catch(error){await this.stopCorrupt();throw error;}
    if(value&&value.phase!=='claiming'){
      if(value.phase!=='stopped')await this.stop();
      return this.deliver(); // Never rerun a saved/uncertain native operation.
    }
    if(!this.configured())return {status:'paused'};
    if(value&&this.now()-value.createdAt>=3600000)return this.clear('claim_expired_before_execution');
    this.host.config();
    const active=await this.host.active(),head=await this.storage.get('searchHead');
    if(!active||head?.bundleSha256!==active.sha256||head.runtimeSha256!==this.host.env.NATIVE_RUNTIME_SHA256)fail('queued_runtime_unavailable');
    const budget=await this.host.budgetStatus();
    const minimumEstimate=budget.monthly&&budget.rolling
      ?Math.max(budget.monthly.requestCents,budget.rolling.requestCents)+Math.max(budget.monthly.startCents,budget.rolling.startCents):Infinity;
    if(!budget.configured||!budget.monthly||!budget.rolling||budget.requestsRemaining<1||budget.startsRemaining<1
        ||budget.monthly.remainingCents<minimumEstimate||budget.rolling.remainingCents<minimumEstimate)fail('queued_native_allowance_unavailable');
    if(!value){
      const nonce=Math.floor(this.now()/1000).toString(16).padStart(16,'0')+crypto.randomUUID().replaceAll('-','')+crypto.randomUUID().replaceAll('-','').slice(0,16);
      value={version:1,phase:'claiming',nonce,createdAt:this.now(),resource:RESOURCE};await this.save(value);
      await this.storage.setAlarm(this.now()+60000);await this.storage.sync();
    }
    const binding={contractVersion:2,policyId:head.policyId,runtimeSha256:head.runtimeSha256,snapshotSha256:head.snapshotSha256};
    const claimed=await this.coordinator('claim',{lanes:['scene'],bindings:{scene:binding},requestToken:value.nonce});
    if(claimed.lost)fail('queued_delivery_unavailable');
    if(claimed.job===null){if(!exact(claimed,'job,retryAfterSeconds')||claimed.retryAfterSeconds!==30)fail('queued_job_invalid');return this.clear('idle');}
    const assigned=job(claimed.job),r=request(assigned);
    if(assigned.claimToken!==value.nonce||Object.entries(binding).some(([k,v])=>r[k]!==v))fail('queued_job_invalid');
    value={...value,phase:'prepared',job:metadata(assigned)};await this.save(value);
    const cutoff=assigned.executionDeadline*1000-40000;this.cancelled=false;let timer;
    try{
      await this.storage.setAlarm(cutoff);await this.storage.sync();
      if(assigned.reservedCents<minimumEstimate)fail('queued_native_allowance_unavailable');
      const authorization=await this.coordinator('authorize',{jobId:assigned.jobId,claimToken:assigned.claimToken});
      if(authorization.lost||authorization.authorized!==true||JSON.stringify(authorization.resource)!==JSON.stringify(RESOURCE)
          ||Object.keys(assigned).some(k=>job(authorization.job)[k]!==assigned[k]))fail('queued_claim_authority_lost');
      this.guard(cutoff);await this.save({...value,phase:'running'});
      const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{this.cancelled=true;reject(new QueueError('queued_execution_deadline'));},Math.max(1,cutoff-this.now()));});
      void deadline.catch(()=>{});
      const operation=(async()=>{
        await this.host.reserveRequest();this.guard(cutoff);
        const health=await this.host.ensure(active,()=>this.guard(cutoff));this.guard(cutoff);
        if(!health.searchReady)fail('queued_runtime_unavailable');
        const response=await this.host.call('/search',{body:text(assigned.requestJson),maximum:MAX_RESULT,timeout:Math.max(1,Math.min(115000,cutoff-this.now()))});
        this.guard(cutoff);const result=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(response.bytes));
        sceneOutput(result,binding,r);
        await this.storage.transaction(async s=>{
          this.guard(cutoff);const current=validateSaved(await s.get(QUEUED_KEY));
          if(current.nonce!==value.nonce||current.phase!=='running')fail('queued_execution_deadline');
          for(let i=0;i<Math.ceil(response.bytes.length/CHUNK);i++)await s.put(chunkKey(i),response.bytes.slice(i*CHUNK,(i+1)*CHUNK));
          await s.put(QUEUED_KEY,{...current,phase:'result',resultBytes:response.bytes.length,resultChunks:Math.ceil(response.bytes.length/CHUNK),resultSha256:sha(response.bytes)});
        });await this.storage.sync();
      })();void operation.catch(()=>{});await Promise.race([operation,deadline]);
    }catch(error){await this.report(error instanceof QueueError?error.code:'queued_native_execution_failed');}
    finally{this.cancelled=true;clearTimeout(timer);await this.stop();}
    return this.deliver();
  }
}
