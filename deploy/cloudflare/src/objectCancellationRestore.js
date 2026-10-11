// Optional offline recovery fences. No request installs this schema or opens
// Object admission. Tombstones deliberately survive backups lacking the lease,
// candidate or account; they never manufacture any of those records.
import {ObjectDispatchError} from './objectAuditDispatch.js';
import {fenceObjectCancellationArtifact} from './objectAuditCancellation.js';
import {indexArtifactIdentity} from './artifactWrites.js';
export const OBJECT_CANCEL_RESTORE_CONTRACT='private-object-cancel-restore-v1-20261011';
export const OBJECT_CANCEL_RESTORE_SCHEMA=[
  `CREATE TABLE IF NOT EXISTS object_cancel_restore_revision (slot INTEGER PRIMARY KEY CHECK(slot=1),contract TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS object_cancellation_tombstones (
    lease_id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,account_id TEXT NOT NULL,policy_id TEXT NOT NULL,
    assignment_sha256 TEXT NOT NULL,submission_sha256 TEXT NOT NULL,artifact_key TEXT NOT NULL UNIQUE,
    payload_bytes INTEGER NOT NULL,cancelled_at INTEGER NOT NULL,source_ledger_sha256 TEXT NOT NULL)`,
  `CREATE INDEX IF NOT EXISTS object_cancel_restore_intents_lease ON account_artifact_writes(lease_id)`,
  `CREATE TRIGGER IF NOT EXISTS object_cancel_restore_immutable BEFORE UPDATE ON object_cancellation_tombstones
    BEGIN SELECT RAISE(ABORT,'object_cancel_restore_immutable'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_cancel_restore_no_delete BEFORE DELETE ON object_cancellation_tombstones
    BEGIN SELECT RAISE(ABORT,'object_cancel_restore_immutable'); END`,
  ...['INSERT','UPDATE'].flatMap(action=>[
    `CREATE TRIGGER IF NOT EXISTS object_cancel_restore_lease_${action.toLowerCase()} BEFORE ${action} ON leases
      WHEN EXISTS (SELECT 1 FROM object_cancellation_tombstones t WHERE t.lease_id=NEW.id
        AND (NEW.account_id IS NOT t.account_id OR NEW.lane!='object' OR NEW.state!='expired'))
      BEGIN SELECT RAISE(ABORT,'object_assignment_cancelled'); END`,
    `CREATE TRIGGER IF NOT EXISTS object_cancel_restore_location_${action.toLowerCase()} BEFORE ${action} ON locations
      WHEN EXISTS (SELECT 1 FROM object_cancellation_tombstones WHERE lease_id=NEW.active_lease)
      BEGIN SELECT RAISE(ABORT,'object_assignment_cancelled'); END`,
    `CREATE TRIGGER IF NOT EXISTS object_cancel_restore_artifact_${action.toLowerCase()} BEFORE ${action} ON account_artifact_writes
      WHEN EXISTS (SELECT 1 FROM object_cancellation_tombstones t WHERE t.lease_id=NEW.lease_id
        OR substr(NEW.artifact_key,1,51)='object-quarantine/'||t.lease_id||'/'
        OR substr(NEW.artifact_key,1,49)='object-index-v4/'||t.lease_id||'/')
      BEGIN SELECT RAISE(ABORT,'object_assignment_cancelled'); END`,
    `CREATE TRIGGER IF NOT EXISTS object_cancel_restore_publication_${action.toLowerCase()} BEFORE ${action} ON published_index
      WHEN EXISTS (SELECT 1 FROM object_cancellation_tombstones t
        WHERE substr(NEW.object_index_key,1,49)='object-index-v4/'||t.lease_id||'/')
      BEGIN SELECT RAISE(ABORT,'object_assignment_cancelled'); END`,
    `CREATE TRIGGER IF NOT EXISTS object_cancel_restore_items_${action.toLowerCase()} BEFORE ${action} ON lease_items
      WHEN EXISTS (SELECT 1 FROM object_cancellation_tombstones WHERE lease_id=NEW.lease_id)
      BEGIN SELECT RAISE(ABORT,'object_assignment_cancelled'); END`,
  ]),
  `CREATE TRIGGER IF NOT EXISTS object_cancel_restore_candidate_insert BEFORE INSERT ON object_audit_candidates
    WHEN EXISTS (SELECT 1 FROM object_cancellation_tombstones WHERE lease_id=NEW.lease_id)
    BEGIN SELECT RAISE(ABORT,'object_assignment_cancelled'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_cancel_restore_candidate_update BEFORE UPDATE ON object_audit_candidates
    WHEN EXISTS (SELECT 1 FROM object_cancellation_tombstones t WHERE t.lease_id=NEW.lease_id
      AND (NEW.state!='cancelled' OR NEW.receipt_sha256 IS NOT NULL OR NEW.claim_token IS NOT NULL
        OR NEW.claim_until!=0 OR NEW.next_attempt!=0))
    BEGIN SELECT RAISE(ABORT,'object_assignment_cancelled'); END`,
];

// Internal recovery only. An immutable tombstone authorizes its exact revoked
// quarantine even when the backup predates the account/lease. Other partial
// bundle members additionally require this database's original owned intent.
// R2 completion does not attest the independently restored native host.
export async function fenceRestoredObjectArtifact(env,lease,key,timeoutMs=20000){
  const identity=indexArtifactIdentity(key);
  if(typeof lease!=='string' || !/^[0-9a-f]{32}$/.test(lease) || identity?.lane!=='object' || identity.lease!==lease
      || !Number.isSafeInteger(timeoutMs) || timeoutMs<1 || timeoutMs>20000)throw new ObjectDispatchError('invalid_object_restore_fence',400);
  let row;
  try{
    if((await env.DB.prepare('SELECT contract FROM object_cancel_restore_revision WHERE slot=1').first())?.contract!==OBJECT_CANCEL_RESTORE_CONTRACT)throw Error('setup');
    row=await env.DB.prepare('SELECT * FROM object_cancellation_tombstones WHERE lease_id=?').bind(lease).first();
  }catch{throw new ObjectDispatchError('object_cancel_restore_setup_required',503);}
  if(!row)throw new ObjectDispatchError('unknown_object_cancellation',404);
  const assignment=await env.DB.prepare('SELECT account_id,lane,state FROM leases WHERE id=?').bind(lease).first();
  if(assignment && (assignment.account_id!==row.account_id || assignment.lane!=='object' || assignment.state!=='expired'))throw new ObjectDispatchError('object_cancel_ownership_unconfirmed');
  const intent=await env.DB.prepare('SELECT * FROM account_artifact_writes WHERE artifact_key=?').bind(key).first();
  if(key!==row.artifact_key && !intent || intent && (intent.account_id!==row.account_id || intent.lease_id!==lease)
      || identity.reference && await env.DB.prepare('SELECT 1 FROM published_index WHERE object_index_key=? LIMIT 1').bind(identity.reference).first()) {
    throw new ObjectDispatchError('object_cancel_ownership_unconfirmed');
  }
  if(!env.INDEX)throw new ObjectDispatchError('index_unavailable',503);
  let timer;const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('object_restore_fence_timeout')),timeoutMs);});
  void deadline.catch(()=>{});
  try{await fenceObjectCancellationArtifact(env,{artifact_key:key},deadline);}
  finally{clearTimeout(timer);}
  return {leaseId:lease,fenced:true,nativeCleanupPending:true,liveReady:false,productionQualified:false};
}
