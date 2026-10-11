import { sha256Hex } from "./model.js";

export const PRIVACY_FENCE = "VISION COMMUNITY PRIVACY FENCE\n";
export const ARTIFACT_WRITES_SCHEMA = `CREATE TABLE IF NOT EXISTS account_artifact_writes (
 artifact_key TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
 lease_id TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, created_at INTEGER NOT NULL)`;
const MAX_BYTES = 32000000;

export class ArtifactWriteError extends Error {
  constructor(code, status = 409) { super(code); this.status = status; }
}

export function sceneArtifactLease(key) {
  if (typeof key !== "string") return null;
  return /^scene-quarantine\/([0-9a-f]{32})\/[0-9a-f]{64}\.i8$/.exec(key)?.[1]
    || /^four-view-v4\/([0-9a-f]{32})\.i8$/.exec(key)?.[1] || null;
}

// One parser defines upload, account cleanup and offline recovery ownership.
// Object lanes can be empty .bin files; their manifest/source cannot be empty.
export function indexArtifactIdentity(key) {
  const scene = sceneArtifactLease(key);
  if (scene) return { lane: "scene", lease: scene, reference: key,
    column: "four_view_key", intentRequired: key.startsWith("four-view-v4/") };
  if (typeof key !== "string") return null;
  const quarantine = /^object-quarantine\/([0-9a-f]{32})\/([0-9a-f]{64})\.json$/.exec(key);
  if (quarantine) return { lane: "object", lease: quarantine[1], reference: null,
    column: "object_index_key", intentRequired: true, digest: quarantine[2], allowEmpty: false };
  const published = /^(object-index-v4\/([0-9a-f]{32})\/)(manifest\.json|locations\.tsv|[a-z0-9][a-z0-9.-]*\.bin)$/.exec(key);
  return published ? { lane: "object", lease: published[2], reference: published[1],
    column: "object_index_key", intentRequired: true, allowEmpty: published[3].endsWith(".bin") } : null;
}

// Used inside deletion/recovery queries before asynchronous cleanup. The exact
// Object prefix is 16 + 32 + 1 bytes, so another lease cannot retain its files.
export function artifactPublicationSql(alias) {
  if (!["w", "c"].includes(alias)) throw Error("invalid_artifact_alias");
  // CASE keeps Scene cleanup on its existing indexed lookup instead of an
  // OR scan across all publications merely because the Object branch exists.
  return `(CASE WHEN substr(${alias}.artifact_key,1,16)='object-index-v4/' THEN
    EXISTS (SELECT 1 FROM published_index p WHERE p.object_index_key=substr(${alias}.artifact_key,1,49))
    ELSE EXISTS (SELECT 1 FROM published_index p WHERE p.four_view_key=${alias}.artifact_key) END)`;
}

export async function writeSceneArtifact(env, account, lease, key, bytes, now = Math.floor(Date.now() / 1000)) {
  return writeOwnedArtifact(env, account, lease, key, bytes, now, "scene");
}

export async function writeObjectArtifact(env, account, lease, key, bytes, now = Math.floor(Date.now() / 1000)) {
  return writeOwnedArtifact(env, account, lease, key, bytes, now, "object");
}

async function writeOwnedArtifact(env, account, lease, key, bytes, now, lane) {
  if (!env.INDEX) throw new ArtifactWriteError("index_unavailable", 503);
  const identity = indexArtifactIdentity(key);
  if (typeof lease !== "string" || !/^[0-9a-f]{32}$/.test(lease)
      || identity?.lease !== lease || identity.lane !== lane || !(bytes instanceof Uint8Array)
      || !bytes.length && !identity.allowEmpty || bytes.length > MAX_BYTES
      || key.endsWith(".json") && bytes.length > 4 * 1024 * 1024) {
    throw new ArtifactWriteError(`invalid_${lane}_artifact`);
  }
  const digest = await sha256Hex(bytes);
  if (identity.digest && identity.digest !== digest) throw new ArtifactWriteError("index_artifact_changed");
  // Persist the intent before any asynchronous R2 write. Deletion can then
  // fence an upload before any Scene or Object candidate exists.
  await env.DB.prepare(`INSERT INTO account_artifact_writes
    SELECT ?,?,?,?,?,? WHERE EXISTS (SELECT 1 FROM leases l JOIN accounts a ON a.id=l.account_id
      WHERE l.id=? AND l.account_id=? AND l.lane=? AND l.state IN ('active','submitted') AND a.deleted_at IS NULL)
    ON CONFLICT(artifact_key) DO NOTHING`).bind(key, account, lease, digest, bytes.length, now, lease, account, lane).run();
  const intent = await env.DB.prepare(`SELECT w.* FROM account_artifact_writes w JOIN accounts a ON a.id=w.account_id
    WHERE w.artifact_key=? AND a.deleted_at IS NULL`).bind(key).first();
  if (!intent) {
    const active = await env.DB.prepare("SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL").bind(account).first();
    throw new ArtifactWriteError(active ? "lease_lost" : "account_not_active", active ? 409 : 401);
  }
  if (intent.account_id !== account || intent.lease_id !== lease || intent.sha256 !== digest || intent.bytes !== bytes.length) {
    throw new ArtifactWriteError("index_artifact_changed");
  }
  // Create-only writes cannot resurrect a payload after cleanup has installed
  // a permanent empty-of-private-data fence at the same key.
  const written = await env.INDEX.put(key, bytes, {
    onlyIf: new Headers({ "if-none-match": "*" }), sha256: digest,
  });
  if (written !== null && (!written || written.size !== bytes.length)) {
    throw new ArtifactWriteError("index_write_unconfirmed", 503);
  }
  if (written === null) {
    const existing = await env.INDEX.get(key);
    if (existing?.customMetadata?.visionPrivacyFence === "1") throw new ArtifactWriteError("index_artifact_fenced");
    if (!existing || existing.size !== bytes.length || existing.size > MAX_BYTES) throw new ArtifactWriteError("index_artifact_changed");
    const retained = new Uint8Array(await existing.arrayBuffer());
    if (retained.length !== bytes.length || await sha256Hex(retained) !== digest) throw new ArtifactWriteError("index_artifact_changed");
  }
  const active = await env.DB.prepare("SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL").bind(account).first();
  if (!active) throw new ArtifactWriteError("account_not_active", 401);
  return digest;
}
