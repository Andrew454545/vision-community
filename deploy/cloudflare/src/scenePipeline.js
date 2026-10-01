import { base64ToBytes, bytesToBase64, sha256Hex, encodeUtf8, randomHex } from "./model.js";
import { SCENE_OUTPUT_MODEL } from "./sceneQuality.js";
import { writeSceneArtifact } from "./artifactWrites.js";

export const SCENE_PIPELINE_SCHEMA = `
CREATE TABLE IF NOT EXISTS scene_qualifications (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, profile_id TEXT NOT NULL,
 policy_id TEXT NOT NULL, canary_sha256 TEXT NOT NULL, expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS scene_candidates (
 lease_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, qualification_id TEXT NOT NULL,
 policy_id TEXT NOT NULL, submission_sha256 TEXT NOT NULL, artifact_key TEXT NOT NULL,
 records_json TEXT NOT NULL, created_at INTEGER NOT NULL, state TEXT NOT NULL
);`;

export function verifierConfigured(env) {
  return typeof env.SCENE_VERIFIER?.fetch === "function" && typeof env.SCENE_POLICY_ID === "string" && !!env.SCENE_POLICY_ID && auditBatchLimit(env) !== null;
}

export function auditBatchLimit(env) {
  // The private audit has a 50-second execution budget. Larger batches require
  // a measured host limit; processing pace does not establish audit capacity.
  if (env.SCENE_AUDIT_MAX_LOCATIONS === undefined) return 8;
  const value = env.SCENE_AUDIT_MAX_LOCATIONS;
  if (typeof value !== "string" || !/^[1-9][0-9]{0,2}$/.test(value)) return null;
  const limit = Number(value);
  return limit <= 128 ? limit : null;
}

export function pipelineCapabilities(env) {
  return { version: 1, sceneContributions: { ready: true, reason: null, model: SCENE_OUTPUT_MODEL,
    policyId: env.SCENE_POLICY_ID, scope: "audited-new-locations", deviceQualificationRequired: true,
    canaryLocations: 112, maxBatchLocations: auditBatchLimit(env), verification: "trusted-profile-canary-and-submission-audit" } };
}

export class ScenePipelineError extends Error {
  constructor(code, status = 400) { super(code); this.status = status; }
}

async function callVerifier(env, action, body) {
  try {
    const response = await env.SCENE_VERIFIER.fetch(new Request(`https://scene-verifier.internal/${action}`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
      signal: AbortSignal.timeout(60000),
    }));
    if (response.status === 422 && action === "qualify") {
      const result = await response.json();
      return result?.approved === false || ["scene_device_not_qualified", "invalid_submission"].includes(result?.error)
        ? { approved: false } : null;
    }
    if (!response.ok) return null;
    return await response.json();
  } catch { return null; }
}

export async function activeQualification(env, account, now, qualificationId = null, profileId = null) {
  if (!verifierConfigured(env)) throw new ScenePipelineError("scene_verification_unavailable", 503);
  const row = await env.DB.prepare(`SELECT * FROM scene_qualifications WHERE account_id=? AND policy_id=?
    AND expires_at>? AND (? IS NULL OR id=?) AND (? IS NULL OR profile_id=?)
    ORDER BY created_at DESC, id DESC LIMIT 1`).bind(account, env.SCENE_POLICY_ID, now,
    qualificationId, qualificationId, profileId, profileId).first();
  if (!row) throw new ScenePipelineError("scene_device_qualification_required", 403);
  return row;
}

export async function qualifyDevice(env, account, body, validRecord, now = Math.floor(Date.now() / 1000)) {
  if (!verifierConfigured(env)) throw new ScenePipelineError("scene_verification_unavailable", 503);
  const { profileId, canary } = body;
  if (typeof profileId !== "string" || !/^[0-9a-f]{64}$/.test(profileId)) throw new ScenePipelineError("invalid_profile_id");
  if (!canary || canary.locations !== 112 || !Array.isArray(canary.records) || canary.records.length !== 112) {
    throw new ScenePipelineError("invalid_scene_canary");
  }
  const blob = new Uint8Array(112 * 3080);
  for (let i = 0; i < 112; i++) {
    let record;
    try { record = base64ToBytes(canary.records[i]); } catch { throw new ScenePipelineError("invalid_scene_canary"); }
    if (!validRecord(record)) throw new ScenePipelineError("invalid_scene_canary");
    blob.set(record, i * 3080);
  }
  if (canary.outputSha256 !== await sha256Hex(blob)) throw new ScenePipelineError("invalid_scene_canary");
  const canarySha256 = await sha256Hex(encodeUtf8(JSON.stringify(canary)));
  const result = await callVerifier(env, "qualify", { accountId: account, profileId,
    policyId: env.SCENE_POLICY_ID, canarySha256, canary });
  if (!result) throw new ScenePipelineError("scene_verification_unavailable", 503);
  if (!result || result.approved !== true || result.policyId !== env.SCENE_POLICY_ID ||
      result.profileId !== profileId || result.canarySha256 !== canarySha256 ||
      !Number.isSafeInteger(result.expiresAt) || result.expiresAt <= now || result.expiresAt > now + 30 * 86400) {
    throw new ScenePipelineError("scene_device_not_qualified", 422);
  }
  const id = randomHex(16);
  await env.DB.prepare("INSERT INTO scene_qualifications VALUES (?, ?, ?, ?, ?, ?, ?)")
    .bind(id, account, profileId, env.SCENE_POLICY_ID, canarySha256, result.expiresAt, now).run();
  return { qualified: true, qualificationId: id, profileId, policyId: env.SCENE_POLICY_ID, expiresAt: result.expiresAt };
}

export async function qualificationStatus(env, account, profileId, now = Math.floor(Date.now() / 1000)) {
  if (!verifierConfigured(env)) throw new ScenePipelineError("scene_verification_unavailable", 503);
  if (typeof profileId !== "string" || !/^[0-9a-f]{64}$/.test(profileId)) throw new ScenePipelineError("invalid_profile_id");
  const row = await env.DB.prepare(`SELECT * FROM scene_qualifications
    WHERE account_id=? AND policy_id=? AND profile_id=? AND expires_at>?
    ORDER BY created_at DESC, id DESC LIMIT 1`).bind(account, env.SCENE_POLICY_ID, profileId, now).first();
  if (!row) return { qualified: false, profileId, policyId: env.SCENE_POLICY_ID };
  return { qualified: true, qualificationId: row.id, profileId: row.profile_id,
    policyId: row.policy_id, expiresAt: row.expires_at };
}

async function submissionHash(metadata, blob) {
  const prefix = encodeUtf8(metadata + "\n");
  const bytes = new Uint8Array(prefix.length + blob.length);
  bytes.set(prefix); bytes.set(blob, prefix.length);
  return sha256Hex(bytes);
}

export function candidateResult(row) {
  return { accepted: 0, unitsEarned: 0, replayed: true, pendingAudit: row.state === "pending",
    pending: row.state === "pending" ? JSON.parse(row.records_json).length : 0,
    rejected: row.state === "rejected", submissionId: row.lease_id, segments: [] };
}

export async function stageScene(env, account, leaseId, verified, now) {
  if (!env.INDEX) throw new ScenePipelineError("index_unavailable", 503);
  const lease = await env.DB.prepare("SELECT * FROM leases WHERE id=? AND account_id=?").bind(leaseId, account).first();
  if (!lease?.scene_qualification_id) throw new ScenePipelineError("scene_device_qualification_required", 403);
  const qualification = await activeQualification(env, account, now, lease.scene_qualification_id);
  const records = verified.map(({ row, digest }) => ({ locationId: row.id, assetId: row.asset_id,
    capture: row.capture, inputModel: row.model, lat: row.lat, lng: row.lon,
    heading: row.heading, pitch: row.pitch, zoom: row.zoom,
    country: row.country ?? null, cameraGeneration: row.camera_generation || "unknown", outputSha256: digest }));
  const blob = new Uint8Array(verified.length * 3080);
  verified.forEach((item, i) => blob.set(item.embedding, i * 3080));
  const metadata = JSON.stringify(records);
  const digest = await submissionHash(metadata, blob);
  const key = `scene-quarantine/${leaseId}/${digest}.i8`;
  await writeSceneArtifact(env, account, leaseId, key, blob, now);
  const staged = await env.DB.batch([
    env.DB.prepare(`INSERT INTO scene_candidates
      SELECT ?, ?, ?, ?, ?, ?, ?, ?, 'pending'
      WHERE EXISTS (SELECT 1 FROM leases WHERE id=? AND account_id=? AND state='active' AND expires_at>?)
        AND NOT EXISTS (SELECT 1 FROM locations l JOIN lease_items i ON i.location_id=l.id
          WHERE i.lease_id=? AND (l.state!='leased' OR l.active_lease!=?))`)
      .bind(leaseId, account, qualification.id, qualification.policy_id, digest, key, metadata, now,
        leaseId, account, now, leaseId, leaseId),
    env.DB.prepare(`UPDATE locations SET state='pending', active_lease=NULL, lease_until=NULL, queue_state='quarantined'
      WHERE active_lease=? AND EXISTS (SELECT 1 FROM scene_candidates WHERE lease_id=?)`).bind(leaseId, leaseId),
    env.DB.prepare(`UPDATE leases SET state='submitted' WHERE id=? AND EXISTS
      (SELECT 1 FROM scene_candidates WHERE lease_id=?)`).bind(leaseId, leaseId),
  ]);
  if (staged[0].meta?.changes !== 1) throw new ScenePipelineError("lease_lost", 409);
  return { accepted: 0, pending: verified.length, staged: verified.length, unitsEarned: 0,
    pendingAudit: true, replayed: false, submissionId: leaseId, segments: [] };
}

export async function auditScene(env, account, leaseId, now = Math.floor(Date.now() / 1000)) {
  if (!verifierConfigured(env)) throw new ScenePipelineError("scene_verification_unavailable", 503);
  const row = await env.DB.prepare("SELECT * FROM scene_candidates WHERE lease_id=? AND account_id=?").bind(leaseId, account).first();
  if (!row) throw new ScenePipelineError("unknown_scene_submission", 404);
  if (row.state !== "pending") return candidateResult(row);
  if (row.policy_id !== env.SCENE_POLICY_ID) throw new ScenePipelineError("scene_policy_changed", 409);
  const object = await env.INDEX.get(row.artifact_key);
  if (!object) throw new ScenePipelineError("scene_quarantine_corrupt", 500);
  const blob = new Uint8Array(await object.arrayBuffer());
  if (await submissionHash(row.records_json, blob) !== row.submission_sha256) throw new ScenePipelineError("scene_quarantine_corrupt", 500);
  const qualification = await env.DB.prepare("SELECT * FROM scene_qualifications WHERE id=?").bind(row.qualification_id).first();
  if (!qualification || qualification.account_id !== account || qualification.policy_id !== row.policy_id) {
    throw new ScenePipelineError("scene_submission_conflict", 409);
  }
  const records = JSON.parse(row.records_json);
  if (!Array.isArray(records) || !records.length || new Set(records.map((record) => record.locationId)).size !== records.length
      || records.some((record) => !Number.isSafeInteger(record.locationId) || record.locationId <= 0)
      || blob.length !== records.length * 3080) throw new ScenePipelineError("scene_quarantine_corrupt", 500);
  const result = await callVerifier(env, "audit", { accountId: account, profileId: qualification.profile_id,
    policyId: row.policy_id, submissionSha256: row.submission_sha256, records, indexBase64: bytesToBase64(blob) });
  if (!result || result.policyId !== row.policy_id || result.submissionSha256 !== row.submission_sha256 ||
      !["approved", "rejected"].includes(result.decision)) return candidateResult(row);
  if (result.decision === "rejected") {
    await env.DB.prepare("UPDATE scene_candidates SET state='rejected' WHERE lease_id=? AND state='pending'").bind(leaseId).run();
    return candidateResult(await env.DB.prepare("SELECT * FROM scene_candidates WHERE lease_id=?").bind(leaseId).first());
  }
  const key = `four-view-v4/${leaseId}.i8`;
  await writeSceneArtifact(env, account, leaseId, key, blob, now);
  // D1 batch is atomic. The ledger's unique reference makes concurrent
  // approvals roll back rather than credit twice. A retry reads published.
  const reference = `lease:${leaseId}`;
  // Make the ownership check part of the same transaction that grants credit.
  // Every later statement requires the ledger row created by this claim.
  const claimed = `EXISTS (SELECT 1 FROM scene_candidates c JOIN ledger d ON d.reference=?
    WHERE c.lease_id=? AND c.state='pending' AND d.account_id=c.account_id)`;
  const statements = [env.DB.prepare(`INSERT INTO ledger (account_id,units,reason,reference)
    SELECT ?,?,'verified_work',? WHERE EXISTS (SELECT 1 FROM scene_candidates WHERE lease_id=? AND state='pending')
      AND (SELECT COUNT(*) FROM lease_items i JOIN locations l ON l.id=i.location_id
        WHERE i.lease_id=? AND l.state='pending' AND l.queue_state='quarantined'
          AND l.id IN (SELECT value FROM json_each(?)))=?
      AND (SELECT COUNT(*) FROM lease_items WHERE lease_id=?)=?`)
    .bind(account, records.length, reference, leaseId, leaseId, JSON.stringify(records.map((record) => record.locationId)),
      records.length, leaseId, records.length)];
  for (const record of records) {
    statements.push(env.DB.prepare(`INSERT INTO published_index
      (location_id,index_text,output_sha256,published_at,embedding,four_view_sha256,four_view_key)
      SELECT ?,'',?,?,NULL,?,? WHERE ${claimed}`)
      .bind(record.locationId, record.outputSha256, now, record.outputSha256, key, reference, leaseId));
    statements.push(env.DB.prepare(`UPDATE locations SET state='published',queue_state='pending',output_sha256=?,contributor_id=?
      WHERE id=? AND ${claimed}`)
      .bind(record.outputSha256, account, record.locationId, reference, leaseId));
  }
  statements.push(env.DB.prepare(`UPDATE accounts SET units=units+? WHERE id=? AND ${claimed}`)
    .bind(records.length, account, reference, leaseId));
  statements.push(env.DB.prepare(`UPDATE scene_candidates SET state='published' WHERE lease_id=? AND ${claimed}`)
    .bind(leaseId, reference, leaseId));
  const published = await env.DB.batch(statements);
  const earned = published[0].meta?.changes === 1 ? records.length : 0;
  if (!earned) {
    const current = await env.DB.prepare("SELECT * FROM scene_candidates WHERE lease_id=?").bind(leaseId).first();
    if (current.state === "pending") throw new ScenePipelineError("scene_submission_conflict", 409);
    return candidateResult(current);
  }
  return { accepted: earned, unitsEarned: earned, pendingAudit: false, replayed: earned === 0, segments: [] };
}
