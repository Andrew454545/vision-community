import assert from "node:assert/strict";
import test from "node:test";
import { check, default as worker } from "../tools/private-native-host-check.js";

function fixture() {
  const values = new Map(), calls = [];
  const key = "native-host/checks/synthetic-check.json";
  const state = { activeBundle: null, fail: null };
  const identity = { identityOnly: true, auditReady: false, searchReady: false, productionQualified: false };
  const env = { CHECK_RECEIPT_KEY: key, OPERATOR_BUCKET_NAME: "vision-community-staging",
    CHECK_REPORTS: { async put(name, bytes, options) {
      if (options?.onlyIf && values.has(name)) return null;
      values.set(name, bytes); return { key: name };
    } },
    NATIVE_OPERATOR: { async fetch(url, init) {
      const path = new URL(url).pathname;
      calls.push([path, init.method]);
      if (state.fail === path) return Response.json({ error: "unavailable" }, { status: 503 });
      return Response.json(path === "/operator/status" ? { activeBundle: state.activeBundle }
        : path === "/health" ? identity : path === "/operator/restart" ? { stopped: true, activeBundleRetained: false }
          : { status: "native_model_check_passed", productionQualified: false });
    } } };
  return { env, state, values, calls, receipt: () => JSON.parse(values.get(key)) };
}

test("private check runs once, tests real diagnostic/restart routes and stops compute", async () => {
  const { env, calls, receipt } = fixture();
  await check(env);
  const count = calls.length;
  await check(env);
  assert.equal(calls.length, count);
  assert.equal(receipt().status, "PRIVATE_NATIVE_MODEL_AND_RESTART_CHECKS_PASSED");
  assert.equal(receipt().checks.length, 5);
  assert.equal(receipt().productionQualified, false);
  assert.equal(receipt().rawRecordsUploaded, false);
  assert.equal(calls.filter(([path]) => path === "/operator/model-check").length, 2);
  assert.deepEqual(calls.at(-1), ["/operator/restart", "POST"]);
});

test("private check cannot load or restart an existing sealed bundle", async () => {
  const { env, state, calls, receipt } = fixture();
  state.activeBundle = { sha256: "a".repeat(64) };
  await check(env);
  assert.ok(calls.every(([path, method]) => path === "/operator/status" && method === "GET"));
  assert.equal(receipt().failureStage, "initial_state");
  assert.equal(receipt().status, "FAILED");
});

test("failed model check preserves a redacted report and ends compute without repeated execution", async () => {
  const { env, state, calls, receipt } = fixture();
  state.fail = "/operator/model-check";
  await check(env);
  assert.equal(receipt().status, "FAILED");
  assert.equal(receipt().failureStage, "real_model_before_restart");
  assert.equal(receipt().error, "private_native_check_failed");
  assert.deepEqual(calls.at(-1), ["/operator/restart", "POST"]);
  const count = calls.length;
  await check(env);
  assert.equal(calls.length, count);
});

test("wrong resources and public requests cannot trigger compute", async () => {
  const { env, calls } = fixture();
  const response = worker.fetch(new Request("https://check.invalid/health"), env);
  assert.equal(response.status, 404);
  env.OPERATOR_BUCKET_NAME = "geonections-images";
  await assert.rejects(check(env), /private_native_check_configuration/);
  assert.equal(calls.length, 0);
});
