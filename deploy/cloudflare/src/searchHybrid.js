// Shared queued-search allocation and executor fencing; no provider/model calls.
import { SearchError } from './searchLedger.js';
import { randomHex,sha256Hex,encodeUtf8 } from './model.js';
import { monthlyRecord } from '../native-container-host/monthly-budget.js';
import { rollingRecord, rollingTotal } from '../native-container-host/rolling-budget.js';
import { HYBRID_CONTRACT } from './searchHybridSchema.js';

const HEX=/^[0-9a-f]{64}$/, ID=/^[0-9a-f]{32}$/;
const fail=(code='search_hybrid_unavailable',status=503)=>{throw new SearchError(code,status);};
const integer=(v,min,max)=>Number.isSafeInteger(v)&&v>=min&&v<=max;
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===keys;

export function hybridPolicy(env) {
  try {
    if(typeof env.SEARCH_HYBRID_POLICY!=='string'||env.SEARCH_HYBRID_POLICY.length>512)throw Error();
    const p=JSON.parse(env.SEARCH_HYBRID_POLICY);
    if(!exact(p,'cloudGraceSeconds,limitCents,maxExecutionSeconds,objectCents,openingCents,sceneCents,version')
        ||p.version!==1||!integer(p.limitCents,0,300)||!integer(p.openingCents,0,p.limitCents)
        ||!integer(p.sceneCents,1,300)||!integer(p.objectCents,1,300)
        ||!integer(p.cloudGraceSeconds,0,300)||!integer(p.maxExecutionSeconds,1,240)
        ||!HEX.test(env.SEARCH_CLOUD_AGENT_SECRET||'')||env.SEARCH_CLOUD_AGENT_SECRET===env.SEARCH_AGENT_SECRET)throw Error();
    return p;
  }catch{fail();}
}

export async function hybridMode(env) {
  const table=await env.DB.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='search_hybrid_revision'").first();
  if(!table){if(env.SEARCH_HYBRID_POLICY!==undefined)fail('search_hybrid_setup_required');return null;}
  if((await env.DB.prepare('SELECT contract FROM search_hybrid_revision WHERE slot=1').first())?.contract!==HYBRID_CONTRACT)
    fail('search_hybrid_setup_required');
  // A rolled-back module cannot bypass the installed SQL claim fence. New code
  // also refuses policy removal; paid browser recovery remains independent.
  return hybridPolicy(env);
}

function budgetDocument(saved,p,now,lane,token,claimHash=null) {
  let prior;
  if(!saved)fail('search_cloud_budget_unavailable');
  if(saved.document==='uninitialized-v1'&&saved.operation_token==='0'.repeat(64)){
    // Only the explicit operator migration creates this retained seed. A lost
    // budget row is never interpreted as a new empty allowance by a request.
  }else{try{if(typeof saved.document!=='string'||saved.document.length>65536)throw Error();prior=JSON.parse(saved.document);}catch{fail('search_cloud_budget_unavailable');}
    if(!(exact(prior,'monthly,rolling,version')&&prior.version===1
        ||exact(prior,'claims,monthly,rolling,version')&&prior.version===2)||!HEX.test(saved.operation_token))fail('search_cloud_budget_unavailable');}
  const policy={limitCents:p.limitCents,openingCents:p.openingCents,requestCents:p.sceneCents,startCents:p.objectCents};
  try {
    const monthly=monthlyRecord(prior?.monthly,policy,now*1000);
    const rolling=rollingRecord(prior?.rolling,policy,now*1000,prior?.monthly);
    const cents=lane==='scene'?Math.max(monthly.requestCents,rolling.requestCents):Math.max(monthly.startCents,rolling.startCents);
    const allowed=monthly.reservedCents+cents<=monthly.limitCents&&rollingTotal(rolling)+cents<=rolling.limitCents;
    const claims=prior?.claims||[];
    if(!Array.isArray(claims)||claims.length>300||claims.some(v=>!exact(v,'at,sha256')
        ||!integer(v.at,0,now*1000)||!HEX.test(v.sha256))||new Set(claims.map(v=>v.sha256)).size!==claims.length)
      throw Error('invalid_cloud_claim_history');
    const tightened={version:2,monthly,rolling,claims:claims.filter(v=>v.at>now*1000-31*86400000)};
    const granted=structuredClone(tightened);
    granted.monthly.reservedCents+=cents;granted.rolling.reservations.push({at:now*1000,cents});
    if(claimHash)granted.claims.push({at:now*1000,sha256:claimHash});
    return {allowed,cents,document:JSON.stringify(allowed?granted:tightened),tightened:JSON.stringify(tightened),token};
  }catch{fail('search_cloud_budget_unavailable');}
}

const wait=()=>({job:null,retryAfterSeconds:30});
export async function claimHybridSearch(env,supported,now,executor,p,requestToken) {
  if(!['cloud','local'].includes(executor))fail('invalid_search_executor',400);
  let claimHash;
  if(requestToken!==undefined){
    const issued=typeof requestToken==='string'&&HEX.test(requestToken)?Number.parseInt(requestToken.slice(0,16),16):NaN;
    if(executor!=='cloud'||!integer(issued,0,now+300)||now-issued>3600)fail('invalid_cloud_claim_request',400);
    claimHash=await sha256Hex(encodeUtf8(requestToken));
  }
  // Four bounded CAS attempts. A lost/uncertain reservation is never refunded.
  for(let attempt=0;attempt<4;attempt++){
    const saved=await env.DB.prepare('SELECT document,operation_token FROM search_cloud_budget WHERE slot=1').first();
    if(requestToken!==undefined){
      const history=JSON.parse(budgetDocument(saved,p,now,'scene',requestToken).tightened).claims;
      const previous=await env.DB.prepare(`SELECT j.id,j.account_id,j.query_json,j.query_digest,j.binding_json,j.claim_token,j.claim_until,j.expires_at,
        h.cloud_deadline,h.cloud_reserved_cents FROM search_hybrid_claims h JOIN search_jobs j ON j.id=h.job_id
        JOIN accounts a ON a.id=j.account_id WHERE h.cloud_token=? AND h.executor='cloud' AND h.stopped_at IS NULL
          AND j.state='claimed' AND j.claim_token=h.cloud_token AND a.deleted_at IS NULL AND j.expires_at>?
          AND j.binding_json=json_extract(?, '$.'||j.lane)`)
        .bind(requestToken,now,JSON.stringify(supported)).first();
      if(previous){
        if(!history.some(v=>v.sha256===claimHash))fail('search_cloud_budget_unavailable');
        return {job:previous,cloud:{executionDeadline:previous.cloud_deadline,reservedCents:previous.cloud_reserved_cents}};
      }
      if(history.some(v=>v.sha256===claimHash))return wait();
    }
    const row=await env.DB.prepare(`SELECT j.*,h.executor AS prior_executor,h.cloud_token,h.stopped_at
      FROM search_jobs j JOIN accounts a ON a.id=j.account_id LEFT JOIN search_hybrid_claims h ON h.job_id=j.id
      WHERE a.deleted_at IS NULL AND j.binding_json=json_extract(?, '$.'||j.lane)
        AND j.expires_at>? AND j.attempts<3
        AND (j.state='queued' OR (j.state='claimed' AND j.claim_until<=?))
        AND (h.cloud_token IS NULL OR h.stopped_at IS NOT NULL)
        AND (?='local' OR (j.attempts=0 AND h.job_id IS NULL))
      ORDER BY j.created_at,j.id LIMIT 1`).bind(JSON.stringify(supported),now,now,executor).first();
    if(!row)return wait();
    const token=requestToken??randomHex(32);
    let budget;
    try{budget=budgetDocument(saved,p,now,row.lane,token,claimHash);}catch(error){if(executor==='cloud')throw error;}
    if(executor==='cloud'&&!budget.allowed){
      // Persist tightening even on refusal, without minting a claim or debit.
      await persistBudget(env.DB,saved,budget.document,token);return wait();
    }
    if(executor==='local'&&!row.cloud_token&&budget?.allowed&&row.created_at+p.cloudGraceSeconds>now)return wait();
    const until=Math.min(row.expires_at,now+(executor==='cloud'?p.maxExecutionSeconds:300));
    const same=`EXISTS (SELECT 1 FROM search_jobs WHERE id=? AND state=? AND claim_token IS ? AND attempts=? AND expires_at>?)`;
    const identity=[row.id,row.state,row.claim_token,row.attempts,now];
    const statements=[];
    if(budget)statements.push(budgetStatement(env.DB,saved,executor==='cloud'?budget.document:budget.tightened,token));
    const grant=executor==='cloud'?` AND EXISTS (SELECT 1 FROM search_cloud_budget WHERE slot=1 AND operation_token=? AND document=?)`:'';
    statements.push(env.DB.prepare(`INSERT INTO search_hybrid_claims
      SELECT ?,?,?,?,${executor==='cloud'?'?,?,?,?':'NULL,NULL,NULL,NULL'},NULL,NULL WHERE ${same}${grant}
      ON CONFLICT(job_id) DO UPDATE SET claim_token=excluded.claim_token,executor=excluded.executor,claimed_at=excluded.claimed_at`)
      .bind(row.id,token,executor,now,...(executor==='cloud'?[token,until,budget.cents,now]:[]),...identity,...(executor==='cloud'?[token,budget.document]:[])));
    statements.push(env.DB.prepare(`UPDATE search_jobs SET state='claimed',claim_token=?,claim_until=?,attempts=attempts+1
      WHERE id=? AND state=? AND claim_token IS ? AND attempts=? AND expires_at>?
        AND EXISTS (SELECT 1 FROM search_hybrid_claims WHERE job_id=? AND claim_token=? AND executor=?)`)
      .bind(token,until,...identity,row.id,token,executor));
    try{await env.DB.batch(statements);}catch(error){
      if(/hybrid_claim_lost|hybrid_claim_immutable/.test(error.message))continue;throw error;}
    const claimed=await env.DB.prepare(`SELECT id,account_id,query_json,query_digest,binding_json,claim_token,claim_until,expires_at
      FROM search_jobs WHERE id=? AND state='claimed' AND claim_token=?`).bind(row.id,token).first();
    if(claimed)return {job:claimed,...(executor==='cloud'?{cloud:{executionDeadline:until,reservedCents:budget.cents}}:{})};
  }
  return wait();
}

function budgetStatement(db,saved,document,token) {
  return db.prepare('UPDATE search_cloud_budget SET document=?,operation_token=? WHERE slot=1 AND document=? AND operation_token=?')
    .bind(document,token,saved.document,saved.operation_token);
}
async function persistBudget(db,saved,document,token){await budgetStatement(db,saved,document,token).run();}

export async function hybridClaimAuthority(env,id,token,executor,now) {
  const p=await hybridMode(env);if(!p){if(executor!=='local')fail();return null;}
  const row=await env.DB.prepare('SELECT * FROM search_hybrid_claims WHERE job_id=? AND claim_token=? AND executor=?')
    .bind(id,token,executor).first();
  if(!row||(executor==='cloud'&&(row.stopped_at!==null||row.cloud_deadline<=now)))fail('search_claim_lost',409);
  return row;
}

// Read-only recovery/preflight inspection. No new policy, reservation or refund.
export function inspectCloudBudget(saved,now=Math.floor(Date.now()/1000)) {
  if(!integer(now,0,8640000000000))fail('search_cloud_budget_unavailable');
  if(saved?.document==='uninitialized-v1'&&saved.operation_token==='0'.repeat(64))return {initialized:false};
  let prior;try{if(typeof saved?.document!=='string'||saved.document.length>65536)throw Error();prior=JSON.parse(saved.document);}catch{fail('search_cloud_budget_unavailable');}
  const p={limitCents:prior?.monthly?.limitCents,openingCents:0,sceneCents:prior?.monthly?.requestCents,objectCents:prior?.monthly?.startCents};
  const checked=budgetDocument(saved,p,now,'scene','0'.repeat(64));
  const state=JSON.parse(checked.tightened);
  return {initialized:true,monthlyReservedCents:state.monthly.reservedCents,rollingReservedCents:rollingTotal(state.rolling)};
}

export async function acknowledgeCloudStop(env,body,now=Math.floor(Date.now()/1000)) {
  if(!exact(body,'claimToken,jobId,shutdownReceiptSha256')||!ID.test(body.jobId)||!HEX.test(body.claimToken)
      ||!HEX.test(body.shutdownReceiptSha256)||!integer(now,0,8640000000000))fail('invalid_cloud_stop',400);
  if(!await hybridMode(env))fail();
  const row=await env.DB.prepare('SELECT * FROM search_hybrid_claims WHERE job_id=? AND cloud_token=?')
    .bind(body.jobId,body.claimToken).first();
  if(!row)fail('search_claim_lost',409);
  if(now<row.claimed_at)fail('invalid_cloud_stop',400);
  if(row.shutdown_sha256!==null&&row.shutdown_sha256!==body.shutdownReceiptSha256)fail('cloud_stop_conflict',409);
  await env.DB.batch([
    env.DB.prepare(`UPDATE search_hybrid_claims SET stopped_at=?,shutdown_sha256=?
      WHERE job_id=? AND cloud_token=? AND stopped_at IS NULL`).bind(now,body.shutdownReceiptSha256,body.jobId,body.claimToken),
    env.DB.prepare(`UPDATE search_jobs SET state='queued',claim_token=NULL,claim_until=NULL
      WHERE id=? AND state='claimed' AND claim_token=? AND expires_at>? AND attempts<3
        AND EXISTS (SELECT 1 FROM search_hybrid_claims WHERE job_id=? AND cloud_token=? AND shutdown_sha256=?)`)
      .bind(body.jobId,body.claimToken,now,body.jobId,body.claimToken,body.shutdownReceiptSha256),
  ]);
  const saved=await env.DB.prepare('SELECT shutdown_sha256 FROM search_hybrid_claims WHERE job_id=? AND cloud_token=?')
    .bind(body.jobId,body.claimToken).first();
  if(!saved)fail('search_claim_lost',409);
  if(saved.shutdown_sha256!==body.shutdownReceiptSha256)fail('cloud_stop_conflict',409);
  return {stopped:true};
}
