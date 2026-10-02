import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, writeFileSync, existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { PRIVACY_TABLES } from "./accountPrivacy.js";
import { RESOURCE, RESOURCE_PROFILES, applyDeletionLedger, exportDeletionLedger, preparePrivateRestore, validateLedger } from "../tools/account-restore.mjs";

const account = "a".repeat(32), other = "b".repeat(32), newer = "e".repeat(32);
const quarantine = `scene-quarantine/${"d".repeat(32)}/${"e".repeat(64)}.i8`;
const digest = raw => createHash("sha256").update(raw).digest("hex");
const bytes = value => Buffer.from(JSON.stringify(value) + "\n");
function ledger() {
  return { version: 1, scope: "vision-community-account-deletions", resource: RESOURCE, exportedAt: 200,
    receipts: [{ accountId: account, requestKey: "c".repeat(64), deletedAt: 150, unitsForfeited: 123000 }] };
}
function fixture(t, path = ":memory:", oldAccountColumn = false) {
  const sql = new DatabaseSync(path);
  t.after(() => { if (sql.isOpen) sql.close(); });
  let schema = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
  if (oldAccountColumn) schema = schema.replace(/recovery_hash TEXT UNIQUE,\r?\n  deleted_at INTEGER/, "recovery_hash TEXT UNIQUE");
  sql.exec(schema);
  sql.exec("ALTER TABLE pose_catalog ADD COLUMN assignee TEXT; ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER;");
  sql.prepare("INSERT INTO accounts (id,token_hash,recovery_hash,units) VALUES (?,?,?,250000)")
    .run(account, "private-old-token", "private-old-recovery");
  sql.prepare("INSERT INTO accounts (id,token_hash,units) VALUES (?,?,100000)").run(other, "other-token");
  sql.exec(`INSERT INTO locations (id,asset_id,capture,lane,model,state,queue_state,active_lease,contributor_id) VALUES
    (1,'one','capture','scene','model','leased','leased','lease-one',NULL),
    (2,'two','capture','scene','model','pending','quarantined',NULL,NULL),
    (3,'three','capture','scene','model','published','published',NULL,'${account}'),
    (4,'four','capture','scene','model','leased','leased','lease-other',NULL);
    INSERT INTO leases (id,account_id,lane,expires_at,state) VALUES
    ('lease-one','${account}','scene',9999,'active'),('${"d".repeat(32)}','${account}','scene',9999,'submitted'),
    ('lease-published','${account}','scene',9999,'submitted'),('lease-other','${other}','scene',9999,'active');
    INSERT INTO lease_items VALUES ('lease-one',1),('${"d".repeat(32)}',2),('lease-published',3),('lease-other',4);
    INSERT INTO scene_qualifications VALUES ('qualified','${account}','profile','policy','digest',9999,1);
    INSERT INTO scene_candidates VALUES
    ('${"d".repeat(32)}','${account}','qualified','policy','digest','${quarantine}','[{"private":"candidate"}]',1,'pending'),
    ('lease-published','${account}','qualified','policy','digest','four-view-v4/kept.i8','[{"published":true}]',1,'published');
    INSERT INTO published_index (location_id,index_text,output_sha256,published_at,four_view_key)
      VALUES (3,'','digest',1,'four-view-v4/kept.i8');
    INSERT INTO ledger (account_id,units,reason,reference) VALUES ('${account}',250000,'verified_work','old-credit');
    INSERT INTO searches VALUES ('private','${account}','old-key','private-old-query','private-old-result'),
      ('other-private','${other}','other-key','other-query','other-result');
    INSERT INTO pose_catalog (lane,shard_id,r2_key,row_start,row_count,bytes,sha256,assignee,assigned_at)
      VALUES ('scene',1,'catalog',0,10,100,'digest','${account}',1);`);
  return sql;
}
function temporary(t) {
  const parent = resolve(tmpdir()), root = mkdtempSync(join(parent, "vision-private-restore-"));
  t.after(() => {
    if (dirname(resolve(root)) !== parent || !basename(root).startsWith("vision-private-restore-")) {
      throw Error("Refusing cleanup outside the task's temporary directory.");
    }
    rmSync(root, { recursive: true });
  });
  return root;
}

test("fresh deletion records revoke old credentials and results while preserving other accounts and contributions", t => {
  const sql = fixture(t, ":memory:", true);
  assert.deepEqual(applyDeletionLedger(sql, ledger(), 100, 210), { deletedAccounts: 1, closedRestoredUnits: 250000 });
  const deleted = sql.prepare("SELECT * FROM accounts WHERE id=?").get(account);
  assert.equal(deleted.deleted_at, 150); assert.equal(deleted.units, 0); assert.equal(deleted.recovery_hash, null);
  assert.notEqual(deleted.token_hash, "private-old-token");
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM searches").get().n, 1);
  assert.equal(sql.prepare("SELECT units FROM accounts WHERE id=?").get(other).units, 100000);
  assert.equal(sql.prepare("SELECT state FROM leases WHERE id='lease-other'").get().state, "active");
  assert.equal(sql.prepare("SELECT expires_at FROM scene_qualifications").get().expires_at, 0);
  assert.equal(sql.prepare("SELECT state FROM leases WHERE id='lease-one'").get().state, "expired");
  assert.equal(sql.prepare("SELECT assignee FROM pose_catalog").get().assignee, null);
  assert.equal(sql.prepare(`SELECT records_json FROM scene_candidates WHERE lease_id='${"d".repeat(32)}'`).get().records_json, "[]");
  assert.equal(sql.prepare("SELECT state FROM locations WHERE id=2").get().state, "pending");
  assert.equal(sql.prepare("SELECT state FROM account_cleanup WHERE artifact_key=?").get(quarantine).state, "pending");
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM published_index").get().n, 1);
  assert.equal(sql.prepare("SELECT contributor_id FROM locations WHERE id=3").get().contributor_id, account);
  assert.equal(sql.prepare("SELECT state FROM scene_candidates WHERE lease_id='lease-published'").get().state, "published");
  assert.equal(sql.prepare("SELECT units_forfeited FROM account_deletion_receipts").get().units_forfeited, 123000);
  assert.equal(sql.prepare("SELECT units FROM ledger WHERE reason='account_restore_deleted'").get().units, -250000);
});

test("reapplied tombstones retain database fences against late searches, credits, credentials and work", t => {
  const sql = fixture(t);
  applyDeletionLedger(sql, ledger(), 100, 210);
  for (const statement of [
    `UPDATE accounts SET deleted_at=NULL WHERE id='${account}'`,
    `UPDATE accounts SET token_hash='changed' WHERE id='${account}'`,
    `UPDATE accounts SET units=1 WHERE id='${account}'`,
    `INSERT INTO searches VALUES ('late','${account}','key','query','private')`,
    `INSERT INTO ledger (account_id,units,reason,reference) VALUES ('${account}',1,'work','late')`,
    `UPDATE scene_qualifications SET expires_at=1000`,
    `UPDATE scene_candidates SET state='published' WHERE lease_id='${"d".repeat(32)}'`,
    `UPDATE locations SET state='published',contributor_id='${account}' WHERE id=1`,
  ]) assert.throws(() => sql.exec(statement), /account_not_active/);
});

test("repeated repair preserves the original receipt and does not close credits twice", t => {
  const sql = fixture(t);
  applyDeletionLedger(sql, ledger(), 100, 210);
  const firstToken = sql.prepare("SELECT token_hash FROM accounts WHERE id=?").get(account).token_hash;
  assert.deepEqual(applyDeletionLedger(sql, ledger(), 100, 220), { deletedAccounts: 1, closedRestoredUnits: 0 });
  assert.equal(sql.prepare("SELECT token_hash FROM accounts WHERE id=?").get(account).token_hash, firstToken);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='account_restore_deleted'").get().n, 1);
  assert.deepEqual(exportDeletionLedger(sql, 250).receipts, ledger().receipts);
});

test("restore requeues journaled uploads without candidates, preserves published indexes and fences late writes", t => {
  const sql = fixture(t);
  for (const statement of PRIVACY_TABLES) sql.exec(statement);
  const final = `four-view-v4/${"d".repeat(32)}.i8`, retained = "four-view-v4/kept.i8";
  for (const key of [final, retained]) sql.prepare("INSERT INTO account_artifact_writes VALUES (?,?,?,?,?,1)")
    .run(key, account, "d".repeat(32), "f".repeat(64), 3080);
  sql.prepare("INSERT INTO account_cleanup VALUES (?,?,1,'fenced')").run(final, account);
  applyDeletionLedger(sql, ledger(), 100, 210);
  assert.equal(sql.prepare("SELECT state FROM account_cleanup WHERE artifact_key=?").get(final).state, "pending");
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM account_cleanup WHERE artifact_key=?").get(retained).n, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM published_index").get().n, 1);
  assert.throws(() => sql.prepare("INSERT INTO account_artifact_writes VALUES (?,?,?,?,?,1)")
    .run(`four-view-v4/${"f".repeat(32)}.i8`, account, "f".repeat(32), "f".repeat(64), 3080), /account_not_active/);
  assert.throws(() => sql.exec("UPDATE account_artifact_writes SET bytes=1"), /artifact_write_intent_immutable/);
});

test("restore rolls back when a journaled upload has a conflicting cleanup owner", t => {
  const sql = fixture(t);
  for (const statement of PRIVACY_TABLES) sql.exec(statement);
  const final = `four-view-v4/${"d".repeat(32)}.i8`;
  sql.prepare("INSERT INTO account_artifact_writes VALUES (?,?,?,?,?,1)").run(final, account, "d".repeat(32), "f".repeat(64), 3080);
  sql.prepare("INSERT INTO account_cleanup VALUES (?,?,1,'pending')").run(final, other);
  assert.throws(() => applyDeletionLedger(sql, ledger(), 100, 210), /restore_cleanup_owner_conflict/);
  assert.equal(sql.prepare("SELECT units FROM accounts WHERE id=?").get(account).units, 250000);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM account_deletion_receipts").get().n, 0);
});

test("a deleted account created after the backup receives an inactive tombstone without new access", t => {
  const sql = fixture(t), document = ledger();
  document.receipts.push({ accountId: newer, requestKey: "f".repeat(64), deletedAt: 180, unitsForfeited: 50000 });
  applyDeletionLedger(sql, document, 100, 210);
  const stub = sql.prepare("SELECT * FROM accounts WHERE id=?").get(newer);
  assert.equal(stub.units, 0); assert.equal(stub.recovery_hash, null); assert.equal(stub.deleted_at, 180);
  assert.throws(() => sql.prepare("UPDATE accounts SET deleted_at=NULL WHERE id=?").run(newer), /account_not_active/);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM account_deletion_receipts").get().n, 2);
});

test("omitted or conflicting deletion history cannot resurrect or replace an earlier receipt", t => {
  const sql = fixture(t);
  applyDeletionLedger(sql, ledger(), 100, 210);
  for (const change of [document => { document.receipts = []; },
    document => { document.receipts[0].requestKey = "f".repeat(64); },
    document => { document.receipts[0].deletedAt = 151; },
    document => { document.receipts[0].unitsForfeited++; }]) {
    const document = ledger(); change(document);
    assert.throws(() => applyDeletionLedger(sql, document, 100, 220), /deletion_history_missing_or_changed/);
  }
  assert.equal(sql.prepare("SELECT request_key FROM account_deletion_receipts").get().request_key, "c".repeat(64));
});

test("stale, future, wrong-resource, duplicate and malformed deletion records fail admission", () => {
  const cases = [document => { document.exportedAt = 99; }, document => { document.exportedAt = 300; },
    document => { document.resource = { ...RESOURCE, bucket: "unconfirmed" }; },
    document => { document.receipts.push({ ...document.receipts[0] }); },
    document => { document.receipts[0].deletedAt = true; },
    document => { document.receipts[0].deletedAt = 201; },
    document => { document.receipts[0].unitsForfeited = Number.MAX_SAFE_INTEGER + 1; }];
  for (const change of cases) {
    const document = ledger(); change(document);
    assert.throws(() => validateLedger(document, 100, 210), /invalid/);
  }
  const document = ledger();
  document.receipts[0].accountId = [account];
  assert.throws(() => validateLedger(document, 100, 210), /invalid_deletion_receipt/);
  const reordered = ledger();
  reordered.resource = { bucket: RESOURCE.bucket, databaseId: RESOURCE.databaseId, accountId: RESOURCE.accountId };
  assert.equal(validateLedger(reordered, 100, 210), reordered);
});

test("a conflicting cleanup owner fails the repair instead of silently losing removal work", t => {
  const sql = fixture(t);
  for (const statement of PRIVACY_TABLES) sql.exec(statement);
  sql.prepare("INSERT INTO account_cleanup VALUES (?,?,1,'removed')").run(quarantine, other);
  assert.throws(() => applyDeletionLedger(sql, ledger(), 100, 210), /restore_cleanup_owner_conflict/);
  assert.equal(sql.prepare("SELECT units FROM accounts WHERE id=?").get(account).units, 250000);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM account_deletion_receipts").get().n, 0);
});

test("staging repair requires its explicit profile and rejects mixed or unknown resources before changing accounts", t => {
  const document = { ...ledger(), resource: RESOURCE_PROFILES.staging }, sql = fixture(t);
  assert.equal(validateLedger(document, 100, 210, "staging"), document);
  assert.throws(() => applyDeletionLedger(sql, document, 100, 210), /invalid_or_stale_deletion_ledger/);
  assert.throws(() => applyDeletionLedger(sql, ledger(), 100, 210, "staging"), /invalid_or_stale_deletion_ledger/);
  for (const environment of ["unknown", "__proto__", "toString", null, {}]) {
    assert.throws(() => applyDeletionLedger(sql, document, 100, 210, environment), /invalid_restore_environment/);
  }
  for (const resource of [ { ...RESOURCE_PROFILES.staging, databaseId: RESOURCE.databaseId },
    { ...RESOURCE_PROFILES.staging, bucket: RESOURCE.bucket },
    { ...RESOURCE_PROFILES.staging, accountId: "f".repeat(32) } ]) {
    assert.throws(() => applyDeletionLedger(sql, { ...document, resource }, 100, 210, "staging"), /invalid_or_stale_deletion_ledger/);
  }
  assert.equal(sql.prepare("SELECT units FROM accounts WHERE id=?").get(account).units, 250000);
  assert.deepEqual(applyDeletionLedger(sql, document, 100, 210, "staging"), { deletedAccounts: 1, closedRestoredUnits: 250000 });
  const exported = exportDeletionLedger(sql, 250, "staging");
  assert.deepEqual(exported.resource, RESOURCE_PROFILES.staging);
  assert.deepEqual(exported.receipts, document.receipts);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM published_index").get().n, 1);
});

test("repair transaction rolls back credentials, credits, receipts and cleanup when a later statement fails", t => {
  const sql = fixture(t);
  sql.exec("CREATE TRIGGER fail_restore BEFORE DELETE ON searches BEGIN SELECT RAISE(ABORT,'forced restore failure'); END;");
  assert.throws(() => applyDeletionLedger(sql, ledger(), 100, 210), /forced restore failure/);
  assert.equal(sql.prepare("SELECT token_hash FROM accounts WHERE id=?").get(account).token_hash, "private-old-token");
  assert.equal(sql.prepare("SELECT units FROM accounts WHERE id=?").get(account).units, 250000);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM searches").get().n, 2);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name='account_deletion_receipts'").get().n, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger").get().n, 1);
});

test("current-ledger export refuses a tombstone without its matching receipt", t => {
  const sql = fixture(t);
  for (const statement of PRIVACY_TABLES) sql.exec(statement);
  sql.prepare("UPDATE accounts SET deleted_at=150 WHERE id=?").run(account);
  assert.throws(() => exportDeletionLedger(sql, 200), /incomplete_deletion_receipts/);
});

function fileFixture(t) {
  const root = temporary(t), backup = join(root, "old.sqlite"), deletions = join(root, "deletions.json");
  const sql = fixture(t, backup); sql.close();
  writeFileSync(deletions, bytes(ledger()));
  return { root, options: { backup, backupSha256: digest(readFileSync(backup)), deletions,
    deletionsSha256: digest(readFileSync(deletions)), notBefore: 100, now: 210, out: join(root, "repaired") } };
}

test("offline repair leaves the source unchanged, erases old private bytes in the new copy and seals last", t => {
  const { options } = fileFixture(t);
  const report = preparePrivateRestore(options);
  assert.equal(report.liveReady, false);
  assert.equal(report.deletedAccounts, 1);
  assert.equal(digest(readFileSync(options.backup)), options.backupSha256);
  const result = readFileSync(join(options.out, "restored.sqlite"));
  assert.equal(digest(result), report.databaseSha256);
  for (const secret of ["private-old-token", "private-old-recovery", "private-old-query", "private-old-result"]) {
    assert.equal(result.includes(Buffer.from(secret)), false, secret);
  }
  const marker = readFileSync(join(options.out, "restore-report.json"), "utf8");
  assert.equal(marker.includes(account), false);
  assert.equal(marker.includes(options.backup), false);
  assert.throws(() => preparePrivateRestore(options), /EEXIST/);
  assert.equal(existsSync(join(options.out, "failure-report.json")), false);
});

test("bad pins, active backup sidecars, changed fences and incompatible schema preserve redacted failures", t => {
  const { options, root } = fileFixture(t);
  for (const [name, override] of [["bad-backup", { backupSha256: "f".repeat(64) }],
    ["bad-ledger", { deletionsSha256: "f".repeat(64) }]]) {
    const out = join(root, name);
    assert.throws(() => preparePrivateRestore({ ...options, ...override, out }), /input_checksum_mismatch/);
    assert.equal(existsSync(join(out, "restore-report.json")), false);
    assert.equal(readFileSync(join(out, "failure-report.json"), "utf8").includes(options.backup), false);
  }
  writeFileSync(options.backup + "-wal", Buffer.from("active"));
  assert.throws(() => preparePrivateRestore(options), /backup_not_closed/);
  assert.equal(existsSync(join(options.out, "restore-report.json")), false);
  const sql = fixture(t);
  sql.exec("CREATE TRIGGER deleted_account_cannot_reactivate BEFORE UPDATE ON accounts BEGIN SELECT 1; END;");
  assert.throws(() => applyDeletionLedger(sql, ledger(), 100, 210), /privacy_fence_definition_changed/);
  const missing = fixture(t); missing.exec("ALTER TABLE searches RENAME TO missing_searches");
  assert.throws(() => applyDeletionLedger(missing, ledger(), 100, 210), /unsupported_restore_schema/);
});

test("a staging backup produces a private staging copy only after explicit profile admission", t => {
  const { options, root } = fileFixture(t);
  const document = { ...ledger(), resource: RESOURCE_PROFILES.staging };
  writeFileSync(options.deletions, bytes(document));
  options.deletionsSha256 = digest(readFileSync(options.deletions));
  assert.throws(() => preparePrivateRestore(options), /invalid_or_stale_deletion_ledger/);
  assert.equal(existsSync(join(options.out, "restore-report.json")), false);
  const report = preparePrivateRestore({ ...options, environment: "staging", out: join(root, "staging-repaired") });
  assert.deepEqual(report.resource, RESOURCE_PROFILES.staging);
  assert.equal(report.liveReady, false);
  assert.equal(report.deletedAccounts, 1);
  assert.equal(digest(readFileSync(options.backup)), options.backupSha256);
  const restored = readFileSync(join(root, "staging-repaired", "restored.sqlite"));
  assert.equal(restored.includes(Buffer.from("private-old-token")), false);
  assert.equal(restored.includes(Buffer.from("private-old-result")), false);
});

test("the CLI accepts only the explicit staging mapping and keeps invalid profile failures redacted", t => {
  const { options } = fileFixture(t), document = { ...ledger(), resource: RESOURCE_PROFILES.staging };
  writeFileSync(options.deletions, bytes(document));
  const args = [fileURLToPath(new URL("../tools/account-restore.mjs", import.meta.url)), "--backup", options.backup,
    "--backup-sha256", options.backupSha256, "--deletions", options.deletions,
    "--deletions-sha256", digest(readFileSync(options.deletions)), "--deletions-not-before", "100", "--out", options.out];
  const result = spawnSync(process.execPath, [...args, "--environment", "staging"], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout).resource, RESOURCE_PROFILES.staging);
  const invalid = spawnSync(process.execPath, [...args.slice(0, -1), options.out + "-bad", "--environment", "__proto__"], { encoding: "utf8" });
  assert.equal(invalid.status, 1);
  assert.deepEqual(JSON.parse(invalid.stdout), { complete: false, error: "invalid_restore_environment" });
  assert.equal(invalid.stdout.includes(options.backup), false);
});

test("the operator CLI prepares a local copy and returns redacted errors for invalid arguments", t => {
  const { options } = fileFixture(t);
  const script = new URL("../tools/account-restore.mjs", import.meta.url);
  const result = spawnSync(process.execPath, [fileURLToPath(script), "--backup", options.backup,
    "--backup-sha256", options.backupSha256, "--deletions", options.deletions,
    "--deletions-sha256", options.deletionsSha256, "--deletions-not-before", "100", "--out", options.out], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).complete, true);
  const bad = spawnSync(process.execPath, [fileURLToPath(script), "--backup", "private-path"], { encoding: "utf8" });
  assert.equal(bad.status, 1);
  assert.deepEqual(JSON.parse(bad.stdout), { complete: false, error: "invalid_restore_arguments" });
});
