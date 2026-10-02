import assert from "node:assert/strict";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import { existsSync, readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { prepareD1Sql } from "../tools/account-restore-sql.mjs";
import { makeSqlFixture, digest, deletedId, retainedId, privateQuery } from "./accountRestoreSql.fixture.mjs";

function temporary(t) {
  const parent = resolve(tmpdir()), root = mkdtempSync(join(parent, "vision-restore-sql-"));
  t.after(() => {
    if (dirname(resolve(root)) !== parent || !basename(root).startsWith("vision-restore-sql-")) throw Error("unsafe_test_cleanup");
    rmSync(root, { recursive: true });
  });
  return root;
}
test("private SQL preserves historical ledger, retained index, NUL/blob values and 64-bit high-water IDs", t => {
  const root = temporary(t), options = makeSqlFixture(root), out = join(root, "sql");
  const original = readFileSync(join(options.repairedDir, "restored.sqlite"));
  const report = prepareD1Sql({ ...options, out });
  assert.equal(report.liveReady, false); assert.equal(report.localRoundtripPassed, true);
  assert.deepEqual(readFileSync(join(options.repairedDir, "restored.sqlite")), original);
  const sql = new DatabaseSync(join(out, "roundtrip.sqlite"));
  try {
    assert.equal(sql.prepare("SELECT units FROM accounts WHERE id=?").get(retainedId).units, 40);
    assert.equal(sql.prepare("SELECT query FROM searches").get().query, privateQuery);
    assert.deepEqual(Buffer.from(sql.prepare("SELECT result_json FROM searches").get().result_json), Buffer.from([0, 255, 39]));
    assert.equal(sql.prepare("SELECT CAST(seq AS TEXT) value FROM sqlite_sequence WHERE name='locations'").get().value, "9007199254740993");
    assert.equal(sql.prepare("SELECT COUNT(*) n FROM published_index").get().n, 1);
    assert.equal(sql.prepare("SELECT SUM(units) n FROM ledger WHERE account_id=?").get(deletedId).n, 0);
    assert.throws(() => sql.prepare("UPDATE accounts SET units=1 WHERE id=?").run(deletedId), /account_not_active/);
    assert.throws(() => sql.prepare("INSERT INTO searches VALUES ('late',?,'late','private','{}')").run(deletedId), /account_not_active/);
  } finally { sql.close(); }
  const raw = readFileSync(join(out, "restore.private.sql")), batch = readFileSync(join(out, "query-batch.private.json"));
  assert.equal(digest(raw), report.sqlSha256); assert.equal(digest(batch), report.batchSha256);
  assert.equal(JSON.parse(batch).batch.length, report.statements);
  assert.ok(!raw.includes(Buffer.from("BEGIN TRANSACTION"))); // Batch API supplies the transaction.
});
for (const scenario of ["report-pin", "database-pin", "mixed-resource", "sidecar", "fence", "unknown-table", "resurrected-query", "oversize-row"]) {
  test(`SQL preparation rejects ${scenario} and preserves a redacted failure report`, t => {
    const root = temporary(t), options = makeSqlFixture(root), out = join(root, "failed");
    const reportPath = join(options.repairedDir, "restore-report.json"), database = join(options.repairedDir, "restored.sqlite");
    if (scenario === "report-pin") options.reportSha256 = "f".repeat(64);
    else if (scenario === "mixed-resource") options.environment = "production";
    else if (scenario === "sidecar") writeFileSync(database + "-wal", "private sidecar");
    else {
      const sql = new DatabaseSync(database);
      try {
        if (scenario === "database-pin") sql.prepare("UPDATE accounts SET units=41 WHERE id=?").run(retainedId);
        if (scenario === "fence") sql.exec("DROP TRIGGER deleted_account_cannot_reactivate");
        if (scenario === "unknown-table") sql.exec("CREATE TABLE unrelated (private TEXT)");
        if (scenario === "resurrected-query") {
          sql.exec("DROP TRIGGER searches_active_account_insert");
          sql.prepare("INSERT INTO searches VALUES ('revived',?,'revived','private-secret','{}')").run(deletedId);
          sql.exec("CREATE TRIGGER searches_active_account_insert BEFORE INSERT ON searches WHEN NOT EXISTS (SELECT 1 FROM accounts WHERE id=NEW.account_id AND deleted_at IS NULL) BEGIN SELECT RAISE(ABORT,'account_not_active'); END");
        }
        if (scenario === "oversize-row") sql.prepare("UPDATE searches SET query=?").run("private-secret".repeat(10000));
      } finally { sql.close(); }
      if (scenario !== "database-pin") {
        const report = JSON.parse(readFileSync(reportPath)); report.databaseSha256 = digest(readFileSync(database));
        writeFileSync(reportPath, JSON.stringify(report)); options.reportSha256 = digest(readFileSync(reportPath));
      }
    }
    const expected = { "report-pin": "input_checksum_mismatch", "database-pin": "input_checksum_mismatch",
      "mixed-resource": "invalid_repaired_copy_report", sidecar: "backup_not_closed", fence: "privacy_fence_definition_changed",
      "unknown-table": "unsupported_sql_export_schema", "resurrected-query": "invalid_restored_account_state",
      "oversize-row": "sql_export_limit_exceeded" }[scenario];
    assert.throws(() => prepareD1Sql({ ...options, out }), error => error.message === expected);
    assert.equal(existsSync(join(out, "sql-report.json")), false);
    const failed = readFileSync(join(out, "failure-report.json"), "utf8");
    assert.equal(JSON.parse(failed).liveReady, false);
    assert.ok(!failed.includes("private-secret") && !failed.includes(root));
  });
}
test("completed outputs cannot be overwritten and the CLI prints aggregate evidence only", t => {
  const root = temporary(t), options = makeSqlFixture(root), out = join(root, "complete");
  const script = fileURLToPath(new URL("../tools/account-restore-sql.mjs", import.meta.url));
  const args = [script, "--repaired-dir", options.repairedDir, "--report-sha256", options.reportSha256,
    "--environment", "staging", "--out", out];
  const first = spawnSync(process.execPath, args, { encoding: "utf8" }); assert.equal(first.status, 0, first.stdout);
  assert.equal(JSON.parse(first.stdout).complete, true);
  assert.ok(!first.stdout.includes("old-token") && !first.stdout.includes(privateQuery));
  const original = readFileSync(join(out, "sql-report.json"));
  const second = spawnSync(process.execPath, args, { encoding: "utf8" }); assert.equal(second.status, 1);
  assert.deepEqual(readFileSync(join(out, "sql-report.json")), original);
});
