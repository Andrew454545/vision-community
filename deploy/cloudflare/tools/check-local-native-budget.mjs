// Actual local workerd SQLite transactions, concurrent RPC and disk restart.
// The appended fixture cannot start compute or access any cloud resource.
import assert from 'node:assert/strict';
import {readFile,mkdtemp,rm} from 'node:fs/promises';
import {resolve,join,dirname,basename} from 'node:path';
import {tmpdir} from 'node:os';
import {pathToFileURL} from 'node:url';
const {Miniflare,convertV4MiniflareOptions,Log,LogLevel}=await import(pathToFileURL(resolve(process.argv[2])));
const bundle=await readFile(resolve(process.argv[3]),'utf8');
const now=Date.UTC(2026,9,9,12),day=86400000;
const root=await mkdtemp(join(tmpdir(),'vision-native-budget-'));
assert.equal(dirname(resolve(root)),resolve(tmpdir()));
assert.ok(basename(root).startsWith('vision-native-budget-'));
const extra=`
export class LocalComputeBudgetFixture extends DurableObject {
  async reserve(kind,requests,starts,now){
    const env={NATIVE_DAILY_COMPUTE_REQUESTS:requests,NATIVE_DAILY_CONTAINER_STARTS:starts};
    try {await reserveCompute(this.ctx.storage,env,kind,now);return {accepted:true};}
    catch(error){return {accepted:false,error:error.message};}
  }
  async inspect(requests,starts,now){return computeBudgetStatus(this.ctx.storage,
    {NATIVE_DAILY_COMPUTE_REQUESTS:requests,NATIVE_DAILY_CONTAINER_STARTS:starts},now);}
}
export class LocalComputeBudgetGateway extends WorkerEntrypoint {
  async fetch(request){
    const body=await request.json(),stub=this.env.BUDGET_FIXTURE.getByName('one-host');
    return Response.json(body.action==='inspect'?await stub.inspect(body.requests,body.starts,body.now)
      :await stub.reserve(body.kind,body.requests,body.starts,body.now));
  }
}
`;
function options(){return {...convertV4MiniflareOptions({
  ...(process.env.VISION_LOCAL_DEBUG==='1'?{log:new Log(LogLevel.DEBUG)}:{}),workers:[
  {name:'budget-gateway',modules:true,compatibilityDate:'2026-10-02',
    script:'export default {async fetch(request,env){try{return await env.TEST.fetch(request);}catch(error){return Response.json({error:String(error)},{status:500});}}};',
    serviceBindings:{TEST:{name:'budget-storage',entrypoint:'LocalComputeBudgetGateway'}}},
  {name:'budget-storage',modules:true,script:bundle+extra,compatibilityDate:'2026-10-02',
    compatibilityFlags:['nodejs_compat'],durableObjects:{BUDGET_FIXTURE:{className:'LocalComputeBudgetFixture',useSQLite:true}}}
]}),resourcePersistencePath:root};}
let instance;
async function call(action,changes={}){
  const response=await instance.dispatchFetch('https://local-budget.invalid/',{method:'POST',
    headers:{'content-type':'application/json'},body:JSON.stringify({action,kind:'request',requests:'4',starts:'2',now,...changes})});
  if(response.status!==200)assert.fail((await response.text()).slice(0,2048));
  return response.json();
}
try{
  instance=new Miniflare(options());
  const attempts=await Promise.allSettled(Array.from({length:20},()=>call('reserve')));
  for(const result of attempts)if(result.status==='rejected')throw result.reason;
  assert.equal(attempts.filter(result=>result.value.accepted).length,4);
  assert.ok(attempts.filter(result=>!result.value.accepted).every(result=>result.value.error==='native_compute_budget_exhausted'));
  assert.equal((await call('inspect')).requests,4);
  assert.deepEqual(await call('reserve',{kind:'start'}),{accepted:true});
  assert.deepEqual(await call('reserve',{kind:'start'}),{accepted:true});
  assert.deepEqual(await call('reserve',{kind:'start'}),{accepted:false,error:'native_compute_budget_exhausted'});
  await instance.dispose();instance=null;
  instance=new Miniflare(options());
  assert.equal((await call('inspect')).requests,4);
  assert.equal((await call('inspect')).starts,2);
  assert.deepEqual(await call('reserve',{requests:'8',starts:'4'}),{accepted:false,error:'native_compute_budget_exhausted'});
  assert.deepEqual(await call('reserve',{requests:'1'}),{accepted:false,error:'native_compute_budget_exhausted'});
  assert.equal((await call('inspect',{requests:'8'})).requestLimit,1);
  assert.deepEqual(await call('reserve',{now:now+day,requests:'8',starts:'4'}),{accepted:true});
  const next=await call('inspect',{now:now+day,requests:'8',starts:'4'});
  assert.equal(next.requestLimit,8);assert.equal(next.requests,1);assert.equal(next.starts,0);
  assert.deepEqual(await call('reserve',{now:now-day}),{accepted:false,error:'native_compute_budget_unavailable'});
  assert.deepEqual(await call('reserve',{now:now+day,requests:null}),{accepted:false,error:'native_compute_budget_unavailable'});
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_DURABLE_COMPUTE_BUDGET_PASSED',
    concurrentAttempts:20,acceptedReservations:4,persistedAcrossRuntimeRestart:true,
    loweredLimitsSealed:true,utcRolloverChecked:true,clockRollbackRefused:true,
    modelInference:false,cloudResourcesAccessed:false,productionQualified:false}));
}finally{if(instance)await instance.dispose();await rm(root,{recursive:true,force:true});}
