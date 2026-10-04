import { randomHex, sha256Hex, encodeUtf8 } from "./model.js";
import { ARTIFACT_WRITES_SCHEMA, PRIVACY_FENCE, sceneArtifactLease } from "./artifactWrites.js";

export class AccountPrivacyError extends Error {
  constructor(code, status = 400) { super(code); this.status = status; }
}

export const PRIVACY_TABLES = [
  ARTIFACT_WRITES_SCHEMA,
  `CREATE INDEX IF NOT EXISTS account_artifact_writes_owner ON account_artifact_writes(account_id)`,
  `CREATE INDEX IF NOT EXISTS published_index_four_view_key ON published_index(four_view_key)`,
  `CREATE TABLE IF NOT EXISTS account_deletion_receipts (
    account_id TEXT PRIMARY KEY REFERENCES accounts(id), request_key TEXT NOT NULL UNIQUE,
    deleted_at INTEGER NOT NULL, units_forfeited INTEGER NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS account_cleanup (
    artifact_key TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
    created_at INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'pending')`,
  `CREATE INDEX IF NOT EXISTS account_cleanup_pending ON account_cleanup(state,created_at,artifact_key)`,
  `CREATE TABLE IF NOT EXISTS account_deletion_archives (
    account_id TEXT PRIMARY KEY REFERENCES account_deletion_receipts(account_id),
    sha256 TEXT NOT NULL, archived_at INTEGER NOT NULL)`,
];

// Database fences protect writes that were authenticated before a deletion,
// including legacy publication paths after an asynchronous storage/verifier call.
export const PRIVACY_FENCES = [
  `CREATE TRIGGER IF NOT EXISTS deleted_account_cannot_reactivate BEFORE UPDATE ON accounts
    WHEN OLD.deleted_at IS NOT NULL AND (NEW.deleted_at IS NULL OR NEW.token_hash!=OLD.token_hash
      OR NEW.recovery_hash IS NOT NULL OR NEW.units!=0)
    BEGIN SELECT RAISE(ABORT,'account_not_active'); END`,
  ...["ledger", "searches", "scene_qualifications", "scene_candidates", "leases", "account_artifact_writes"].map(table =>
    `CREATE TRIGGER IF NOT EXISTS ${table}_active_account_insert BEFORE INSERT ON ${table}
      WHEN NOT EXISTS (SELECT 1 FROM accounts WHERE id=NEW.account_id AND deleted_at IS NULL)
      BEGIN SELECT RAISE(ABORT,'account_not_active'); END`),
  `CREATE TRIGGER IF NOT EXISTS artifact_write_intent_immutable BEFORE UPDATE ON account_artifact_writes
    BEGIN SELECT RAISE(ABORT,'artifact_write_intent_immutable'); END`,
  `CREATE TRIGGER IF NOT EXISTS searches_active_account_update BEFORE UPDATE ON searches
    WHEN NOT EXISTS (SELECT 1 FROM accounts WHERE id=NEW.account_id AND deleted_at IS NULL)
    BEGIN SELECT RAISE(ABORT,'account_not_active'); END`,
  `CREATE TRIGGER IF NOT EXISTS leases_active_account_update BEFORE UPDATE ON leases
    WHEN NEW.state='active' AND NOT EXISTS
      (SELECT 1 FROM accounts WHERE id=NEW.account_id AND deleted_at IS NULL)
    BEGIN SELECT RAISE(ABORT,'account_not_active'); END`,
  `CREATE TRIGGER IF NOT EXISTS qualifications_active_account_update BEFORE UPDATE ON scene_qualifications
    WHEN NEW.expires_at>0 AND NOT EXISTS
      (SELECT 1 FROM accounts WHERE id=NEW.account_id AND deleted_at IS NULL)
    BEGIN SELECT RAISE(ABORT,'account_not_active'); END`,
  `CREATE TRIGGER IF NOT EXISTS candidates_active_account_update BEFORE UPDATE ON scene_candidates
    WHEN NEW.state IN ('pending','published') AND NOT EXISTS
      (SELECT 1 FROM accounts WHERE id=NEW.account_id AND deleted_at IS NULL)
    BEGIN SELECT RAISE(ABORT,'account_not_active'); END`,
  `CREATE TRIGGER IF NOT EXISTS catalog_active_assignee BEFORE UPDATE OF assignee ON pose_catalog
    WHEN NEW.assignee IS NOT NULL AND EXISTS
      (SELECT 1 FROM accounts WHERE id=NEW.assignee AND deleted_at IS NOT NULL)
    BEGIN SELECT RAISE(ABORT,'account_not_active'); END`,
  `CREATE TRIGGER IF NOT EXISTS locations_active_contributor BEFORE UPDATE ON locations
    WHEN NEW.state='published' AND (OLD.state!='published' OR NEW.contributor_id IS NOT OLD.contributor_id) AND EXISTS
      (SELECT 1 FROM accounts WHERE id=NEW.contributor_id AND deleted_at IS NOT NULL)
    BEGIN SELECT RAISE(ABORT,'account_not_active'); END`,
  `CREATE TRIGGER IF NOT EXISTS locations_active_lease BEFORE UPDATE OF active_lease ON locations
    WHEN NEW.active_lease IS NOT NULL AND EXISTS
      (SELECT 1 FROM leases l JOIN accounts a ON a.id=l.account_id
        WHERE l.id=NEW.active_lease AND a.deleted_at IS NOT NULL)
    BEGIN SELECT RAISE(ABORT,'account_not_active'); END`,
];

export async function migrateAccountPrivacy(env) {
  const columns = (await env.DB.prepare("PRAGMA table_info(accounts)").all()).results || [];
  if (!columns.some(column => column.name === "deleted_at")) {
    await env.DB.prepare("ALTER TABLE accounts ADD COLUMN deleted_at INTEGER").run();
  }
  // Avoid repeating every DDL statement on every API request. Inspect the
  // persisted schema rather than caching an environment/database in JS globals.
  const names = [...PRIVACY_TABLES.map(statement => statement.match(/CREATE (?:TABLE|INDEX) IF NOT EXISTS (\w+)/)[1]),
    ...PRIVACY_FENCES.map(statement => statement.match(/CREATE TRIGGER IF NOT EXISTS (\w+)/)[1])];
  const existing = (await env.DB.prepare(`SELECT name FROM sqlite_master WHERE name IN (${names.map(() => "?").join(",")})`)
    .bind(...names).all()).results || [];
  if (existing.length === names.length) return;
  // Install the new writer protocol and requeue old deletions atomically. A
  // crash must not leave the completed schema with unfenced "removed" keys.
  await env.DB.batch([...PRIVACY_TABLES, ...PRIVACY_FENCES,
    "UPDATE account_cleanup SET state='pending' WHERE state='removed'"].map(statement => env.DB.prepare(statement)));
}

function receiptResult(row) {
  return { deleted: true, contributionsRetained: true, unitsForfeited: row.units_forfeited };
}

const ARCHIVE_RESOURCES = Object.freeze({
  production: { accountId: "272760294910ef0b246980278aeb36e2", databaseId: "ed4705fa-1190-41fa-86a0-02d755db1b2a", bucket: "vision-community" },
  staging: { accountId: "272760294910ef0b246980278aeb36e2", databaseId: "17043cb7-5dab-4a6f-84ca-19ae1c14cc05", bucket: "vision-community-staging" },
});

function archiveSettings(env) {
  // Local development may omit archival. Release environments explicitly
  // require it; never infer a bucket or accept an arbitrary resource mapping.
  if ([undefined, "0"].includes(env.DELETION_ARCHIVE_REQUIRED)) return null;
  const resource = ["production", "staging"].includes(env.DELETION_ARCHIVE_ENVIRONMENT)
    ? ARCHIVE_RESOURCES[env.DELETION_ARCHIVE_ENVIRONMENT] : null;
  if (env.DELETION_ARCHIVE_REQUIRED !== "1" || !resource
      || env.INDEX_BUCKET_NAME !== resource.bucket || env.DELETION_ARCHIVE_DB_ID !== resource.databaseId
      || !env.INDEX?.get || !env.INDEX?.put) throw new AccountPrivacyError("deletion_archive_unavailable", 503);
  return resource;
}

async function archiveDeletionReceipt(env, row, now = Math.floor(Date.now() / 1000)) {
  const resource = archiveSettings(env);
  if (!resource) return false;
  try {
    if (!/^[a-f0-9]{32}$/.test(row.account_id) || !/^[a-f0-9]{64}$/.test(row.request_key)
        || !Number.isSafeInteger(row.deleted_at) || row.deleted_at < 0
        || !Number.isSafeInteger(row.units_forfeited) || row.units_forfeited < 0) throw Error("invalid_receipt");
    const document = encodeUtf8(JSON.stringify({ version: 1, scope: "vision-community-account-deletion",
      resource, receipt: { accountId: row.account_id, requestKey: row.request_key,
        deletedAt: row.deleted_at, unitsForfeited: row.units_forfeited } }) + "\n");
    const sha256 = await sha256Hex(document);
    const recorded = await env.DB.prepare("SELECT sha256 FROM account_deletion_archives WHERE account_id=?")
      .bind(row.account_id).first();
    if (recorded) {
      if (recorded.sha256 !== sha256) throw Error("archive_changed");
      return true;
    }
    const key = `privacy/account-deletions/v1/${await sha256Hex(encodeUtf8(row.account_id))}.json`;
    let object = await env.INDEX.get(key);
    if (!object) {
      await env.INDEX.put(key, document, { onlyIf: { etagDoesNotMatch: "*" },
        httpMetadata: { contentType: "application/json", cacheControl: "no-store" },
        customMetadata: { visionDeletionReceipt: "1", sha256 } });
      object = await env.INDEX.get(key);
    }
    if (!object?.body || object.size !== document.byteLength || object.size > 2048) throw Error("archive_unconfirmed");
    // Bounded readback before acknowledging independent durability. Immutable
    // conditional creation also handles concurrent retries without overwrites.
    const reader = object.body.getReader(), chunks = [];
    let size = 0;
    try {
      while (true) {
        const next = await reader.read();
        if (next.done) break;
        size += next.value.byteLength;
        if (size > document.byteLength) throw Error("archive_changed");
        if (next.value.byteLength) chunks.push(next.value);
      }
    } finally { await reader.cancel().catch(() => {}); }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    if (size !== document.byteLength || await sha256Hex(bytes) !== sha256) throw Error("archive_changed");
    await env.DB.prepare(`INSERT OR IGNORE INTO account_deletion_archives (account_id,sha256,archived_at)
      SELECT account_id,?,? FROM account_deletion_receipts WHERE account_id=? AND request_key=?`)
      .bind(sha256, now, row.account_id, row.request_key).run();
    const confirmed = await env.DB.prepare("SELECT sha256 FROM account_deletion_archives WHERE account_id=?")
      .bind(row.account_id).first();
    if (confirmed?.sha256 !== sha256) throw Error("archive_unconfirmed");
    return true;
  } catch {
    // Revocation remains committed; the exact private deletion request can be
    // replayed after loss/outage without restoring credentials or debiting twice.
    throw new AccountPrivacyError("deletion_archive_unavailable", 503);
  }
}

export async function archiveAccountDeletionReceipts(env, limit = 25) {
  if (!archiveSettings(env)) return { enabled: false, archived: 0 };
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new AccountPrivacyError("invalid_archive_limit");
  const rows = (await env.DB.prepare(`SELECT r.* FROM account_deletion_receipts r
    LEFT JOIN account_deletion_archives a ON a.account_id=r.account_id
    WHERE a.account_id IS NULL ORDER BY r.deleted_at,r.account_id LIMIT ?`).bind(limit).all()).results || [];
  let archived = 0;
  for (const row of rows) {
    try { await archiveDeletionReceipt(env, row); archived++; }
    catch { break; } // A scheduled retry resumes the durable outbox on outage.
  }
  return { enabled: true, archived };
}

export async function deleteAccount(env, authenticatedAccount, body, now = Math.floor(Date.now() / 1000)) {
  const account = body.accountId, key = body.idempotencyKey;
  if (body.confirmation !== "DELETE" || typeof account !== "string" || !account || account.length > 128
      || typeof key !== "string" || !/^[0-9a-f]{64}$/.test(key)) {
    throw new AccountPrivacyError("invalid_account_deletion");
  }
  if (authenticatedAccount && account !== authenticatedAccount) throw new AccountPrivacyError("account_changed", 409);
  archiveSettings(env); // Refuse a misbound required archive before revocation.
  // An unguessable, account-bound receipt can recover a lost deletion response
  // after the session was revoked. It grants no account or search access.
  const receipt = await env.DB.prepare("SELECT * FROM account_deletion_receipts WHERE account_id=? AND request_key=?")
    .bind(account, key).first();
  if (receipt) { await archiveDeletionReceipt(env, receipt); return receiptResult(receipt); }
  if (authenticatedAccount !== account) throw new AccountPrivacyError("unauthorized", 401);
  const claim = "EXISTS (SELECT 1 FROM account_deletion_receipts WHERE account_id=? AND request_key=?)";
  await env.DB.batch([
    env.DB.prepare(`INSERT INTO account_deletion_receipts
      SELECT id,?,?,units FROM accounts WHERE id=? AND deleted_at IS NULL
        AND NOT EXISTS (SELECT 1 FROM account_deletion_receipts WHERE account_id=?)`)
      .bind(key, now, account, account),
    env.DB.prepare(`INSERT INTO ledger (account_id,units,reason,reference)
      SELECT id,-units,'account_deleted',? FROM accounts WHERE id=? AND deleted_at IS NULL AND ${claim}`)
      .bind(`account-delete:${account}`, account, account, key),
    env.DB.prepare(`INSERT INTO account_cleanup (artifact_key,account_id,created_at,state)
      SELECT artifact_key,account_id,?,'pending' FROM account_artifact_writes w
        WHERE account_id=? AND ${claim} AND NOT EXISTS
          (SELECT 1 FROM published_index i WHERE i.four_view_key=w.artifact_key)
      ON CONFLICT(artifact_key) DO NOTHING`).bind(now, account, account, key),
    env.DB.prepare(`INSERT INTO account_cleanup (artifact_key,account_id,created_at,state)
      SELECT artifact_key,account_id,?,'pending' FROM scene_candidates
        WHERE account_id=? AND state!='published' AND ${claim}
      ON CONFLICT(artifact_key) DO NOTHING`).bind(now, account, account, key),
    env.DB.prepare(`UPDATE accounts SET deleted_at=?,units=0,recovery_hash=NULL,token_hash=?
      WHERE id=? AND deleted_at IS NULL AND ${claim}`).bind(now, randomHex(32), account, account, key),
    env.DB.prepare(`DELETE FROM searches WHERE account_id=? AND ${claim}`).bind(account, account, key),
    env.DB.prepare(`UPDATE scene_qualifications SET expires_at=0 WHERE account_id=? AND ${claim}`)
      .bind(account, account, key),
    env.DB.prepare(`UPDATE locations SET state='pending',queue_state='pending',active_lease=NULL,lease_until=NULL
      WHERE state!='published' AND ${claim} AND (
        active_lease IN (SELECT id FROM leases WHERE account_id=?) OR
        (queue_state='quarantined' AND active_lease IS NULL AND id IN
          (SELECT i.location_id FROM lease_items i JOIN scene_candidates c ON c.lease_id=i.lease_id
            WHERE c.account_id=? AND c.state='pending')))`)
      .bind(account, key, account, account),
    env.DB.prepare(`UPDATE scene_candidates SET state='rejected',records_json='[]'
      WHERE account_id=? AND state!='published' AND ${claim}`).bind(account, account, key),
    env.DB.prepare(`UPDATE leases SET state='expired' WHERE account_id=? AND state='active' AND ${claim}`)
      .bind(account, account, key),
    env.DB.prepare(`UPDATE pose_catalog SET assignee=NULL,assigned_at=NULL
      WHERE assignee=? AND ${claim}`).bind(account, account, key),
  ]);
  const saved = await env.DB.prepare("SELECT * FROM account_deletion_receipts WHERE account_id=? AND request_key=?")
    .bind(account, key).first();
  if (!saved) throw new AccountPrivacyError("account_changed", 409);
  await archiveDeletionReceipt(env, saved);
  return receiptResult(saved);
}

export async function cleanupAccountArtifacts(env, account = null, limit = 16) {
  if (!env.INDEX || !Number.isInteger(limit) || limit < 1 || limit > 64) return;
  const jobs = (await env.DB.prepare(`SELECT artifact_key,account_id FROM account_cleanup
    WHERE (? IS NULL OR account_id=?) AND state='pending' ORDER BY created_at,artifact_key LIMIT ?`)
    .bind(account, account, limit).all()).results || [];
  for (const job of jobs) {
    const owner = await env.DB.prepare("SELECT deleted_at FROM accounts WHERE id=?").bind(job.account_id).first();
    const intent = await env.DB.prepare("SELECT * FROM account_artifact_writes WHERE artifact_key=?").bind(job.artifact_key).first();
    const lease = sceneArtifactLease(job.artifact_key);
    const assignment = lease && await env.DB.prepare("SELECT account_id,lane FROM leases WHERE id=?").bind(lease).first();
    // Quarantine predates the intent journal; unpublished final artifacts must
    // have a journal proof of ownership. Never touch arbitrary or live keys.
    if (!owner || owner.deleted_at === null || !lease || !assignment
        || assignment.account_id !== job.account_id || assignment.lane !== "scene"
        || intent && (intent.account_id !== job.account_id || intent.lease_id !== lease)
        || job.artifact_key.startsWith("four-view-v4/") && !intent) {
      await env.DB.prepare("UPDATE account_cleanup SET state='needs_review' WHERE artifact_key=?")
        .bind(job.artifact_key).run();
      continue;
    }
    if (await env.DB.prepare("SELECT 1 FROM published_index WHERE four_view_key=? LIMIT 1").bind(job.artifact_key).first()) {
      await env.DB.prepare("UPDATE account_cleanup SET state='retained' WHERE artifact_key=?").bind(job.artifact_key).run();
      continue;
    }
    try {
      // An ordinary delete permits a delayed create to put private bytes back.
      // Keep this tiny fence permanently; every new scene writer is create-only.
      const written = await env.INDEX.put(job.artifact_key, PRIVACY_FENCE, {
        customMetadata: { visionPrivacyFence: "1" },
        httpMetadata: { contentType: "application/x-vision-privacy-fence", cacheControl: "no-store" },
      });
      if (!written || written.size !== PRIVACY_FENCE.length) throw new Error("privacy_fence_unconfirmed");
      await env.DB.prepare("UPDATE account_cleanup SET state='fenced' WHERE artifact_key=?")
        .bind(job.artifact_key).run();
    } catch {
      // Deletion of credentials/searches is committed. Keep this independent,
      // durable cleanup job pending for a retry; never report complete erasure.
    }
  }
}
