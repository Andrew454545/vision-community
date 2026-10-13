// Optional operator migration. Preserve these fences and the budget on rollback.
export const HYBRID_CONTRACT = 'vision-search-hybrid-v1-20261013';
export const HYBRID_SCHEMA = [
  `CREATE TABLE IF NOT EXISTS search_hybrid_revision (slot INTEGER PRIMARY KEY CHECK(slot=1),contract TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS search_cloud_budget (slot INTEGER PRIMARY KEY CHECK(slot=1),document TEXT NOT NULL,operation_token TEXT NOT NULL)`,
  `CREATE TRIGGER IF NOT EXISTS search_cloud_budget_retained BEFORE DELETE ON search_cloud_budget
    BEGIN SELECT RAISE(ABORT,'cloud_budget_retained'); END`,
  `CREATE TRIGGER IF NOT EXISTS search_cloud_budget_reset BEFORE UPDATE ON search_cloud_budget
    WHEN NEW.document='uninitialized-v1' AND OLD.document!='uninitialized-v1'
    BEGIN SELECT RAISE(ABORT,'cloud_budget_reset'); END`,
  `CREATE TABLE IF NOT EXISTS search_hybrid_claims (
    job_id TEXT PRIMARY KEY REFERENCES search_jobs(id) ON DELETE CASCADE,
    claim_token TEXT NOT NULL UNIQUE,executor TEXT NOT NULL CHECK(executor IN ('cloud','local')),claimed_at INTEGER NOT NULL,
    cloud_token TEXT UNIQUE,cloud_deadline INTEGER,cloud_reserved_cents INTEGER,cloud_reserved_at INTEGER,
    stopped_at INTEGER,shutdown_sha256 TEXT)`,
  `CREATE TRIGGER IF NOT EXISTS search_hybrid_insert BEFORE INSERT ON search_hybrid_claims BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM search_jobs j JOIN accounts a ON a.id=j.account_id
      WHERE j.id=NEW.job_id AND j.attempts<3 AND a.deleted_at IS NULL
        AND (j.state='queued' OR (NEW.executor='local' AND j.state='claimed' AND j.claim_until<=NEW.claimed_at
          AND EXISTS (SELECT 1 FROM search_hybrid_claims h WHERE h.job_id=j.id AND h.executor='local'))))
      THEN RAISE(ABORT,'hybrid_claim_lost') END;
    SELECT CASE WHEN NEW.stopped_at IS NOT NULL OR NEW.shutdown_sha256 IS NOT NULL
      OR (NEW.executor='local' AND (NEW.cloud_token IS NOT NULL OR NEW.cloud_deadline IS NOT NULL OR NEW.cloud_reserved_cents IS NOT NULL OR NEW.cloud_reserved_at IS NOT NULL))
      OR NEW.claimed_at<0
      OR (NEW.executor='cloud' AND (NEW.cloud_token IS NOT NEW.claim_token OR NEW.cloud_deadline IS NULL
        OR NEW.cloud_reserved_at IS NOT NEW.claimed_at
        OR NEW.cloud_deadline<=NEW.claimed_at OR NEW.cloud_deadline>NEW.claimed_at+240
        OR NEW.cloud_reserved_cents IS NULL OR NEW.cloud_reserved_cents NOT BETWEEN 1 AND 300
        OR NOT EXISTS (SELECT 1 FROM search_jobs WHERE id=NEW.job_id AND attempts=0 AND expires_at>=NEW.cloud_deadline)
        OR NOT EXISTS (SELECT 1 FROM search_cloud_budget WHERE slot=1 AND operation_token=NEW.claim_token)))
      THEN RAISE(ABORT,'hybrid_claim_invalid') END;
  END`,
  `CREATE TRIGGER IF NOT EXISTS search_hybrid_replace BEFORE UPDATE ON search_hybrid_claims
    WHEN NEW.job_id IS NOT OLD.job_id OR NEW.claimed_at<OLD.claimed_at OR NEW.cloud_token IS NOT OLD.cloud_token
      OR NEW.cloud_deadline IS NOT OLD.cloud_deadline OR NEW.cloud_reserved_cents IS NOT OLD.cloud_reserved_cents OR NEW.cloud_reserved_at IS NOT OLD.cloud_reserved_at
      OR (OLD.stopped_at IS NOT NULL AND (NEW.stopped_at IS NOT OLD.stopped_at OR NEW.shutdown_sha256 IS NOT OLD.shutdown_sha256))
      OR ((NEW.stopped_at IS NULL) != (NEW.shutdown_sha256 IS NULL))
      OR (NEW.stopped_at IS NOT OLD.stopped_at AND OLD.cloud_token IS NULL)
      OR (NEW.claim_token IS NOT OLD.claim_token AND (NEW.executor!='local'
        OR (OLD.cloud_token IS NOT NULL AND OLD.stopped_at IS NULL)
        OR NOT EXISTS (SELECT 1 FROM search_jobs WHERE id=OLD.job_id AND (state='queued'
          OR (state='claimed' AND claim_token=OLD.claim_token AND claim_until<=NEW.claimed_at)))))
      OR (NEW.claim_token IS OLD.claim_token AND NEW.executor IS NOT OLD.executor)
    BEGIN SELECT RAISE(ABORT,'hybrid_claim_immutable'); END`,
  `CREATE TRIGGER IF NOT EXISTS search_hybrid_claim_guard BEFORE UPDATE ON search_jobs
    WHEN NEW.state='claimed' AND (NOT EXISTS (SELECT 1 FROM search_hybrid_claims h
      WHERE h.job_id=NEW.id AND h.claim_token=NEW.claim_token
        AND (h.executor='local' OR (h.stopped_at IS NULL AND NEW.claim_until<=h.cloud_deadline)))
      OR NEW.claim_until>NEW.expires_at)
    BEGIN SELECT RAISE(ABORT,'hybrid_claim_required'); END`,
  // This also works for offline SQLite imports with foreign_keys disabled.
  `CREATE TRIGGER IF NOT EXISTS search_hybrid_private_delete AFTER DELETE ON search_jobs
    BEGIN DELETE FROM search_hybrid_claims WHERE job_id=OLD.id; END`,
];

const normalize = sql => sql.replace(/IF NOT EXISTS/ig,'').replace(/[\s;]/g,'').toLowerCase();
const quote = v => "'" + v.replaceAll("'","''") + "'";
const stored = "lower(replace(replace(replace(replace(replace(replace(replace(sql,'IF NOT EXISTS',''),'if not exists',''),' ',''),char(10),''),char(13),''),char(9),''),';',''))";
const checks = HYBRID_SCHEMA.map(sql => {
  const [,kind,name] = sql.match(/^CREATE (TABLE|TRIGGER) IF NOT EXISTS (\w+)/);
  return `EXISTS (SELECT 1 FROM sqlite_master WHERE type=${quote(kind.toLowerCase())} AND name=${quote(name)} AND ${stored}=${quote(normalize(sql))})`;
}).join(' AND ');
export const HYBRID_CONTRACT_SQL = `INSERT INTO search_hybrid_revision
  SELECT 1,CASE WHEN (${checks}) AND EXISTS (SELECT 1 FROM search_queue_revision WHERE slot=1
    AND contract='vision-search-queue-v1-20261012') THEN '${HYBRID_CONTRACT}' ELSE NULL END
  ON CONFLICT(slot) DO UPDATE SET contract=CASE WHEN contract=excluded.contract THEN contract ELSE NULL END`;
