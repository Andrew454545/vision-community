// Offline operator tool. Never contacts Cloudflare or opens a live database.
import { createHash, randomBytes } from "node:crypto";
import { copyFileSync, constants, existsSync, openSync, closeSync, readSync, writeFileSync,
  fsyncSync, mkdirSync, statSync } from "node:fs";
import { resolve, join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";
import { PRIVACY_FENCES, PRIVACY_TABLES } from "../src/accountPrivacy.js";

export const RESOURCE_PROFILES = Object.freeze({
  production: Object.freeze({ accountId: "272760294910ef0b246980278aeb36e2",
    databaseId: "ed4705fa-1190-41fa-86a0-02d755db1b2a", bucket: "vision-community" }),
  staging: Object.freeze({ accountId: "272760294910ef0b246980278aeb36e2",
    databaseId: "17043cb7-5dab-4a6f-84ca-19ae1c14cc05", bucket: "vision-community-staging" }),
});
export const RESOURCE = RESOURCE_PROFILES.production;
export const DELETION_EXPORT_SQL = `SELECT a.id AS accountId,r.request_key AS requestKey,
  a.deleted_at AS deletedAt,r.deleted_at AS receiptDeletedAt,r.units_forfeited AS unitsForfeited
  FROM accounts a LEFT JOIN account_deletion_receipts r ON r.account_id=a.id
  WHERE a.deleted_at IS NOT NULL ORDER BY a.id`;
const HEX = /^[0-9a-f]{64}$/, ACCOUNT = /^[0-9a-f]{32}$/;
const MAX_LEDGER_BYTES = 4 * 1024 * 1024, MAX_BACKUP_BYTES = 512 * 1024 * 1024;
const REQUIRED = {
  accounts: ["id", "token_hash", "recovery_hash", "units"],
  ledger: ["account_id", "units", "reason", "reference"], searches: ["account_id"],
  leases: ["id", "account_id", "state"], lease_items: ["lease_id", "location_id"],
  locations: ["id", "state", "queue_state", "active_lease", "lease_until"],
  scene_qualifications: ["account_id", "expires_at"],
  scene_candidates: ["lease_id", "account_id", "state", "artifact_key", "records_json"],
  published_index: ["four_view_key"],
  pose_catalog: ["assignee", "assigned_at"],
};

export class RestoreError extends Error {}
function integer(value) { return Number.isSafeInteger(value) && value >= 0; }
function resourceFor(environment) {
  if (!["production", "staging"].includes(environment)) throw new RestoreError("invalid_restore_environment");
  return RESOURCE_PROFILES[environment];
}
function resourceMatches(value, resource) {
  return value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 3
    && Object.entries(resource).every(([key, expected]) => value[key] === expected);
}
function encoded(value) { return Buffer.from(JSON.stringify(value) + "\n"); }
function checksum(raw) { return createHash("sha256").update(raw).digest("hex"); }
function syncFile(path) { const fd = openSync(path, "r+"); try { fsyncSync(fd); } finally { closeSync(fd); } }
function writeNew(path, raw) { writeFileSync(path, raw, { flag: "wx", mode: 0o600 }); syncFile(path); }
function fileChecksum(path, maximum) {
  if (!statSync(path).isFile() || statSync(path).size > maximum) throw new RestoreError("input_too_large");
  const fd = openSync(path, "r"), hash = createHash("sha256"), buffer = Buffer.alloc(1024 * 1024);
  let total = 0;
  try {
    for (let size; (size = readSync(fd, buffer, 0, buffer.length, null)) > 0;) {
      total += size;
      if (total > maximum) throw new RestoreError("input_too_large");
      hash.update(buffer.subarray(0, size));
    }
  } finally { closeSync(fd); }
  return hash.digest("hex");
}
function readLedger(path, pin) {
  if (!HEX.test(pin || "")) throw new RestoreError("invalid_checksum_pin");
  const fd = openSync(path, "r"), buffer = Buffer.alloc(MAX_LEDGER_BYTES + 1);
  let length = 0;
  try {
    while (length < buffer.length) {
      const count = readSync(fd, buffer, length, buffer.length - length, null);
      if (!count) break;
      length += count;
    }
  } finally { closeSync(fd); }
  if (length > MAX_LEDGER_BYTES) throw new RestoreError("input_too_large");
  const raw = buffer.subarray(0, length);
  if (checksum(raw) !== pin) throw new RestoreError("input_checksum_mismatch");
  return JSON.parse(raw.toString("utf8"));
}

export function validateLedger(document, notBefore, now = Math.floor(Date.now() / 1000), environment = "production") {
  const resource = resourceFor(environment);
  if (!integer(notBefore) || notBefore > now || !integer(now) || !document || document.version !== 1
      || document.scope !== "vision-community-account-deletions"
      || !resourceMatches(document.resource, resource)
      || !integer(document.exportedAt) || document.exportedAt < notBefore || document.exportedAt > now
      || !Array.isArray(document.receipts) || document.receipts.length > 10000) {
    throw new RestoreError("invalid_or_stale_deletion_ledger");
  }
  const accounts = new Set(), keys = new Set();
  for (const row of document.receipts) {
    if (!row || typeof row.accountId !== "string" || !ACCOUNT.test(row.accountId)
        || typeof row.requestKey !== "string" || !HEX.test(row.requestKey)
        || !integer(row.deletedAt) || row.deletedAt > document.exportedAt || !integer(row.unitsForfeited)
        || accounts.has(row.accountId) || keys.has(row.requestKey)) throw new RestoreError("invalid_deletion_receipt");
    accounts.add(row.accountId); keys.add(row.requestKey);
  }
  return document;
}

function checkSchema(sql) {
  for (const [table, required] of Object.entries(REQUIRED)) {
    const columns = new Set(sql.prepare(`PRAGMA table_info(${table})`).all().map(row => row.name));
    if (required.some(name => !columns.has(name))) throw new RestoreError("unsupported_restore_schema");
  }
}
function installFences(sql) {
  if (!sql.prepare("PRAGMA table_info(accounts)").all().some(row => row.name === "deleted_at")) {
    sql.exec("ALTER TABLE accounts ADD COLUMN deleted_at INTEGER");
  }
  for (const statement of PRIVACY_TABLES) sql.exec(statement);
  const normalized = value => value.replace(/IF NOT EXISTS/ig, "").replace(/\s+/g, "").replace(/;$/, "").toLowerCase();
  for (const statement of PRIVACY_FENCES) {
    const name = statement.match(/CREATE TRIGGER IF NOT EXISTS (\w+)/)[1];
    const existing = sql.prepare("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?").get(name);
    if (existing && normalized(existing.sql) !== normalized(statement)) throw new RestoreError("privacy_fence_definition_changed");
    sql.exec(statement);
  }
}

// Export from a closed, current local rehearsal/copy. A live operator export
// must provide the same complete envelope after stopping all account writes.
export function exportDeletionLedger(sql, exportedAt = Math.floor(Date.now() / 1000), environment = "production") {
  const resource = resourceFor(environment);
  sql.exec("BEGIN");
  try {
    const rows = sql.prepare(DELETION_EXPORT_SQL).all();
    const count = Number(sql.prepare("SELECT COUNT(*) AS n FROM account_deletion_receipts").get().n);
    if (count !== rows.length || rows.some(row => row.receiptDeletedAt !== row.deletedAt)) {
      throw new RestoreError("incomplete_deletion_receipts");
    }
    const document = { version: 1, scope: "vision-community-account-deletions", resource, exportedAt,
      receipts: rows.map(({ receiptDeletedAt, ...row }) => row) };
    validateLedger(document, exportedAt, exportedAt, environment);
    sql.exec("COMMIT");
    return document;
  } catch (error) { sql.exec("ROLLBACK"); throw error; }
}

export function applyDeletionLedger(sql, ledger, notBefore, now = Math.floor(Date.now() / 1000), environment = "production") {
  validateLedger(ledger, notBefore, now, environment);
  checkSchema(sql);
  sql.exec("PRAGMA foreign_keys=ON; PRAGMA secure_delete=ON; BEGIN IMMEDIATE;");
  try {
    installFences(sql);
    const wanted = new Map(ledger.receipts.map(row => [row.accountId, row]));
    for (const row of sql.prepare("SELECT id,deleted_at FROM accounts WHERE deleted_at IS NOT NULL").all()) {
      if (wanted.get(row.id)?.deletedAt !== row.deleted_at) throw new RestoreError("deletion_history_missing_or_changed");
    }
    for (const old of sql.prepare("SELECT * FROM account_deletion_receipts").all()) {
      const row = wanted.get(old.account_id);
      if (!row || row.requestKey !== old.request_key || row.deletedAt !== old.deleted_at
          || row.unitsForfeited !== old.units_forfeited) throw new RestoreError("deletion_history_missing_or_changed");
    }
    let closedUnits = 0;
    for (const row of ledger.receipts) {
      const id = row.accountId;
      let account = sql.prepare("SELECT * FROM accounts WHERE id=?").get(id);
      if (!account) {
        sql.prepare("INSERT INTO accounts (id,token_hash,recovery_hash,units,deleted_at) VALUES (?,?,NULL,0,?)")
          .run(id, randomBytes(32).toString("hex"), row.deletedAt);
        account = sql.prepare("SELECT * FROM accounts WHERE id=?").get(id);
      }
      if (!integer(account.units) || (account.deleted_at !== null && (account.units !== 0 || account.recovery_hash !== null))) {
        throw new RestoreError("invalid_restored_account_state");
      }
      sql.prepare(`INSERT INTO account_deletion_receipts VALUES (?,?,?,?) ON CONFLICT(account_id) DO NOTHING`)
        .run(id, row.requestKey, row.deletedAt, row.unitsForfeited);
      if (account.units > 0) {
        sql.prepare("INSERT INTO ledger (account_id,units,reason,reference) VALUES (?,?,'account_restore_deleted',?)")
          .run(id, -account.units, `account-restore-delete:${id}`);
        closedUnits += account.units;
        if (!Number.isSafeInteger(closedUnits)) throw new RestoreError("restore_accounting_overflow");
      }
      if (sql.prepare(`SELECT 1 FROM scene_candidates c JOIN account_cleanup q ON q.artifact_key=c.artifact_key
          WHERE c.account_id=? AND c.state!='published' AND q.account_id!=c.account_id LIMIT 1`).get(id)) {
        throw new RestoreError("restore_cleanup_owner_conflict");
      }
      if (sql.prepare(`SELECT 1 FROM account_artifact_writes w JOIN account_cleanup q ON q.artifact_key=w.artifact_key
          WHERE w.account_id=? AND q.account_id!=w.account_id LIMIT 1`).get(id)) {
        throw new RestoreError("restore_cleanup_owner_conflict");
      }
      sql.prepare(`INSERT INTO account_cleanup (artifact_key,account_id,created_at,state)
        SELECT artifact_key,account_id,?,'pending' FROM account_artifact_writes w WHERE account_id=?
          AND NOT EXISTS (SELECT 1 FROM published_index i WHERE i.four_view_key=w.artifact_key)
        ON CONFLICT(artifact_key) DO UPDATE SET state='pending' WHERE account_cleanup.account_id=excluded.account_id`)
        .run(now, id);
      sql.prepare(`INSERT INTO account_cleanup (artifact_key,account_id,created_at,state)
        SELECT artifact_key,account_id,?,'pending' FROM scene_candidates WHERE account_id=? AND state!='published'
        ON CONFLICT(artifact_key) DO UPDATE SET state='pending' WHERE account_cleanup.account_id=excluded.account_id`)
        .run(now, id);
      if (account.deleted_at === null) {
        sql.prepare("UPDATE accounts SET deleted_at=?,units=0,recovery_hash=NULL,token_hash=? WHERE id=?")
          .run(row.deletedAt, randomBytes(32).toString("hex"), id);
      }
      sql.prepare("DELETE FROM searches WHERE account_id=?").run(id);
      sql.prepare("UPDATE scene_qualifications SET expires_at=0 WHERE account_id=?").run(id);
      sql.prepare(`UPDATE locations SET state='pending',queue_state='pending',active_lease=NULL,lease_until=NULL
        WHERE state!='published' AND (active_lease IN (SELECT id FROM leases WHERE account_id=?)
          OR (queue_state='quarantined' AND active_lease IS NULL AND id IN
            (SELECT i.location_id FROM lease_items i JOIN scene_candidates c ON c.lease_id=i.lease_id
              WHERE c.account_id=? AND c.state='pending')))`)
        .run(id, id);
      sql.prepare("UPDATE scene_candidates SET state='rejected',records_json='[]' WHERE account_id=? AND state!='published'").run(id);
      sql.prepare("UPDATE leases SET state='expired' WHERE account_id=? AND state='active'").run(id);
      sql.prepare("UPDATE pose_catalog SET assignee=NULL,assigned_at=NULL WHERE assignee=?").run(id);
    }
    if (sql.prepare("PRAGMA foreign_key_check").all().length) throw new RestoreError("restore_foreign_key_failure");
    sql.exec("COMMIT");
    return { deletedAccounts: ledger.receipts.length, closedRestoredUnits: closedUnits };
  } catch (error) { sql.exec("ROLLBACK"); throw error; }
}

export function preparePrivateRestore({ backup, backupSha256, deletions, deletionsSha256, notBefore, out,
  now = Math.floor(Date.now() / 1000), environment = "production" }) {
  const destination = resolve(out);
  mkdirSync(destination, { recursive: false, mode: 0o700 }); // Refuse overwrites, including completed outputs.
  let sql;
  try {
    const resource = resourceFor(environment);
    if (!HEX.test(backupSha256 || "")) throw new RestoreError("invalid_checksum_pin");
    const ledger = readLedger(deletions, deletionsSha256);
    validateLedger(ledger, notBefore, now, environment);
    // A raw backup is supported only when it is closed and self-contained.
    if (["-wal", "-shm", "-journal"].some(suffix => existsSync(backup + suffix))) {
      throw new RestoreError("backup_not_closed");
    }
    if (!statSync(backup).isFile() || statSync(backup).size > MAX_BACKUP_BYTES) throw new RestoreError("input_too_large");
    const database = join(destination, "restored.sqlite");
    copyFileSync(backup, database, constants.COPYFILE_EXCL);
    if (fileChecksum(database, MAX_BACKUP_BYTES) !== backupSha256) throw new RestoreError("input_checksum_mismatch");
    sql = new DatabaseSync(database, { allowExtension: false });
    sql.exec("PRAGMA trusted_schema=OFF");
    if (sql.prepare("PRAGMA integrity_check").all().some(row => row.integrity_check !== "ok")) {
      throw new RestoreError("backup_integrity_failure");
    }
    const result = applyDeletionLedger(sql, ledger, notBefore, now, environment);
    sql.exec("VACUUM"); // Remove deleted credential/search bytes from the new copy's unused pages.
    sql.close(); sql = null;
    syncFile(database);
    const report = { version: 1, scope: "offline-privacy-repaired-community-copy", resource,
      ...result, backupSha256, deletionsSha256, deletionExportedAt: ledger.exportedAt,
      databaseSha256: fileChecksum(database, MAX_BACKUP_BYTES), liveReady: false };
    writeNew(join(destination, "restore-report.json"), encoded(report)); // Completion marker written last.
    return report;
  } catch (error) {
    if (sql) sql.close();
    writeNew(join(destination, "failure-report.json"), encoded({ complete: false,
      error: error instanceof RestoreError ? error.message : "privacy_restore_failed" }));
    throw error;
  }
}

function main() {
  try {
    const { values } = parseArgs({ options: {
      backup: { type: "string" }, "backup-sha256": { type: "string" }, deletions: { type: "string" },
      "deletions-sha256": { type: "string" }, "deletions-not-before": { type: "string" }, out: { type: "string" },
      environment: { type: "string", default: "production" },
    } });
    if (["backup", "backup-sha256", "deletions", "deletions-sha256", "deletions-not-before", "out"].some(key => !values[key])
        || !/^\d+$/.test(values["deletions-not-before"])) throw new RestoreError("invalid_restore_arguments");
    const report = preparePrivateRestore({ backup: values.backup, backupSha256: values["backup-sha256"],
      deletions: values.deletions, deletionsSha256: values["deletions-sha256"],
      notBefore: Number(values["deletions-not-before"]), out: values.out, environment: values.environment });
    console.log(JSON.stringify({ complete: true, ...report }));
  } catch (error) {
    console.log(JSON.stringify({ complete: false, error: error instanceof RestoreError ? error.message : "privacy_restore_failed" }));
    process.exitCode = 1;
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main();
