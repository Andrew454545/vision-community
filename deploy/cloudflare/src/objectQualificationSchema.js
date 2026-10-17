// Optional operator migration. No public request installs or repairs authority.
export const OBJECT_QUALIFICATION_CONTRACT='saved-object-qualification-v1-20261013';
export const OBJECT_QUALIFICATION_SCHEMA=[
  `CREATE TABLE IF NOT EXISTS object_qualification_revision (slot INTEGER PRIMARY KEY CHECK(slot=1),contract TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS object_qualification_controls (
    account_id TEXT NOT NULL REFERENCES accounts(id),authority_sha256 TEXT NOT NULL,profile_id TEXT NOT NULL,
    epoch INTEGER NOT NULL DEFAULT 0 CHECK(epoch>=0),PRIMARY KEY(account_id,authority_sha256,profile_id))`,
  `CREATE TABLE IF NOT EXISTS object_qualification_requests (
    id TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id),authority_sha256 TEXT NOT NULL,
    profile_id TEXT NOT NULL,artifact_sha256 TEXT NOT NULL,challenge TEXT NOT NULL UNIQUE,epoch INTEGER NOT NULL,
    created_at INTEGER NOT NULL,deadline_at INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'pending'
      CHECK(state IN ('pending','qualified','incompatible','cancelled')),
    claim_token TEXT,claim_until INTEGER NOT NULL DEFAULT 0,completed_at INTEGER,
    expires_at INTEGER,proof_sha256 TEXT,proof_json TEXT)`,
  `CREATE INDEX IF NOT EXISTS object_qualification_lookup ON object_qualification_requests(account_id,authority_sha256,profile_id,state,expires_at)`,
  `CREATE TABLE IF NOT EXISTS object_qualification_revocations (
    id TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id),authority_sha256 TEXT NOT NULL,
    profile_id TEXT NOT NULL,epoch INTEGER NOT NULL,created_at INTEGER NOT NULL)`,
  `CREATE TRIGGER IF NOT EXISTS object_qualification_controls_immutable BEFORE UPDATE ON object_qualification_controls
    WHEN NEW.account_id IS NOT OLD.account_id OR NEW.authority_sha256 IS NOT OLD.authority_sha256
      OR NEW.profile_id IS NOT OLD.profile_id OR NEW.epoch!=OLD.epoch+1
    BEGIN SELECT RAISE(ABORT,'object_qualification_control_immutable'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_qualification_controls_retained BEFORE DELETE ON object_qualification_controls
    BEGIN SELECT RAISE(ABORT,'object_qualification_control_retained'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_qualification_request_insert BEFORE INSERT ON object_qualification_requests
    WHEN NEW.state!='pending' OR NEW.completed_at IS NOT NULL OR NEW.expires_at IS NOT NULL
      OR NEW.proof_sha256 IS NOT NULL OR NEW.proof_json IS NOT NULL OR NEW.claim_token IS NOT NULL OR NEW.claim_until!=0
      OR NEW.deadline_at!=NEW.created_at+600
      OR NOT EXISTS (SELECT 1 FROM accounts a JOIN object_qualification_controls c ON c.account_id=a.id
        WHERE a.id=NEW.account_id AND a.deleted_at IS NULL AND c.authority_sha256=NEW.authority_sha256
          AND c.profile_id=NEW.profile_id AND c.epoch=NEW.epoch)
      OR (SELECT COUNT(*) FROM object_qualification_requests WHERE account_id=NEW.account_id
        AND state='pending' AND deadline_at>NEW.created_at)>=4
    BEGIN SELECT RAISE(ABORT,'object_qualification_request_unavailable'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_qualification_request_immutable BEFORE UPDATE ON object_qualification_requests
    WHEN NEW.id IS NOT OLD.id OR NEW.account_id IS NOT OLD.account_id OR NEW.authority_sha256 IS NOT OLD.authority_sha256
      OR NEW.profile_id IS NOT OLD.profile_id OR NEW.artifact_sha256 IS NOT OLD.artifact_sha256
      OR NEW.challenge IS NOT OLD.challenge OR NEW.epoch IS NOT OLD.epoch
      OR NEW.created_at IS NOT OLD.created_at OR NEW.deadline_at IS NOT OLD.deadline_at
      OR OLD.state!='pending'
    BEGIN SELECT RAISE(ABORT,'object_qualification_request_immutable'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_qualification_request_decision BEFORE UPDATE ON object_qualification_requests
    WHEN NEW.state IN ('qualified','incompatible') AND (OLD.claim_token IS NULL
      OR NEW.claim_token IS NOT NULL OR NEW.claim_until!=0
      OR NEW.completed_at IS NULL OR NEW.completed_at>=OLD.claim_until OR NEW.completed_at>=OLD.deadline_at
      OR NEW.proof_sha256 IS NULL OR NEW.proof_json IS NULL
      OR (NEW.state='qualified' AND (NEW.expires_at IS NULL OR NEW.expires_at<=NEW.completed_at))
      OR NOT EXISTS (SELECT 1 FROM accounts a JOIN object_qualification_controls c ON c.account_id=a.id
        WHERE a.id=NEW.account_id AND a.deleted_at IS NULL AND c.authority_sha256=NEW.authority_sha256
          AND c.profile_id=NEW.profile_id AND c.epoch=NEW.epoch))
    BEGIN SELECT RAISE(ABORT,'object_qualification_authority_lost'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_qualification_requests_retained BEFORE DELETE ON object_qualification_requests
    BEGIN SELECT RAISE(ABORT,'object_qualification_request_retained'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_qualification_revocations_immutable BEFORE UPDATE ON object_qualification_revocations
    BEGIN SELECT RAISE(ABORT,'object_qualification_revocation_immutable'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_qualification_revocations_retained BEFORE DELETE ON object_qualification_revocations
    BEGIN SELECT RAISE(ABORT,'object_qualification_revocation_retained'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_qualification_deleted AFTER UPDATE OF deleted_at ON accounts
    WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL
    BEGIN
      UPDATE object_qualification_requests SET state='cancelled',claim_token=NULL,claim_until=0
        WHERE account_id=NEW.id AND state='pending';
      UPDATE object_qualification_controls SET epoch=epoch+1 WHERE account_id=NEW.id;
    END`,
];
const normalized=sql=>sql.replace(/IF NOT EXISTS/ig,'').replace(/[\s;]/g,'').toLowerCase();
const quote=v=>"'"+v.replaceAll("'","''")+"'";
const stored="lower(replace(replace(replace(replace(replace(replace(replace(sql,'IF NOT EXISTS',''),'if not exists',''),' ',''),char(10),''),char(13),''),char(9),''),';',''))";
const checks=OBJECT_QUALIFICATION_SCHEMA.map(sql=>{
  const [,kind,name]=sql.match(/^CREATE (TABLE|INDEX|TRIGGER) IF NOT EXISTS (\w+)/);
  return `EXISTS (SELECT 1 FROM sqlite_master WHERE type=${quote(kind.toLowerCase())} AND name=${quote(name)}
    AND ${stored}=${quote(normalized(sql))})`;
}).join(' AND ');
export const OBJECT_QUALIFICATION_CONTRACT_SQL=`INSERT INTO object_qualification_revision
  SELECT 1,CASE WHEN (${checks}) AND (EXISTS (SELECT 1 FROM object_qualification_revision WHERE slot=1
    AND contract='${OBJECT_QUALIFICATION_CONTRACT}') OR (NOT EXISTS (SELECT 1 FROM object_qualification_requests)
    AND NOT EXISTS (SELECT 1 FROM object_qualification_controls) AND NOT EXISTS (SELECT 1 FROM object_qualification_revocations)))
    THEN '${OBJECT_QUALIFICATION_CONTRACT}' ELSE NULL END
  ON CONFLICT(slot) DO UPDATE SET contract=CASE WHEN contract=excluded.contract THEN contract ELSE NULL END`;
