// One-time, account-private scheduled check. No public route or secret export.
import { bounded } from "../native-scene-bridge/worker.js";

async function call(env, path, method = "GET") {
  const response = await env.NATIVE_OPERATOR.fetch(`https://operator.invalid${path}`, { method });
  if (response.status !== 200) throw Error("private_native_check_unavailable");
  const body = new TextDecoder().decode(await bounded(response.body, 16384));
  return JSON.parse(body);
}

export async function check(env) {
  const key = env.CHECK_RECEIPT_KEY;
  if (env.OPERATOR_BUCKET_NAME !== "vision-community-staging"
      || typeof key !== "string" || !/^native-host\/checks\/[a-z0-9-]{1,80}\.json$/.test(key)) {
    throw Error("private_native_check_configuration");
  }
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
    stage = "initial_identity";
    const identity = await call(env, "/health");
    if (!identity.identityOnly || identity.auditReady || identity.searchReady || identity.productionQualified) throw Error("unexpected_readiness");
    receipt.checks.push({ stage, ...identity });
    stage = "real_model_before_restart";
    receipt.checks.push({ stage, ...await call(env, "/operator/model-check", "POST") });
    stage = "container_restart";
    const stopped = await call(env, "/operator/restart", "POST");
    if (!stopped.stopped || stopped.activeBundleRetained) throw Error("unexpected_active_bundle");
    receipt.checks.push({ stage, ...stopped });
    stage = "identity_after_restart";
    const reopened = await call(env, "/health");
    if (JSON.stringify(reopened) !== JSON.stringify(identity)) throw Error("runtime_identity_changed");
    receipt.checks.push({ stage, ...reopened });
    stage = "real_model_after_restart";
    receipt.checks.push({ stage, ...await call(env, "/operator/model-check", "POST") });
    receipt.status = "PRIVATE_NATIVE_MODEL_AND_RESTART_CHECKS_PASSED";
  } catch {
    receipt.failureStage = stage;
    receipt.error = "private_native_check_failed";
    try {
      const state = await call(env, "/operator/status");
      receipt.lastControlFailure = state.lastControlFailure ?? null;
      receipt.lastContainerExit = state.lastContainerExit ?? null;
    } catch { /* The stage still preserves a failure if status is unavailable. */ }
  } finally {
    // Stop compute after either result. A sealed production bundle is never used
    // by this identity-only check; durable metadata remains for diagnostics.
    if (identityOnly) {
      try { await call(env, "/operator/restart", "POST"); }
      catch { receipt.finalStopFailed = true; }
    }
    const document = JSON.stringify(receipt);
    await env.CHECK_REPORTS.put(key, document, {
      httpMetadata: { contentType: "application/json" },
      // Account-private list metadata remains readable when a connector cannot
      // unwrap raw R2 object responses. The complete report stays in the body.
      customMetadata: { receipt: document.length <= 1800 ? document : JSON.stringify({
        scope: receipt.scope, status: receipt.status, failureStage: receipt.failureStage,
        lastControlFailure: receipt.lastControlFailure, lastContainerExit: receipt.lastContainerExit,
        checksCompleted: receipt.checks.length, productionQualified: false,
      }) },
    });
  }
}

export default {
  fetch() { return Response.json({ error: "not_found" }, { status: 404 }); },
  scheduled(_controller, env, ctx) { ctx.waitUntil(check(env)); },
};
