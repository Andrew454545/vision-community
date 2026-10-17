// Real high-budget counters for finite local checks, never hosted configuration.
export const localRateLimits=()=>Object.fromEntries(['API_RATE_LIMITER','API_INGRESS_LIMITER','API_VIEW_LIMITER']
  .map((name,i)=>[name,{namespace_id:String(8801+i),simple:{limit:10000,period:60}}]));
