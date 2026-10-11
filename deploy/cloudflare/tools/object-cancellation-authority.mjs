// Offline current authority only; no provider binding, uploads or mutation.
import {RESOURCE_PROFILES} from './account-restore.mjs';
import {indexArtifactIdentity} from '../src/artifactWrites.js';
import {objectCancellationPublicationSafe} from '../src/objectAuditCancellation.js';
const ID=/^[0-9a-f]{32}$/,HEX=/^[0-9a-f]{64}$/;
const integer=n=>Number.isSafeInteger(n)&&n>=0;
const shape=(value,keys)=>value && typeof value==='object' && !Array.isArray(value)
  && Object.keys(value).sort().join(',')===keys.split(',').sort().join(',');
function require(value){if(!value)throw Error('invalid_object_cancellation_authority');}
export function validateObjectCancellationLedger(value,notBefore,now,environment){
  const resource=RESOURCE_PROFILES[environment];
  require(resource && integer(now) && integer(notBefore) && notBefore<=now
    && shape(value,'version,scope,resource,exportedAt,cancellations') && value.version===1
    && value.scope==='private-object-cancellation-ledger-v1' && shape(value.resource,'accountId,bucket,databaseId')
    && Object.entries(resource).every(([key,wanted])=>value.resource[key]===wanted)
    && integer(value.exportedAt) && value.exportedAt>=notBefore && value.exportedAt<=now
    && now-value.exportedAt<600 && Array.isArray(value.cancellations) && value.cancellations.length<=4096);
  const leases=new Set(),requests=new Set();
  for(const row of value.cancellations){
    require(shape(row,'requestId,leaseId,accountId,policyId,assignmentSha256,submissionSha256,artifactKey,payloadBytes,cancelledAt')
      && typeof row.requestId==='string' && HEX.test(row.requestId) && !requests.has(row.requestId)
      && typeof row.leaseId==='string' && ID.test(row.leaseId) && !leases.has(row.leaseId)
      && typeof row.accountId==='string' && ID.test(row.accountId)
      && typeof row.policyId==='string' && /^[A-Za-z0-9_.-]{1,128}$/.test(row.policyId)
      && (environment!=='production' || !row.policyId.startsWith('staging.'))
      && typeof row.assignmentSha256==='string' && HEX.test(row.assignmentSha256)
      && typeof row.submissionSha256==='string' && HEX.test(row.submissionSha256)
      && integer(row.payloadBytes) && row.payloadBytes>0 && row.payloadBytes<=4*1024**2
      && integer(row.cancelledAt) && row.cancelledAt<=value.exportedAt);
    const key=indexArtifactIdentity(row.artifactKey);
    require(key?.lane==='object' && key.lease===row.leaseId && key.digest===row.submissionSha256 && key.reference===null);
    leases.add(row.leaseId);requests.add(row.requestId);
  }
  return value;
}
function currentRows(sql){
  const table=sql.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='object_audit_cancellations'").get();
  const revision=sql.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='object_cancel_revision'").get();
  if(!table){require(!revision);return [];}
  require(revision && sql.prepare('SELECT contract FROM object_cancel_revision WHERE slot=1').get()?.contract==='private-object-cancellation-v1-20261011');
  const rows=sql.prepare('SELECT * FROM object_audit_cancellations ORDER BY lease_id LIMIT 4097').all();require(rows.length<=4096);
  for(const row of rows){
    const candidate=sql.prepare('SELECT * FROM object_audit_candidates WHERE lease_id=?').get(row.lease_id);
    const lease=sql.prepare('SELECT account_id,lane,state FROM leases WHERE id=?').get(row.lease_id);
    const account=sql.prepare('SELECT deleted_at FROM accounts WHERE id=?').get(row.account_id);
    const intent=sql.prepare('SELECT * FROM account_artifact_writes WHERE artifact_key=?').get(row.artifact_key);
    require(['pending','erased','needs_review'].includes(row.state) && candidate?.state==='cancelled'
      && candidate.account_id===row.account_id && candidate.policy_id===row.policy_id
      && candidate.assignment_sha256===row.assignment_sha256 && candidate.submission_sha256===row.submission_sha256
      && candidate.artifact_key===row.artifact_key && candidate.payload_bytes===row.payload_bytes
      && lease?.account_id===row.account_id && lease.lane==='object' && lease.state==='expired' && account
      && (account.deleted_at===null || sql.prepare('SELECT 1 FROM account_deletion_receipts WHERE account_id=? AND deleted_at=?').get(row.account_id,account.deleted_at))
      && intent?.account_id===row.account_id && intent.lease_id===row.lease_id
      && intent.sha256===row.submission_sha256 && intent.bytes===row.payload_bytes);
    const published=sql.prepare('SELECT p.object_index_key,p.published_at FROM lease_items i JOIN published_index p ON p.location_id=i.location_id WHERE i.lease_id=?').all(row.lease_id);
    require(published.every(p=>objectCancellationPublicationSafe(p,row.lease_id,row.created_at)));
  }
  require(!sql.prepare(`SELECT 1 FROM object_audit_candidates c JOIN accounts a ON a.id=c.account_id
    WHERE c.state='cancelled' AND a.deleted_at IS NULL AND NOT EXISTS
    (SELECT 1 FROM object_audit_cancellations r WHERE r.lease_id=c.lease_id) LIMIT 1`).get());
  return rows.map(row=>({requestId:row.request_id,leaseId:row.lease_id,accountId:row.account_id,policyId:row.policy_id,
    assignmentSha256:row.assignment_sha256,submissionSha256:row.submission_sha256,artifactKey:row.artifact_key,
    payloadBytes:row.payload_bytes,cancelledAt:row.created_at}));
}
export function exportObjectCancellationLedger(sql,exportedAt,environment){
  sql.exec('BEGIN');
  try{
    const value={version:1,scope:'private-object-cancellation-ledger-v1',resource:RESOURCE_PROFILES[environment],
      exportedAt,cancellations:currentRows(sql)};
    validateObjectCancellationLedger(value,exportedAt,exportedAt,environment);sql.exec('COMMIT');return value;
  }catch(error){sql.exec('ROLLBACK');throw error;}
}
// Caller holds the closed-current database transaction. An independently pinned
// ledger must match the COMPLETE current set, not just this host's 64 leases.
export function reconcileObjectCancellations(sql,ledger,notBefore,now,environment){
  validateObjectCancellationLedger(ledger,notBefore,now,environment);
  const expected=currentRows(sql);
  require(expected.length===ledger.cancellations.length);
  const saved=new Map(ledger.cancellations.map(row=>[row.leaseId,row]));
  for(const row of expected)require(saved.has(row.leaseId) && Object.entries(row).every(([key,value])=>saved.get(row.leaseId)[key]===value));
  return saved;
}
