// Opt-in operator entrypoint for one private, finite Scene trial. No checked-in
// deployment selects it. It never schedules work or binds a native executor.
import worker from '../src/worker.js';
import { sha256Hex, encodeUtf8, equalHex } from '../src/model.js';

const ACCOUNT='272760294910ef0b246980278aeb36e2';
const DB='17043cb7-5dab-4a6f-84ca-19ae1c14cc05';
export const FINITE_HEADERS=Object.freeze({read:'x-vision-trial-rows-read',written:'x-vision-trial-rows-written',
  puts:'x-vision-trial-r2-puts',bytes:'x-vision-trial-r2-bytes'});
export const FINITE_LIMITS=Object.freeze({read:2000,written:128,puts:4,bytes:524288});
const allowed=new Set(['GET /api/capabilities','GET /api/me','GET /api/scene-qualifications',
  'POST /api/recovery','POST /api/leases','POST /api/leases/renew','POST /api/leases/release',
  'POST /api/submissions','POST /api/scene-audits']);
const integer=value=>Number.isSafeInteger(value)&&value>=0;
class TrialLimit extends Error {}

export function meterSceneBindings(env,limits=FINITE_LIMITS) {
  const usage={read:0,written:0,puts:0,bytes:0,complete:true}, original=new WeakMap();
  const check=()=>{
    if(!usage.complete)throw new TrialLimit('finite_scene_usage_unknown');
    if(Object.entries(limits).some(([key,value])=>usage[key]>value))throw new TrialLimit('finite_scene_usage_limit');
  };
  function record(result) {
    if(!integer(result?.meta?.rows_read)||!integer(result?.meta?.rows_written)){
      usage.complete=false;throw new TrialLimit('finite_scene_usage_unknown');
    }
    usage.read+=result.meta.rows_read;usage.written+=result.meta.rows_written;
    if(!integer(usage.read)||!integer(usage.written))throw new TrialLimit('finite_scene_usage_unknown');
    return result;
  }
  function statement(inner) {
    const wrapped={
      bind(...values){return statement(inner.bind(...values));},
      async all(){check();try{return record(await inner.all());}catch(error){usage.complete=false;throw error;}},
      async run(){check();try{return record(await inner.run());}catch(error){usage.complete=false;throw error;}},
      async first(column){const result=await wrapped.all(),row=result.results?.[0];
        if(!row)return null;
        if(column===undefined)return row;
        if(!Object.hasOwn(row,column))throw new TrialLimit('finite_scene_column_missing');
        return row[column];},
    };
    original.set(wrapped,inner);return wrapped;
  }
  const db={prepare(sql){return statement(env.DB.prepare(sql));},
    async batch(statements){check();const items=statements.map(item=>{
      const raw=original.get(item);if(!raw)throw new TrialLimit('finite_scene_statement_scope');return raw;
    });try{return (await env.DB.batch(items)).map(record);}catch(error){usage.complete=false;throw error;}},
  };
  // Keep D1 batch atomic. Usage is observed after execution, then further work
  // is refused; this cannot reverse metered work or an already committed award.
  const index=new Proxy(env.INDEX,{get(target,name){
    if(name==='put')return async(key,value,options)=>{
      check();let size;
      if(typeof value==='string')size=encodeUtf8(value).byteLength;
      else if(value instanceof ArrayBuffer||ArrayBuffer.isView(value))size=value.byteLength;
      else throw new TrialLimit('finite_scene_upload_unbounded');
      if(usage.puts>=limits.puts||usage.bytes+size>limits.bytes)throw new TrialLimit('finite_scene_upload_limit');
      usage.puts++;usage.bytes+=size;
      return target.put(key,value,options);
    };
    const value=Reflect.get(target,name,target);return typeof value==='function'?value.bind(target):value;
  }});
  return {usage,env:{...env,DB:db,INDEX:index,SCENE_VERIFIER:undefined,SEARCH_ENGINE:undefined}};
}

export function createFiniteSceneGateway(base=worker) {
  return {async fetch(request,env,ctx){
    const reject=(code,status)=>{
      if(request.body)void request.body.cancel().catch(()=>{});
      return Response.json({error:code},{status,headers:{'cache-control':'no-store'}});
    };
    const until=Number(env.FINITE_SCENE_UNTIL),now=Date.now();
    let accounts;try{accounts=JSON.parse(env.SCENE_COHORT_ACCOUNTS);}catch{accounts=null;}
    if(env.DEPLOYMENT_ENVIRONMENT!=='staging'||env.INDEX_BUCKET_NAME!=='vision-community-staging'
      ||env.DELETION_ARCHIVE_DB_ID!==DB||env.FINITE_SCENE_ACCOUNT!==ACCOUNT
      ||env.SCENE_ADMISSION_MODE!=='qualified-device-v1'||env.SCENE_AUDIT_MAX_LOCATIONS!=='2'
      ||!Array.isArray(accounts)||accounts.length!==1||!/^[0-9a-f]{64}$/.test(accounts[0])
      ||env.SCENE_COHORT_UNTIL!==env.FINITE_SCENE_UNTIL
      ||!/^[0-9a-f]{64}$/.test(env.FINITE_SCENE_TOKEN_SHA256||'')
      ||!Number.isSafeInteger(until)||until<=now||until>now+20*60000||!env.DB||!env.INDEX)
      return reject('scene_verification_unavailable',503);
    const token=request.headers.get('x-vision-finite-cohort')||'';
    if(!/^[0-9a-f]{64}$/.test(token)||!equalHex(await sha256Hex(encodeUtf8(token)),env.FINITE_SCENE_TOKEN_SHA256))
      return reject('unauthorized',403);
    const url=new URL(request.url);
    if(!allowed.has(request.method+' '+url.pathname))return reject('not_found',404);
    const remaining={};
    for(const [key,maximum]of Object.entries(FINITE_LIMITS)){
      const raw=request.headers.get('x-vision-trial-remaining-'+key)||'';
      if(!/^(?:0|[1-9][0-9]{0,6})$/.test(raw)||Number(raw)>maximum)return reject('finite_scene_budget_required',400);
      remaining[key]=Number(raw);
    }
    const metered=meterSceneBindings(env,remaining);
    let result;
    try{result=await base.fetch(request,metered.env,ctx);}
    catch {result=Response.json({error:'finite_scene_trial_incomplete'},{status:503});}
    const headers=new Headers(result.headers);headers.set('cache-control','no-store');
    headers.set('x-vision-trial-usage-complete',metered.usage.complete?'1':'0');
    for(const [key,name]of Object.entries(FINITE_HEADERS))headers.set(name,String(metered.usage[key]));
    return new Response(result.body,{status:result.status,statusText:result.statusText,headers});
  }};
}
export default createFiniteSceneGateway();
