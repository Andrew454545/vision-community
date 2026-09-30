import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { deleteAccount, cleanupAccountArtifacts, migrateAccountPrivacy } from "./accountPrivacy.js";

const account = "a".repeat(32), other = "b".repeat(32);
const request = { accountId: account, confirmation: "DELETE", idempotencyKey: "c".repeat(64) };
const quarantine = `scene-quarantine/${"d".repeat(32)}/${"e".repeat(64)}.i8`;
function d1(sql) {
  return { prepare(query) {
    const statement = (args = []) => ({ bind: (...bound) => statement(bound),
      first: async () => sql.prepare(query).get(...args) || null,
      all: async () => ({ results: sql.prepare(query).all(...args) }),
      run: async () => statement(args).execute(),
      execute: () => ({ success: true, meta: { changes: Number(sql.prepare(query).run(...args).changes) } }),
    });
    return statement();
  }, async batch(statements) {
    sql.exec("BEGIN IMMEDIATE");
    try { const result = statements.map(s => s.execute()); sql.exec("COMMIT"); return result; }
    catch (failure) { sql.exec("ROLLBACK"); throw failure; }
  } };
}
async function fixture(t, legacy = false) {
  const sql = new DatabaseSync(":memory:");
  t.after(() => sql.close());
  let schema = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
  if (legacy) schema = schema.replace("recovery_hash TEXT UNIQUE,\n  deleted_at INTEGER", "recovery_hash TEXT UNIQUE");
  // On Windows readFileSync may include CRLF.
  if (legacy) schema = schema.replace("recovery_hash TEXT UNIQUE,\r\n  deleted_at INTEGER", "recovery_hash TEXT UNIQUE");
  sql.exec(schema);
  sql.exec("ALTER TABLE pose_catalog ADD COLUMN assignee TEXT; ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER;");
  const env = { DB: d1(sql), INDEX: { async delete() {} } };
  await migrateAccountPrivacy(env);
  sql.prepare("INSERT INTO accounts (id,token_hash,recovery_hash,units) VALUES (?,?,?,250000)").run(account, "old-token", "old-recovery");
  sql.prepare("INSERT INTO accounts (id,token_hash,units) VALUES (?,?,100000)").run(other, "other-token");
  sql.exec(`INSERT INTO locations (id,asset_id,capture,lane,model,state,queue_state,active_lease,contributor_id) VALUES
    (1,'one','capture','scene','model','leased','leased','lease-one',NULL),
    (2,'two','capture','scene','model','pending','quarantined',NULL,NULL),
    (3,'three','capture','scene','model','published','published',NULL,'${account}'),
    (4,'four','capture','scene','model','leased','leased','lease-other',NULL);
    INSERT INTO leases (id,account_id,lane,expires_at,state) VALUES
    ('lease-one','${account}','scene',9999,'active'),
    ('lease-two','${account}','scene',9999,'submitted'),
    ('lease-published','${account}','scene',9999,'submitted'),
    ('lease-other','${other}','scene',9999,'active');
    INSERT INTO lease_items VALUES ('lease-one',1),('lease-two',2),('lease-published',3),('lease-other',4);
    INSERT INTO scene_qualifications VALUES ('qualified','${account}','profile','policy','digest',9999,1);
    INSERT INTO scene_candidates VALUES
    ('lease-two','${account}','qualified','policy','digest','${quarantine}','[{"private":"metadata"}]',1,'pending'),
    ('lease-published','${account}','qualified','policy','published-digest','four-view-v4/kept.i8','[{"published":true}]',1,'published');
    INSERT INTO pose_catalog (lane,shard_id,r2_key,row_start,row_count,bytes,sha256,assignee,assigned_at)
      VALUES ('scene',1,'catalog',0,10,100,'digest','${account}',1);
    INSERT INTO published_index (location_id,index_text,output_sha256,published_at,four_view_key)
      VALUES (3,'','verified-digest',1,'four-view-v4/kept.i8');
    INSERT INTO ledger (account_id,units,reason,reference) VALUES ('${account}',250000,'contribution','accepted-before-deletion');
    INSERT INTO searches VALUES ('private','${account}','old-key','sha256:query','{"map":"private search"}'),
      ('other-private','${other}','other-key','sha256:other','{"map":"other search"}');`);
  return { sql, env };
}
function row(sql, query) { return sql.prepare(query).get(); }
test("deletion revokes credentials, removes private results, forfeits credits and releases only unpublished work", async t => {
  const { sql, env } = await fixture(t);
  const result = await deleteAccount(env, account, request, 1234);
  assert.deepEqual(result, { deleted: true, contributionsRetained: true, unitsForfeited: 250000 });
  const deleted = row(sql, `SELECT * FROM accounts WHERE id='${account}'`);
  assert.equal(deleted.deleted_at, 1234);
  assert.equal(deleted.recovery_hash, null);
  assert.notEqual(deleted.token_hash, "old-token");
  assert.equal(deleted.units, 0);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM searches").n, 1);
  assert.equal(row(sql, "SELECT expires_at FROM scene_qualifications").expires_at, 0);
  assert.equal(row(sql, "SELECT state FROM leases WHERE id='lease-one'").state, "expired");
  assert.equal(row(sql, "SELECT state FROM leases WHERE id='lease-other'").state, "active");
  for (const id of [1, 2]) assert.equal(row(sql, `SELECT state FROM locations WHERE id=${id}`).state, "pending");
  assert.equal(row(sql, "SELECT state FROM locations WHERE id=3").state, "published");
  assert.equal(row(sql, "SELECT contributor_id FROM locations WHERE id=3").contributor_id, account);
  assert.equal(row(sql, "SELECT state FROM locations WHERE id=4").state, "leased");
  assert.equal(row(sql, "SELECT records_json FROM scene_candidates WHERE lease_id='lease-two'").records_json, "[]");
  assert.equal(row(sql, "SELECT state FROM scene_candidates WHERE lease_id='lease-published'").state, "published");
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM published_index").n, 1);
  assert.equal(row(sql, "SELECT assignee FROM pose_catalog").assignee, null);
  assert.equal(row(sql, "SELECT units FROM ledger WHERE reason='account_deleted'").units, -250000);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_cleanup").n, 1);
  assert.equal(row(sql, `SELECT units FROM accounts WHERE id='${other}'`).units, 100000);
});

test("a lost response can be recovered after credential revocation, using only the exact private receipt", async t => {
  const { sql, env } = await fixture(t);
  const result = await deleteAccount(env, account, request);
  assert.deepEqual(await deleteAccount(env, null, request), result);
  await assert.rejects(deleteAccount(env, null, { ...request, idempotencyKey: "f".repeat(64) }), /unauthorized/);
  await assert.rejects(deleteAccount(env, other, request), /account_changed/);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM ledger WHERE reason='account_deleted'").n, 1);
});

test("concurrent duplicate deletion closes the account exactly once", async t => {
  const { sql, env } = await fixture(t);
  const results = await Promise.all([deleteAccount(env, account, request), deleteAccount(env, account, request)]);
  assert.deepEqual(results[0], results[1]);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_deletion_receipts").n, 1);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM ledger WHERE reason='account_deleted'").n, 1);
});

test("a database failure rolls back the receipt, access revocation, balance and work release together", async t => {
  const { sql, env } = await fixture(t);
  sql.exec("CREATE TRIGGER fail_deletion BEFORE DELETE ON searches BEGIN SELECT RAISE(ABORT,'simulated failure'); END;");
  await assert.rejects(deleteAccount(env, account, request), /simulated failure/);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_deletion_receipts").n, 0);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_cleanup").n, 0);
  assert.equal(row(sql, `SELECT token_hash FROM accounts WHERE id='${account}'`).token_hash, "old-token");
  assert.equal(row(sql, `SELECT units FROM accounts WHERE id='${account}'`).units, 250000);
  assert.equal(row(sql, "SELECT state FROM leases WHERE id='lease-one'").state, "active");
});

test("late recovery, credits, searches, lease assignment and publication cannot reactivate a deleted account", async t => {
  const { sql, env } = await fixture(t);
  await deleteAccount(env, account, request);
  const lateWrites = [
    `UPDATE accounts SET token_hash='new-token' WHERE id='${account}'`,
    `UPDATE accounts SET deleted_at=NULL WHERE id='${account}'`,
    `UPDATE accounts SET units=100000 WHERE id='${account}'`,
    `UPDATE accounts SET recovery_hash='new-recovery' WHERE id='${account}'`,
    `INSERT INTO ledger (account_id,units,reason,reference) VALUES ('${account}',100000,'contribution','late-credit')`,
    `INSERT INTO searches VALUES ('late-search','${account}','late-key','query','private result')`,
    `INSERT INTO leases (id,account_id,lane,expires_at,state) VALUES ('late','${account}','scene',9999,'active')`,
    `UPDATE leases SET state='active' WHERE id='lease-one'`,
    `UPDATE pose_catalog SET assignee='${account}'`,
    `UPDATE scene_qualifications SET expires_at=9999`,
    `UPDATE scene_candidates SET state='published' WHERE lease_id='lease-two'`,
    `UPDATE locations SET active_lease='lease-one' WHERE id=1`,
    `UPDATE locations SET state='published',contributor_id='${account}' WHERE id=1`,
  ];
  for (const query of lateWrites) assert.throws(() => sql.exec(query), /account_not_active/, query);
  // Retained contributed records may still receive ordinary metadata maintenance.
  sql.exec("UPDATE locations SET country='Italy' WHERE id=3");
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM published_index").n, 1);
});

test("cleanup failures remain retryable and cleanup never deletes published or malformed paths", async t => {
  const { sql, env } = await fixture(t);
  await deleteAccount(env, account, request);
  sql.prepare("INSERT INTO account_cleanup VALUES (?,?,1,'pending')").run("four-view-v4/kept.i8", account);
  const removed = [];
  env.INDEX.delete = async () => { throw Error("storage temporarily unavailable"); };
  await cleanupAccountArtifacts(env, account);
  assert.equal(row(sql, `SELECT state FROM account_cleanup WHERE artifact_key='${quarantine}'`).state, "pending");
  assert.equal(row(sql, "SELECT state FROM account_cleanup WHERE artifact_key='four-view-v4/kept.i8'").state, "needs_review");
  env.INDEX.delete = async key => removed.push(key);
  await cleanupAccountArtifacts(env, null, 64);
  assert.deepEqual(removed, [quarantine]);
  assert.equal(row(sql, `SELECT state FROM account_cleanup WHERE artifact_key='${quarantine}'`).state, "removed");
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM published_index").n, 1);
});

test("privacy migration upgrades existing accounts without losing data and may safely run again", async t => {
  const { sql, env } = await fixture(t, true);
  await migrateAccountPrivacy(env);
  assert.equal(row(sql, `SELECT units FROM accounts WHERE id='${account}'`).units, 250000);
  assert.equal((await deleteAccount(env, account, request)).deleted, true);
});

test("deletion requires explicit typed confirmation, a saved nonce, and the matching account", async t => {
  const { sql, env } = await fixture(t);
  for (const body of [{ ...request, confirmation: "delete" }, { ...request, idempotencyKey: "guessable" }]) {
    await assert.rejects(deleteAccount(env, account, body), /invalid_account_deletion/);
  }
  await assert.rejects(deleteAccount(env, null, request), /unauthorized/);
  await assert.rejects(deleteAccount(env, other, request), /account_changed/);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_deletion_receipts").n, 0);
});
