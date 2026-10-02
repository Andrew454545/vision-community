import assert from "node:assert/strict";
import test from "node:test";
import { check, default as worker } from "../tools/private-native-host-check.js";

function fixture() {
  const values = new Map(), calls = [];
  const key = "native-host/checks/synthetic-check.json";
  const state = { activeBundle: null, fail: null };
  const identity = { identityOnly: true, auditReady: false, searchReady: false, productionQualified: false };
  const env = { CHECK_RECEIPT_KEY: key, OPERATOR_BUCKET_NAME: "vision-community-staging",
    CHECK_NOT_BEFORE: new Date(Date.now() - 60000).toISOString(),
    CHECK_NOT_AFTER: new Date(Date.now() + 60000).toISOString(),
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
          : { status: path === "/operator/launch-check" ? "native_launch_check_passed" : "native_model_check_passed", productionQualified: false });
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

test("isolated launch mode runs once without health, model inference or imagery", async () => {
  const { env, calls, receipt } = fixture();
  env.CHECK_MODE = "launch";
  await check(env);
  assert.equal(receipt().status, "PRIVATE_NATIVE_LAUNCH_CHECKS_PASSED");
  assert.equal(receipt().checks.length, 1);
  assert.deepEqual(calls, [["/operator/status", "GET"], ["/operator/launch-check", "POST"], ["/operator/restart", "POST"]]);
  const count = calls.length;
  await check(env);
  assert.equal(calls.length, count);
});

test("early and expired deliveries cannot write storage or start compute", async () => {
  for (const offset of [-120000, 120000]) {
    const { env, calls, values } = fixture();
    env.CHECK_NOT_BEFORE = new Date(Date.now() + offset).toISOString();
    env.CHECK_NOT_AFTER = new Date(Date.now() + offset + 60000).toISOString();
    await check(env);
    assert.equal(values.size, 0);
    assert.equal(calls.length, 0);
  }
});

test("missing, ambiguous, invalid or oversized execution windows fail closed", async () => {
  for (const [start, end] of [
    [undefined, undefined], ["2026-10-02T19:00:00Z", "2026-10-02T19:01:00Z"],
    ["2026-02-30T19:00:00.000Z", "2026-02-30T19:01:00.000Z"],
    ["2026-10-02T19:00:00.000Z", "2026-10-02T19:00:00.000Z"],
    ["2026-10-02T19:00:00.000Z", "2026-10-02T19:31:00.000Z"],
    ["2026-10-02T19:00:00.000Z", "2026-10-02T18:59:00.000Z"],
  ]) {
    const { env, calls, values } = fixture();
    env.CHECK_NOT_BEFORE = start; env.CHECK_NOT_AFTER = end;
    await assert.rejects(check(env), /private_native_check_configuration/);
    assert.equal(values.size, 0);
    assert.equal(calls.length, 0);
  }
});

test("a successful HTTP response cannot substitute for a model check receipt", async () => {
  for (const result of [{ error: "unavailable" },
    { status: "native_model_check_passed", productionQualified: true }]) {
    const { env, receipt, calls } = fixture(), fetch = env.NATIVE_OPERATOR.fetch;
    env.NATIVE_OPERATOR.fetch = async (url, init) => new URL(url).pathname === "/operator/model-check"
      ? Response.json(result) : fetch(url, init);
    await check(env);
    assert.equal(receipt().status, "FAILED");
    assert.equal(receipt().failureStage, "real_model_before_restart");
    assert.deepEqual(calls.at(-1), ["/operator/restart", "POST"]);
  }
});

test("failed final shutdown cannot be reported as a passed launch check", async () => {
  const { env, state, receipt } = fixture();
  env.CHECK_MODE = "launch"; state.fail = "/operator/restart";
  await check(env);
  assert.equal(receipt().status, "FAILED");
  assert.equal(receipt().failureStage, "final_stop");
  assert.equal(receipt().finalStopFailed, true);
  assert.equal(receipt().checks.length, 1);
});

test("combined check preserves offline launch evidence before testing model and restart", async () => {
  const { env, calls, receipt } = fixture();
  env.CHECK_MODE = "launch-model-restart";
  await check(env);
  assert.equal(receipt().status, "PRIVATE_NATIVE_MODEL_AND_RESTART_CHECKS_PASSED");
  assert.equal(receipt().checks.length, 6);
  assert.equal(receipt().checks[0].stage, "isolated_launch");
  assert.deepEqual(calls.slice(0, 3), [["/operator/status", "GET"],
    ["/operator/launch-check", "POST"], ["/health", "GET"]]);
  assert.deepEqual(calls.at(-1), ["/operator/restart", "POST"]);
  const count = calls.length;
  await check(env);
  assert.equal(calls.length, count);
});

test("large combined reports retain independently readable model and restart evidence", async () => {
  const { env, values, receipt } = fixture(), fetch = env.NATIVE_OPERATOR.fetch;
  env.CHECK_MODE = "launch-model-restart";
  env.NATIVE_OPERATOR.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    if (path === "/health") return Response.json({ status: "native_host_available",
      runtimeSha256: "a".repeat(64), identityOnly: true, auditReady: false, searchReady: false,
      activeNativeProcessesMaximum: 1, productionQualified: false });
    if (path === "/operator/launch-check") return Response.json({ status: "native_launch_check_passed",
      runtimeSha256: "a".repeat(64), pythonVersion: "3.12.15", uid: 10001,
      modelFilesValidated: true, httpServerChecked: true, serviceAuthChecked: true,
      operatorAuthChecked: true, productionQualified: false });
    return path === "/operator/model-check" ? Response.json({ status: "native_model_check_passed", runtimeSha256: "a".repeat(64),
      locations: 1, views: 4, fetchErrors: 0, inferenceErrors: 0, bytes: 3080,
      outputSha256: "b".repeat(64), sceneGraph: "fp32", executionProvider: "cpu", threads: 1,
      elapsedSeconds: 41.123, peakChildRssKiB: 1324000, productionQualified: false })
    : fetch(url, init);
  };
  await check(env);
  const report = receipt();
  assert.ok(new TextEncoder().encode(values.get(env.CHECK_RECEIPT_KEY)).byteLength > 1800);
  assert.equal(report.status, "PRIVATE_NATIVE_MODEL_AND_RESTART_CHECKS_PASSED");
  const steps = [...values].filter(([key]) => key.startsWith(env.CHECK_RECEIPT_KEY + ".step-"));
  assert.equal(steps.length, report.checks.length);
  assert.deepEqual(steps.map(([, body]) => JSON.parse(body)), report.checks);
  const count = values.size;
  await check(env);
  assert.equal(values.size, count);
});

test("a stage-receipt storage failure preserves the failure and cannot report a passed check", async () => {
  for (const outcome of ["throw", "conflict"]) {
    const { env, receipt, calls } = fixture(), put = env.CHECK_REPORTS.put;
    env.CHECK_MODE = "launch";
    env.CHECK_REPORTS.put = async (key, ...args) => {
      if (key.includes(".step-")) {
        if (outcome === "throw") throw Error("synthetic storage failure");
        return null;
      }
      return put(key, ...args);
    };
    await check(env);
    assert.equal(receipt().status, "FAILED");
    assert.equal(receipt().failureStage, "receipt_details");
    assert.equal(receipt().receiptDetailsUnavailable, true);
    assert.deepEqual(calls.at(-1), ["/operator/restart", "POST"]);
  }
});
