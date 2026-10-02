// Real local workerd/D1/R2; synthetic accounts only, no external resources.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(process.argv[2])));
const scriptPath = resolve(process.argv[3]);
const options = { modules: true, scriptPath, modulesRoot: dirname(scriptPath),
  compatibilityDate: "2026-10-02", compatibilityFlags: ["nodejs_compat"],
  d1Databases: ["DB"], r2Buckets: ["INDEX"], bindings: {
    DEPLOYMENT_ENVIRONMENT: "staging", INDEX_BUCKET_NAME: "vision-community-staging",
    DELETION_ARCHIVE_REQUIRED: "1", DELETION_ARCHIVE_ENVIRONMENT: "staging",
    DELETION_ARCHIVE_DB_ID: "17043cb7-5dab-4a6f-84ca-19ae1c14cc05",
  }, serviceBindings: { ASSETS: () => new Response(null, { status: 404 }) } };
const instance = new Miniflare(convertV4MiniflareOptions(options));
const sha = value => createHash("sha256").update(value).digest("hex");
async function deleted(accountId, token, key) {
  return instance.dispatchFetch("https://community.invalid/api/account/delete", {
    method: "POST", headers: { "content-type": "application/json", ...(token ? { authorization: "Bearer " + token } : {}) },
    body: JSON.stringify({ accountId, confirmation: "DELETE", idempotencyKey: key }),
  });
}
try {
  const db = await instance.getD1Database("DB"), bucket = await instance.getR2Bucket("INDEX");
  const schema = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
  for (const statement of schema.split(";").filter(part => part.trim())) await db.prepare(statement).run();
  assert.equal((await instance.dispatchFetch("https://community.invalid/api/status")).status, 200);
  const account = "a".repeat(32), token = "synthetic-local-token-one", key = "c".repeat(64);
  await db.prepare("INSERT INTO accounts (id,token_hash,units) VALUES (?,?,200000)").bind(account, sha(token)).run();
  const response = await deleted(account, token, key);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { deleted: true, contributionsRetained: true, unitsForfeited: 200000 });
  const archiveKey = `privacy/account-deletions/v1/${sha(account)}.json`;
  const archived = await bucket.get(archiveKey);
  assert.ok(archived);
  assert.equal(archived.customMetadata.visionDeletionReceipt, "1");
  const data = await archived.text();
  assert.equal(sha(data), archived.customMetadata.sha256);
  assert.equal(JSON.parse(data).resource.bucket, "vision-community-staging");
  assert.equal(JSON.parse(data).receipt.requestKey, key);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM account_deletion_archives").first()).n, 1);
  assert.equal((await deleted(account, null, key)).status, 200);
  assert.equal((await deleted(account, null, "f".repeat(64))).status, 401);

  // Deliberately damaged LOCAL object forces a committed revocation with an
  // unacknowledged archive. The real scheduled handler drains that outbox after
  // this synthetic storage fault is removed. Nothing is changed in Cloudflare.
  const other = "b".repeat(32), otherToken = "synthetic-local-token-two";
  await db.prepare("INSERT INTO accounts (id,token_hash,units) VALUES (?,?,50000)").bind(other, sha(otherToken)).run();
  const otherKey = `privacy/account-deletions/v1/${sha(other)}.json`;
  await bucket.put(otherKey, "synthetic damaged local archive");
  const failed = await deleted(other, otherToken, "d".repeat(64));
  assert.equal(failed.status, 503);
  assert.deepEqual(await failed.json(), { error: "deletion_archive_unavailable" });
  assert.equal((await db.prepare("SELECT units FROM accounts WHERE id=?").bind(other).first()).units, 0);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM account_deletion_archives").first()).n, 1);
  await bucket.delete(otherKey);
  await (await instance.getWorker()).scheduled({ cron: "0 * * * *" });
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM account_deletion_archives").first()).n, 2);
  assert.ok(await bucket.get(otherKey));
  assert.equal((await deleted(other, null, "d".repeat(64))).status, 200);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='account_deleted'").first()).n, 2);
  console.log(JSON.stringify({ status: "ACTUAL_WORKERD_D1_R2_DELETION_ARCHIVE_PASSED",
    syntheticAccounts: 2, archiveReadback: true, lostResponseReplay: true,
    corruptedArchiveRejected: true, scheduledRecovery: true, liveRestore: false }));
} finally { await instance.dispose(); }
