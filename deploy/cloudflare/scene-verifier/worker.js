const RECORD_BYTES = 3080;
const VIEW_BYTES = 770;
const DIMENSIONS = 768;
const CANARY_LOCATIONS = 112;
const MAX_EXPIRY_SECONDS = 30 * 86400;
const MAX_REQUEST_BYTES = 6 * 1024 * 1024;
const MAX_POLICY_BYTES = 1024 * 1024;
const MAX_SUBMISSION_LOCATIONS = 1000;

class VerifierError extends Error {
  constructor(code, status) { super(code); this.status = status; }
}

async function boundedBytes(body, limit) {
  if (!body) throw new VerifierError("invalid_request", 400);
  const reader = body.getReader();
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > limit) {
        await reader.cancel();
        throw new VerifierError("payload_too_large", 413);
      }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return bytes;
}

function response(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
}

function hex(value) { return typeof value === "string" && /^[a-f0-9]{64}$/.test(value); }

async function sha256(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function f16(bytes, offset) {
  const raw = bytes[offset] | (bytes[offset + 1] << 8);
  const sign = raw >>> 15;
  const exponent = (raw >>> 10) & 31;
  const fraction = raw & 1023;
  if (sign || exponent === 31 || (!exponent && !fraction)) return null;
  return exponent ? (1 + fraction / 1024) * 2 ** (exponent - 15) : fraction * 2 ** -24;
}

function signed(bytes, offset) { return bytes[offset] > 127 ? bytes[offset] - 256 : bytes[offset]; }

function validRecord(bytes, offset) {
  for (let view = 0; view < 4; view += 1) if (f16(bytes, offset + view * VIEW_BYTES) === null) return false;
  return true;
}

function decodeBase64(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9+/]*={0,2}$/.test(value) || value.length % 4) return null;
  try {
    const raw = atob(value);
    const bytes = new Uint8Array(raw.length);
    for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
    return bytes;
  } catch { return null; }
}

function canaryBytes(canary) {
  if (!canary || canary.locations !== CANARY_LOCATIONS || !Array.isArray(canary.records) || canary.records.length !== CANARY_LOCATIONS) return null;
  const output = new Uint8Array(CANARY_LOCATIONS * RECORD_BYTES);
  for (let index = 0; index < CANARY_LOCATIONS; index += 1) {
    const record = decodeBase64(canary.records[index]);
    if (!record || record.length !== RECORD_BYTES || !validRecord(record, 0)) return null;
    output.set(record, index * RECORD_BYTES);
  }
  return output;
}

function canaryMetrics(candidate, reference) {
  if (candidate.length !== reference.length || candidate.length !== CANARY_LOCATIONS * RECORD_BYTES) return null;
  let minimumViewCosine = 2;
  let maximumViewRelativeL2 = 0;
  for (let offset = 0; offset < candidate.length; offset += VIEW_BYTES) {
    const candidateScale = f16(candidate, offset);
    const referenceScale = f16(reference, offset);
    if (candidateScale === null || referenceScale === null) return null;
    let dot = 0; let candidateNorm = 0; let referenceNorm = 0; let error = 0;
    for (let dimension = 0; dimension < DIMENSIONS; dimension += 1) {
      const left = signed(candidate, offset + 2 + dimension);
      const right = signed(reference, offset + 2 + dimension);
      dot += left * right; candidateNorm += left * left; referenceNorm += right * right;
      const delta = left * candidateScale - right * referenceScale;
      error += delta * delta;
    }
    if (!candidateNorm || !referenceNorm) return null;
    minimumViewCosine = Math.min(minimumViewCosine, Math.max(-1, Math.min(1, dot / Math.sqrt(candidateNorm * referenceNorm))));
    maximumViewRelativeL2 = Math.max(maximumViewRelativeL2, Math.sqrt(error) / (Math.sqrt(referenceNorm) * referenceScale));
  }
  return { minimumViewCosine, maximumViewRelativeL2 };
}

function policyValid(policy) {
  const calibration = policy?.fullCalibration;
  const threshold = policy?.thresholds;
  return policy?.version === 1 && policy.scope === "staging-reference-only"
    && typeof policy.policyId === "string" && policy.policyId.length > 0
    && ["runtimeProfileSha256", "fixtureSha256", "referenceSha256"].every((key) => hex(policy[key]))
    && calibration?.approved === true && calibration.locations === 1024 && Number.isInteger(calibration.repetitions)
    && calibration.repetitions >= 3 && hex(calibration.evidenceSha256) && threshold !== null
    && typeof threshold === "object" && !Array.isArray(threshold)
    && Object.keys(threshold).sort().join(",") === "maximumViewRelativeL2,minimumViewCosine"
    && Number.isFinite(threshold.minimumViewCosine) && Number.isFinite(threshold.maximumViewRelativeL2)
    && threshold.minimumViewCosine >= -1 && threshold.minimumViewCosine <= 1 && threshold.maximumViewRelativeL2 >= 0
    && (policy.expiresInSeconds === undefined || (Number.isInteger(policy.expiresInSeconds) && policy.expiresInSeconds > 0 && policy.expiresInSeconds <= MAX_EXPIRY_SECONDS))
    && (policy.approvedSubmissionSha256 === undefined || (Array.isArray(policy.approvedSubmissionSha256) && policy.approvedSubmissionSha256.every(hex)));
}

async function loadPolicy(env) {
  if (env.VERIFIER_MODE !== "staging-reference-only" || !env.POLICY
      || typeof env.SCENE_POLICY_KEY !== "string" || !hex(env.SCENE_POLICY_SHA256 || "")) return null;
  const object = await env.POLICY.get(env.SCENE_POLICY_KEY);
  if (!object) return null;
  if (object.size > MAX_POLICY_BYTES) return null;
  const raw = await boundedBytes(object.body, MAX_POLICY_BYTES);
  if (await sha256(raw) !== env.SCENE_POLICY_SHA256) return null;
  try { const policy = JSON.parse(new TextDecoder().decode(raw)); return policyValid(policy) ? policy : null; } catch { return null; }
}

async function loadReference(env, policy) {
  if (!env.POLICY || typeof env.CANARY_REFERENCE_KEY !== "string") return null;
  const object = await env.POLICY.get(env.CANARY_REFERENCE_KEY);
  if (!object) return null;
  if (object.size !== undefined && object.size !== CANARY_LOCATIONS * RECORD_BYTES) return null;
  const bytes = await boundedBytes(object.body, CANARY_LOCATIONS * RECORD_BYTES);
  if (bytes.length !== CANARY_LOCATIONS * RECORD_BYTES || await sha256(bytes) !== policy.referenceSha256) return null;
  for (let offset = 0; offset < bytes.length; offset += RECORD_BYTES) if (!validRecord(bytes, offset)) return null;
  return bytes;
}

async function qualification(env, body) {
  const policy = await loadPolicy(env);
  if (!policy) return response({ error: "scene_verifier_unavailable" }, 503);
  if (body?.policyId !== policy.policyId || body?.profileId !== policy.runtimeProfileSha256) return response({ approved: false }, 422);
  const canary = body.canary;
  if (canary?.fixtureSha256 !== policy.fixtureSha256 || canary?.referenceSha256 !== policy.referenceSha256) return response({ approved: false }, 422);
  const candidate = canaryBytes(canary);
  if (!candidate || canary.outputSha256 !== await sha256(candidate)) return response({ approved: false }, 422);
  const reference = await loadReference(env, policy);
  const metrics = reference ? canaryMetrics(candidate, reference) : null;
  if (!metrics || metrics.minimumViewCosine < policy.thresholds.minimumViewCosine || metrics.maximumViewRelativeL2 > policy.thresholds.maximumViewRelativeL2) return response({ approved: false }, 422);
  const canarySha256 = await sha256(new TextEncoder().encode(JSON.stringify(canary)));
  if (body.canarySha256 !== canarySha256) return response({ approved: false }, 422);
  const expiresAt = Math.floor(Date.now() / 1000) + (policy.expiresInSeconds || 7 * 86400);
  return response({ approved: true, policyId: policy.policyId, profileId: body.profileId, canarySha256, expiresAt });
}

async function audit(env, body) {
  const policy = await loadPolicy(env);
  if (!policy) return response({ error: "scene_verifier_unavailable" }, 503);
  if (body?.policyId !== policy.policyId || body?.profileId !== policy.runtimeProfileSha256 || !hex(body?.submissionSha256)) return response({ decision: "rejected" }, 422);
  const records = body.records;
  const blob = decodeBase64(body.indexBase64);
  if (!Array.isArray(records) || !records.length || records.length > MAX_SUBMISSION_LOCATIONS
      || !blob || blob.length !== records.length * RECORD_BYTES) return response({ error: "invalid_submission" }, 422);
  const ids = new Set();
  for (let index = 0; index < records.length; index += 1) {
    const record = records[index];
    if (!record || !Number.isSafeInteger(record.locationId) || record.locationId <= 0 || ids.has(record.locationId)
        || ["assetId", "capture", "inputModel"].some((key) => typeof record[key] !== "string" || !record[key])
        || ["lat", "lng", "heading", "pitch", "zoom"].some((key) => !Number.isFinite(record[key]))
        || !hex(record.outputSha256) || !validRecord(blob, index * RECORD_BYTES)
        || await sha256(blob.subarray(index * RECORD_BYTES, (index + 1) * RECORD_BYTES)) !== record.outputSha256) {
      return response({ error: "invalid_submission" }, 422);
    }
    ids.add(record.locationId);
  }
  const metadata = new TextEncoder().encode(JSON.stringify(records) + "\n");
  const submitted = new Uint8Array(metadata.length + blob.length);
  submitted.set(metadata); submitted.set(blob, metadata.length);
  if (await sha256(submitted) !== body.submissionSha256) return response({ error: "invalid_submission" }, 422);
  // New work remains rejected until an independently reviewed inference auditor is connected.
  const approved = new Set(policy.approvedSubmissionSha256 || []);
  return response({ policyId: policy.policyId, submissionSha256: body.submissionSha256, decision: approved.has(body.submissionSha256) ? "approved" : "rejected" });
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (!["/qualify", "/audit"].includes(path)) return response({ error: "not_found" }, 404);
    if (request.method !== "POST") return response({ error: "not_found" }, 404);
    if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") return response({ error: "invalid_request" }, 400);
    try {
      const raw = await boundedBytes(request.body, MAX_REQUEST_BYTES);
      let body;
      try { body = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)); }
      catch { return response({ error: "invalid_request" }, 400); }
      if (!body || typeof body !== "object" || Array.isArray(body)) return response({ error: "invalid_request" }, 400);
      return await (path === "/qualify" ? qualification(env, body) : audit(env, body));
    } catch (error) {
      return response({ error: error instanceof VerifierError ? error.message : "scene_verifier_unavailable" }, error instanceof VerifierError ? error.status : 503);
    }
  },
};
