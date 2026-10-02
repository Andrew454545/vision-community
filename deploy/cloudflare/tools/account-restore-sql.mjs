// Offline operator preparation only. Does not contact Cloudflare or execute live SQL.
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { closeSync, constants, copyFileSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readSync, statSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { PRIVACY_FENCES } from "../src/accountPrivacy.js";
import { RESOURCE_PROFILES, RestoreError } from "./account-restore.mjs";

const HEX = /^[0-9a-f]{64}$/;
const TABLES = ["account_artifact_writes", "account_cleanup", "account_deletion_archives",
  "account_deletion_receipts", "accounts", "index_shards", "lease_items", "leases", "ledger",
  "locations", "object_coverage", "pose_catalog", "published_index", "scene_candidates",
  "scene_qualifications", "searches"];
const MAX_DATABASE = 512 * 1024 * 1024, MAX_REPORT = 16384;
const MAX_SQL = 16 * 1024 * 1024, MAX_STATEMENTS = 10000, MAX_STATEMENT = 100000;
const checksum = raw => createHash("sha256").update(raw).digest("hex");
const encoded = value => Buffer.from(JSON.stringify(value) + "\n");
const quoteName = name => '"' + name.replaceAll('"', '""') + '"';
const normalized = sql => sql.replace(/IF NOT EXISTS/ig, "").replace(/\s+/g, "").replace(/;$/, "").toLowerCase();
const hasSidecar = path => ["-wal", "-shm", "-journal"].some(suffix => existsSync(path + suffix));
function fileChecksum(path) {
  if (!statSync(path).isFile() || statSync(path).size > MAX_DATABASE) throw new RestoreError("input_too_large");
  const fd = openSync(path, "r"), hash = createHash("sha256"), buffer = Buffer.alloc(1024 * 1024);
  let total = 0;
  try {
    for (let count; (count = readSync(fd, buffer, 0, buffer.length, null)) > 0;) {
      total += count;
      if (total > MAX_DATABASE) throw new RestoreError("input_too_large");
      hash.update(buffer.subarray(0, count));
    }
  } finally { closeSync(fd); }
  return hash.digest("hex");
}
function writeNew(path, raw) {
  writeFileSync(path, raw, { flag: "wx", mode: 0o600 });
  const fd = openSync(path, "r+"); try { fsyncSync(fd); } finally { closeSync(fd); }
}
function literalRows(sql, table) {
  const columns = sql.prepare(`PRAGMA table_xinfo(${quoteName(table)})`).all();
  if (!columns.length || columns.some(c => c.hidden !== 0)) throw new RestoreError("unsupported_sql_export_schema");
  // SQLite supplies exact numeric/blob literals, including 64-bit integers.
  // quote(TEXT) truncates NULs; encode those strings explicitly as UTF-8 bytes.
  const selections = columns.map(({ name }) => {
    const col = quoteName(name);
    return `CASE WHEN typeof(${col})='text' AND instr(${col},char(0))>0
      THEN 'CAST(X'''||hex(CAST(${col} AS BLOB))||''' AS TEXT)' ELSE quote(${col}) END AS ${col}`;
  });
  const rows = [];
  for (const row of sql.prepare(`SELECT ${selections.join(",")} FROM ${quoteName(table)}`).iterate()) {
    if (rows.length >= MAX_STATEMENTS) throw new RestoreError("sql_export_limit_exceeded");
    rows.push(columns.map(c => row[c.name]).join(","));
  }
  return { columns: columns.map(c => quoteName(c.name)).join(","), rows: rows.sort() };
}

export function prepareD1Sql({ repairedDir, reportSha256, environment = "production", out }) {
  const destination = resolve(out);
  mkdirSync(destination, { recursive: false, mode: 0o700 }); // Preserve existing outputs.
  let source, roundtrip;
  try {
    const resource = RESOURCE_PROFILES[environment];
    if (!resource) throw new RestoreError("invalid_restore_environment");
    if (!HEX.test(reportSha256 || "")) throw new RestoreError("invalid_checksum_pin");
    const reportPath = join(resolve(repairedDir), "restore-report.json");
    if (!statSync(reportPath).isFile() || statSync(reportPath).size > MAX_REPORT) throw new RestoreError("input_too_large");
    const rawReport = readFileSync(reportPath);
    if (rawReport.length > MAX_REPORT || checksum(rawReport) !== reportSha256) throw new RestoreError("input_checksum_mismatch");
    const report = JSON.parse(rawReport);
    if (report.version !== 1 || report.scope !== "offline-privacy-repaired-community-copy"
        || report.liveReady !== false || !HEX.test(report.databaseSha256 || "")
        || !report.resource || Object.keys(report.resource).length !== 3
        || Object.entries(resource).some(([key, value]) => report.resource[key] !== value)) {
      throw new RestoreError("invalid_repaired_copy_report");
    }
    const database = join(resolve(repairedDir), "restored.sqlite");
    if (hasSidecar(database)) throw new RestoreError("backup_not_closed");
    if (!statSync(database).isFile() || statSync(database).size > MAX_DATABASE) throw new RestoreError("input_too_large");
    const inputCopy = join(destination, "input.sqlite");
    // Query a pinned private copy, so a late WAL on the operator's input cannot
    // silently supply unhashed rows while the original main file stays unchanged.
    copyFileSync(database, inputCopy, constants.COPYFILE_EXCL);
    if (hasSidecar(database)) throw new RestoreError("backup_not_closed");
    if (fileChecksum(inputCopy) !== report.databaseSha256) throw new RestoreError("input_checksum_mismatch");
    source = new DatabaseSync(inputCopy, { readOnly: true, allowExtension: false });
    source.exec("PRAGMA trusted_schema=OFF; BEGIN;");
    const schema = source.prepare("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").all();
    if (schema.some(row => !["table", "index", "trigger"].includes(row.type) || !row.sql
        || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(row.name) || row.name.startsWith("_cf_") || !TABLES.includes(row.tbl_name))
        || JSON.stringify(schema.filter(row => row.type === "table").map(row => row.name).sort()) !== JSON.stringify(TABLES)) {
      throw new RestoreError("unsupported_sql_export_schema");
    }
    const fences = new Map(PRIVACY_FENCES.map(sql => [sql.match(/CREATE TRIGGER IF NOT EXISTS (\w+)/)[1], sql]));
    const triggers = schema.filter(row => row.type === "trigger");
    if (triggers.length !== fences.size || triggers.some(row => !fences.has(row.name)
        || normalized(row.sql) !== normalized(fences.get(row.name)))) throw new RestoreError("privacy_fence_definition_changed");
    if (source.prepare("PRAGMA integrity_check").all().some(row => row.integrity_check !== "ok")
        || source.prepare("PRAGMA foreign_key_check").all().length) throw new RestoreError("backup_integrity_failure");
    if (source.prepare("SELECT 1 FROM accounts WHERE deleted_at IS NOT NULL AND (units!=0 OR recovery_hash IS NOT NULL) LIMIT 1").get()
        || source.prepare("SELECT 1 FROM searches s JOIN accounts a ON a.id=s.account_id WHERE a.deleted_at IS NOT NULL LIMIT 1").get()) {
      throw new RestoreError("invalid_restored_account_state");
    }
    const statements = [];
    let sqlBytes = 0;
    const add = sql => {
      const statement = sql.replace(/;\s*$/, "") + ";", size = Buffer.byteLength(statement + "\n");
      sqlBytes += size;
      if (size > MAX_STATEMENT || sqlBytes > MAX_SQL || statements.length >= MAX_STATEMENTS) throw new RestoreError("sql_export_limit_exceeded");
      statements.push(statement);
    };
    add("PRAGMA defer_foreign_keys=ON");
    for (const row of triggers) add(`DROP TRIGGER IF EXISTS ${quoteName(row.name)}`);
    for (const table of TABLES) add(`DROP TABLE IF EXISTS ${quoteName(table)}`);
    // D1 validates referenced tables even with deferred constraints: create ALL
    // tables before inserting. Install fences AFTER historical rows are copied.
    for (const row of schema.filter(row => row.type === "table")) add(row.sql);
    const expected = new Map();
    for (const table of TABLES) {
      const content = literalRows(source, table); expected.set(table, content);
      for (const row of content.rows) add(`INSERT INTO ${quoteName(table)} (${content.columns}) VALUES (${row})`);
    }
    // Preserve deleted high-water IDs as well as currently present rows.
    if (source.prepare("SELECT 1 FROM sqlite_sequence WHERE name NOT IN ('locations','ledger') LIMIT 1").get()) {
      throw new RestoreError("unsupported_sql_export_schema");
    }
    // Do not clear any provider-owned sequence in the destination database.
    add("DELETE FROM sqlite_sequence WHERE name IN ('locations','ledger')");
    const sequence = literalRows(source, "sqlite_sequence");
    for (const row of sequence.rows) add(`INSERT INTO sqlite_sequence (${sequence.columns}) VALUES (${row})`);
    for (const row of schema.filter(row => row.type === "index" || row.type === "trigger")) add(row.sql);
    const sql = Buffer.from(statements.join("\n") + "\n"), batch = encoded({ batch: statements.map(sql => ({ sql, params: [] })) });
    writeNew(join(destination, "restore.private.sql"), sql);
    writeNew(join(destination, "query-batch.private.json"), batch);
    roundtrip = new DatabaseSync(join(destination, "roundtrip.sqlite"), { allowExtension: false });
    roundtrip.exec("PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;");
    for (const statement of statements) roundtrip.exec(statement);
    roundtrip.exec("COMMIT;");
    if (roundtrip.prepare("PRAGMA foreign_key_check").all().length
        || roundtrip.prepare("PRAGMA integrity_check").all().some(row => row.integrity_check !== "ok")
        || TABLES.some(table => JSON.stringify(literalRows(roundtrip, table)) !== JSON.stringify(expected.get(table)))
        || JSON.stringify(literalRows(roundtrip, "sqlite_sequence")) !== JSON.stringify(sequence)) {
      throw new RestoreError("sql_roundtrip_mismatch");
    }
    roundtrip.close(); roundtrip = null;
    source.exec("COMMIT"); source.close(); source = null;
    if (hasSidecar(database)) throw new RestoreError("backup_not_closed");
    if (fileChecksum(database) !== report.databaseSha256 || fileChecksum(inputCopy) !== report.databaseSha256) {
      throw new RestoreError("input_checksum_mismatch");
    }
    const result = { version: 1, scope: "offline-community-d1-sql-preparation", resource,
      reportSha256, databaseSha256: report.databaseSha256, sqlSha256: checksum(sql), batchSha256: checksum(batch),
      statements: statements.length, bytes: sql.length, applicationTables: TABLES.length,
      localRoundtripPassed: true, replacesApplicationTables: true, liveReady: false };
    writeNew(join(destination, "sql-report.json"), encoded(result)); // Completion marker last.
    return result;
  } catch (error) {
    if (source) source.close(); if (roundtrip) roundtrip.close();
    writeNew(join(destination, "failure-report.json"), encoded({ complete: false, liveReady: false,
      error: error instanceof RestoreError ? error.message : "private_sql_preparation_failed" }));
    throw error;
  }
}

function main() {
  try {
    const { values } = parseArgs({ options: { "repaired-dir": { type: "string" }, "report-sha256": { type: "string" },
      environment: { type: "string", default: "production" }, out: { type: "string" } } });
    if (["repaired-dir", "report-sha256", "out"].some(key => !values[key])) throw new RestoreError("invalid_restore_arguments");
    console.log(JSON.stringify({ complete: true, ...prepareD1Sql({ repairedDir: values["repaired-dir"],
      reportSha256: values["report-sha256"], environment: values.environment, out: values.out }) }));
  } catch (error) {
    console.log(JSON.stringify({ complete: false, liveReady: false,
      error: error instanceof RestoreError ? error.message : "private_sql_preparation_failed" }));
    process.exitCode = 1;
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main();
