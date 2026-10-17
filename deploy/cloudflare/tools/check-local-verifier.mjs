// Synthetic, local-only R2/Worker exercise. This is not a Windows approval.
import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash } from "node:crypto";

const runtime = process.argv[2];
if (!runtime) throw Error("Specify the local Miniflare module entry.");
const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(runtime)).href);
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const record = Buffer.alloc(3080);
for (let view = 0; view < 4; view++) { record[view * 770 + 1] = 60; record[view * 770 + 2] = view + 1; }
const reference = Buffer.concat(Array.from({ length: 112 }, () => record));
const canary = { locations: 112, fixtureSha256: "a".repeat(64), referenceSha256: digest(reference),
  outputSha256: digest(reference), records: Array.from({ length: 112 }, () => record.toString("base64")) };
const records = [{ locationId: 1, assetId: "synthetic-local-only", capture: "2026-09", inputModel: "local-fixture",
  lat: 10, lng: 20, heading: 90, pitch: 0, zoom: 0, outputSha256: digest(record) }];
const submissionSha256 = digest(Buffer.concat([Buffer.from(JSON.stringify(records) + "\n"), record]));
const policy = { version: 1, scope: "staging-reference-only", policyId: "synthetic-local-only",
  runtimeProfileSha256: "b".repeat(64), fixtureSha256: canary.fixtureSha256, referenceSha256: canary.referenceSha256,
  fullCalibration: { approved: true, locations: 1024, repetitions: 3, evidenceSha256: "c".repeat(64) },
  thresholds: { minimumViewCosine: 1, maximumViewRelativeL2: 0 }, approvedSubmissionSha256: [submissionSha256] };
const encodedPolicy = Buffer.from(JSON.stringify(policy));
const source = fileURLToPath(new URL("../scene-verifier/worker.js", import.meta.url));
const options = { modules: true, scriptPath: source, modulesRoot: dirname(source), compatibilityDate: "2026-09-29",
  r2Buckets: ["POLICY"], bindings: { VERIFIER_MODE: "staging-reference-only", SCENE_POLICY_KEY: "local-policy.json",
    CANARY_REFERENCE_KEY: "local-reference.i8", SCENE_POLICY_SHA256: digest(encodedPolicy) } };
const mf = new Miniflare(convertV4MiniflareOptions ? convertV4MiniflareOptions(options) : options);
try {
  const bucket = await mf.getR2Bucket("POLICY");
  await bucket.put("local-policy.json", encodedPolicy);
  await bucket.put("local-reference.i8", reference);
  const qualifyBody = { policyId: policy.policyId, profileId: policy.runtimeProfileSha256,
    canarySha256: digest(Buffer.from(JSON.stringify(canary))), canary };
  const post = (route, body) => mf.dispatchFetch(`https://verifier.test/${route}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const qualified = await post("qualify", qualifyBody);
  assert.equal(qualified.status, 200);
  assert.equal((await qualified.json()).approved, true);
  const changedCanary = structuredClone(canary);
  const changedRecord = Buffer.from(record); changedRecord[2] = 255;
  changedCanary.records[0] = changedRecord.toString("base64");
  changedCanary.outputSha256 = digest(Buffer.concat([changedRecord, reference.subarray(3080)]));
  const altered = await post("qualify", { ...qualifyBody, canary: changedCanary,
    canarySha256: digest(Buffer.from(JSON.stringify(changedCanary))), metrics: { minimumViewCosine: 1, maximumViewRelativeL2: 0 } });
  assert.equal(altered.status, 422);
  assert.equal((await altered.json()).approved, false);
  const audit = { policyId: policy.policyId, profileId: policy.runtimeProfileSha256, records,
    indexBase64: record.toString("base64"), submissionSha256 };
  assert.equal((await (await post("audit", audit)).json()).decision, "approved");
  const changedMetadata = structuredClone(audit); changedMetadata.records[0].heading = 180;
  const rejected = await post("audit", changedMetadata);
  assert.equal(rejected.status, 422);
  await bucket.put("local-policy.json", JSON.stringify({ ...policy, policyId: "tampered" }));
  assert.equal((await post("qualify", qualifyBody)).status, 503);
  await bucket.put("local-policy.json", encodedPolicy);
  await bucket.put("local-reference.i8", Buffer.alloc(reference.length));
  assert.equal((await post("qualify", qualifyBody)).status, 503);
  console.log("Cloudflare local verifier passed: private R2 policy/reference pins, independent vector comparison, payload-bound audit, tampering rejection.");
} finally { await mf.dispose(); }
