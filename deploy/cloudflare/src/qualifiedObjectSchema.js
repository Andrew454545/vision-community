// Optional operator migration. Separate from native-audited history/approval.
export const QUALIFIED_OBJECT_CONTRACT='qualified-object-publication-v1-20261014';
const controls=`EXISTS (SELECT 1 FROM qualified_object_policy p JOIN object_qualification_requests q
  ON q.authority_sha256=p.qualification_authority_sha256 JOIN object_qualification_controls k
  ON k.account_id=q.account_id AND k.authority_sha256=q.authority_sha256 AND k.profile_id=q.profile_id
  WHERE p.slot=1 AND p.eligibility_sha256=NEW.eligibility_policy_sha256 AND q.id=NEW.qualification_id
    AND q.account_id=NEW.account_id AND q.profile_id=NEW.profile_id AND q.state='qualified'
    AND q.epoch=k.epoch AND q.expires_at>max(NEW.created_at,unixepoch()))`;
export const QUALIFIED_OBJECT_SCHEMA=[
  `CREATE TABLE IF NOT EXISTS qualified_object_revision (slot INTEGER PRIMARY KEY CHECK(slot=1),contract TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS qualified_object_policy (slot INTEGER PRIMARY KEY CHECK(slot=1),
    generation INTEGER NOT NULL CHECK(generation>=0),eligibility_sha256 TEXT NOT NULL,qualification_authority_sha256 TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS qualified_object_candidates (
    lease_id TEXT PRIMARY KEY REFERENCES leases(id),account_id TEXT NOT NULL REFERENCES accounts(id),
    qualification_id TEXT NOT NULL REFERENCES object_qualification_requests(id),eligibility_policy_sha256 TEXT NOT NULL,
    profile_id TEXT NOT NULL,policy_id TEXT NOT NULL,assignment_sha256 TEXT NOT NULL,source_sha256 TEXT NOT NULL,
    submission_sha256 TEXT NOT NULL,artifact_key TEXT NOT NULL UNIQUE,payload_bytes INTEGER NOT NULL CHECK(payload_bytes BETWEEN 1 AND 4193280),
    location_count INTEGER NOT NULL CHECK(location_count BETWEEN 1 AND 4),created_at INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','published','cancelled')))`,
  `CREATE INDEX IF NOT EXISTS qualified_object_owner ON qualified_object_candidates(account_id,state)`,
  `CREATE TABLE IF NOT EXISTS qualified_object_acceptances (
    lease_id TEXT PRIMARY KEY REFERENCES qualified_object_candidates(lease_id),account_id TEXT NOT NULL REFERENCES accounts(id),
    operation_token TEXT NOT NULL UNIQUE,location_count INTEGER NOT NULL CHECK(location_count BETWEEN 1 AND 4),
    units INTEGER NOT NULL CHECK(units=location_count*10),accepted_at INTEGER NOT NULL,
    qualification_id TEXT NOT NULL REFERENCES object_qualification_requests(id),qualification_authority_sha256 TEXT NOT NULL,
    eligibility_policy_sha256 TEXT NOT NULL,qualification_policy_sha256 TEXT NOT NULL,
    protected_policy_sha256 TEXT NOT NULL,quality_sha256 TEXT NOT NULL,protected_sha256 TEXT NOT NULL,origin_sha256 TEXT NOT NULL,
    assignment_sha256 TEXT NOT NULL,source_sha256 TEXT NOT NULL,submission_sha256 TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,protection_sha256 TEXT NOT NULL,artifacts_sha256 TEXT NOT NULL)`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_policy_retained BEFORE DELETE ON qualified_object_policy
    BEGIN SELECT RAISE(ABORT,'qualified_object_policy_retained'); END`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_policy_monotonic BEFORE UPDATE ON qualified_object_policy
    WHEN NEW.slot IS NOT OLD.slot OR NEW.generation!=OLD.generation+1
    BEGIN SELECT RAISE(ABORT,'qualified_object_policy_rotation_required'); END`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_candidate_insert BEFORE INSERT ON qualified_object_candidates
    WHEN NEW.state!='pending' OR EXISTS (SELECT 1 FROM object_audit_candidates WHERE lease_id=NEW.lease_id)
      OR EXISTS (SELECT 1 FROM ledger WHERE reference='lease:'||NEW.lease_id)
      OR (SELECT COUNT(*) FROM qualified_object_candidates WHERE state='pending')>=8
      OR NOT (${controls}) OR NOT EXISTS (SELECT 1 FROM accounts a JOIN leases l ON l.account_id=a.id
        WHERE a.id=NEW.account_id AND a.deleted_at IS NULL AND l.id=NEW.lease_id AND l.lane='object'
          AND l.state='active' AND l.expires_at>max(NEW.created_at,unixepoch()))
    BEGIN SELECT RAISE(ABORT,'qualified_object_candidate_unavailable'); END`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_no_audit_mix BEFORE INSERT ON object_audit_candidates
    WHEN EXISTS (SELECT 1 FROM qualified_object_candidates WHERE lease_id=NEW.lease_id)
    BEGIN SELECT RAISE(ABORT,'object_admission_mode_conflict'); END`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_candidate_immutable BEFORE UPDATE ON qualified_object_candidates
    WHEN NEW.lease_id IS NOT OLD.lease_id OR NEW.account_id IS NOT OLD.account_id
      OR NEW.qualification_id IS NOT OLD.qualification_id OR NEW.eligibility_policy_sha256 IS NOT OLD.eligibility_policy_sha256
      OR NEW.profile_id IS NOT OLD.profile_id OR NEW.policy_id IS NOT OLD.policy_id
      OR NEW.assignment_sha256 IS NOT OLD.assignment_sha256 OR NEW.source_sha256 IS NOT OLD.source_sha256
      OR NEW.submission_sha256 IS NOT OLD.submission_sha256 OR NEW.artifact_key IS NOT OLD.artifact_key
      OR NEW.payload_bytes IS NOT OLD.payload_bytes OR NEW.location_count IS NOT OLD.location_count OR NEW.created_at IS NOT OLD.created_at
      OR OLD.state!='pending' OR NEW.state NOT IN ('published','cancelled')
    BEGIN SELECT RAISE(ABORT,'qualified_object_candidate_immutable'); END`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_candidate_publish BEFORE UPDATE OF state ON qualified_object_candidates
    WHEN NEW.state='published' AND NOT EXISTS (SELECT 1 FROM qualified_object_acceptances WHERE lease_id=NEW.lease_id)
    BEGIN SELECT RAISE(ABORT,'qualified_object_acceptance_required'); END`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_candidate_retained BEFORE DELETE ON qualified_object_candidates
    BEGIN SELECT RAISE(ABORT,'qualified_object_candidate_retained'); END`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_acceptance_immutable BEFORE UPDATE ON qualified_object_acceptances
    BEGIN SELECT RAISE(ABORT,'qualified_object_acceptance_immutable'); END`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_acceptance_retained BEFORE DELETE ON qualified_object_acceptances
    BEGIN SELECT RAISE(ABORT,'qualified_object_acceptance_retained'); END`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_acceptance_active BEFORE INSERT ON qualified_object_acceptances
    WHEN NOT EXISTS (SELECT 1 FROM qualified_object_candidates c JOIN accounts a ON a.id=c.account_id
      JOIN leases l ON l.id=c.lease_id AND l.account_id=c.account_id JOIN object_qualification_requests q ON q.id=c.qualification_id
      JOIN object_qualification_controls k ON k.account_id=q.account_id AND k.authority_sha256=q.authority_sha256 AND k.profile_id=q.profile_id
      JOIN qualified_object_policy p ON p.slot=1 AND p.eligibility_sha256=c.eligibility_policy_sha256
      WHERE c.lease_id=NEW.lease_id AND c.account_id=NEW.account_id AND c.state='pending' AND a.deleted_at IS NULL
        AND l.state='submitted' AND l.expires_at>max(NEW.accepted_at,unixepoch())
        AND q.id=NEW.qualification_id AND q.authority_sha256=NEW.qualification_authority_sha256
        AND p.qualification_authority_sha256=q.authority_sha256 AND q.epoch=k.epoch AND q.state='qualified'
        AND q.expires_at>max(NEW.accepted_at,unixepoch()))
    BEGIN SELECT RAISE(ABORT,'qualified_object_authority_lost'); END`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_deleted AFTER UPDATE OF deleted_at ON accounts
    WHEN NEW.deleted_at IS NOT NULL
    BEGIN UPDATE qualified_object_candidates SET state='cancelled' WHERE account_id=NEW.id AND state='pending'; END`,
  `CREATE TRIGGER IF NOT EXISTS qualified_object_expired AFTER UPDATE OF state ON leases
    WHEN NEW.state='expired'
    BEGIN UPDATE qualified_object_candidates SET state='cancelled' WHERE lease_id=NEW.id AND state='pending';
      UPDATE locations SET state='pending',queue_state='pending',active_lease=NULL,lease_until=NULL
        WHERE active_lease=NEW.id AND state!='published' AND queue_state='quarantined'; END`,
];
const normalized=s=>s.replace(/IF NOT EXISTS/ig,'').replace(/[\s;]/g,'').toLowerCase();
const quote=s=>"'"+s.replaceAll("'","''")+"'";
const stored="lower(replace(replace(replace(replace(replace(replace(replace(sql,'IF NOT EXISTS',''),'if not exists',''),' ',''),char(10),''),char(13),''),char(9),''),';',''))";
const checks=QUALIFIED_OBJECT_SCHEMA.map(s=>{const[,kind,name]=s.match(/^CREATE (TABLE|INDEX|TRIGGER) IF NOT EXISTS (\w+)/);
  return `EXISTS (SELECT 1 FROM sqlite_master WHERE type=${quote(kind.toLowerCase())} AND name=${quote(name)} AND ${stored}=${quote(normalized(s))})`;
}).join(' AND ');
export const QUALIFIED_OBJECT_CONTRACT_SQL=`INSERT INTO qualified_object_revision SELECT 1,
  CASE WHEN (${checks}) AND EXISTS (SELECT 1 FROM object_qualification_revision WHERE slot=1 AND contract='saved-object-qualification-v1-20261013')
    AND EXISTS (SELECT 1 FROM object_dispatch_revision WHERE slot=1 AND contract='private-object-dispatch-v2-20261012')
    AND (EXISTS (SELECT 1 FROM qualified_object_revision WHERE slot=1 AND contract='${QUALIFIED_OBJECT_CONTRACT}')
      OR (NOT EXISTS (SELECT 1 FROM qualified_object_candidates) AND NOT EXISTS (SELECT 1 FROM qualified_object_acceptances)
        AND NOT EXISTS (SELECT 1 FROM qualified_object_policy))) THEN '${QUALIFIED_OBJECT_CONTRACT}' ELSE NULL END
  ON CONFLICT(slot) DO UPDATE SET contract=CASE WHEN contract=excluded.contract THEN contract ELSE NULL END`;
