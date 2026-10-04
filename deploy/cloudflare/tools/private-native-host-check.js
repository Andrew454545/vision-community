// One-time, account-private scheduled check. No public route or secret export.
import { bounded } from "../native-scene-bridge/worker.js";

async function call(env, path, method = "GET") {
  const response = await env.NATIVE_OPERATOR.fetch(`https://operator.invalid${path}`, { method });
  if (response.status !== 200) throw Error("private_native_check_unavailable");
  const body = new TextDecoder().decode(await bounded(response.body, 16384));
  return JSON.parse(body);
}

async function modelCheck(env) {
  const receipt = await call(env, "/operator/model-check", "POST");
  if (receipt.status !== "native_model_check_passed" || receipt.productionQualified !== false) {
    throw Error("model_check_unavailable");
  }
  return receipt;
}

export async function check(env) {
  const key = env.CHECK_RECEIPT_KEY;
  const start = Date.parse(env.CHECK_NOT_BEFORE), end = Date.parse(env.CHECK_NOT_AFTER);
  const timestamp = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
  if (env.OPERATOR_BUCKET_NAME !== "vision-community-staging"
      || ![undefined, "model-restart", "launch", "main", "launch-model-restart"].includes(env.CHECK_MODE)
      || typeof key !== "string" || !/^native-host\/checks\/[a-z0-9-]{1,80}\.json$/.test(key)
      || !timestamp.test(env.CHECK_NOT_BEFORE) || !timestamp.test(env.CHECK_NOT_AFTER)
      || !Number.isFinite(start) || !Number.isFinite(end)
      || new Date(start).toISOString() !== env.CHECK_NOT_BEFORE
      || new Date(end).toISOString() !== env.CHECK_NOT_AFTER
      || end <= start || end - start > 30 * 60 * 1000) {
    throw Error("private_native_check_configuration");
  }
  // Cron has no year field and trigger removal can take time to propagate.
  // An absolute, short window prevents late or next-year deliveries from
  // creating a marker or starting compute, even if a trigger is left behind.
  const now = Date.now();
  if (now < start || now >= end) return;
  // A persisted marker prevents a later cron delivery from repeating work.
  const marker = await env.CHECK_REPORTS.put(key + ".started", "one-time operator check", {
    onlyIf: { etagDoesNotMatch: "*" }, httpMetadata: { contentType: "text/plain" },
  });
  if (!marker) return;
  const receipt = { scope: "private-native-host-check", status: "FAILED", checks: [],
    productionQualified: false, acceptedContributions: 0, publicRouteEnabled: false,
    rawRecordsUploaded: false, checkedAt: new Date().toISOString() };
  let stage = "initial_state", identityOnly = false;
  try {
    const state = await call(env, "/operator/status");
    if (state.activeBundle !== null) throw Error("sealed_bundle_already_active");
    identityOnly = true;
    if (env.CHECK_MODE === "main") {
      stage = "main_program_startup";
      const result = await call(env, "/operator/main-check", "POST");
      if (result.status !== "native_main_check_passed" || result.mainProgramChecked !== true
          || result.productionQualified !== false) throw Error("main_check_unavailable");
      receipt.checks.push({ stage, ...result });
      receipt.status = "PRIVATE_NATIVE_MAIN_CHECKS_PASSED";
      return;
    }
    if (["launch", "launch-model-restart"].includes(env.CHECK_MODE)) {
      stage = "isolated_launch";
      const result = await call(env, "/operator/launch-check", "POST");
      if (result.status !== "native_launch_check_passed" || result.productionQualified !== false) throw Error("launch_check_unavailable");
      receipt.checks.push({ stage, ...result });
      if (env.CHECK_MODE === "launch") {
        receipt.status = "PRIVATE_NATIVE_LAUNCH_CHECKS_PASSED";
        return;
      }
    }
    stage = "initial_identity";
    const identity = await call(env, "/health");
    if (!identity.identityOnly || identity.auditReady || identity.searchReady || identity.productionQualified) throw Error("unexpected_readiness");
    receipt.checks.push({ stage, ...identity });
    stage = "real_model_before_restart";
    receipt.checks.push({ stage, ...await modelCheck(env) });
    stage = "container_restart";
    const stopped = await call(env, "/operator/restart", "POST");
    if (!stopped.stopped || stopped.activeBundleRetained) throw Error("unexpected_active_bundle");
    receipt.checks.push({ stage, ...stopped });
    stage = "identity_after_restart";
    const reopened = await call(env, "/health");
    if (JSON.stringify(reopened) !== JSON.stringify(identity)) throw Error("runtime_identity_changed");
    receipt.checks.push({ stage, ...reopened });
    stage = "real_model_after_restart";
    receipt.checks.push({ stage, ...await modelCheck(env) });
    receipt.status = "PRIVATE_NATIVE_MODEL_AND_RESTART_CHECKS_PASSED";
  } catch {
    receipt.failureStage = stage;
    receipt.error = "private_native_check_failed";
    try {
      const state = await call(env, "/operator/status");
      receipt.lastControlFailure = state.lastControlFailure ?? null;
      receipt.lastContainerExit = state.lastContainerExit ?? null;
      receipt.lastBootFailure = state.lastBootFailure ?? null;
      receipt.lastLaunchFailure = state.lastLaunchFailure ?? null;
    } catch { /* The stage still preserves a failure if status is unavailable. */ }
  } finally {
    // Stop compute after either result. A sealed production bundle is never used
    // by this identity-only check; durable metadata remains for diagnostics.
    if (identityOnly) {
      try { await call(env, "/operator/restart", "POST"); }
      catch {
        receipt.finalStopFailed = true;
        if (receipt.status !== "FAILED") {
          receipt.status = "FAILED";
          receipt.failureStage = "final_stop";
          receipt.error = "private_native_check_failed";
        }
      }
    }
    // Keep each small stage receipt independently inspectable when the complete
    // combined report exceeds R2's custom-metadata budget. The API connector
    // can list metadata even when it cannot unwrap a raw object response.
    // These fixed diagnostics contain hashes/measurements, never source data.
    try {
      for (let index = 0; index < receipt.checks.length; index++) {
        const document = JSON.stringify(receipt.checks[index]);
        if (new TextEncoder().encode(document).byteLength > 1800) throw Error("receipt_detail_limit");
        const saved = await env.CHECK_REPORTS.put(key + ".step-" + index, document, {
          onlyIf: { etagDoesNotMatch: "*" },
          httpMetadata: { contentType: "application/json" },
          customMetadata: { receipt: document },
        });
        if (!saved) throw Error("receipt_detail_conflict");
      }
    } catch {
      receipt.receiptDetailsUnavailable = true;
      if (receipt.status !== "FAILED") {
        receipt.status = "FAILED";
        receipt.failureStage = "receipt_details";
        receipt.error = "private_native_check_failed";
      }
    }
    const document = JSON.stringify(receipt);
    await env.CHECK_REPORTS.put(key, document, {
      httpMetadata: { contentType: "application/json" },
      // Account-private list metadata remains readable when a connector cannot
      // unwrap raw R2 object responses. The complete report stays in the body.
      customMetadata: { receipt: document.length <= 1800 ? document : JSON.stringify({
        scope: receipt.scope, status: receipt.status, failureStage: receipt.failureStage,
        lastControlFailure: receipt.lastControlFailure, lastContainerExit: receipt.lastContainerExit,
        lastBootFailure: receipt.lastBootFailure,
        lastLaunchFailure: receipt.lastLaunchFailure,
        checksCompleted: receipt.checks.length, productionQualified: false,
      }) },
    });
  }
}

export default {
  fetch() { return Response.json({ error: "not_found" }, { status: 404 }); },
  scheduled(_controller, env, ctx) { ctx.waitUntil(check(env)); },
};
