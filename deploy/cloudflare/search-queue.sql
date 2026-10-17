-- OPTIONAL operator migration. Install before enabling SEARCH_DELIVERY=queued-v1.
-- Never run DDL from a request. Keep this table and its guards during rollback.
CREATE TABLE search_jobs (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  idempotency_key TEXT NOT NULL,
  query_digest TEXT NOT NULL,
  query_json TEXT,
  lane TEXT NOT NULL CHECK(lane IN ('scene','object')),
  binding_json TEXT NOT NULL,
  cost_units INTEGER NOT NULL CHECK(cost_units > 0),
  state TEXT NOT NULL CHECK(state IN ('queued','claimed','settled','failed','cancelled','expired')),
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL CHECK(expires_at > created_at),
  claim_token TEXT,
  claim_until INTEGER,
  attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
  completion_nonce TEXT,
  error_code TEXT,
  UNIQUE(account_id,idempotency_key)
);
CREATE INDEX search_jobs_owner ON search_jobs(account_id,state);
CREATE INDEX search_jobs_deadline ON search_jobs(state,expires_at);
CREATE INDEX search_jobs_claim ON search_jobs(state,claim_until,created_at);

CREATE TRIGGER search_jobs_reserve BEFORE INSERT ON search_jobs BEGIN
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM accounts WHERE id=NEW.account_id AND deleted_at IS NULL)
    THEN RAISE(ABORT,'account_not_active') END;
  SELECT CASE WHEN EXISTS (SELECT 1 FROM searches WHERE account_id=NEW.account_id AND idempotency_key=NEW.idempotency_key)
    THEN RAISE(ABORT,'search_already_paid') END;
  SELECT CASE WHEN NEW.state!='queued' OR NEW.query_json IS NULL
    OR length(CAST(NEW.query_json AS BLOB))>65536 OR NEW.attempts!=0
    OR NEW.claim_token IS NOT NULL OR NEW.completion_nonce IS NOT NULL
    THEN RAISE(ABORT,'invalid_search_job') END;
  SELECT CASE WHEN (SELECT COUNT(*) FROM search_jobs)>=512
    OR (SELECT COUNT(*) FROM search_jobs WHERE state IN ('queued','claimed'))>=128
    OR (SELECT COUNT(*) FROM search_jobs WHERE account_id=NEW.account_id AND state IN ('queued','claimed'))>=3
    THEN RAISE(ABORT,'search_queue_full') END;
  SELECT CASE WHEN (SELECT units FROM accounts WHERE id=NEW.account_id) < NEW.cost_units
    + COALESCE((SELECT SUM(cost_units) FROM search_jobs WHERE account_id=NEW.account_id AND state IN ('queued','claimed')),0)
    THEN RAISE(ABORT,'search_credit_reserved') END;
END;

-- Also protects old synchronous writers if delivery mode is rolled back.
CREATE TRIGGER search_jobs_credit_guard BEFORE UPDATE OF units ON accounts
WHEN NEW.deleted_at IS NULL AND NEW.units < COALESCE((SELECT SUM(cost_units) FROM search_jobs
  WHERE account_id=OLD.id AND state IN ('queued','claimed')),0)
BEGIN SELECT RAISE(ABORT,'search_credit_reserved'); END;

CREATE TRIGGER search_jobs_result_guard BEFORE INSERT ON searches
WHEN EXISTS(SELECT 1 FROM search_jobs WHERE account_id=NEW.account_id
  AND idempotency_key=NEW.idempotency_key AND state!='settled')
BEGIN SELECT RAISE(ABORT,'search_credit_reserved'); END;

CREATE TRIGGER search_jobs_identity BEFORE UPDATE ON search_jobs
WHEN NEW.id IS NOT OLD.id OR NEW.account_id IS NOT OLD.account_id
  OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.query_digest IS NOT OLD.query_digest
  OR NEW.binding_json IS NOT OLD.binding_json OR NEW.cost_units IS NOT OLD.cost_units
  OR NEW.lane IS NOT OLD.lane
  OR NEW.created_at IS NOT OLD.created_at OR NEW.expires_at IS NOT OLD.expires_at
  OR (NEW.query_json IS NOT OLD.query_json AND NEW.query_json IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'search_job_immutable'); END;

-- Deletion wins even against a claimed job or a completion already in flight.
CREATE TRIGGER search_jobs_delete_private AFTER UPDATE OF deleted_at ON accounts
WHEN NEW.deleted_at IS NOT NULL
BEGIN DELETE FROM search_jobs WHERE account_id=NEW.id; END;

CREATE TABLE search_queue_revision (
  slot INTEGER PRIMARY KEY CHECK(slot=1),
  revision INTEGER NOT NULL CHECK(revision=1),
  contract TEXT NOT NULL CHECK(contract='vision-search-queue-v1-20261012')
);
INSERT INTO search_queue_revision VALUES(1,1,'vision-search-queue-v1-20261012');
