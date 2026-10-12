// Private candidate handoff only. Upstream qualification/assignment authority
// and downstream publication remain separate gates. No public route installs
// this schema, accepts caller-chosen authority or awards work/search credit.
import {sha256Hex, encodeUtf8, base64ToBytes, randomHex} from './model.js';
import {writeObjectArtifact} from './artifactWrites.js';
import {objectCoverageComplete, COVERAGE_VALIDATOR} from './objectCoverage.js';
import {objectAuditResult, MAX_REQUEST} from '../native-object-verifier-bridge/worker.js';
import {readVerifierJson} from './scenePipeline.js';

export const OBJECT_DISPATCH_CONTRACT = 'private-object-dispatch-v2-20261012';
export const OBJECT_DISPATCH_LEGACY_CONTRACT = 'private-object-dispatch-v1-20261011';
const CONTRACT = OBJECT_DISPATCH_CONTRACT;
const ID = /^[0-9a-f]{32}$/, HEX = /^[0-9a-f]{64}$/;
const POLICY = /^[A-Za-z0-9_.-]{1,128}$/;
const CLAIM_SECONDS = 30, MAX_FAILURES = 8, MAX_BACKOFF = 900;
export class ObjectDispatchError extends Error {
  constructor(code, status = 409) { super(code); this.status = status; }
}

// Optional, explicit operator migration. It does not alter the deployed schema
// revision or open admission. All publication/credit fields are absent.
export const OBJECT_DISPATCH_LEGACY_SCHEMA = [
  `CREATE TABLE IF NOT EXISTS object_dispatch_revision (
    slot INTEGER PRIMARY KEY CHECK(slot=1), contract TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS object_audit_candidates (
    lease_id TEXT PRIMARY KEY REFERENCES leases(id), account_id TEXT NOT NULL REFERENCES accounts(id),
    profile_id TEXT NOT NULL, policy_id TEXT NOT NULL, assignment_sha256 TEXT NOT NULL,
    source_sha256 TEXT NOT NULL, submission_sha256 TEXT NOT NULL, artifact_key TEXT NOT NULL UNIQUE,
    payload_bytes INTEGER NOT NULL, location_count INTEGER NOT NULL CHECK(location_count BETWEEN 1 AND 4),
    created_at INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','rejected','cancelled')),
    job_id TEXT, candidate_manifest_sha256 TEXT, native_state TEXT, receipt_sha256 TEXT,
    native_attempts INTEGER NOT NULL DEFAULT 0, claim_token TEXT, claim_until INTEGER NOT NULL DEFAULT 0,
    transport_failures INTEGER NOT NULL DEFAULT 0, next_attempt INTEGER NOT NULL DEFAULT 0,
    last_error TEXT)`,
  `CREATE INDEX IF NOT EXISTS object_audit_candidates_owner ON object_audit_candidates(account_id,state)`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_active_insert BEFORE INSERT ON object_audit_candidates
    WHEN NEW.state!='pending' OR NOT EXISTS (SELECT 1 FROM accounts a JOIN leases l ON l.account_id=a.id
      WHERE a.id=NEW.account_id AND a.deleted_at IS NULL AND l.id=NEW.lease_id AND l.lane='object' AND l.state='active')
    BEGIN SELECT RAISE(ABORT,'object_dispatch_owner_lost'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_capacity BEFORE INSERT ON object_audit_candidates
    WHEN NOT EXISTS (SELECT 1 FROM object_audit_candidates WHERE lease_id=NEW.lease_id)
      AND ((SELECT COUNT(*) FROM object_audit_candidates)>=64
        OR (SELECT COUNT(*) FROM object_audit_candidates WHERE state='pending')>=8)
    BEGIN SELECT RAISE(ABORT,'object_dispatch_capacity'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_immutable BEFORE UPDATE ON object_audit_candidates
    WHEN NEW.lease_id IS NOT OLD.lease_id OR NEW.account_id IS NOT OLD.account_id
      OR NEW.profile_id IS NOT OLD.profile_id OR NEW.policy_id IS NOT OLD.policy_id
      OR NEW.assignment_sha256 IS NOT OLD.assignment_sha256 OR NEW.source_sha256 IS NOT OLD.source_sha256
      OR NEW.submission_sha256 IS NOT OLD.submission_sha256 OR NEW.artifact_key IS NOT OLD.artifact_key
      OR NEW.payload_bytes IS NOT OLD.payload_bytes OR NEW.location_count IS NOT OLD.location_count
      OR NEW.created_at IS NOT OLD.created_at
      OR (OLD.job_id IS NOT NULL AND NEW.job_id IS NOT OLD.job_id)
      OR (OLD.candidate_manifest_sha256 IS NOT NULL AND NEW.candidate_manifest_sha256 IS NOT OLD.candidate_manifest_sha256)
      OR (OLD.state!='pending' AND NEW.state!=OLD.state AND NEW.state!='cancelled')
    BEGIN SELECT RAISE(ABORT,'object_dispatch_immutable'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_active_update BEFORE UPDATE ON object_audit_candidates
    WHEN NEW.state='pending' AND NOT EXISTS (SELECT 1 FROM accounts a JOIN leases l ON l.account_id=a.id
      WHERE a.id=NEW.account_id AND a.deleted_at IS NULL AND l.id=NEW.lease_id AND l.lane='object' AND l.state='submitted')
    BEGIN SELECT RAISE(ABORT,'object_dispatch_owner_lost'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_deleted AFTER UPDATE OF deleted_at ON accounts
    WHEN NEW.deleted_at IS NOT NULL
    BEGIN UPDATE object_audit_candidates SET state='cancelled',claim_token=NULL,claim_until=0,
      next_attempt=0,receipt_sha256=NULL WHERE account_id=NEW.id; END`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_expired AFTER UPDATE OF state ON leases
    WHEN NEW.state='expired'
    BEGIN UPDATE object_audit_candidates SET state='cancelled',claim_token=NULL,claim_until=0,
      next_attempt=0,receipt_sha256=NULL WHERE lease_id=NEW.id AND state='pending';
      UPDATE locations SET state='pending',queue_state='pending',active_lease=NULL,lease_until=NULL
        WHERE active_lease=NEW.id AND state!='published' AND queue_state='quarantined'; END`,
];
// Historical candidates/receipts remain intact. Only unfinished work occupies
// a queue slot. A native approval alone cannot release one: publication and the
// unique earned-work ledger entry must both exist for the exact owned lease.
const settled = alias => `EXISTS (SELECT 1 FROM ledger g WHERE g.reference='lease:'||${alias}.lease_id
  AND g.account_id=${alias}.account_id AND g.reason='verified_work' AND g.units=${alias}.location_count*10)
  AND (SELECT COUNT(*) FROM lease_items WHERE lease_id=${alias}.lease_id)=${alias}.location_count
  AND (SELECT COUNT(*) FROM lease_items i JOIN locations l ON l.id=i.location_id
    JOIN published_index p ON p.location_id=l.id WHERE i.lease_id=${alias}.lease_id AND l.state='published'
      AND l.contributor_id=${alias}.account_id AND p.object_index_key='object-index-v4/'||${alias}.lease_id||'/')=${alias}.location_count`;
export const OBJECT_DISPATCH_SCHEMA = [
  ...OBJECT_DISPATCH_LEGACY_SCHEMA.filter(sql=>!sql.startsWith('CREATE TRIGGER IF NOT EXISTS object_dispatch_capacity')),
  `CREATE TABLE IF NOT EXISTS object_dispatch_slots (lease_id TEXT PRIMARY KEY REFERENCES object_audit_candidates(lease_id))`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_capacity BEFORE INSERT ON object_audit_candidates
    WHEN NOT EXISTS (SELECT 1 FROM object_audit_candidates WHERE lease_id=NEW.lease_id)
      AND (SELECT COUNT(*) FROM object_dispatch_slots)>=8
    BEGIN SELECT RAISE(ABORT,'object_dispatch_capacity'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_slot_insert BEFORE INSERT ON object_dispatch_slots
    WHEN NOT EXISTS (SELECT 1 FROM object_dispatch_slots WHERE lease_id=NEW.lease_id)
      AND ((SELECT COUNT(*) FROM object_dispatch_slots)>=8 OR NOT EXISTS
        (SELECT 1 FROM object_audit_candidates c WHERE c.lease_id=NEW.lease_id AND c.state='pending' AND NOT (${settled('c')})))
    BEGIN SELECT RAISE(ABORT,'object_dispatch_slot_invalid'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_slot_immutable BEFORE UPDATE ON object_dispatch_slots
    BEGIN SELECT RAISE(ABORT,'object_dispatch_slot_immutable'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_slot_delete BEFORE DELETE ON object_dispatch_slots
    WHEN EXISTS (SELECT 1 FROM object_audit_candidates c WHERE c.lease_id=OLD.lease_id
      AND c.state='pending' AND NOT (${settled('c')}))
    BEGIN SELECT RAISE(ABORT,'object_dispatch_slot_unfinished'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_slot_reserve AFTER INSERT ON object_audit_candidates
    BEGIN INSERT INTO object_dispatch_slots VALUES (NEW.lease_id); END`,
  `CREATE TRIGGER IF NOT EXISTS object_dispatch_slot_terminal AFTER UPDATE OF state ON object_audit_candidates
    WHEN NEW.state!='pending'
    BEGIN DELETE FROM object_dispatch_slots WHERE lease_id=NEW.lease_id; END`,
];
const backfill = `INSERT INTO object_dispatch_slots SELECT c.lease_id FROM object_audit_candidates c
  WHERE c.state='pending' AND NOT (${settled('c')})
    AND NOT EXISTS (SELECT 1 FROM object_dispatch_slots s WHERE s.lease_id=c.lease_id)`;
const normalized = sql => sql.replace(/IF NOT EXISTS/ig,'').replace(/[\s;]/g,'').toLowerCase();
const quote = value => "'"+value.replaceAll("'","''")+"'";
const stored = "lower(replace(replace(replace(replace(replace(replace(replace(sql,'IF NOT EXISTS',''),'if not exists',''),' ',''),char(10),''),char(13),''),char(9),''),';',''))";
const checks=definitions=>definitions.map(sql=>{
  const [,kind,name]=sql.match(/^CREATE (TABLE|INDEX|TRIGGER) IF NOT EXISTS (\w+)/);
  return `EXISTS (SELECT 1 FROM sqlite_master WHERE type=${quote(kind.toLowerCase())} AND name=${quote(name)}
    AND ${stored}=${quote(normalized(sql))})`;
}).join(' AND ');
export const OBJECT_DISPATCH_LEGACY_CONTRACT_SQL = `INSERT INTO object_dispatch_revision
  SELECT 1,CASE WHEN (${checks(OBJECT_DISPATCH_LEGACY_SCHEMA)}) THEN '${OBJECT_DISPATCH_LEGACY_CONTRACT}' ELSE NULL END
  ON CONFLICT(slot) DO UPDATE SET contract=CASE WHEN contract=excluded.contract THEN contract ELSE NULL END`;
export const OBJECT_DISPATCH_CONTRACT_SQL = `INSERT INTO object_dispatch_revision
  SELECT 1,CASE WHEN (${checks(OBJECT_DISPATCH_SCHEMA)}) THEN '${CONTRACT}' ELSE NULL END
  ON CONFLICT(slot) DO UPDATE SET contract=CASE WHEN contract IN ('${OBJECT_DISPATCH_LEGACY_CONTRACT}','${CONTRACT}')
    THEN excluded.contract ELSE NULL END`;

// One operator transaction, shared by D1 setup and offline recovery. Validate
// every original fence before changing the v1 capacity trigger; never rebuild
// candidate tables or their dependent acceptance/cancellation/retry journals.
export function objectDispatchMigration(contract=null) {
  if(contract!==null && ![CONTRACT,OBJECT_DISPATCH_LEGACY_CONTRACT].includes(contract)) {
    throw new ObjectDispatchError('object_dispatch_setup_required',503);
  }
  return [...(contract===OBJECT_DISPATCH_LEGACY_CONTRACT
    ? [OBJECT_DISPATCH_LEGACY_CONTRACT_SQL,'DROP TRIGGER object_dispatch_capacity']:[]),
    ...OBJECT_DISPATCH_SCHEMA,backfill,OBJECT_DISPATCH_CONTRACT_SQL];
}

async function schema(env) {
  try {
    const row = await env.DB.prepare('SELECT contract FROM object_dispatch_revision WHERE slot=1').first();
    if (row?.contract !== CONTRACT) throw Error('missing_schema');
  } catch { throw new ObjectDispatchError('object_dispatch_setup_required', 503); }
}
function identity(account, lease, now) {
  if (typeof account !== 'string' || !ID.test(account) || typeof lease !== 'string' || !ID.test(lease)
      || !Number.isSafeInteger(now) || now < 0 || now > Number.MAX_SAFE_INTEGER - MAX_BACKOFF) {
    throw new ObjectDispatchError('invalid_object_dispatch', 400);
  }
}
export function objectAuditDispatchResult(row, fresh = false) {
  if(row.settled_count===row.location_count && row.settled_units===row.location_count*10) {
    return {submissionId:row.lease_id,accepted:row.location_count,unitsEarned:0,replayed:true,pendingAudit:false,
      pending:0,rejected:false,cancelled:false,auditState:'published',freshAuditReply:false,
      retryAt:0,needsAttention:false,qualificationScope:'batch-only'};
  }
  return {submissionId:row.lease_id, accepted:0, unitsEarned:0, pendingAudit:row.state === 'pending',
    pending:row.state === 'pending' ? row.location_count : 0, rejected:row.state === 'rejected',
    cancelled:row.state === 'cancelled', auditState:row.native_state, freshAuditReply:fresh,
    retryAt:row.next_attempt, needsAttention:row.transport_failures >= MAX_FAILURES || row.native_state === 'failed',
    auditProtocol:'object-saved-audit-v1',
    productionQualified:false, serverAuthorization:false};
}
const result=objectAuditDispatchResult;
const readRow = (env, account, lease) => env.DB.prepare(
  `SELECT c.*,(SELECT COUNT(*) FROM lease_items i JOIN locations l ON l.id=i.location_id
    JOIN published_index p ON p.location_id=l.id WHERE i.lease_id=c.lease_id AND l.state='published'
      AND l.contributor_id=c.account_id AND p.object_index_key='object-index-v4/'||c.lease_id||'/') AS settled_count,
    (SELECT units FROM ledger WHERE reference='lease:'||c.lease_id AND account_id=c.account_id AND reason='verified_work') AS settled_units
    FROM object_audit_candidates c WHERE c.lease_id=? AND c.account_id=?`).bind(lease,account).first();

// authority is supplied by the trusted qualification/assignment caller, never
// copied from an HTTP uploader. A saved native approval still cannot authorize
// publication. Native import guards, exact canary and settlement remain required.
export async function stageObjectAudit(env, account, authority, objectIndex, now = Math.floor(Date.now()/1000)) {
  const lease = authority?.leaseId;
  identity(account,lease,now); await schema(env);
  if (!authority || Object.keys(authority).sort().join(',') !== 'assignmentSha256,leaseId,policyId,profileId,sourceSha256'
      || ![authority.profileId,authority.assignmentSha256,authority.sourceSha256].every(v => typeof v === 'string' && HEX.test(v))
      || typeof authority.policyId !== 'string' || !POLICY.test(authority.policyId)) {
    throw new ObjectDispatchError('invalid_object_dispatch_authority',400);
  }
  if (!objectIndex || typeof objectIndex !== 'object' || Array.isArray(objectIndex)
      || Object.keys(objectIndex).sort().join(',') !== 'files,manifest,sourceTsv'
      || !objectIndex.manifest || typeof objectIndex.manifest !== 'object' || Array.isArray(objectIndex.manifest)
      || !objectIndex.files || typeof objectIndex.files !== 'object' || Array.isArray(objectIndex.files)
      || Object.keys(objectIndex.files).length > 87
      || Object.entries(objectIndex.files).some(([name,value]) => !/^[a-z0-9][a-z0-9.-]*\.bin$/.test(name) || typeof value !== 'string')
      || typeof objectIndex.sourceTsv !== 'string') throw new ObjectDispatchError('invalid_object_candidate',400);
  let payload, source;
  try {
    payload = encodeUtf8(JSON.stringify(objectIndex));
    if (payload.length < 1 || payload.length > MAX_REQUEST - 1024) throw Error('payload_limit');
    source = base64ToBytes(objectIndex.sourceTsv);
    if (!source.length || await sha256Hex(source) !== authority.sourceSha256) throw Error('source_changed');
  } catch { throw new ObjectDispatchError('invalid_object_candidate',400); }
  const submission = await sha256Hex(payload), key = `object-quarantine/${lease}/${submission}.json`;
  const previous = await readRow(env,account,lease);
  if (previous) {
    if (previous.profile_id !== authority.profileId || previous.policy_id !== authority.policyId
        || previous.assignment_sha256 !== authority.assignmentSha256 || previous.source_sha256 !== authority.sourceSha256
        || previous.submission_sha256 !== submission || previous.payload_bytes !== payload.length) {
      throw new ObjectDispatchError('object_candidate_conflict');
    }
    // A revoked account receives no cached audit approval on upload replay.
    const owner = await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first();
    if (!owner) throw new ObjectDispatchError('account_not_active',401);
    return result(previous);
  }
  const owned = await env.DB.prepare(`SELECT 1 FROM leases l JOIN accounts a ON a.id=l.account_id
    WHERE l.id=? AND l.account_id=? AND l.lane='object' AND l.state='active' AND l.expires_at>? AND a.deleted_at IS NULL`)
    .bind(lease,account,now).first();
  if (!owned) throw new ObjectDispatchError('lease_lost');
  const rows = (await env.DB.prepare(`SELECT l.* FROM locations l JOIN lease_items i ON i.location_id=l.id
    WHERE i.lease_id=? ORDER BY l.id`).bind(lease).all()).results || [];
  if (!rows.length || rows.length > 4 || rows.some(row => row.state !== 'leased' || row.active_lease !== lease)
      || !await objectCoverageComplete(env.DB,rows)) throw new ObjectDispatchError('object_assignment_changed');
  const fresh = await env.DB.prepare(`SELECT COUNT(*) AS n FROM object_coverage WHERE location_id IN
    (SELECT location_id FROM lease_items WHERE lease_id=?) AND validator=? AND validated_at<=? AND validated_at>?`)
    .bind(lease,COVERAGE_VALIDATOR,now,now-86400).first();
  if (fresh?.n !== rows.length) throw new ObjectDispatchError('object_coverage_expired');
  const capacity=await env.DB.prepare('SELECT COUNT(*) AS pending FROM object_dispatch_slots').first();
  if(capacity.pending>=8) throw new ObjectDispatchError('object_dispatch_capacity',503);
  await writeObjectArtifact(env,account,lease,key,payload,now);
  try {
    await env.DB.batch([
      env.DB.prepare(`INSERT INTO object_audit_candidates
        (lease_id,account_id,profile_id,policy_id,assignment_sha256,source_sha256,submission_sha256,artifact_key,
          payload_bytes,location_count,created_at,state)
        SELECT ?,?,?,?,?,?,?,?,?,?,?,'pending' WHERE EXISTS
          (SELECT 1 FROM leases WHERE id=? AND account_id=? AND state='active' AND expires_at>?)
          AND (SELECT COUNT(*) FROM lease_items WHERE lease_id=?)=?
          AND (SELECT COUNT(*) FROM lease_items i JOIN locations l ON l.id=i.location_id
            WHERE i.lease_id=? AND l.state='leased' AND l.active_lease=? AND l.lane='object')=?
          AND (SELECT COUNT(*) FROM object_coverage c JOIN locations l ON l.id=c.location_id
            JOIN lease_items i ON i.location_id=l.id WHERE i.lease_id=? AND l.camera_generation='gen4'
              AND c.validator=? AND c.validated_at<=? AND c.validated_at>?
              AND length(c.evidence_sha256)=64 AND c.evidence_sha256 NOT GLOB '*[^0-9a-f]*')=?
        ON CONFLICT(lease_id) DO NOTHING`)
        .bind(lease,account,authority.profileId,authority.policyId,authority.assignmentSha256,authority.sourceSha256,
          submission,key,payload.length,rows.length,now,lease,account,now,lease,rows.length,lease,lease,rows.length,
          lease,COVERAGE_VALIDATOR,now,now-86400,rows.length),
      // Keep ownership during quarantine; account deletion can find and release
      // these rows without consulting this optional schema. They are unleaseable.
      env.DB.prepare(`UPDATE locations SET state='pending',queue_state='quarantined',lease_until=NULL
        WHERE active_lease=? AND EXISTS (SELECT 1 FROM object_audit_candidates WHERE lease_id=? AND state='pending')`)
        .bind(lease,lease),
      env.DB.prepare(`UPDATE leases SET state='submitted' WHERE id=? AND EXISTS
        (SELECT 1 FROM object_audit_candidates WHERE lease_id=? AND state='pending')`).bind(lease,lease),
    ]);
  } catch (error) {
    if (String(error?.message).includes('object_dispatch_capacity')) throw new ObjectDispatchError('object_dispatch_capacity',503);
    throw error;
  }
  const saved = await readRow(env,account,lease);
  if (!saved) throw new ObjectDispatchError('lease_lost');
  if (saved.submission_sha256 !== submission || saved.assignment_sha256 !== authority.assignmentSha256
      || saved.source_sha256 !== authority.sourceSha256 || saved.profile_id !== authority.profileId
      || saved.policy_id !== authority.policyId) throw new ObjectDispatchError('object_candidate_conflict');
  return result(saved);
}

async function payloadFor(env,row,deadline) {
  const object = await Promise.race([env.INDEX.get(row.artifact_key),deadline]);
  if (!object || object.customMetadata?.visionPrivacyFence === '1' || object.size !== row.payload_bytes
      || object.size < 1 || object.size > MAX_REQUEST - 1024) throw Error('candidate_corrupt');
  let bytes;
  if (object.body) {
    const reader=object.body.getReader(), chunks=[];
    let size=0;
    try {
      for(let i=0;i<65536;i++) {
        const next=await Promise.race([reader.read(),deadline]);
        if(next.done) {bytes=new Uint8Array(size);let offset=0;for(const c of chunks){bytes.set(c,offset);offset+=c.length;}break;}
        if(!(next.value instanceof Uint8Array) || size+next.value.length>row.payload_bytes) throw Error('candidate_corrupt');
        size+=next.value.length;chunks.push(next.value);
      }
    } finally {void reader.cancel().catch(()=>{});reader.releaseLock();}
  } else throw Error('candidate_corrupt');
  if(!bytes || bytes.length!==row.payload_bytes || await sha256Hex(bytes)!==row.submission_sha256) throw Error('candidate_corrupt');
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
}

export async function advanceObjectAudit(env,account,lease,now=Math.floor(Date.now()/1000),timeoutMs=20000) {
  identity(account,lease,now); await schema(env);
  if(typeof env.OBJECT_VERIFIER?.fetch!=='function' || !env.INDEX
      || !Number.isSafeInteger(timeoutMs) || timeoutMs<1 || timeoutMs>20000) {
    throw new ObjectDispatchError('object_verifier_unavailable',503);
  }
  const initial=await readRow(env,account,lease);
  if(!initial) throw new ObjectDispatchError('unknown_object_candidate',404);
  const owner=await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first();
  if(!owner) throw new ObjectDispatchError('account_not_active',401);
  if(initial.state!=='pending' || initial.transport_failures>=MAX_FAILURES || result(initial).accepted) return result(initial);
  const claim=randomHex(16);
  // Durable per-candidate lease prevents simultaneous status reads/starts from
  // racing saved state. Repeated POST after a lost reply uses identical bytes;
  // the native host's assignment fingerprint gives it the same job identity.
  await env.DB.prepare(`UPDATE object_audit_candidates SET claim_token=?,claim_until=?
    WHERE lease_id=? AND account_id=? AND state='pending' AND transport_failures<?
      AND (claim_until<=? OR claim_until>?) AND (next_attempt<=? OR next_attempt>?)`)
    .bind(claim,now+CLAIM_SECONDS,lease,account,MAX_FAILURES,now,now+CLAIM_SECONDS,now,now+MAX_BACKOFF).run();
  const row=await readRow(env,account,lease);
  if(row.claim_token!==claim) return result(row);
  const abort=new AbortController();let timer,checked,applied=false;
  const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{abort.abort();reject(Error('object_dispatch_timeout'));},timeoutMs);});
  void deadline.catch(()=>{});
  try {
    let body;
    if(!row.job_id) {
      const objectIndex=await payloadFor(env,row,deadline);
      body=JSON.stringify({version:1,leaseId:lease,profileId:row.profile_id,policyId:row.policy_id,
        assignmentSha256:row.assignment_sha256,submissionSha256:row.submission_sha256,objectIndex});
      if(encodeUtf8(body).length>MAX_REQUEST) throw Error('candidate_corrupt');
    }
    const request=new Request('https://object-verifier.internal/object-audits'+(row.job_id?'/'+row.job_id:''),{
      method:row.job_id?'GET':'POST',signal:abort.signal,...(body?{body,headers:{'content-type':'application/json'}}:{})});
    const transfer=Promise.resolve().then(()=>env.OBJECT_VERIFIER.fetch(request)).then(response=>{
      if(abort.signal.aborted){if(response.body)void response.body.cancel().catch(()=>{});throw Error('late_reply');}return response;
    });
    const response=await Promise.race([transfer,deadline]);
    if(response.status!==200){if(response.body)void response.body.cancel().catch(()=>{});throw Error('object_verifier_unavailable');}
    const value=await Promise.race([readVerifierJson(response,Math.min(timeoutMs,10000)),deadline]);
    checked=objectAuditResult(value,{leaseId:lease,profileId:row.profile_id,policyId:row.policy_id,
      assignmentSha256:row.assignment_sha256,submissionSha256:row.submission_sha256,
      ...(row.job_id?{jobId:row.job_id,candidateManifestSha256:row.candidate_manifest_sha256}:{})});
    if(checked.attempts<row.native_attempts || row.native_state==='approved'
        && (!['approved','cancelled','erasing','erased'].includes(checked.state)
          || checked.state==='approved' && checked.receiptSha256!==row.receipt_sha256)) throw Error('stale_audit_reply');
    const state=checked.state==='rejected'?'rejected':['cancelled','erasing','erased'].includes(checked.state)?'cancelled':'pending';
    // Claim+owner checks also reject approvals delivered after deletion or a
    // newer recovery claim. No read/modify/write balance operations occur here.
    const updates=await env.DB.batch([
      env.DB.prepare(`UPDATE object_audit_candidates SET job_id=?,candidate_manifest_sha256=?,native_state=?,
        receipt_sha256=?,native_attempts=?,state=?,claim_token=NULL,claim_until=0,transport_failures=0,
        next_attempt=?,last_error=NULL WHERE lease_id=? AND account_id=? AND state='pending' AND claim_token=?`)
        .bind(checked.jobId,checked.candidateManifestSha256,checked.state,checked.receiptSha256,checked.attempts,state,
          state==='pending'?now+30:0,lease,account,claim),
      env.DB.prepare(`UPDATE locations SET state='pending',queue_state='pending',active_lease=NULL,lease_until=NULL
        WHERE active_lease=? AND queue_state='quarantined' AND EXISTS
          (SELECT 1 FROM object_audit_candidates WHERE lease_id=? AND state IN ('rejected','cancelled'))`).bind(lease,lease),
    ]);
    applied=updates[0].meta?.changes===1;
  } catch {
    const failures=row.transport_failures+1, delay=Math.min(MAX_BACKOFF,30*2**(failures-1));
    await env.DB.prepare(`UPDATE object_audit_candidates SET claim_token=NULL,claim_until=0,
      transport_failures=?,next_attempt=?,last_error='object_audit_transport_unavailable'
      WHERE lease_id=? AND account_id=? AND state='pending' AND claim_token=?`)
      .bind(failures,now+delay,lease,account,claim).run();
  } finally {clearTimeout(timer);abort.abort();}
  const saved=await readRow(env,account,lease);
  const active=await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first();
  if(!active) throw new ObjectDispatchError('account_not_active',401);
  return result(saved,applied && saved.job_id===checked?.jobId && saved.native_state===checked?.state && saved.state==='pending');
}
