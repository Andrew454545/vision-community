// Actual local workerd/D1 only. No network, real accounts or live import.
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { prepareD1Sql } from "./account-restore-sql.mjs";
import { deletedId, retainedId, privateQuery, makeSqlFixture } from "../src/accountRestoreSql.fixture.mjs";

const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(process.argv[2])));
const parent = resolve(tmpdir()), root = mkdtempSync(join(parent, "vision-d1-restore-sql-"));
let instance;
try {
  const out = join(root, "prepared");
  prepareD1Sql({ ...makeSqlFixture(root), out });
  const batch = JSON.parse(readFileSync(join(out, "query-batch.private.json"))).batch;
  instance = new Miniflare(convertV4MiniflareOptions({ modules: true,
    script: 'export default {fetch(){return new Response("synthetic local restore check")}}',
    compatibilityDate: "2026-10-02", d1Databases: ["DB"] }));
  const db = await instance.getD1Database("DB");
  const statements = () => batch.map(({ sql }) => db.prepare(sql));
  await db.batch(statements());
  await db.prepare("UPDATE accounts SET units=70 WHERE id=?").bind(retainedId).run();
  await db.prepare("INSERT INTO searches VALUES ('later',?,'later','synthetic later search','{}')").bind(retainedId).run();
  await db.prepare("CREATE TABLE provider_owned_synthetic (id INTEGER PRIMARY KEY AUTOINCREMENT)").run();
  await db.prepare("INSERT INTO provider_owned_synthetic (id) VALUES (99)").run();
  // A failed replacement must roll back the entire DROP/CREATE/data batch.
  await assert.rejects(db.batch([...statements(), db.prepare("INSERT INTO missing_restore_table VALUES (1)")]));
  assert.equal((await db.prepare("SELECT units FROM accounts WHERE id=?").bind(retainedId).first()).units, 70);
  assert.equal((await db.prepare("SELECT COUNT(*) n FROM searches").first()).n, 2);
  await db.batch(statements());
  assert.equal((await db.prepare("SELECT units FROM accounts WHERE id=?").bind(retainedId).first()).units, 40);
  assert.equal((await db.prepare("SELECT units,recovery_hash,deleted_at FROM accounts WHERE id=?").bind(deletedId).first()).units, 0);
  const search = await db.prepare("SELECT query,hex(result_json) bytes FROM searches").first();
  assert.equal(search.query, privateQuery); assert.equal(search.bytes, "00FF27");
  assert.equal((await db.prepare("SELECT COUNT(*) n FROM searches WHERE account_id=?").bind(deletedId).first()).n, 0);
  assert.equal((await db.prepare("SELECT COUNT(*) n FROM account_deletion_receipts").first()).n, 1);
  assert.equal((await db.prepare("SELECT units FROM ledger WHERE reason='account_restore_deleted'").first()).units, -20);
  assert.equal((await db.prepare("SELECT COUNT(*) n FROM published_index").first()).n, 1);
  assert.equal((await db.prepare("SELECT CAST(seq AS TEXT) value FROM sqlite_sequence WHERE name='locations'").first()).value, "9007199254740993");
  assert.equal((await db.prepare("SELECT seq FROM sqlite_sequence WHERE name='provider_owned_synthetic'").first()).seq, 99);
  assert.equal((await db.prepare("PRAGMA foreign_key_check").all()).results.length, 0);
  await assert.rejects(db.prepare("UPDATE accounts SET units=1 WHERE id=?").bind(deletedId).run(), /account_not_active/);
  await assert.rejects(db.prepare("INSERT INTO searches VALUES ('late',?,'late','private','{}')").bind(deletedId).run(), /account_not_active/);
  console.log(JSON.stringify({ status: "ACTUAL_WORKERD_PRIVATE_RESTORE_SQL_PASSED", replacedPopulatedDatabase: true,
    failedReplacementRolledBack: true, privacyFencesChecked: true, retainedIndexChecked: true,
    privateValueAndHighWaterChecks: true, liveImport: false }));
} finally {
  if (instance) await instance.dispose();
  if (dirname(resolve(root)) !== parent || !basename(root).startsWith("vision-d1-restore-sql-")) throw Error("unsafe_test_cleanup");
  rmSync(root, { recursive: true });
}
