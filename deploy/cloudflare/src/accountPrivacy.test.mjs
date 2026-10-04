import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { deleteAccount, cleanupAccountArtifacts, migrateAccountPrivacy, archiveAccountDeletionReceipts } from "./accountPrivacy.js";
import { PRIVACY_FENCE } from "./artifactWrites.js";

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
    ('${"d".repeat(32)}','${account}','scene',9999,'submitted'),
    ('lease-published','${account}','scene',9999,'submitted'),
    ('lease-other','${other}','scene',9999,'active');
    INSERT INTO lease_items VALUES ('lease-one',1),('${"d".repeat(32)}',2),('lease-published',3),('lease-other',4);
    INSERT INTO scene_qualifications VALUES ('qualified','${account}','profile','policy','digest',9999,1);
    INSERT INTO scene_candidates VALUES
    ('${"d".repeat(32)}','${account}','qualified','policy','digest','${quarantine}','[{"private":"metadata"}]',1,'pending'),
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

function requiredArchive(env) {
  Object.assign(env, { DELETION_ARCHIVE_REQUIRED: "1", DELETION_ARCHIVE_ENVIRONMENT: "staging",
    INDEX_BUCKET_NAME: "vision-community-staging", DELETION_ARCHIVE_DB_ID: "17043cb7-5dab-4a6f-84ca-19ae1c14cc05" });
  const values = new Map(), writes = [], controls = { failPut: false, failGet: false, corruptRead: false };
  env.INDEX = {
    async get(key) {
      if (controls.failGet) throw Error("private R2 details");
      if (!values.has(key)) return null;
      const bytes = values.get(key);
      return { size: bytes.byteLength,
        body: new Blob([controls.corruptRead ? new Uint8Array(bytes).fill(0) : bytes]).stream() };
    },
    async put(key, bytes, options) {
      if (controls.failPut) throw Error("private R2 credentials and path");
      assert.deepEqual(options.onlyIf, { etagDoesNotMatch: "*" });
      if (values.has(key)) return null;
      values.set(key, new Uint8Array(bytes)); writes.push({ key, options });
      return { key, size: bytes.byteLength };
    },
  };
  return { values, writes, controls };
}

test("required deletion archive is read back privately before success and retries are immutable", async t => {
  const { env, sql } = await fixture(t);
  const { values, writes } = requiredArchive(env);
  const result = await deleteAccount(env, account, request, 1234);
  assert.equal(result.deleted, true);
  assert.equal(writes.length, 1);
  assert.match(writes[0].key, /^privacy\/account-deletions\/v1\/[a-f0-9]{64}\.json$/);
  assert.ok(!writes[0].key.includes(account));
  assert.deepEqual(Object.keys(writes[0].options.customMetadata).sort(), ["sha256", "visionDeletionReceipt"]);
  const archived = JSON.parse(new TextDecoder().decode([...values.values()][0]));
  assert.equal(archived.resource.bucket, "vision-community-staging");
  assert.deepEqual(archived.receipt, { accountId: account, requestKey: request.idempotencyKey,
    deletedAt: 1234, unitsForfeited: 250000 });
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_deletion_archives").n, 1);
  assert.deepEqual(await deleteAccount(env, null, request, 2345), result);
  assert.equal(writes.length, 1);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM ledger WHERE reason='account_deleted'").n, 1);
});

test("archive outage preserves revocation and recovers with the exact lost-response request", async t => {
  const { env, sql } = await fixture(t);
  const { controls, writes } = requiredArchive(env);
  controls.failPut = true;
  await assert.rejects(deleteAccount(env, account, request, 1234), failure => failure.message === "deletion_archive_unavailable" && failure.status === 503);
  assert.equal(row(sql, `SELECT units FROM accounts WHERE id='${account}'`).units, 0);
  assert.equal(row(sql, `SELECT recovery_hash FROM accounts WHERE id='${account}'`).recovery_hash, null);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_deletion_archives").n, 0);
  controls.failPut = false;
  await assert.rejects(deleteAccount(env, null, { ...request, idempotencyKey: "f".repeat(64) }), failure => failure.status === 401);
  assert.equal(writes.length, 0);
  assert.equal((await deleteAccount(env, null, request)).deleted, true);
  assert.equal(writes.length, 1);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM ledger WHERE reason='account_deleted'").n, 1);
});

test("damaged archive readback cannot be acknowledged, marked or overwritten", async t => {
  const { env, sql } = await fixture(t);
  const { controls, writes } = requiredArchive(env);
  controls.corruptRead = true;
  await assert.rejects(deleteAccount(env, account, request), failure => failure.status === 503);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_deletion_archives").n, 0);
  await assert.rejects(deleteAccount(env, null, request), failure => failure.status === 503);
  assert.equal(writes.length, 1);
  controls.corruptRead = false;
  assert.equal((await deleteAccount(env, null, request)).deleted, true);
  assert.equal(writes.length, 1);
});

test("required wrong bucket, database or profile refuses deletion before credentials change", async t => {
  for (const changed of [{ INDEX_BUCKET_NAME: "geonections-images" },
    { DELETION_ARCHIVE_DB_ID: "different-database" }, { DELETION_ARCHIVE_ENVIRONMENT: "toString" }]) {
    const { env, sql } = await fixture(t);
    const { writes } = requiredArchive(env);
    Object.assign(env, changed);
    await assert.rejects(deleteAccount(env, account, request), failure => failure.status === 503);
    assert.equal(row(sql, `SELECT token_hash FROM accounts WHERE id='${account}'`).token_hash, "old-token");
    assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_deletion_receipts").n, 0);
    assert.equal(writes.length, 0);
  }
});

test("scheduled outbox resumes archived deletions after an outage without new account requests", async t => {
  const { env, sql } = await fixture(t);
  const { controls, writes } = requiredArchive(env);
  controls.failPut = true;
  await assert.rejects(deleteAccount(env, account, request), failure => failure.status === 503);
  assert.deepEqual(await archiveAccountDeletionReceipts(env), { enabled: true, archived: 0 });
  controls.failPut = false;
  assert.deepEqual(await archiveAccountDeletionReceipts(env), { enabled: true, archived: 1 });
  assert.deepEqual(await archiveAccountDeletionReceipts(env), { enabled: true, archived: 0 });
  assert.equal(writes.length, 1);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_deletion_archives").n, 1);
});

test("a failed archive acknowledgement resumes from the immutable R2 copy without overwriting it", async t => {
  const { env, sql } = await fixture(t);
  const { writes } = requiredArchive(env);
  const prepare = env.DB.prepare.bind(env.DB);
  let failed = false;
  env.DB.prepare = query => {
    if (query.startsWith("INSERT OR IGNORE INTO account_deletion_archives") && !failed) {
      failed = true;
      return { bind: () => ({ run: async () => { throw Error("private D1 failure details"); } }) };
    }
    return prepare(query);
  };
  await assert.rejects(deleteAccount(env, account, request), failure => failure.status === 503);
  assert.equal(writes.length, 1);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_deletion_archives").n, 0);
  assert.equal((await deleteAccount(env, null, request)).deleted, true);
  assert.equal(writes.length, 1);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM account_deletion_archives").n, 1);
});
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
  assert.equal(row(sql, `SELECT records_json FROM scene_candidates WHERE lease_id='${"d".repeat(32)}'`).records_json, "[]");
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
    `UPDATE scene_candidates SET state='published' WHERE lease_id='${"d".repeat(32)}'`,
    `UPDATE locations SET active_lease='lease-one' WHERE id=1`,
    `UPDATE locations SET state='published',contributor_id='${account}' WHERE id=1`,
  ];
  for (const query of lateWrites) assert.throws(() => sql.exec(query), /account_not_active/, query);
  // Retained contributed records may still receive ordinary metadata maintenance.
  sql.exec("UPDATE locations SET country='Italy' WHERE id=3");
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM published_index").n, 1);
});

test("cleanup failures remain retryable and cleanup never fences published or malformed paths", async t => {
  const { sql, env } = await fixture(t);
  await deleteAccount(env, account, request);
  sql.prepare("INSERT INTO account_cleanup VALUES (?,?,1,'pending')").run("four-view-v4/kept.i8", account);
  const fenced = [];
  env.INDEX.put = async () => { throw Error("storage temporarily unavailable"); };
  await cleanupAccountArtifacts(env, account);
  assert.equal(row(sql, `SELECT state FROM account_cleanup WHERE artifact_key='${quarantine}'`).state, "pending");
  assert.equal(row(sql, "SELECT state FROM account_cleanup WHERE artifact_key='four-view-v4/kept.i8'").state, "needs_review");
  env.INDEX.put = async key => { fenced.push(key); return { size: PRIVACY_FENCE.length }; };
  await cleanupAccountArtifacts(env, null, 64);
  assert.deepEqual(fenced, [quarantine]);
  assert.equal(row(sql, `SELECT state FROM account_cleanup WHERE artifact_key='${quarantine}'`).state, "fenced");
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM published_index").n, 1);
});

test("privacy migration upgrades existing accounts without losing data and may safely run again", async t => {
  const { sql, env } = await fixture(t, true);
  await migrateAccountPrivacy(env);
  assert.equal(row(sql, `SELECT units FROM accounts WHERE id='${account}'`).units, 250000);
  assert.equal((await deleteAccount(env, account, request)).deleted, true);
});

test("an unconfirmed fence write remains pending instead of claiming privacy cleanup", async t => {
  const { sql, env } = await fixture(t);
  await deleteAccount(env, account, request);
  for (const response of [null, undefined, { size: 1 }]) {
    env.INDEX.put = async () => response;
    await cleanupAccountArtifacts(env);
    assert.equal(row(sql, "SELECT state FROM account_cleanup").state, "pending");
  }
});

test("upgrading the cleanup protocol requeues old removals atomically and only once", async t => {
  const { sql, env } = await fixture(t);
  await deleteAccount(env, account, request);
  sql.exec("DROP TRIGGER artifact_write_intent_immutable; UPDATE account_cleanup SET state='removed'");
  const ordinaryBatch = env.DB.batch;
  env.DB.batch = statements => ordinaryBatch([...statements,
    env.DB.prepare("INSERT INTO missing_migration_table VALUES (1)")]);
  await assert.rejects(migrateAccountPrivacy(env), /missing_migration_table/);
  assert.equal(row(sql, "SELECT COUNT(*) AS n FROM sqlite_master WHERE name='artifact_write_intent_immutable'").n, 0);
  assert.equal(row(sql, "SELECT state FROM account_cleanup").state, "removed");
  env.DB.batch = ordinaryBatch;
  await migrateAccountPrivacy(env);
  assert.equal(row(sql, "SELECT state FROM account_cleanup").state, "pending");
  sql.exec("UPDATE account_cleanup SET state='fenced'");
  await migrateAccountPrivacy(env);
  assert.equal(row(sql, "SELECT state FROM account_cleanup").state, "fenced");
});

test("legacy quarantine cleanup requires an owned scene lease, even without a write intent", async t => {
  const { sql, env } = await fixture(t);
  await deleteAccount(env, account, request);
  const fenced = [];
  env.INDEX.put = async key => fenced.push(key);
  // Corrupt legacy provenance must not cross an account boundary or lane.
  for (const override of [{ owner: other, lane: "scene" }, { owner: account, lane: "object" }]) {
    sql.prepare("UPDATE leases SET account_id=?,lane=? WHERE id=?").run(override.owner, override.lane, "d".repeat(32));
    sql.exec("UPDATE account_cleanup SET state='pending'");
    await cleanupAccountArtifacts(env);
    assert.equal(row(sql, "SELECT state FROM account_cleanup").state, "needs_review");
  }
  assert.deepEqual(fenced, []);
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
