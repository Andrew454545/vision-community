// Abuse protection only. Financial accounting stays in the transactional ledger.
import { sha256Hex, encodeUtf8 } from "./model.js";
export class ApiLimitError extends Error {
  constructor(code,status) {super(code);this.status=status;}
}
const names=["API_RATE_LIMITER","API_INGRESS_LIMITER","API_VIEW_LIMITER"];
function configured(env) {
  const hosted=['staging','production'].includes(env.DEPLOYMENT_ENVIRONMENT)
    || ['vision-community','vision-community-staging'].includes(env.INDEX_BUCKET_NAME);
  if(hosted && env.RATE_LIMITS_REQUIRED!=='1') throw new ApiLimitError('rate_limit_unavailable',503);
  if (env.RATE_LIMITS_REQUIRED!==undefined && !["0","1"].includes(env.RATE_LIMITS_REQUIRED))
    throw new ApiLimitError("rate_limit_unavailable",503);
  if (env.RATE_LIMITS_REQUIRED==="1" && names.some(name=>typeof env[name]?.limit!=="function"))
    throw new ApiLimitError("rate_limit_unavailable",503);
}
async function limit(env,name,key,timeoutMs=1000) {
  configured(env);
  if (env[name]===undefined && env.RATE_LIMITS_REQUIRED!=="1") return;
  if (typeof env[name]?.limit!=="function") throw new ApiLimitError("rate_limit_unavailable",503);
  let timer;
  try {
    const result=await Promise.race([
      Promise.resolve().then(()=>env[name].limit({key})),
      new Promise((_,reject)=>{timer=setTimeout(()=>reject(new ApiLimitError("rate_limit_unavailable",503)),timeoutMs);})
    ]);
    if (result?.success===false) throw new ApiLimitError("rate_limited",429);
    if (result?.success!==true) throw new ApiLimitError("rate_limit_unavailable",503);
  } catch(error) {
    if (error instanceof ApiLimitError) throw error;
    throw new ApiLimitError("rate_limit_unavailable",503);
  } finally {clearTimeout(timer);}
}
async function anonymousKey(env,request) {
  const raw=request.headers.get("CF-Connecting-IP")||"unknown";
  const ip=raw.length<=64 && /^[0-9a-fA-F:.]+$/.test(raw) ? raw : "unknown";
  // Keys rotate hourly and never contain the address, token, query or recovery code.
  // This is an abuse counter, not proof that provider metadata is anonymous.
  const scope=env.INDEX_BUCKET_NAME==="vision-community" ? "production" :
    env.INDEX_BUCKET_NAME==="vision-community-staging" ? "staging" : "local";
  return scope+":"+await sha256Hex(encodeUtf8("vision-ingress-v2:"+scope+":"+Math.floor(Date.now()/3600000)+":"+ip));
}
export async function ingressLimit(env,request) {
  await limit(env,"API_INGRESS_LIMITER","ingress:"+await anonymousKey(env,request));
}
export async function accountLimit(env,request,account) {
  const actor=account ? "account:"+account : "anonymous:"+await anonymousKey(env,request);
  await limit(env,"API_RATE_LIMITER",actor);
}
export async function viewLimit(env,account) {
  await limit(env,"API_VIEW_LIMITER","views:"+account);
}
