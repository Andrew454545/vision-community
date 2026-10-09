import assert from "node:assert/strict";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, truncateSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { RESOURCE_PROFILES } from "../tools/account-restore.mjs";
import { checkPrivacyStorage, planPrivacyStorage, privacyObjectCacheName } from "../tools/privacy-storage-restore.mjs";
import { PRIVACY_TABLES, deleteAccount, cleanupAccountArtifacts, migrateAccountPrivacy } from "./accountPrivacy.js";

const account = "a".repeat(32), other = "b".repeat(32), lease = "d".repeat(32);
const key = `four-view-v4/${lease}.i8`, quarantine = `scene-quarantine/${lease}/${"e".repeat(64)}.i8`;
const sha = raw => createHash("sha256").update(raw).digest("hex");
const encoded = value => Buffer.from(JSON.stringify(value) + "\n");
const receipt = { accountId: account, requestKey: "c".repeat(64), deletedAt: 150, unitsForfeited: 100 };
const archive = environment => encoded({ version: 1, scope: "vision-community-account-deletion",
  resource: RESOURCE_PROFILES[environment], receipt });
function fixture(t, change = () => {}, environment = "staging") {
  const root = mkdtempSync(join(tmpdir(), "vision-private-storage-")); t.after(() => rmSync(root, { recursive: true, force: true }));
  const current = join(root, "current.sqlite"), sql = new DatabaseSync(current);
  sql.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  sql.exec("ALTER TABLE pose_catalog ADD COLUMN assignee TEXT; ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER");
  for (const statement of PRIVACY_TABLES) sql.exec(statement);
  sql.prepare("INSERT INTO accounts (id,token_hash,recovery_hash,units,deleted_at) VALUES (?,?,NULL,0,150)").run(account, "revoked-token");
  sql.prepare("INSERT INTO accounts (id,token_hash,units) VALUES (?,?,40)").run(other, "retained-token");
  sql.prepare("INSERT INTO account_deletion_receipts VALUES (?,?,150,100)").run(account, receipt.requestKey);
  sql.prepare("INSERT INTO account_deletion_archives VALUES (?,?,160)").run(account, sha(archive(environment)));
  sql.prepare("INSERT INTO leases (id,account_id,lane,expires_at,state) VALUES (?,?,'scene',100,'expired')").run(lease, account);
  sql.prepare("INSERT INTO account_artifact_writes VALUES (?,?,?,?,?,150)").run(key, account, lease, "f".repeat(64), 123);
  sql.prepare("INSERT INTO account_cleanup VALUES (?,?,150,'fenced')").run(key, account);
  change(sql, { root, current }); sql.close();
  return { root, current, currentSha256: sha(readFileSync(current)), environment, notBefore: 100, now: 210, out: join(root, "plan") };
}
function setup(t, change, environment) {
  const options = fixture(t, change, environment), report = planPrivacyStorage(options);
  const plan = join(options.out, "privacy-object-plan.private.json"), cache = join(options.root, "cache"); mkdirSync(cache);
  // Independent expected worker bytes/metadata, not copied from the generated plan.
  const bodies = [
    { key: `privacy/account-deletions/v1/${sha(Buffer.from(account))}.json`, body: archive(options.environment),
      httpMetadata: { contentType: "application/json", cacheControl: "no-store" }, customMetadata: { visionDeletionReceipt: "1", sha256: sha(archive(options.environment)) } },
    { key, body: Buffer.from("VISION COMMUNITY PRIVACY FENCE\n"),
      httpMetadata: { contentType: "application/x-vision-privacy-fence", cacheControl: "no-store" }, customMetadata: { visionPrivacyFence: "1" } },
  ];
  const observed = { version: 1, scope: "vision-community-privacy-object-cache", resource: RESOURCE_PROFILES[options.environment], exportedAt: 200,
    objects: bodies.map(({ body, ...metadata }) => ({ ...metadata, size: body.length, sha256: sha(body) })) };
  for (const object of bodies) writeFileSync(join(cache, privacyObjectCacheName(object.key)), object.body);
  const inventory = join(options.root, "observed.private.json"); writeFileSync(inventory, encoded(observed));
  return { ...options, out: join(options.root, "check"), plan, planSha256: report.planSha256,
    inventory, inventorySha256: sha(readFileSync(inventory)), observed, cache };
}
function fails(options, fn = checkPrivacyStorage) {
  assert.throws(() => fn(options));
  assert.equal(existsSync(join(options.out, fn === checkPrivacyStorage ? "privacy-storage-report.json" : "privacy-plan-report.json")), false);
}
function fileLink(t, target, path) {
  try { symlinkSync(target, path, "file"); return true; }
  catch (error) {
    if (process.platform === "win32" && ["EPERM", "EACCES"].includes(error.code)) {
      t.skip("Windows file-symlink privilege is unavailable; directory-junction checks run separately");
      return false;
    }
    throw error;
  }
}
for (const environment of ["production", "staging"]) test(`independently cached privacy bytes verify for ${environment} without live approval`, t => {
  const options = setup(t, undefined, environment), original = readFileSync(options.current), result = checkPrivacyStorage(options);
  assert.equal(result.complete, true); assert.equal(result.objectsVerified, true);
  assert.equal(result.deletionReceipts, 1); assert.equal(result.privacyFences, 1);
  assert.equal(result.liveReady, false); assert.equal(result.productionQualified, false); assert.equal(result.creditRecoveryVerified, false);
  assert.deepEqual(readFileSync(options.current), original);
  assert.ok(!JSON.stringify(result).includes(account) && !JSON.stringify(result).includes(receipt.requestKey));
});

const databaseFaults = {
  missing_receipt: "DELETE FROM account_deletion_archives; DELETE FROM account_deletion_receipts",
  changed_receipt_date: "UPDATE account_deletion_receipts SET deleted_at=149",
  missing_archive: "DELETE FROM account_deletion_archives",
  changed_archive: "UPDATE account_deletion_archives SET sha256='bad'",
  future_archive: "UPDATE account_deletion_archives SET archived_at=300",
  resurrected_credit: "UPDATE accounts SET units=1 WHERE deleted_at IS NOT NULL",
  resurrected_recovery: "UPDATE accounts SET recovery_hash='secret' WHERE deleted_at IS NOT NULL",
  resurrected_search: `INSERT INTO searches VALUES ('old','${account}','key','private query','{}')`,
  missing_cleanup_for_intent: "DELETE FROM account_cleanup",
  pending_cleanup: "UPDATE account_cleanup SET state='pending'",
  removed_cleanup: "UPDATE account_cleanup SET state='removed'",
  review_cleanup: "UPDATE account_cleanup SET state='needs_review'",
  retained_without_publication: "UPDATE account_cleanup SET state='retained'",
  wrong_owner: `UPDATE account_cleanup SET account_id='${other}'`,
  wrong_lease_owner: `UPDATE leases SET account_id='${other}'`,
  wrong_lease_lane: "UPDATE leases SET lane='object'",
  wrong_intent_owner: `UPDATE account_artifact_writes SET account_id='${other}'`,
  wrong_intent_lease: "UPDATE account_artifact_writes SET lease_id='invalid'",
  missing_final_intent: "DELETE FROM account_artifact_writes",
  unknown_key: "UPDATE account_cleanup SET artifact_key='unrelated/private-key'",
};
for (const [name, statement] of Object.entries(databaseFaults)) test(`incomplete current privacy state is refused: ${name}`, t => {
  const options = fixture(t, sql => sql.exec(statement)); fails(options, planPrivacyStorage);
});
test("legacy quarantine can be fenced without a new intent journal", t => {
  const options = fixture(t, sql => {
    sql.exec("DELETE FROM account_artifact_writes"); sql.prepare("UPDATE account_cleanup SET artifact_key=?").run(quarantine);
  }); assert.equal(planPrivacyStorage(options).privacyFences, 1);
});
test("published retained contributions are preserved and excluded from privacy fences", t => {
  const options = fixture(t, sql => {
    sql.exec(`INSERT INTO locations (id,asset_id,capture,lane,model,state) VALUES (1,'saved','synthetic','scene','synthetic','published')`);
    sql.prepare("INSERT INTO published_index (location_id,index_text,output_sha256,published_at,four_view_key) VALUES (1,'','hash',160,?)").run(key);
    sql.exec("UPDATE account_cleanup SET state='retained'");
  }); assert.equal(planPrivacyStorage(options).privacyFences, 0);
});
test("a fence at a published contribution is refused", t => {
  const options = fixture(t, sql => {
    sql.exec(`INSERT INTO locations (id,asset_id,capture,lane,model,state) VALUES (1,'saved','synthetic','scene','synthetic','published')`);
    sql.prepare("INSERT INTO published_index (location_id,index_text,output_sha256,published_at,four_view_key) VALUES (1,'','hash',160,?)").run(key);
  }); fails(options, planPrivacyStorage);
});
const inventoryFaults = {
  missing_object: o => o.objects.pop(), duplicate: o => { o.objects[1] = o.objects[0]; },
  foreign_key: o => { o.objects[0].key = "different-private-key"; },
  changed_size: o => { o.objects[0].size++; }, changed_hash: o => { o.objects[0].sha256 = "0".repeat(64); },
  missing_metadata: o => { delete o.objects[0].customMetadata; },
  changed_fence_metadata: o => { o.objects[1].customMetadata.visionPrivacyFence = "0"; },
  changed_content_type: o => { o.objects[0].httpMetadata.contentType = "text/plain"; },
  changed_cache_control: o => { o.objects[1].httpMetadata.cacheControl = "public"; },
  old_export: o => { o.exportedAt = 99; }, future_export: o => { o.exportedAt = 211; },
  wrong_scope: o => { o.scope = "other"; }, wrong_resource: o => { o.resource = RESOURCE_PROFILES.production; },
};
for (const [name, change] of Object.entries(inventoryFaults)) test(`observed inventory is independently checked: ${name}`, t => {
  const options = setup(t); change(options.observed); writeFileSync(options.inventory, encoded(options.observed));
  options.inventorySha256 = sha(readFileSync(options.inventory)); fails(options);
});
for (const mode of ["missing", "changed", "truncated", "linked"]) test(`cached private object refuses ${mode} payload`, t => {
  const options = setup(t), p = join(options.cache, privacyObjectCacheName(key));
  if (mode === "changed") writeFileSync(p, "changed");
  if (mode === "truncated") truncateSync(p, 2);
  if (mode === "missing") rmSync(p);
  if (mode === "linked") { rmSync(p); if (!fileLink(t, options.current, p)) return; }
  fails(options);
});
test("a repinned plan cannot omit an object present in the pinned current database", t => {
  const options = setup(t), d = JSON.parse(readFileSync(options.plan)); d.objects.pop();
  writeFileSync(options.plan, encoded(d)); options.planSha256 = sha(readFileSync(options.plan)); fails(options);
});
test("changed source database and existing output cannot be overwritten", t => {
  const options = setup(t); writeFileSync(join(options.root, "plan/current.sqlite"), "changed private database"); fails(options);
  const original = readFileSync(options.inventory); fails({ ...options, out: options.cache }); assert.deepEqual(readFileSync(options.inventory), original);
});
test("database sidecars fail before a successful report", t => {
  const options = fixture(t); writeFileSync(options.current + "-wal", "unhashed WAL"); fails(options, planPrivacyStorage);
});
test("linked source fails before a successful report", t => {
  const options = fixture(t), link = join(options.root, "alias.sqlite");
  if (!fileLink(t, options.current, link)) return;
  fails({ ...options, current: link, out: join(options.root, "linked-plan") }, planPrivacyStorage);
});
test("a linked database parent is refused without file-symlink privilege", t => {
  const options = fixture(t), source = join(options.root, "source"), alias = join(options.root, "source-alias");
  mkdirSync(source); writeFileSync(join(source, "current.sqlite"), readFileSync(options.current));
  symlinkSync(source, alias, "junction");
  fails({ ...options, current: join(alias, "current.sqlite") }, planPrivacyStorage);
});
test("a linked cache directory is refused without file-symlink privilege", t => {
  const options = setup(t), alias = join(options.root, "cache-alias");
  symlinkSync(options.cache, alias, "junction");
  fails({ ...options, cache: alias });
});
test("closed WAL-mode export remains read-only and creates no sidecars", t => {
  const options = fixture(t, sql => sql.exec("PRAGMA journal_mode=WAL")); planPrivacyStorage(options);
  for (const prefix of [options.current, join(options.out, "current.sqlite")])
    for (const suffix of ["-wal", "-shm", "-journal"]) assert.equal(existsSync(prefix + suffix), false);
});
test("CLI sanitizes raw SQLite errors and private paths", t => {
  const options = fixture(t); writeFileSync(options.current, "private-token secret query invalid SQLite");
  const script = fileURLToPath(new URL("../tools/privacy-storage-restore.mjs", import.meta.url));
  const result = spawnSync(process.execPath, [script, "plan", "--current", options.current, "--current-sha256", sha(readFileSync(options.current)),
    "--writers-stopped-at", "100", "--environment", "staging", "--out", options.out], { encoding: "utf8" });
  assert.equal(result.status, 1); const report = JSON.parse(result.stdout); assert.equal(report.complete, false);
  assert.ok(!result.stdout.includes(options.root) && !result.stdout.includes("private-token") && !result.stdout.includes("secret query"));
});
function d1(sql) {
  return { prepare(query) {
    const statement = (args = []) => ({ bind: (...bound) => statement(bound),
      first: async () => sql.prepare(query).get(...args) || null,
      all: async () => ({ results: sql.prepare(query).all(...args) }),
      run: async () => statement(args).execute(),
      execute: () => ({ success: true, meta: { changes: Number(sql.prepare(query).run(...args).changes) } }),
    }); return statement();
  }, async batch(statements) {
    sql.exec("BEGIN IMMEDIATE");
    try { const rows = statements.map(s => s.execute()); sql.exec("COMMIT"); return rows; }
    catch (error) { sql.exec("ROLLBACK"); throw error; }
  } };
}
test("real deletion/archive/cleanup worker outputs pass the independent offline reader", async t => {
  const options = fixture(t, sql => {
    sql.exec("DELETE FROM account_deletion_archives; DELETE FROM account_deletion_receipts; DELETE FROM account_cleanup");
    sql.prepare("UPDATE accounts SET deleted_at=NULL,units=100,recovery_hash='active-recovery' WHERE id=?").run(account);
    sql.prepare("UPDATE leases SET state='active' WHERE id=?").run(lease);
  });
  const sql = new DatabaseSync(options.current), objects = new Map();
  t.after(() => { if (sql.isOpen) sql.close(); });
  const env = { DB: d1(sql), DELETION_ARCHIVE_REQUIRED: "1", DELETION_ARCHIVE_ENVIRONMENT: "staging",
    INDEX_BUCKET_NAME: RESOURCE_PROFILES.staging.bucket, DELETION_ARCHIVE_DB_ID: RESOURCE_PROFILES.staging.databaseId,
    INDEX: { async get(key) {
      const value = objects.get(key); return value && { size: value.body.length, body: new Blob([value.body]).stream() };
    }, async put(key, body, metadata) {
      if (metadata.onlyIf && objects.has(key)) return null;
      const raw = Buffer.from(body); objects.set(key, { body: raw, ...metadata }); return { size: raw.length };
    } },
  };
  await migrateAccountPrivacy(env);
  await deleteAccount(env, account, { accountId: account, confirmation: "DELETE", idempotencyKey: receipt.requestKey }, 150);
  await cleanupAccountArtifacts(env); sql.close();
  const now = Math.floor(Date.now() / 1000) + 1;
  const report = planPrivacyStorage({ ...options, currentSha256: sha(readFileSync(options.current)), now });
  const cache = join(options.root, "actual-cache"); mkdirSync(cache);
  const observed = { version: 1, scope: "vision-community-privacy-object-cache", resource: RESOURCE_PROFILES.staging,
    exportedAt: now, objects: [...objects].map(([key, value]) => ({ key, size: value.body.length, sha256: sha(value.body),
      httpMetadata: value.httpMetadata, customMetadata: value.customMetadata })) };
  for (const [key, value] of objects) writeFileSync(join(cache, privacyObjectCacheName(key)), value.body);
  const inventory = join(options.root, "actual-inventory.private.json"); writeFileSync(inventory, encoded(observed));
  const result = checkPrivacyStorage({ plan: join(options.out, "privacy-object-plan.private.json"), planSha256: report.planSha256,
    inventory, inventorySha256: sha(readFileSync(inventory)), cache, now, environment: options.environment, out: join(options.root, "actual-check") });
  assert.equal(result.deletionReceipts, 1); assert.equal(result.privacyFences, 1); assert.equal(result.objectsVerified, true);
});
for (const mutation of ["early_cached_payload", "plan_database"]) test(`late changes cannot yield completion: ${mutation}`, t => {
  const options = setup(t); options.observed.objects.reverse(); writeFileSync(options.inventory, encoded(options.observed));
  options.inventorySha256 = sha(readFileSync(options.inventory));
  const marker = join(options.cache, privacyObjectCacheName(key));
  const archiveFile = join(options.cache, privacyObjectCacheName(options.observed.objects[1].key));
  const originalOpen = fs.openSync, originalRead = fs.readSync, descriptors = new Map(); let changed = false;
  t.mock.method(fs, "openSync", (...args) => { const fd = originalOpen(...args); descriptors.set(fd, String(args[0])); return fd; });
  t.mock.method(fs, "readSync", (...args) => {
    const count = originalRead(...args);
    if (count && !changed && descriptors.get(args[0]) === archiveFile) {
      changed = true; writeFileSync(mutation === "early_cached_payload" ? marker : join(options.root, "plan/current.sqlite"), "late private change");
    } return count;
  });
  syncBuiltinESMExports();
  try { fails(options); assert.equal(changed, true); }
  finally { t.mock.restoreAll(); syncBuiltinESMExports(); }
});
test("outputs cannot overlap the pinned plan or cached objects", t => {
  const options = setup(t); fails({ ...options, out: join(options.cache, "nested-check") });
  fails({ ...options, out: join(options.root, "plan/nested-check") });
});
test("oversized database input is rejected without reading it", t => {
  const options = fixture(t); truncateSync(options.current, 512 * 1024 ** 2 + 1); fails(options, planPrivacyStorage);
});
