// Offline operator evidence only. No provider calls, live writes or admission.
import { createHash } from "node:crypto";
import { chmodSync, closeSync, constants, copyFileSync, existsSync, fsyncSync, lstatSync, mkdirSync,
  openSync, readFileSync, readSync, writeFileSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { DatabaseSync } from "node:sqlite";
import { exportDeletionLedger, RESOURCE_PROFILES, RestoreError } from "./account-restore.mjs";
import { PRIVACY_FENCE, sceneArtifactLease } from "../src/artifactWrites.js";

const HEX = /^[0-9a-f]{64}$/, ACCOUNT = /^[0-9a-f]{32}$/;
const MAX_DATABASE = 512 * 1024 ** 2, MAX_JSON = 64 * 1024 ** 2, MAX_OBJECTS = 110000;
const encoded = value => Buffer.from(JSON.stringify(value) + "\n");
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const integer = value => Number.isSafeInteger(value) && value >= 0;
export class PrivacyStorageError extends Error {}
function require(value, code) { if (!value) throw new PrivacyStorageError(code); }
function regular(path, directory = false) {
  path = resolve(path);
  for (let p = path; ; p = dirname(p)) {
    const info = lstatSync(p);
    require(!info.isSymbolicLink() && (p === path ? directory ? info.isDirectory() : info.isFile() : info.isDirectory()), "unsafe_input_path");
    if (dirname(p) === p) break;
  }
  return path;
}
function digestFile(path, maximum) {
  regular(path); require(lstatSync(path).size <= maximum, "input_too_large");
  const fd = openSync(path, "r"), buffer = Buffer.alloc(1024 ** 2), hash = createHash("sha256");
  let total = 0;
  try {
    for (let count; (count = readSync(fd, buffer, 0, buffer.length, null)); ) {
      total += count; require(total <= maximum, "input_too_large"); hash.update(buffer.subarray(0, count));
    }
  } finally { closeSync(fd); }
  return hash.digest("hex");
}
function pinned(path, pin, maximum) {
  require(HEX.test(pin || "") && digestFile(path, maximum) === pin, "input_checksum_mismatch");
}
function readJson(path, pin) {
  pinned(path, pin, MAX_JSON); const raw = readFileSync(path);
  require(raw.length <= MAX_JSON && sha(raw) === pin, "input_checksum_mismatch");
  return JSON.parse(raw.toString("utf8"));
}
function writeNew(path, raw) {
  writeFileSync(path, raw, { flag: "wx", mode: 0o600 });
  const fd = openSync(path, "r+"); try { fsyncSync(fd); } finally { closeSync(fd); }
}
function closed(path) {
  require(!["-wal", "-shm", "-journal"].some(suffix => existsSync(path + suffix)), "database_not_closed");
}
function privateCopy(input, pin, out) {
  input = regular(input); closed(input); pinned(input, pin, MAX_DATABASE);
  const copy = join(out, "current.sqlite"); copyFileSync(input, copy, constants.COPYFILE_EXCL); chmodSync(copy, 0o600);
  const fd = openSync(copy, "r+"); try { fsyncSync(fd); } finally { closeSync(fd); }
  closed(input); pinned(copy, pin, MAX_DATABASE); pinned(input, pin, MAX_DATABASE);
  // immutable avoids SQLite creating a SHM/WAL while reading a closed WAL-mode export.
  const sql = new DatabaseSync(pathToFileURL(copy).href + "?immutable=1", { readOnly: true, allowExtension: false });
  try {
    sql.exec("PRAGMA trusted_schema=OFF; PRAGMA foreign_keys=ON");
    require(sql.prepare("PRAGMA integrity_check").all().every(row => row.integrity_check === "ok")
      && !sql.prepare("PRAGMA foreign_key_check").all().length, "database_integrity_failure");
  } catch (failure) { sql.close(); throw failure; }
  return { sql, copy, input };
}
function freshOutput(out) {
  out = resolve(out); regular(dirname(out), true); mkdirSync(out, { mode: 0o700 }); return out;
}
function resourceMatches(value, resource) {
  return value && !Array.isArray(value) && Object.keys(value).length === 3
    && Object.entries(resource).every(([k, v]) => value[k] === v);
}
function clock(notBefore, now, environment) {
  require(integer(notBefore) && integer(now) && notBefore <= now && ["production", "staging"].includes(environment), "invalid_storage_profile");
  return RESOURCE_PROFILES[environment];
}
function expectedObjects(sql, notBefore, now, environment) {
  const resource = clock(notBefore, now, environment);
  require(sql.prepare("SELECT count(*) AS n FROM account_deletion_receipts").get().n <= 10000
    && sql.prepare("SELECT count(*) AS n FROM accounts WHERE deleted_at IS NOT NULL").get().n <= 10000, "storage_object_limit");
  const ledger = exportDeletionLedger(sql, now, environment), objects = [];
  require(!sql.prepare("SELECT 1 FROM accounts WHERE deleted_at IS NOT NULL AND (units!=0 OR recovery_hash IS NOT NULL) LIMIT 1").get()
    && !sql.prepare("SELECT 1 FROM searches s JOIN accounts a ON a.id=s.account_id WHERE a.deleted_at IS NOT NULL LIMIT 1").get(), "deleted_account_not_closed");
  for (const receipt of ledger.receipts) {
    const raw = encoded({ version: 1, scope: "vision-community-account-deletion", resource, receipt });
    const hash = sha(raw), archive = sql.prepare("SELECT * FROM account_deletion_archives WHERE account_id=?").get(receipt.accountId);
    require(archive?.sha256 === hash && integer(archive.archived_at) && archive.archived_at >= receipt.deletedAt && archive.archived_at <= now, "deletion_archive_unconfirmed");
    objects.push({ key: `privacy/account-deletions/v1/${sha(Buffer.from(receipt.accountId))}.json`, kind: "deletion-receipt",
      size: raw.length, sha256: hash, httpMetadata: { contentType: "application/json", cacheControl: "no-store" },
      customMetadata: { visionDeletionReceipt: "1", sha256: hash } });
  }
  // Include intent-only uploads: a delayed create need not have reached candidates.
  const unfinished = sql.prepare(`SELECT w.artifact_key,w.account_id FROM account_artifact_writes w
    JOIN accounts a ON a.id=w.account_id WHERE a.deleted_at IS NOT NULL AND NOT EXISTS
      (SELECT 1 FROM published_index p WHERE p.four_view_key=w.artifact_key)
    UNION SELECT c.artifact_key,c.account_id FROM scene_candidates c JOIN accounts a ON a.id=c.account_id
    WHERE a.deleted_at IS NOT NULL AND NOT EXISTS
      (SELECT 1 FROM published_index p WHERE p.four_view_key=c.artifact_key) LIMIT ?`).all(MAX_OBJECTS + 1);
  require(unfinished.length <= MAX_OBJECTS, "storage_object_limit");
  for (const item of unfinished) {
    const job = sql.prepare("SELECT account_id,state FROM account_cleanup WHERE artifact_key=?").get(item.artifact_key);
    require(job?.account_id === item.account_id && job.state === "fenced", "deleted_artifact_not_fenced");
  }
  const jobs = sql.prepare("SELECT * FROM account_cleanup ORDER BY artifact_key LIMIT ?").all(MAX_OBJECTS + 1);
  require(jobs.length <= MAX_OBJECTS, "storage_object_limit");
  for (const job of jobs) {
    const published = sql.prepare("SELECT 1 FROM published_index WHERE four_view_key=? LIMIT 1").get(job.artifact_key);
    if (published) { require(job.state === "retained", "published_artifact_fence_conflict"); continue; }
    const owner = sql.prepare("SELECT deleted_at FROM accounts WHERE id=?").get(job.account_id);
    const lease = sceneArtifactLease(job.artifact_key);
    const assignment = lease && sql.prepare("SELECT account_id,lane FROM leases WHERE id=?").get(lease);
    const intent = sql.prepare("SELECT * FROM account_artifact_writes WHERE artifact_key=?").get(job.artifact_key);
    require(job.state === "fenced" && ACCOUNT.test(job.account_id) && owner && owner.deleted_at !== null
      && assignment?.account_id === job.account_id && assignment.lane === "scene"
      && (!intent || intent.account_id === job.account_id && intent.lease_id === lease)
      && (!job.artifact_key.startsWith("four-view-v4/") || intent), "unsafe_or_pending_cleanup");
    const raw = Buffer.from(PRIVACY_FENCE);
    objects.push({ key: job.artifact_key, kind: "privacy-fence", size: raw.length, sha256: sha(raw),
      httpMetadata: { contentType: "application/x-vision-privacy-fence", cacheControl: "no-store" },
      customMetadata: { visionPrivacyFence: "1" } });
  }
  require(objects.length <= MAX_OBJECTS && new Set(objects.map(o => o.key)).size === objects.length, "storage_object_limit");
  return objects.sort((a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
}
const summary = (objects, resource) => ({ version: 1, scope: "offline-community-privacy-storage", resource,
  complete: true, deletionReceipts: objects.filter(o => o.kind === "deletion-receipt").length,
  privacyFences: objects.filter(o => o.kind === "privacy-fence").length, liveReady: false,
  productionQualified: false, acceptedContributions: 0, creditRecoveryVerified: false });
export function planPrivacyStorage({ current, currentSha256, notBefore, now = Math.floor(Date.now() / 1000), environment = "production", out }) {
  out = freshOutput(out); let sql;
  try {
    const resource = clock(notBefore, now, environment), copy = privateCopy(current, currentSha256, out); sql = copy.sql;
    const objects = expectedObjects(sql, notBefore, now, environment);
    const plan = { version: 1, scope: "vision-community-privacy-storage-plan", resource, environment,
      exportedAt: now, writersStoppedAt: notBefore, databaseSha256: currentSha256, objects };
    const raw = encoded(plan); require(raw.length <= MAX_JSON, "storage_object_limit");
    closed(copy.input); pinned(copy.input, currentSha256, MAX_DATABASE); pinned(copy.copy, currentSha256, MAX_DATABASE);
    writeNew(join(out, "privacy-object-plan.private.json"), raw);
    const report = { ...summary(objects, resource), objectsVerified: false, planSha256: sha(raw) };
    writeNew(join(out, "privacy-plan-report.json"), encoded(report)); return report;
  } finally { sql?.close(); }
}
export const privacyObjectCacheName = key => sha(Buffer.from(key)) + ".blob";
export function checkPrivacyStorage({ plan, planSha256, inventory, inventorySha256, cache, now = Math.floor(Date.now() / 1000), environment = "production", out }) {
  plan = regular(plan); inventory = regular(inventory); cache = regular(cache, true); out = resolve(out);
  require(![dirname(plan), cache].some(input => out === input || out.startsWith(input + sep)), "unsafe_output_overlap");
  out = freshOutput(out); let sql;
  try {
    const document = readJson(plan, planSha256), resource = clock(document.writersStoppedAt, now, environment);
    require(document.version === 1 && document.scope === "vision-community-privacy-storage-plan"
      && document.environment === environment && resourceMatches(document.resource, resource)
      && integer(document.exportedAt) && document.exportedAt >= document.writersStoppedAt && document.exportedAt <= now,
    "invalid_storage_plan");
    const copy = privateCopy(join(dirname(plan), "current.sqlite"), document.databaseSha256, out); sql = copy.sql;
    const objects = expectedObjects(sql, document.writersStoppedAt, now, environment);
    require(JSON.stringify(document.objects) === JSON.stringify(objects), "storage_plan_incomplete_or_changed");
    const observed = readJson(inventory, inventorySha256);
    require(observed.version === 1 && observed.scope === "vision-community-privacy-object-cache"
      && resourceMatches(observed.resource, resource) && integer(observed.exportedAt)
      && observed.exportedAt >= document.writersStoppedAt && observed.exportedAt <= now
      && Array.isArray(observed.objects) && observed.objects.length === objects.length, "invalid_storage_inventory");
    const wanted = new Map(objects.map(o => [o.key, o])), seen = new Set(), files = [];
    for (const item of observed.objects) {
      const expected = wanted.get(item.key);
      require(expected && !seen.has(item.key) && item.size === expected.size && item.sha256 === expected.sha256
        && Object.entries(expected.httpMetadata).every(([k, v]) => item.httpMetadata?.[k] === v)
        && Object.entries(expected.customMetadata).every(([k, v]) => item.customMetadata?.[k] === v), "storage_object_metadata_changed");
      seen.add(item.key);
      const name = privacyObjectCacheName(item.key), file = regular(join(cache, name));
      require(lstatSync(file).size === expected.size && digestFile(file, 2048) === expected.sha256, "storage_object_payload_changed");
      files.push({ file: name, kind: expected.kind, bytes: expected.size, sha256: expected.sha256 });
    }
    // Recheck all inputs after reading every object; early files can change mid-check.
    for (const item of files) require(lstatSync(regular(join(cache, item.file))).size === item.bytes
      && digestFile(join(cache, item.file), 2048) === item.sha256, "storage_object_payload_changed");
    closed(copy.input); pinned(copy.input, document.databaseSha256, MAX_DATABASE); pinned(copy.copy, document.databaseSha256, MAX_DATABASE);
    pinned(plan, planSha256, MAX_JSON); pinned(inventory, inventorySha256, MAX_JSON);
    const checked = encoded({ files }); writeNew(join(out, "checked-files.private.json"), checked);
    const report = { ...summary(objects, resource), objectsVerified: true, planSha256, inventorySha256,
      checkedFilesSha256: sha(checked) };
    writeNew(join(out, "privacy-storage-report.json"), encoded(report)); return report;
  } finally { sql?.close(); }
}
export function main(argv = process.argv.slice(2)) {
  try {
    const mode = argv.shift(); require(["plan", "check"].includes(mode), "invalid_storage_mode");
    const names = mode === "plan" ? ["current", "current-sha256", "writers-stopped-at", "out", "environment"]
      : ["plan", "plan-sha256", "inventory", "inventory-sha256", "cache", "out", "environment"];
    const { values } = parseArgs({ args: argv, options: Object.fromEntries(names.map(name => [name, { type: "string" }])) });
    require(names.filter(n => n !== "environment").every(n => typeof values[n] === "string" && values[n]), "missing_storage_option");
    const environment = values.environment || "production";
    const report = mode === "plan" ? planPrivacyStorage({ current: values.current, currentSha256: values["current-sha256"],
      notBefore: Number(values["writers-stopped-at"]), environment, out: values.out })
      : checkPrivacyStorage({ plan: values.plan, planSha256: values["plan-sha256"], inventory: values.inventory,
        inventorySha256: values["inventory-sha256"], cache: values.cache, environment, out: values.out });
    console.log(JSON.stringify(report)); return 0;
  } catch (error) {
    const code = (error instanceof PrivacyStorageError || error instanceof RestoreError)
      && /^[a-z_]{1,80}$/.test(error.message) ? error.message : "privacy_storage_check_failed";
    console.log(JSON.stringify({ complete: false, liveReady: false, productionQualified: false, code })); return 1;
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = main();
