// Optional owner-outbound coordinator. No model execution, schema installation,
// new admission authority or hosted fallback. Absent from all deployed configs.
import {ObjectDispatchError,objectAuditDispatchResult,
  requireObjectAuditDispatch,readObjectAuditCandidate,readObjectAuditPayload} from './objectAuditDispatch.js';
import {objectSettlementPolicy,savedObjectAcceptance,settleObjectAudit,OBJECT_SETTLEMENT_CONTRACT} from './objectSettlement.js';
import {objectAuditResult,objectSettlementEvidence,MAX_REQUEST} from '../native-object-verifier-bridge/worker.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {randomHex,encodeUtf8} from './model.js';

export const OWNER_OBJECT_MODE='owner-outbound-v1',OWNER_OBJECT_RESULT_BYTES=98304;
const ID=/^[0-9a-f]{32}$/,HEX=/^[0-9a-f]{64}$/;
const CLAIM_SECONDS=1200,MAX_BACKOFF=900,MAX_FAILURES=8;
const fail=(code='owner_object_unavailable',status=503)=>{throw new ObjectDispatchError(code,status);};
const exact=(v,keys)=>v && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join(',')===keys.sort().join(',');
const canonical=v=>Array.isArray(v)?v.map(canonical):v && typeof v==='object'
  ?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;

export function ownerObjectDelivery(env) {
  if(env.OBJECT_AUDIT_DELIVERY===undefined)return false;
  if(env.OBJECT_AUDIT_DELIVERY!==OWNER_OBJECT_MODE || env.OBJECT_VERIFIER!==undefined
    || typeof env.OBJECT_AUDIT_AGENT_SECRET!=='string' || !HEX.test(env.OBJECT_AUDIT_AGENT_SECRET))fail();
  return true;
}
function enabled(env){if(!ownerObjectDelivery(env))fail();}
function at(now){if(!Number.isSafeInteger(now)||now<0||now>Number.MAX_SAFE_INTEGER-86400)fail('invalid_owner_object_request',400);}
function identity(lease,token){if(typeof lease!=='string'||!ID.test(lease)||typeof token!=='string'||!ID.test(token))fail('invalid_owner_object_request',400);}
export function ownerObjectBinding(env) {
  enabled(env);const p=objectSettlementPolicy(env);
  if(env.DEPLOYMENT_ENVIRONMENT!== (p.resource.bucket==='vision-community'?'production':'staging'))fail('owner_object_binding_required');
  return canonical(p);
}
export async function requireOwnerObjectAgent(env,request) {
  enabled(env);
  const auth=request.headers.get('authorization')||'';
  if(!/^Bearer [0-9a-f]{64}$/.test(auth))fail('unauthorized',401);
  const key=await crypto.subtle.importKey('raw',encodeUtf8(env.OBJECT_AUDIT_AGENT_SECRET),{name:'HMAC',hash:'SHA-256'},false,['sign','verify']);
  const mac=await crypto.subtle.sign('HMAC',key,encodeUtf8(`Bearer ${env.OBJECT_AUDIT_AGENT_SECRET}`));
  if(!await crypto.subtle.verify('HMAC',key,mac,encodeUtf8(auth)))fail('unauthorized',401);
}
async function ready(env) {
  await requireObjectAuditDispatch(env);
  let revision;try{revision=await env.DB.prepare('SELECT contract FROM object_settlement_revision WHERE slot=1').first();}catch{fail('object_settlement_setup_required');}
  if(revision?.contract!==OBJECT_SETTLEMENT_CONTRACT)fail('object_settlement_setup_required');
}
const candidate=(env,lease)=>env.DB.prepare('SELECT * FROM object_audit_candidates WHERE lease_id=?').bind(lease).first();
async function ownedClaim(env,lease,token,now) {
  identity(lease,token);const row=await candidate(env,lease);
  if(!row||row.state!=='pending'||row.claim_token!==token||row.claim_until<=now)fail('owner_object_claim_lost',409);
  const owner=await env.DB.prepare(`SELECT 1 FROM accounts a JOIN leases l ON l.account_id=a.id
    JOIN object_audit_candidates c ON c.lease_id=l.id AND c.account_id=a.id WHERE a.id=?
    AND a.deleted_at IS NULL AND l.id=? AND l.lane='object' AND l.state='submitted' AND l.expires_at>max(?,unixepoch())
    AND c.state='pending' AND c.claim_token=? AND c.claim_until>max(?,unixepoch())`).bind(row.account_id,lease,now,token,now).first();
  if(!owner)fail('owner_object_claim_lost',409);
  return row;
}

export async function claimOwnerObjectAudit(env,body,now=Math.floor(Date.now()/1000)) {
  at(now);const p=ownerObjectBinding(env);
  if(!exact(body,['binding'])||JSON.stringify(canonical(body.binding))!==JSON.stringify(p))fail('owner_object_binding_required',409);
  await ready(env);const token=randomHex(16),profiles=p.profiles.map(()=>'?').join(',');
  await env.DB.prepare(`UPDATE object_audit_candidates SET claim_token=?,claim_until=min(?,
    (SELECT expires_at FROM leases WHERE id=object_audit_candidates.lease_id)) WHERE lease_id=(
      SELECT c.lease_id FROM object_dispatch_slots s JOIN object_audit_candidates c ON c.lease_id=s.lease_id
      JOIN accounts a ON a.id=c.account_id JOIN leases l ON l.id=c.lease_id AND l.account_id=c.account_id
      WHERE c.state='pending' AND a.deleted_at IS NULL AND l.lane='object' AND l.state='submitted' AND l.expires_at>?
        AND c.policy_id=? AND c.profile_id IN (${profiles}) AND c.transport_failures<?
        AND (c.native_state IS NULL OR c.native_state IN ('staging','queued','running','approved'))
        AND (c.claim_until<=? OR c.claim_until>?) AND (c.next_attempt<=? OR c.next_attempt>?)
        AND NOT EXISTS (SELECT 1 FROM ledger WHERE reference='lease:'||c.lease_id)
        AND (SELECT COUNT(*) FROM lease_items i JOIN locations x ON x.id=i.location_id
          JOIN object_coverage v ON v.location_id=x.id WHERE i.lease_id=c.lease_id AND x.lane='object'
          AND x.state='pending' AND x.queue_state='quarantined' AND x.active_lease=c.lease_id AND x.camera_generation='gen4'
          AND v.validator=? AND v.validated_at<=? AND v.validated_at>?
          AND length(v.evidence_sha256)=64 AND v.evidence_sha256 NOT GLOB '*[^0-9a-f]*')=c.location_count
      ORDER BY c.created_at,c.lease_id LIMIT 1)`).bind(token,now+CLAIM_SECONDS,now+30,p.policyId,...p.profiles,
        MAX_FAILURES,now,now+CLAIM_SECONDS,now,now+MAX_BACKOFF,COVERAGE_VALIDATOR,now,now-86400).run();
  const row=await env.DB.prepare('SELECT * FROM object_audit_candidates WHERE claim_token=?').bind(token).first();
  if(!row)return {job:null,retryAfterSeconds:30};
  return {job:{version:1,leaseId:row.lease_id,claimToken:token,claimUntil:row.claim_until,binding:p,
    profileId:row.profile_id,assignmentSha256:row.assignment_sha256,sourceSha256:row.source_sha256,
    submissionSha256:row.submission_sha256,payloadBytes:row.payload_bytes,locations:row.location_count,
    jobId:row.job_id,candidateManifestSha256:row.candidate_manifest_sha256,nativeAttempts:row.native_attempts}};
}

export async function ownerObjectCandidate(env,body,now=Math.floor(Date.now()/1000),timeoutMs=20000) {
  at(now);const p=ownerObjectBinding(env);await ready(env);
  if(!exact(body,['leaseId','claimToken'])||!Number.isSafeInteger(timeoutMs)||timeoutMs<1||timeoutMs>20000)fail('invalid_owner_object_request',400);
  const row=await ownedClaim(env,body.leaseId,body.claimToken,now);
  if(row.policy_id!==p.policyId||!p.profiles.includes(row.profile_id))fail('owner_object_binding_changed',409);
  const started=performance.now();
  let timer;const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('owner_candidate_timeout')),timeoutMs);});
  void deadline.catch(()=>{});
  try {
    const objectIndex=await readObjectAuditPayload(env,row,deadline);
    await Promise.race([ownedClaim(env,body.leaseId,body.claimToken,now+Math.ceil((performance.now()-started)/1000)),deadline]);
    const raw=JSON.stringify({version:1,leaseId:row.lease_id,profileId:row.profile_id,policyId:row.policy_id,
      assignmentSha256:row.assignment_sha256,submissionSha256:row.submission_sha256,objectIndex});
    if(encodeUtf8(raw).length>MAX_REQUEST)fail('owner_object_candidate_invalid');
    return raw;
  }catch(error){if(error instanceof ObjectDispatchError)throw error;fail('owner_object_candidate_unavailable');}
  finally{clearTimeout(timer);}
}

function expected(row) {
  return {leaseId:row.lease_id,profileId:row.profile_id,policyId:row.policy_id,
    assignmentSha256:row.assignment_sha256,submissionSha256:row.submission_sha256,
    ...(row.job_id?{jobId:row.job_id,candidateManifestSha256:row.candidate_manifest_sha256}:{})};
}
function approvedEvidence(value,audit,p,now) {
  // A caller can refresh CURRENT protected evidence on the same native job.
  // It must first try the old completion to recover any committed acceptance.
  if(Number.isSafeInteger(value?.expiresAt)&&value.expiresAt<=now)fail('owner_object_evidence_refresh_required',409);
  let full;try{full=objectSettlementEvidence(value,audit,now);}catch{fail('invalid_owner_object_result',400);}
  if(['policySha256','runtimeProfileSha256','qualityImplementationIdentity','protectedAuthoritySha256','protectedOriginHandoffSha256']
    .some(k=>full[k]!==p[k])||JSON.stringify(canonical(full.resource))!==JSON.stringify(p.resource))fail('object_settlement_policy_mismatch',409);
  return full;
}
export async function completeOwnerObjectAudit(env,body,now=Math.floor(Date.now()/1000)) {
  enabled(env);at(now);await ready(env);
  if(!exact(body,['leaseId','claimToken','audit','evidence']))fail('invalid_owner_object_request',400);
  identity(body.leaseId,body.claimToken);
  const row=await candidate(env,body.leaseId);if(!row)fail('owner_object_claim_lost',409);
  let prior;try{prior=await savedObjectAcceptance(env,row.account_id,row.lease_id);}
  catch(error){if(error?.message==='account_not_active')fail('owner_object_claim_lost',409);throw error;}
  if(prior){
    // Recovery is bound to immutable accepted identity, not new runtime policy
    // or still-fresh source evidence. It can never grant the award again.
    const accepted=await env.DB.prepare('SELECT * FROM object_acceptances WHERE lease_id=?').bind(row.lease_id).first();
    try{objectAuditResult(body.audit,{...expected(row),jobId:accepted.job_id,candidateManifestSha256:accepted.candidate_sha256,
      attempts:accepted.attempt,receiptSha256:accepted.receipt_sha256,state:'approved',decision:'approved'});}
    catch{fail('invalid_owner_object_result',400);}
    return {completed:true,...prior};
  }
  const p=ownerObjectBinding(env);await ownedClaim(env,body.leaseId,body.claimToken,now);
  if(row.policy_id!==p.policyId||!p.profiles.includes(row.profile_id))fail('owner_object_binding_changed',409);
  let audit;try{audit=objectAuditResult(body.audit,expected(row));}catch{fail('invalid_owner_object_result',400);}
  if(audit.attempts<row.native_attempts||row.native_state==='approved'&&(audit.state!=='approved'||audit.receiptSha256!==row.receipt_sha256))fail('invalid_owner_object_result',409);
  if(!['staging','queued','running','approved','rejected','failed'].includes(audit.state)
    || (audit.state==='approved'?body.evidence===null:body.evidence!==null))fail('invalid_owner_object_result',400);
  let full;if(audit.state==='approved')full=approvedEvidence(body.evidence,audit,p,now);
  const state=audit.state==='rejected'?'rejected':'pending';
  const updates=await env.DB.batch([
    env.DB.prepare(`UPDATE object_audit_candidates SET job_id=?,candidate_manifest_sha256=?,native_state=?,receipt_sha256=?,
      native_attempts=?,state=?,claim_token=NULL,claim_until=0,transport_failures=0,next_attempt=?,last_error=NULL
      WHERE lease_id=? AND state='pending' AND claim_token=? AND claim_until>max(?,unixepoch())
        AND EXISTS (SELECT 1 FROM accounts a JOIN leases l ON l.account_id=a.id WHERE a.id=object_audit_candidates.account_id
          AND a.deleted_at IS NULL AND l.id=object_audit_candidates.lease_id AND l.state='submitted' AND l.expires_at>max(?,unixepoch()))`)
      .bind(audit.jobId,audit.candidateManifestSha256,audit.state,audit.receiptSha256,audit.attempts,state,
        state==='pending'?now+30:0,row.lease_id,body.claimToken,now,now),
    env.DB.prepare(`UPDATE locations SET state='pending',queue_state='pending',active_lease=NULL,lease_until=NULL
      WHERE active_lease=? AND queue_state='quarantined' AND EXISTS
        (SELECT 1 FROM object_audit_candidates WHERE lease_id=? AND state='rejected')`).bind(row.lease_id,row.lease_id)
  ]);
  if(updates[0].meta?.changes!==1)fail('owner_object_claim_lost',409);
  if(audit.state!=='approved')return {completed:true,...objectAuditDispatchResult(await readObjectAuditCandidate(env,row.account_id,row.lease_id))};
  // A scoped in-memory bridge feeds the EXISTING guarded settlement writer.
  // It supports only this exact approved job/evidence, never an external URL.
  const scoped={...env,OBJECT_VERIFIER:{async fetch(request){
    const url=new URL(request.url),base=`/object-audits/${audit.jobId}`;
    if(url.origin!=='https://object-verifier.internal'||url.search||url.hash)fail();
    if(request.method==='GET'&&url.pathname===base)return Response.json(audit);
    if(request.method==='POST'&&url.pathname===base+'/settlement-evidence')return Response.json(full);
    fail();
  }}};
  return {completed:true,...await settleObjectAudit(scoped,row.account_id,row.lease_id,now)};
}

export async function failOwnerObjectAudit(env,body,now=Math.floor(Date.now()/1000)) {
  at(now);ownerObjectBinding(env);await ready(env);
  if(!exact(body,['leaseId','claimToken','reason'])||!['busy','unavailable'].includes(body.reason))fail('invalid_owner_object_request',400);
  const row=await ownedClaim(env,body.leaseId,body.claimToken,now),busy=body.reason==='busy';
  const failures=row.transport_failures+(busy?0:1),delay=busy?MAX_BACKOFF:Math.min(MAX_BACKOFF,30*2**(failures-1));
  const saved=await env.DB.prepare(`UPDATE object_audit_candidates SET claim_token=NULL,claim_until=0,transport_failures=?,
    next_attempt=?,last_error=? WHERE lease_id=? AND state='pending' AND claim_token=? AND claim_until>max(?,unixepoch())`)
    .bind(failures,now+delay,busy?'object_audit_queue_wait':'object_audit_transport_unavailable',row.lease_id,body.claimToken,now).run();
  if(saved.meta?.changes!==1)fail('owner_object_claim_lost',409);
  return {failed:true,charged:false,retryAt:now+delay,needsAttention:failures>=MAX_FAILURES};
}

export async function ownerObjectAuditStatus(env,account,lease) {
  ownerObjectBinding(env);await ready(env);
  if(typeof account!=='string'||!ID.test(account)||typeof lease!=='string'||!ID.test(lease))fail('invalid_object_dispatch',400);
  if(!await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first())fail('account_not_active',401);
  const row=await readObjectAuditCandidate(env,account,lease);if(!row)fail('unknown_object_candidate',404);
  return objectAuditDispatchResult(row);
}
