// Optional owner-outbound retirement, using the existing immutable acceptance
// and cleanup journal. No schema installation, inference, credit or R2 writes.
import {ownerObjectBinding,ownerObjectDelivery} from './ownerObjectAudit.js';
import {OBJECT_RETENTION_CONTRACT} from './objectAuditRetention.js';
import {objectRetirementProof,OBJECT_SETTLEMENT_CONTRACT} from './objectSettlement.js';
import {requireObjectAuditDispatch,ObjectDispatchError} from './objectAuditDispatch.js';
import {objectAuditResult} from '../native-object-verifier-bridge/worker.js';
import {sha256Hex,encodeUtf8} from './model.js';

const ID=/^[0-9a-f]{32}$/,HEX=/^[0-9a-f]{64}$/;
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===keys.sort().join(',');
const canonical=v=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'
  ?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;
const fail=(code='owner_retirement_unavailable',status=503)=>{throw new ObjectDispatchError(code,status);};
const at=now=>{if(!Number.isSafeInteger(now)||now<0||now>Number.MAX_SAFE_INTEGER-3600)fail('invalid_owner_retirement',400);};
async function ready(env){
  await requireObjectAuditDispatch(env);
  try{
    if((await env.DB.prepare('SELECT contract FROM object_retention_revision WHERE slot=1').first())?.contract!==OBJECT_RETENTION_CONTRACT
      ||(await env.DB.prepare('SELECT contract FROM object_settlement_revision WHERE slot=1').first())?.contract!==OBJECT_SETTLEMENT_CONTRACT)throw Error();
  }catch{fail('owner_retirement_setup_required');}
}
const journal=(env,lease)=>env.DB.prepare(`SELECT r.*,a.account_id FROM object_audit_retirements r
  JOIN object_acceptances a ON a.lease_id=r.lease_id WHERE r.lease_id=?`).bind(lease).first();
const proofHash=proof=>sha256Hex(encodeUtf8(JSON.stringify(proof)));

export async function claimOwnerObjectRetirement(env,body,now=Math.floor(Date.now()/1000)){
  at(now);const binding=ownerObjectBinding(env);
  if(!exact(body,['binding'])||JSON.stringify(canonical(body.binding))!==JSON.stringify(binding))fail('owner_object_binding_required',409);
  await ready(env);
  const compatible=`a.policy_id=? AND a.policy_sha256=? AND a.runtime_sha256=? AND a.quality_sha256=?
    AND a.protected_sha256=? AND a.origin_sha256=? AND a.profile_id IN (${binding.profiles.map(()=>'?').join(',')})`;
  const pins=[binding.policyId,binding.policySha256,binding.runtimeProfileSha256,binding.qualityImplementationIdentity,
    binding.protectedAuthoritySha256,binding.protectedOriginHandoffSha256,...binding.profiles];
  // At most one historical acceptance is seeded and one command reserved.
  // Failed native attempts are never selected or discarded by retirement.
  const next=await env.DB.prepare(`SELECT a.account_id,a.lease_id FROM object_acceptances a
    JOIN accounts u ON u.id=a.account_id LEFT JOIN object_audit_retirements r ON r.lease_id=a.lease_id
    WHERE r.lease_id IS NULL AND u.deleted_at IS NULL AND ${compatible}
    ORDER BY a.accepted_at,a.lease_id LIMIT 1`).bind(...pins).first();
  if(next){
    const proof=await objectRetirementProof(env,next.account_id,next.lease_id);
    if(proof)await env.DB.prepare(`INSERT INTO object_audit_retirements(lease_id,request_sha256,state)
      SELECT ?,?,'pending' WHERE EXISTS (SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL)
      ON CONFLICT(lease_id) DO NOTHING`).bind(next.lease_id,await proofHash(proof),next.account_id).run();
  }
  const row=await env.DB.prepare(`SELECT r.*,a.account_id FROM object_audit_retirements r
    JOIN object_acceptances a ON a.lease_id=r.lease_id JOIN accounts u ON u.id=a.account_id
    WHERE r.state='pending' AND u.deleted_at IS NULL AND r.next_attempt<=? AND ${compatible}
    ORDER BY r.next_attempt,a.accepted_at,r.lease_id LIMIT 1`).bind(now,...pins).first();
  if(!row)return {command:null,retryAfterSeconds:30};
  const proof=await objectRetirementProof(env,row.account_id,row.lease_id);
  if(!proof||await proofHash(proof)!==row.request_sha256)fail('owner_retirement_changed',409);
  const reserved=await env.DB.prepare(`UPDATE object_audit_retirements SET failures=min(failures+1,16),next_attempt=?
    WHERE lease_id=? AND state='pending' AND failures=? AND next_attempt=?
    AND EXISTS (SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL)`)
    .bind(now+Math.min(3600,60*2**row.failures),row.lease_id,row.failures,row.next_attempt,row.account_id).run();
  if(reserved.meta?.changes!==1)return {command:null,retryAfterSeconds:30};
  const accepted=await env.DB.prepare('SELECT profile_id FROM object_acceptances WHERE lease_id=?').bind(row.lease_id).first();
  return {command:{version:1,policyId:binding.policyId,profileId:accepted.profile_id,leaseId:row.lease_id,jobId:proof.jobId,
    requestSha256:row.request_sha256,body:proof.body}};
}

export async function acknowledgeOwnerObjectRetirement(env,body,now=Math.floor(Date.now()/1000)){
  at(now);if(!ownerObjectDelivery(env))fail();await ready(env);
  if(!exact(body,['command','audit']))fail('invalid_owner_retirement',400);
  const c=body.command;
  if(!exact(c,['version','policyId','profileId','leaseId','jobId','requestSha256','body'])||c.version!==1
    ||![c.leaseId,c.jobId].every(v=>typeof v==='string'&&ID.test(v))||typeof c.requestSha256!=='string'||!HEX.test(c.requestSha256))fail('invalid_owner_retirement',400);
  const row=await journal(env,c.leaseId);
  const accepted=await env.DB.prepare('SELECT * FROM object_acceptances WHERE lease_id=?').bind(c.leaseId).first();
  if(!row||!accepted||row.request_sha256!==c.requestSha256||accepted.policy_id!==c.policyId||accepted.profile_id!==c.profileId||accepted.job_id!==c.jobId)fail('owner_retirement_changed',409);
  // Reconstruct solely from immutable acceptance for replay, even if current
  // policy/assets are unavailable. This never authorizes new publication.
  const identity=Object.fromEntries(Object.keys(accepted).sort().map(k=>[k,accepted[k]]));
  const wanted={version:1,leaseId:c.leaseId,assignmentSha256:accepted.assignment_sha256,
    submissionSha256:accepted.submission_sha256,candidateManifestSha256:accepted.candidate_sha256,
    receiptSha256:accepted.receipt_sha256,attempts:accepted.attempt,
    acceptanceSha256:await sha256Hex(encodeUtf8(JSON.stringify(identity)))};
  if(JSON.stringify(canonical(c.body))!==JSON.stringify(canonical(wanted))
    ||await proofHash({jobId:c.jobId,body:wanted})!==row.request_sha256)fail('owner_retirement_changed',409);
  let audit;
  try{audit=objectAuditResult(body.audit,{jobId:c.jobId,leaseId:c.leaseId,policyId:c.policyId,profileId:accepted.profile_id,
    assignmentSha256:wanted.assignmentSha256,submissionSha256:wanted.submissionSha256,
    candidateManifestSha256:wanted.candidateManifestSha256,attempts:wanted.attempts});}
  catch{fail('invalid_owner_retirement',400);}
  if(!['retired','erased'].includes(audit.state)||audit.state==='retired'&&audit.receiptSha256!==wanted.receiptSha256)fail('invalid_owner_retirement',400);
  // Account erasure remains a separate stronger command. This acknowledgement
  // cannot claim that pending private account deletion has completed.
  await env.DB.prepare(`UPDATE object_audit_retirements SET state=CASE
      WHEN EXISTS (SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NOT NULL) OR ?='erased' THEN 'privacy' ELSE 'delivered' END,
      next_attempt=0,delivered_at=? WHERE lease_id=? AND request_sha256=? AND state='pending'`)
    .bind(row.account_id,audit.state,now,c.leaseId,c.requestSha256).run();
  const saved=await journal(env,c.leaseId);
  if(!['delivered','privacy'].includes(saved?.state))fail();
  const owner=await env.DB.prepare('SELECT deleted_at FROM accounts WHERE id=?').bind(row.account_id).first();
  return {acknowledged:true,leaseId:c.leaseId,requestSha256:c.requestSha256,
    privacyPending:saved.state==='privacy'||owner?.deleted_at!==null||audit.state==='erased'};
}
