// Private cancellation outbox. Revocation precedes all asynchronous cleanup;
// account deletion is not required. No qualification/publication/credit route.
import {ObjectDispatchError} from './objectAuditDispatch.js';
import {randomHex,encodeUtf8} from './model.js';
import {indexArtifactIdentity,PRIVACY_FENCE} from './artifactWrites.js';
import {eraseObjectAssignment} from './objectAuditPrivacy.js';
const ID=/^[0-9a-f]{32}$/,HEX=/^[0-9a-f]{64}$/;
const CONTRACT='private-object-cancellation-v1-20261011',CLAIM=30,MAX_DELAY=900;
export const OBJECT_CANCELLATION_SCHEMA=[
  `CREATE TABLE IF NOT EXISTS object_cancel_revision (slot INTEGER PRIMARY KEY CHECK(slot=1),contract TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS object_audit_cancellations (
    request_id TEXT PRIMARY KEY,lease_id TEXT NOT NULL UNIQUE REFERENCES object_audit_candidates(lease_id),
    account_id TEXT NOT NULL REFERENCES accounts(id),policy_id TEXT NOT NULL,assignment_sha256 TEXT NOT NULL,
    submission_sha256 TEXT NOT NULL,artifact_key TEXT NOT NULL,payload_bytes INTEGER NOT NULL,
    prior_native_state TEXT,prior_job_id TEXT,prior_receipt TEXT,prior_attempts INTEGER NOT NULL,
    prior_failures INTEGER NOT NULL,prior_retry_at INTEGER NOT NULL,prior_error TEXT,created_at INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','erased','needs_review')),
    native_erased_at INTEGER,r2_fenced_at INTEGER,claim_token TEXT,claim_until INTEGER NOT NULL DEFAULT 0,
    transport_failures INTEGER NOT NULL DEFAULT 0,next_attempt INTEGER NOT NULL DEFAULT 0,last_error TEXT)`,
  `CREATE INDEX IF NOT EXISTS object_cancel_pending ON object_audit_cancellations(account_id,state,next_attempt)`,
  `CREATE TRIGGER IF NOT EXISTS object_cancel_authority BEFORE INSERT ON object_audit_cancellations
    WHEN NEW.state!='pending' OR NOT EXISTS (SELECT 1 FROM object_audit_candidates c JOIN accounts a ON a.id=c.account_id
      JOIN leases l ON l.id=c.lease_id WHERE c.lease_id=NEW.lease_id AND c.account_id=NEW.account_id AND a.deleted_at IS NULL
      AND l.account_id=c.account_id AND l.lane='object' AND l.state='submitted' AND c.state='pending' AND c.policy_id=NEW.policy_id
      AND c.assignment_sha256=NEW.assignment_sha256 AND c.submission_sha256=NEW.submission_sha256
      AND c.artifact_key=NEW.artifact_key AND c.payload_bytes=NEW.payload_bytes)
      OR EXISTS (SELECT 1 FROM lease_items i JOIN published_index p ON p.location_id=i.location_id WHERE i.lease_id=NEW.lease_id)
    BEGIN SELECT RAISE(ABORT,'object_cancel_authority_lost'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_cancel_immutable BEFORE UPDATE ON object_audit_cancellations
    WHEN NEW.request_id IS NOT OLD.request_id OR NEW.lease_id IS NOT OLD.lease_id OR NEW.account_id IS NOT OLD.account_id
      OR NEW.policy_id IS NOT OLD.policy_id OR NEW.assignment_sha256 IS NOT OLD.assignment_sha256
      OR NEW.submission_sha256 IS NOT OLD.submission_sha256 OR NEW.artifact_key IS NOT OLD.artifact_key
      OR NEW.payload_bytes IS NOT OLD.payload_bytes OR NEW.prior_native_state IS NOT OLD.prior_native_state
      OR NEW.prior_job_id IS NOT OLD.prior_job_id OR NEW.prior_receipt IS NOT OLD.prior_receipt
      OR NEW.prior_attempts IS NOT OLD.prior_attempts OR NEW.prior_failures IS NOT OLD.prior_failures
      OR NEW.prior_retry_at IS NOT OLD.prior_retry_at OR NEW.prior_error IS NOT OLD.prior_error
      OR NEW.created_at IS NOT OLD.created_at OR (OLD.state!='pending' AND NEW.state!=OLD.state)
      OR (OLD.native_erased_at IS NOT NULL AND NEW.native_erased_at IS NOT OLD.native_erased_at)
      OR (OLD.r2_fenced_at IS NOT NULL AND NEW.r2_fenced_at IS NOT OLD.r2_fenced_at)
    BEGIN SELECT RAISE(ABORT,'object_cancel_immutable'); END`,
];
const normalized=sql=>sql.replace(/IF NOT EXISTS/ig,'').replace(/[\s;]/g,'').toLowerCase();
const quote=value=>"'"+value.replaceAll("'","''")+"'";
const stored="lower(replace(replace(replace(replace(replace(replace(replace(sql,'IF NOT EXISTS',''),'if not exists',''),' ',''),char(10),''),char(13),''),char(9),''),';',''))";
const checks=OBJECT_CANCELLATION_SCHEMA.map(sql=>{
  const [,kind,name]=sql.match(/^CREATE (TABLE|INDEX|TRIGGER) IF NOT EXISTS (\w+)/);
  return `EXISTS (SELECT 1 FROM sqlite_master WHERE type=${quote(kind.toLowerCase())} AND name=${quote(name)}
    AND ${stored}=${quote(normalized(sql))})`;
}).join(' AND ');
export const OBJECT_CANCELLATION_CONTRACT_SQL=`INSERT INTO object_cancel_revision
  SELECT 1,CASE WHEN (${checks}) AND EXISTS (SELECT 1 FROM object_dispatch_revision
    WHERE slot=1 AND contract='private-object-dispatch-v1-20261011') THEN '${CONTRACT}' ELSE NULL END
  ON CONFLICT(slot) DO UPDATE SET contract=CASE WHEN contract=excluded.contract THEN contract ELSE NULL END`;
async function ready(env) {
  try {if((await env.DB.prepare('SELECT contract FROM object_cancel_revision WHERE slot=1').first())?.contract!==CONTRACT)throw Error('missing');}
  catch {throw new ObjectDispatchError('object_cancel_setup_required',503);}
}
function identity(account,lease,now) {
  if(typeof account!=='string' || !ID.test(account) || typeof lease!=='string' || !ID.test(lease)
      || !Number.isSafeInteger(now) || now<0 || now>Number.MAX_SAFE_INTEGER-MAX_DELAY) {
    throw new ObjectDispatchError('invalid_object_cancellation',400);
  }
}
const saved=(env,account,lease)=>env.DB.prepare('SELECT * FROM object_audit_cancellations WHERE account_id=? AND lease_id=?').bind(account,lease).first();
function result(row) {
  return {submissionId:row.lease_id,cancellationId:row.request_id,cancelled:true,accepted:0,unitsEarned:0,
    pendingAudit:false,cleanupState:row.state,cleanupPending:row.state!=='erased',retryAt:row.next_attempt,
    needsAttention:row.state==='needs_review' || row.transport_failures>=8,
    productionQualified:false,serverAuthorization:false};
}

export async function cancelObjectAudit(env,account,lease,requestId,now=Math.floor(Date.now()/1000)) {
  identity(account,lease,now);if(typeof requestId!=='string' || !HEX.test(requestId))throw new ObjectDispatchError('invalid_object_cancellation',400);
  await ready(env);
  if(!await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first()) {
    throw new ObjectDispatchError('account_not_active',401);
  }
  const prior=await saved(env,account,lease);
  if(prior) {if(prior.request_id!==requestId)throw new ObjectDispatchError('object_cancel_conflict');return result(prior);}
  const reused=await env.DB.prepare('SELECT 1 FROM object_audit_cancellations WHERE request_id=?').bind(requestId).first();
  if(reused)throw new ObjectDispatchError('object_cancel_conflict');
  await env.DB.batch([
    env.DB.prepare(`INSERT INTO object_audit_cancellations
      (request_id,lease_id,account_id,policy_id,assignment_sha256,submission_sha256,artifact_key,payload_bytes,
        prior_native_state,prior_job_id,prior_receipt,prior_attempts,prior_failures,prior_retry_at,prior_error,created_at,state)
      SELECT ?,lease_id,account_id,policy_id,assignment_sha256,submission_sha256,artifact_key,payload_bytes,
        native_state,job_id,receipt_sha256,native_attempts,transport_failures,next_attempt,last_error,?,'pending'
      FROM object_audit_candidates WHERE lease_id=? AND account_id=? AND state='pending'
        AND NOT EXISTS (SELECT 1 FROM object_audit_cancellations WHERE lease_id=? OR request_id=?)`)
      .bind(requestId,now,lease,account,lease,requestId),
    env.DB.prepare(`UPDATE object_audit_candidates SET state='cancelled',receipt_sha256=NULL,claim_token=NULL,claim_until=0,next_attempt=0
      WHERE lease_id=? AND account_id=? AND state='pending' AND EXISTS
      (SELECT 1 FROM object_audit_cancellations WHERE lease_id=? AND account_id=? AND request_id=?)`)
      .bind(lease,account,lease,account,requestId),
    env.DB.prepare(`UPDATE locations SET state='pending',queue_state='pending',active_lease=NULL,lease_until=NULL
      WHERE active_lease=? AND state!='published' AND queue_state='quarantined' AND EXISTS
      (SELECT 1 FROM object_audit_cancellations WHERE lease_id=? AND account_id=? AND request_id=?)`)
      .bind(lease,lease,account,requestId),
    env.DB.prepare(`UPDATE leases SET state='expired' WHERE id=? AND account_id=? AND lane='object' AND EXISTS
      (SELECT 1 FROM object_audit_cancellations WHERE lease_id=? AND account_id=? AND request_id=?)`)
      .bind(lease,account,lease,account,requestId),
  ]);
  const row=await saved(env,account,lease);
  if(!row || row.request_id!==requestId)throw new ObjectDispatchError('object_cancel_conflict');
  // Authentication can be revoked by a concurrent account deletion. Cleanup
  // remains durable and can proceed through the internal outbox either way.
  if(!await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first()) {
    throw new ObjectDispatchError('account_not_active',401);
  }
  return result(row);
}

async function owned(env,row) {
  const key=indexArtifactIdentity(row.artifact_key);
  if(key?.lane!=='object' || key.lease!==row.lease_id || key.digest!==row.submission_sha256 || key.reference!==null) return false;
  const proof=await env.DB.prepare(`SELECT 1 FROM object_audit_candidates c JOIN leases l ON l.id=c.lease_id
    JOIN accounts a ON a.id=c.account_id JOIN account_artifact_writes w ON w.artifact_key=c.artifact_key
    WHERE c.lease_id=? AND c.account_id=? AND c.state='cancelled' AND l.account_id=c.account_id
      AND l.lane='object' AND l.state='expired' AND c.policy_id=? AND c.assignment_sha256=?
      AND c.submission_sha256=? AND c.artifact_key=? AND c.payload_bytes=?
      AND w.account_id=c.account_id AND w.lease_id=c.lease_id AND w.sha256=c.submission_sha256 AND w.bytes=c.payload_bytes
      AND (a.deleted_at IS NULL OR EXISTS (SELECT 1 FROM account_deletion_receipts d WHERE d.account_id=a.id AND d.deleted_at=a.deleted_at))
      AND NOT EXISTS (SELECT 1 FROM lease_items i JOIN published_index p ON p.location_id=i.location_id WHERE i.lease_id=c.lease_id)`)
    .bind(row.lease_id,row.account_id,row.policy_id,row.assignment_sha256,row.submission_sha256,row.artifact_key,row.payload_bytes).first();
  return !!proof;
}
async function fence(env,row,deadline) {
  const written=await Promise.race([env.INDEX.put(row.artifact_key,PRIVACY_FENCE,{
    customMetadata:{visionPrivacyFence:'1'},httpMetadata:{contentType:'application/x-vision-privacy-fence',cacheControl:'no-store'},
  }),deadline]);
  const expected=encodeUtf8(PRIVACY_FENCE);
  if(!written || written.size!==expected.length)throw Error('fence_unconfirmed');
  const value=await Promise.race([env.INDEX.get(row.artifact_key),deadline]);
  if(!value || value.customMetadata?.visionPrivacyFence!=='1' || value.size!==expected.length || !value.body)throw Error('fence_unconfirmed');
  const reader=value.body.getReader();let offset=0,finished=false;
  try {
    for(let i=0;i<1024;i++) {
      const {done,value:chunk}=await Promise.race([reader.read(),deadline]);
      if(done){finished=offset===expected.length;break;}
      if(!(chunk instanceof Uint8Array) || offset+chunk.length>expected.length
          || chunk.some((byte,i)=>byte!==expected[offset+i]))throw Error('fence_changed');
      offset+=chunk.length;
    }
  } finally {void reader.cancel().catch(()=>{});reader.releaseLock();}
  if(!finished)throw Error('fence_unconfirmed');
}

// Internal outbox advancement, not authenticated account access. A deleted
// owner is allowed only with its matching durable account-deletion receipt.
export async function advanceObjectCancellation(env,account,lease,now=Math.floor(Date.now()/1000),timeoutMs=20000) {
  identity(account,lease,now);await ready(env);
  if(!Number.isSafeInteger(timeoutMs) || timeoutMs<1 || timeoutMs>20000)throw new ObjectDispatchError('invalid_object_cancellation',400);
  let row=await saved(env,account,lease);
  if(!row)throw new ObjectDispatchError('unknown_object_cancellation',404);
  if(row.state!=='pending')return result(row);
  const claim=randomHex(16);
  await env.DB.prepare(`UPDATE object_audit_cancellations SET claim_token=?,claim_until=? WHERE lease_id=? AND account_id=? AND state='pending'
    AND (claim_until<=? OR claim_until>?) AND (next_attempt<=? OR next_attempt>?)`)
    .bind(claim,now+CLAIM,lease,account,now,now+CLAIM,now,now+MAX_DELAY).run();
  row=await saved(env,account,lease);if(row.claim_token!==claim)return result(row);
  if(!await owned(env,row)) {
    await env.DB.prepare(`UPDATE object_audit_cancellations SET state='needs_review',claim_token=NULL,claim_until=0,next_attempt=0,
      last_error='object_cancel_ownership_unconfirmed' WHERE lease_id=? AND claim_token=?`).bind(lease,claim).run();
    return result(await saved(env,account,lease));
  }
  let timer;const ends=Date.now()+timeoutMs;
  const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('cancel_cleanup_timeout')),timeoutMs);});
  void deadline.catch(()=>{});
  try {
    let nativeDone=row.native_erased_at!==null;
    if(!nativeDone) {
      // Reserve time for R2 too. Neither a storage outage nor a still-running
      // native owner should prevent the other independent cleanup step.
      const remaining=Math.min(10000,Math.max(1,Math.floor(timeoutMs/2)),ends-Date.now());
      nativeDone=remaining>0 && await Promise.race([eraseObjectAssignment(env,lease,remaining,{
        policyId:row.policy_id,assignmentSha256:row.assignment_sha256}),deadline]);
      if(nativeDone)await env.DB.prepare('UPDATE object_audit_cancellations SET native_erased_at=? WHERE lease_id=? AND claim_token=? AND state=\'pending\'')
        .bind(now,lease,claim).run();
    }
    if(row.r2_fenced_at===null) {
      if(!env.INDEX)throw Error('index_unavailable');
      await fence(env,row,deadline);
      await env.DB.prepare('UPDATE object_audit_cancellations SET r2_fenced_at=? WHERE lease_id=? AND claim_token=? AND state=\'pending\'')
        .bind(now,lease,claim).run();
    }
    if(!nativeDone)throw Error('native_cleanup_pending');
    await env.DB.prepare(`UPDATE object_audit_cancellations SET state='erased',claim_token=NULL,claim_until=0,next_attempt=0,last_error=NULL
      WHERE lease_id=? AND claim_token=? AND state='pending' AND native_erased_at IS NOT NULL AND r2_fenced_at IS NOT NULL`).bind(lease,claim).run();
  } catch {
    const failures=row.transport_failures+1,delay=Math.min(MAX_DELAY,30*2**Math.min(failures-1,5));
    await env.DB.prepare(`UPDATE object_audit_cancellations SET claim_token=NULL,claim_until=0,transport_failures=?,next_attempt=?,
      last_error='object_cancel_cleanup_pending' WHERE lease_id=? AND claim_token=? AND state='pending'`)
      .bind(failures,now+delay,lease,claim).run();
  } finally {clearTimeout(timer);}
  return result(await saved(env,account,lease));
}
