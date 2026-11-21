// Optional prepared-pool allocation. No native job or account qualification is created.
export const OBJECT_WORK_CONTRACT='qualified-object-prepared-pool-v1-20261014';
export const OBJECT_WORK_SCHEMA=[
 `CREATE TABLE IF NOT EXISTS object_work_revision(slot INTEGER PRIMARY KEY CHECK(slot=1),contract TEXT NOT NULL)`,
 `CREATE TABLE IF NOT EXISTS object_work_pool(lease_id TEXT PRIMARY KEY,profile_id TEXT NOT NULL,policy_id TEXT NOT NULL,
   eligibility_sha256 TEXT NOT NULL,assignment_sha256 TEXT NOT NULL,source_sha256 TEXT NOT NULL,source_tsv TEXT NOT NULL,
   records_json TEXT NOT NULL,created_at INTEGER NOT NULL,valid_until INTEGER NOT NULL,
   state TEXT NOT NULL CHECK(state IN ('available','claimed','retired')))`,
 `CREATE TABLE IF NOT EXISTS object_work_requests(account_id TEXT NOT NULL REFERENCES accounts(id),request_key TEXT NOT NULL,
   lease_id TEXT NOT NULL UNIQUE REFERENCES leases(id),qualification_id TEXT NOT NULL REFERENCES object_qualification_requests(id),
   created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,requested_count INTEGER NOT NULL CHECK(requested_count BETWEEN 1 AND 4),
   pace TEXT NOT NULL CHECK(pace IN ('slow','medium','max')),
   state TEXT NOT NULL CHECK(state IN ('preparing','ready','cancelled')),proof_sha256 TEXT,
   PRIMARY KEY(account_id,request_key),FOREIGN KEY(lease_id) REFERENCES object_work_pool(lease_id))`,
 `CREATE INDEX IF NOT EXISTS object_work_available ON object_work_pool(profile_id,state,valid_until,lease_id)`,
 `CREATE TRIGGER IF NOT EXISTS object_work_pool_insert BEFORE INSERT ON object_work_pool
   WHEN NEW.state!='available' OR NEW.valid_until<=NEW.created_at OR NEW.valid_until>NEW.created_at+3600
     OR length(CAST(NEW.source_tsv AS BLOB)) NOT BETWEEN 1 AND 8192
     OR length(CAST(NEW.records_json AS BLOB)) NOT BETWEEN 1 AND 16384
     OR (SELECT COUNT(*) FROM object_work_pool)>=4096 OR (SELECT COUNT(*) FROM object_work_pool WHERE state='available')>=64
   BEGIN SELECT RAISE(ABORT,'object_work_pool_unavailable'); END`,
 `CREATE TRIGGER IF NOT EXISTS object_work_pool_immutable BEFORE UPDATE ON object_work_pool
   WHEN NEW.lease_id IS NOT OLD.lease_id OR NEW.profile_id IS NOT OLD.profile_id OR NEW.policy_id IS NOT OLD.policy_id
     OR NEW.eligibility_sha256 IS NOT OLD.eligibility_sha256 OR NEW.assignment_sha256 IS NOT OLD.assignment_sha256
     OR NEW.source_sha256 IS NOT OLD.source_sha256 OR NEW.source_tsv IS NOT OLD.source_tsv OR NEW.records_json IS NOT OLD.records_json
     OR NEW.created_at IS NOT OLD.created_at OR NEW.valid_until IS NOT OLD.valid_until
     OR OLD.state!='available' OR NEW.state NOT IN ('claimed','retired')
   BEGIN SELECT RAISE(ABORT,'object_work_pool_immutable'); END`,
 `CREATE TRIGGER IF NOT EXISTS object_work_pool_retained BEFORE DELETE ON object_work_pool
   BEGIN SELECT RAISE(ABORT,'object_work_pool_retained'); END`,
 `CREATE TRIGGER IF NOT EXISTS object_work_request_insert BEFORE INSERT ON object_work_requests
   WHEN NEW.state!='preparing' OR NEW.proof_sha256 IS NOT NULL
     OR NOT EXISTS (SELECT 1 FROM object_work_pool p JOIN leases l ON l.id=p.lease_id JOIN accounts a ON a.id=l.account_id
       WHERE p.lease_id=NEW.lease_id AND p.state='available' AND p.valid_until>=NEW.expires_at
         AND a.id=NEW.account_id AND a.deleted_at IS NULL AND l.state='active' AND l.lane='object' AND l.expires_at=NEW.expires_at)
   BEGIN SELECT RAISE(ABORT,'object_work_request_unavailable'); END`,
 `CREATE TRIGGER IF NOT EXISTS object_work_request_immutable BEFORE UPDATE ON object_work_requests
   WHEN NEW.account_id IS NOT OLD.account_id OR NEW.request_key IS NOT OLD.request_key OR NEW.lease_id IS NOT OLD.lease_id
     OR NEW.qualification_id IS NOT OLD.qualification_id OR NEW.created_at IS NOT OLD.created_at
     OR NEW.expires_at IS NOT OLD.expires_at OR NEW.requested_count IS NOT OLD.requested_count OR NEW.pace IS NOT OLD.pace
     OR OLD.state='cancelled' OR (OLD.state='ready' AND NEW.state!='cancelled')
     OR (OLD.state='preparing' AND NEW.state NOT IN ('ready','cancelled'))
     OR (NEW.state='ready' AND (NEW.proof_sha256 IS NULL OR length(NEW.proof_sha256)!=64))
     OR (NEW.state='cancelled' AND NEW.proof_sha256 IS NOT OLD.proof_sha256)
   BEGIN SELECT RAISE(ABORT,'object_work_request_immutable'); END`,
 `CREATE TRIGGER IF NOT EXISTS object_work_request_retained BEFORE DELETE ON object_work_requests
   BEGIN SELECT RAISE(ABORT,'object_work_request_retained'); END`,
 `CREATE TRIGGER IF NOT EXISTS object_work_expired AFTER UPDATE OF state ON leases WHEN NEW.state='expired' AND NEW.lane='object'
   AND EXISTS (SELECT 1 FROM object_work_requests WHERE lease_id=NEW.id)
   BEGIN UPDATE object_work_requests SET state='cancelled' WHERE lease_id=NEW.id AND state!='cancelled';
     UPDATE locations SET state='pending',queue_state='pending',active_lease=NULL,lease_until=NULL
       WHERE active_lease=NEW.id AND state!='published'; END`,
 `CREATE TRIGGER IF NOT EXISTS object_work_deleted AFTER UPDATE OF deleted_at ON accounts WHEN NEW.deleted_at IS NOT NULL
   BEGIN UPDATE object_work_requests SET state='cancelled' WHERE account_id=NEW.id AND state!='cancelled'
       AND lease_id IN (SELECT id FROM leases WHERE state='active');
     UPDATE leases SET state='expired' WHERE account_id=NEW.id AND state='active' AND lane='object'; END`,
];
const normal=s=>s.replace(/IF NOT EXISTS/ig,'').replace(/[\s;]/g,'').toLowerCase();
export async function checkObjectWorkSchema(db) {
 const rows=(await db.prepare("SELECT type,name,sql FROM sqlite_master WHERE name GLOB 'object_work_*' ORDER BY name").all()).results;
 const expected=OBJECT_WORK_SCHEMA.map(sql=>({type:sql.match(/^CREATE (\w+)/)[1].toLowerCase(),
   name:sql.match(/IF NOT EXISTS (\w+)/)[1],sql:normal(sql)})).sort((a,b)=>a.name<b.name?-1:1);
 if(JSON.stringify(rows.map(r=>({...r,sql:normal(r.sql)})))!==JSON.stringify(expected))throw Error('object_work_schema_mismatch');
}
export async function prepareObjectWorkPool(db) {
 await db.batch(OBJECT_WORK_SCHEMA.map(s=>db.prepare(s)));
 await checkObjectWorkSchema(db);
 const old=await db.prepare('SELECT contract FROM object_work_revision WHERE slot=1').first();
 if(old?.contract===OBJECT_WORK_CONTRACT)return;
 if(old||(await db.prepare('SELECT COUNT(*) n FROM object_work_pool').first()).n
   ||(await db.prepare('SELECT COUNT(*) n FROM object_work_requests').first()).n)throw Error('object_work_recovery_required');
 await db.prepare('INSERT INTO object_work_revision VALUES (1,?)').bind(OBJECT_WORK_CONTRACT).run();
}
