// Explicit private recovery controls. These do not qualify a device, publish
// work, award credit or install schema from an HTTP request.
import {ObjectDispatchError,objectAuditDispatchResult} from './objectAuditDispatch.js';
import {randomHex} from './model.js';
import {objectAuditResult} from '../native-object-verifier-bridge/worker.js';
import {readVerifierJson} from './scenePipeline.js';
const CONTRACT='private-object-recovery-v1-20261011',ID=/^[0-9a-f]{32}$/,HEX=/^[0-9a-f]{64}$/;
const CLAIM=30,MAX_DELAY=900;
export const OBJECT_RECOVERY_SCHEMA=[
  `CREATE TABLE IF NOT EXISTS object_recovery_revision (slot INTEGER PRIMARY KEY CHECK(slot=1),contract TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS object_audit_recoveries (
    request_id TEXT PRIMARY KEY,lease_id TEXT NOT NULL REFERENCES object_audit_candidates(lease_id),
    account_id TEXT NOT NULL REFERENCES accounts(id),action TEXT NOT NULL CHECK(action IN ('resume-transport','retry-native')),
    expected_attempts INTEGER NOT NULL,prior_failures INTEGER NOT NULL,prior_retry_at INTEGER NOT NULL,
    prior_error TEXT,prior_native_state TEXT,prior_receipt TEXT,job_id TEXT,created_at INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','applied')),transport_failures INTEGER NOT NULL DEFAULT 0,
    next_attempt INTEGER NOT NULL DEFAULT 0)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS object_recovery_pending ON object_audit_recoveries(lease_id) WHERE state='pending'`,
  `CREATE INDEX IF NOT EXISTS object_recovery_owner ON object_audit_recoveries(account_id,lease_id)`,
  `CREATE TRIGGER IF NOT EXISTS object_recovery_active BEFORE INSERT ON object_audit_recoveries
    WHEN NOT EXISTS (SELECT 1 FROM object_audit_candidates c JOIN accounts a ON a.id=c.account_id
      JOIN leases l ON l.id=c.lease_id WHERE c.lease_id=NEW.lease_id AND c.account_id=NEW.account_id
      AND a.deleted_at IS NULL AND l.lane='object' AND l.state='submitted' AND c.state='pending')
    BEGIN SELECT RAISE(ABORT,'object_recovery_owner_lost'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_recovery_capacity BEFORE INSERT ON object_audit_recoveries
    WHEN (SELECT COUNT(*) FROM object_audit_recoveries WHERE lease_id=NEW.lease_id AND action=NEW.action)
      >=CASE NEW.action WHEN 'resume-transport' THEN 4 ELSE 3 END
    BEGIN SELECT RAISE(ABORT,'object_recovery_limited'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_recovery_immutable BEFORE UPDATE ON object_audit_recoveries
    WHEN NEW.request_id IS NOT OLD.request_id OR NEW.lease_id IS NOT OLD.lease_id OR NEW.account_id IS NOT OLD.account_id
      OR NEW.action IS NOT OLD.action OR NEW.expected_attempts IS NOT OLD.expected_attempts
      OR NEW.prior_failures IS NOT OLD.prior_failures OR NEW.prior_retry_at IS NOT OLD.prior_retry_at
      OR NEW.prior_error IS NOT OLD.prior_error OR NEW.prior_native_state IS NOT OLD.prior_native_state
      OR NEW.prior_receipt IS NOT OLD.prior_receipt OR NEW.job_id IS NOT OLD.job_id OR NEW.created_at IS NOT OLD.created_at
      OR (OLD.state='applied' AND NEW.state!='applied')
    BEGIN SELECT RAISE(ABORT,'object_recovery_immutable'); END`,
];
const normalized=sql=>sql.replace(/IF NOT EXISTS/ig,'').replace(/[\s;]/g,'').toLowerCase();
const quote=value=>"'"+value.replaceAll("'","''")+"'";
const stored="lower(replace(replace(replace(replace(replace(replace(replace(sql,'IF NOT EXISTS',''),'if not exists',''),' ',''),char(10),''),char(13),''),char(9),''),';',''))";
const checks=OBJECT_RECOVERY_SCHEMA.map(sql=>{
  const [,kind,name]=sql.match(/^CREATE (?:UNIQUE )?(TABLE|INDEX|TRIGGER) IF NOT EXISTS (\w+)/);
  return `EXISTS (SELECT 1 FROM sqlite_master WHERE type=${quote(kind.toLowerCase())} AND name=${quote(name)}
    AND ${stored}=${quote(normalized(sql))})`;
}).join(' AND ');
export const OBJECT_RECOVERY_CONTRACT_SQL=`INSERT INTO object_recovery_revision
  SELECT 1,CASE WHEN (${checks}) AND EXISTS (SELECT 1 FROM object_dispatch_revision
    WHERE slot=1 AND contract='private-object-dispatch-v2-20261012') THEN '${CONTRACT}' ELSE NULL END
  ON CONFLICT(slot) DO UPDATE SET contract=CASE WHEN contract=excluded.contract THEN contract ELSE NULL END`;
const readCandidate=(env,account,lease)=>env.DB.prepare('SELECT * FROM object_audit_candidates WHERE lease_id=? AND account_id=?').bind(lease,account).first();
const readIntent=(env,id)=>env.DB.prepare('SELECT * FROM object_audit_recoveries WHERE request_id=?').bind(id).first();
async function active(env,account) {
  if(!await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first()) {
    throw new ObjectDispatchError('account_not_active',401);
  }
}
function response(candidate,intent,fresh=false) {
  return {...objectAuditDispatchResult(candidate,fresh),recoveryId:intent.request_id,recoveryState:intent.state,
    recoveryRetryAt:intent.next_attempt,recoveryNeedsAttention:intent.transport_failures>=8};
}

// The trusted caller chooses an opaque nonce once and saves it across retries.
// No timer automatically authorizes another native inference attempt.
export async function recoverObjectAudit(env,account,lease,request,now=Math.floor(Date.now()/1000),timeoutMs=20000) {
  if(typeof account!=='string' || typeof lease!=='string' || !ID.test(account) || !ID.test(lease)
      || !Number.isSafeInteger(now) || now<0 || now>Number.MAX_SAFE_INTEGER-MAX_DELAY
      || !request || typeof request!=='object' || Array.isArray(request) || Object.keys(request).sort().join(',')!=='action,requestId'
      || typeof request.requestId!=='string' || !HEX.test(request.requestId)
      || !['resume-transport','retry-native'].includes(request.action)
      || !Number.isSafeInteger(timeoutMs) || timeoutMs<1 || timeoutMs>20000) {
    throw new ObjectDispatchError('invalid_object_recovery',400);
  }
  try {
    const ready=await env.DB.prepare('SELECT contract FROM object_recovery_revision WHERE slot=1').first();
    if(ready?.contract!==CONTRACT) throw Error('missing');
  } catch {throw new ObjectDispatchError('object_recovery_setup_required',503);}
  await active(env,account);
  let row=await readCandidate(env,account,lease),intent=await readIntent(env,request.requestId);
  if(!row) throw new ObjectDispatchError('unknown_object_candidate',404);
  if(intent && (intent.account_id!==account || intent.lease_id!==lease || intent.action!==request.action)) {
    throw new ObjectDispatchError('object_recovery_conflict');
  }
  if(!intent) {
    if(row.state!=='pending' || row.claim_until>now && row.claim_until<=now+CLAIM) {
      throw new ObjectDispatchError('object_recovery_busy');
    }
    if(request.action==='resume-transport' && row.transport_failures<8
        || request.action==='retry-native' && (row.native_state!=='failed' || !row.job_id || row.native_attempts>=3)) {
      throw new ObjectDispatchError('object_recovery_not_needed');
    }
    try {
      await env.DB.batch([
        env.DB.prepare(`INSERT INTO object_audit_recoveries
          (request_id,lease_id,account_id,action,expected_attempts,prior_failures,prior_retry_at,prior_error,
            prior_native_state,prior_receipt,job_id,created_at,state)
          SELECT ?,lease_id,account_id,?,native_attempts,transport_failures,next_attempt,last_error,native_state,
            receipt_sha256,job_id,?,'pending' FROM object_audit_candidates WHERE lease_id=? AND account_id=?
            AND state='pending' AND native_attempts=? AND transport_failures=? AND native_state IS ?
            AND (claim_until<=? OR claim_until>?) AND NOT EXISTS
              (SELECT 1 FROM object_audit_recoveries WHERE lease_id=? AND state='pending')
          ON CONFLICT(request_id) DO NOTHING`)
          .bind(request.requestId,request.action,now,lease,account,row.native_attempts,row.transport_failures,row.native_state,
            now,now+CLAIM,lease),
        ...(request.action==='resume-transport' ? [
          env.DB.prepare(`UPDATE object_audit_candidates SET transport_failures=0,next_attempt=?,last_error=NULL,
            claim_token=NULL,claim_until=0 WHERE lease_id=? AND account_id=? AND state='pending' AND EXISTS
            (SELECT 1 FROM object_audit_recoveries WHERE request_id=? AND lease_id=? AND account_id=?
              AND state='pending' AND action='resume-transport')`)
            .bind(now,lease,account,request.requestId,lease,account),
          env.DB.prepare("UPDATE object_audit_recoveries SET state='applied' WHERE request_id=? AND lease_id=? AND account_id=? AND action='resume-transport'")
            .bind(request.requestId,lease,account),
        ]:[]),
      ]);
    } catch(error) {
      if(String(error?.message).includes('object_recovery_limited')) throw new ObjectDispatchError('object_recovery_limited',429);
      throw error;
    }
    intent=await readIntent(env,request.requestId);row=await readCandidate(env,account,lease);
    if(!intent) throw new ObjectDispatchError('object_recovery_busy');
    if(intent.account_id!==account || intent.lease_id!==lease || intent.action!==request.action) {
      throw new ObjectDispatchError('object_recovery_conflict');
    }
  }
  if(intent.state==='applied' || row.state!=='pending') return response(row,intent);
  if(typeof env.OBJECT_VERIFIER?.fetch!=='function') throw new ObjectDispatchError('object_verifier_unavailable',503);
  const claim=randomHex(16);
  await env.DB.prepare(`UPDATE object_audit_candidates SET claim_token=?,claim_until=? WHERE lease_id=? AND account_id=?
    AND state='pending' AND (claim_until<=? OR claim_until>?) AND EXISTS (SELECT 1 FROM object_audit_recoveries
      WHERE request_id=? AND state='pending' AND (next_attempt<=? OR next_attempt>?))`)
    .bind(claim,now+CLAIM,lease,account,now,now+CLAIM,request.requestId,now,now+MAX_DELAY).run();
  row=await readCandidate(env,account,lease);
  if(row.claim_token!==claim) return response(row,intent);
  // A separately observed newer attempt proves this intent need not be sent
  // again. This also avoids overwriting a later approval with an older reply.
  if(row.native_attempts>intent.expected_attempts) {
    await env.DB.batch([
      env.DB.prepare("UPDATE object_audit_recoveries SET state='applied',next_attempt=0 WHERE request_id=? AND EXISTS (SELECT 1 FROM object_audit_candidates WHERE lease_id=? AND claim_token=?)")
        .bind(request.requestId,lease,claim),
      env.DB.prepare('UPDATE object_audit_candidates SET claim_token=NULL,claim_until=0 WHERE lease_id=? AND claim_token=?').bind(lease,claim),
    ]);
    await active(env,account);return response(await readCandidate(env,account,lease),await readIntent(env,request.requestId));
  }
  let timer,checked,applied=false;const abort=new AbortController();
  const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{abort.abort();reject(Error('recovery_timeout'));},timeoutMs);});
  void deadline.catch(()=>{});
  try {
    const transfer=Promise.resolve().then(()=>env.OBJECT_VERIFIER.fetch(new Request(
      `https://object-verifier.internal/object-audits/${intent.job_id}/retry`,{method:'POST',signal:abort.signal,
        headers:{'content-type':'application/json'},body:JSON.stringify({requestId:intent.request_id,expectedAttempts:intent.expected_attempts})})))
      .then(value=>{if(abort.signal.aborted){if(value.body)void value.body.cancel().catch(()=>{});throw Error('late_reply');}return value;});
    const reply=await Promise.race([transfer,deadline]);
    if(reply.status!==200){if(reply.body)void reply.body.cancel().catch(()=>{});throw Error('unavailable');}
    checked=objectAuditResult(await Promise.race([readVerifierJson(reply,Math.min(timeoutMs,10000)),deadline]),{
      jobId:row.job_id,leaseId:lease,profileId:row.profile_id,policyId:row.policy_id,assignmentSha256:row.assignment_sha256,
      submissionSha256:row.submission_sha256,candidateManifestSha256:row.candidate_manifest_sha256});
    if(checked.attempts<row.native_attempts || checked.state==='staging'
        || ['approved','rejected','failed'].includes(checked.state) && checked.attempts<=intent.expected_attempts) throw Error('stale_reply');
    const state=checked.state==='rejected'?'rejected':['cancelled','erasing','erased'].includes(checked.state)?'cancelled':'pending';
    const updates=await env.DB.batch([
      env.DB.prepare(`UPDATE object_audit_recoveries SET state='applied',next_attempt=0 WHERE request_id=? AND state='pending'
        AND EXISTS (SELECT 1 FROM object_audit_candidates WHERE lease_id=? AND account_id=? AND state='pending' AND claim_token=?)`)
        .bind(request.requestId,lease,account,claim),
      env.DB.prepare(`UPDATE object_audit_candidates SET state=?,native_state=?,native_attempts=?,receipt_sha256=?,transport_failures=0,
        last_error=NULL,next_attempt=?,claim_token=NULL,claim_until=0 WHERE lease_id=? AND account_id=? AND state='pending' AND claim_token=?`)
        .bind(state,checked.state,checked.attempts,checked.receiptSha256,state==='pending'?now+30:0,lease,account,claim),
      env.DB.prepare(`UPDATE locations SET state='pending',queue_state='pending',active_lease=NULL,lease_until=NULL
        WHERE active_lease=? AND queue_state='quarantined' AND EXISTS
        (SELECT 1 FROM object_audit_candidates WHERE lease_id=? AND state IN ('rejected','cancelled'))`).bind(lease,lease),
    ]);
    applied=updates[1].meta?.changes===1;
  } catch {
    const failures=intent.transport_failures+1,delay=Math.min(MAX_DELAY,30*2**Math.min(failures-1,5));
    await env.DB.batch([
      env.DB.prepare(`UPDATE object_audit_recoveries SET transport_failures=?,next_attempt=? WHERE request_id=? AND state='pending'
        AND EXISTS (SELECT 1 FROM object_audit_candidates WHERE lease_id=? AND claim_token=?)`)
        .bind(failures,now+delay,request.requestId,lease,claim),
      env.DB.prepare('UPDATE object_audit_candidates SET claim_token=NULL,claim_until=0 WHERE lease_id=? AND claim_token=?').bind(lease,claim),
    ]);
  } finally {clearTimeout(timer);abort.abort();}
  await active(env,account);
  const saved=await readCandidate(env,account,lease);
  return response(saved,await readIntent(env,request.requestId),applied && saved.state==='pending'
    && saved.job_id===checked?.jobId && saved.native_state===checked?.state);
}
