import assert from "node:assert/strict";
import test from "node:test";
import worker from "./worker.js";

async function digest(bytes) {
  const value = await crypto.subtle.digest("SHA-256", bytes);
  return Buffer.from(value).toString("hex");
}

function reference() {
  const record = new Uint8Array(3080);
  for (let view = 0; view < 4; view += 1) {
    const offset = view * 770;
    record[offset] = 0; record[offset + 1] = 60; // binary16 1.0
    record[offset + 2] = view + 1;
  }
  const bytes = new Uint8Array(112 * 3080);
  for (let index = 0; index < 112; index += 1) bytes.set(record, index * 3080);
  return { bytes, records: Array.from({ length: 112 }, () => Buffer.from(record).toString("base64")) };
}

async function fixture(policyOverrides = {}) {
  const { bytes, records } = reference();
  const referenceSha256 = await digest(bytes);
  const canary = { locations: 112, fixtureSha256: "a".repeat(64), referenceSha256,
    outputSha256: referenceSha256, records };
  const canarySha256 = await digest(new TextEncoder().encode(JSON.stringify(canary)));
  const policy = { version: 1, scope: "staging-reference-only", policyId: "staging-policy", runtimeProfileSha256: "b".repeat(64),
    fixtureSha256: canary.fixtureSha256, referenceSha256, fullCalibration: { approved: true, locations: 1024,
      repetitions: 3, evidenceSha256: "c".repeat(64) }, thresholds: { minimumViewCosine: 1, maximumViewRelativeL2: 0 },
    expiresInSeconds: 3600, ...policyOverrides };
  const encodedPolicy = new TextEncoder().encode(JSON.stringify(policy));
  const env = { VERIFIER_MODE: "staging-reference-only", SCENE_POLICY_KEY: "scene-policy.json", CANARY_REFERENCE_KEY: "canary-reference.i8",
    SCENE_POLICY_SHA256: await digest(encodedPolicy), POLICY: { get(key) {
      return key === "scene-policy.json" ? new Response(encodedPolicy) : key === "canary-reference.i8" ? new Response(bytes) : null;
    } } };
  return { env, policy, canary, canarySha256 };
}

function post(path, body) {
  return new Request(`https://scene-verifier.internal/${path}`, { method: "POST",
    headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
}

async function qualifyBody(canary, policy) {
  return { policyId: policy.policyId, profileId: policy.runtimeProfileSha256,
    canarySha256: await digest(new TextEncoder().encode(JSON.stringify(canary))), canary };
}

async function auditBody(policy) {
  const bytes = reference().bytes.subarray(0, 3080);
  const records = [{ locationId: 1, assetId: "synthetic-staging-panorama", capture: "2026-09",
    inputModel: "community-visual-v1", lat: 10, lng: 20, heading: 90, pitch: 0, zoom: 0,
    outputSha256: await digest(bytes) }];
  const metadata = new TextEncoder().encode(JSON.stringify(records) + "\n");
  const submission = new Uint8Array(metadata.length + bytes.length);
  submission.set(metadata); submission.set(bytes, metadata.length);
  return { policyId: policy.policyId, profileId: policy.runtimeProfileSha256, records,
    indexBase64: Buffer.from(bytes).toString("base64"), submissionSha256: await digest(submission) };
}

test("private verifier approves only a checksum-pinned reference result", async () => {
  const { env, policy, canary, canarySha256 } = await fixture();
  const request = post("qualify", {
    policyId: policy.policyId, profileId: policy.runtimeProfileSha256, canarySha256, canary,
  });
  const result = await (await worker.fetch(request, env)).json();
  assert.equal(result.approved, true);
  assert.equal(result.policyId, policy.policyId);
  assert.ok(result.expiresAt > Math.floor(Date.now() / 1000));
});

test("private verifier rejects a changed profile and unreviewed submission", async () => {
  const { env, policy, canary, canarySha256 } = await fixture();
  const rejected = await (await worker.fetch(post("qualify", {
    policyId: policy.policyId, profileId: "d".repeat(64), canarySha256, canary,
  }), env)).json();
  assert.equal(rejected.approved, false);
  const audit = await (await worker.fetch(post("audit", await auditBody(policy)), env)).json();
  assert.equal(audit.decision, "rejected");
});

test("claimed metrics cannot hide wrong vector direction, scale or a zero vector", async () => {
  for (const variation of ["direction", "scale", "zero"]) {
    const { env, policy, canary } = await fixture();
    const bytes = Buffer.from(canary.records[0], "base64");
    if (variation === "direction") bytes[2] = 255;
    if (variation === "scale") bytes[1] = 64;
    if (variation === "zero") bytes[2] = 0;
    canary.records[0] = bytes.toString("base64");
    canary.outputSha256 = await digest(Buffer.concat(canary.records.map((item) => Buffer.from(item, "base64"))));
    canary.metrics = { minimumViewCosine: 1, maximumViewRelativeL2: 0 };
    const result = await worker.fetch(post("qualify", await qualifyBody(canary, policy)), env);
    assert.equal(result.status, 422, variation);
  }
});

test("missing mode, invalid policy, storage failure and bad pins never approve", async () => {
  for (const changed of [{ thresholds: null }, { fullCalibration: { approved: false } }, { scope: "production" }]) {
    const { env, policy, canary } = await fixture(changed);
    assert.equal((await worker.fetch(post("qualify", await qualifyBody(canary, policy)), env)).status, 503);
  }
  for (const change of [
    (env) => { delete env.VERIFIER_MODE; },
    (env) => { env.SCENE_POLICY_SHA256 = "f".repeat(64); },
    (env) => { env.POLICY.get = () => { throw new Error("storage down"); }; },
  ]) {
    const { env, policy, canary } = await fixture();
    change(env);
    assert.equal((await worker.fetch(post("qualify", await qualifyBody(canary, policy)), env)).status, 503);
  }
});

test("staging approval verifies metadata and bytes instead of trusting the submitted hash", async () => {
  const initial = await fixture();
  const body = await auditBody(initial.policy);
  const { env } = await fixture({ approvedSubmissionSha256: [body.submissionSha256] });
  assert.equal((await (await worker.fetch(post("audit", body), env)).json()).decision, "approved");
  for (const changed of [
    { ...body, records: [{ ...body.records[0], heading: 180 }] },
    { ...body, indexBase64: Buffer.alloc(3080).toString("base64") },
    { ...body, profileId: "f".repeat(64) },
  ]) {
    assert.equal((await worker.fetch(post("audit", changed), env)).status, 422);
  }
});

test("missing, corrupt and zero-norm operator references are retryable service failures", async () => {
  for (const variation of ["missing", "truncated", "checksum", "zero-norm"]) {
    const bytes = reference().bytes;
    if (variation === "zero-norm") bytes[2] = 0;
    const { env, policy, canary } = await fixture(variation === "zero-norm" ? { referenceSha256: await digest(bytes) } : {});
    canary.referenceSha256 = policy.referenceSha256;
    const policyGet = env.POLICY.get;
    env.POLICY.get = key => key !== "canary-reference.i8" ? policyGet(key)
      : variation === "missing" ? null
      : new Response(variation === "truncated" ? bytes.subarray(0, 100)
        : variation === "checksum" ? new Uint8Array(bytes.length) : bytes);
    const result = await worker.fetch(post("qualify", await qualifyBody(canary, policy)), env);
    assert.equal(result.status, 503, variation);
    assert.deepEqual(await result.json(), { error: "scene_verifier_unavailable" }, variation);
  }
});

test("oversized streamed bodies and malformed JSON return safe errors", async () => {
  const { env } = await fixture();
  const oversized = new Request("https://scene-verifier.internal/qualify", { method: "POST",
    headers: { "content-type": "application/json" }, body: "x".repeat(6 * 1024 * 1024 + 1) });
  assert.equal((await worker.fetch(oversized, env)).status, 413);
  assert.equal((await worker.fetch(post("qualify", null), env)).status, 400);
  assert.equal((await worker.fetch(new Request("https://scene-verifier.internal/qualify", { method: "POST",
    headers: { "content-type": "application/json" }, body: "{" }), env)).status, 400);
});
