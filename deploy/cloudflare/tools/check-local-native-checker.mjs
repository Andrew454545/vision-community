// Deliver actual scheduled events to the deployed checker bundle. Native
// responses are synthetic; this checks private orchestration, not inference.
import assert from "node:assert/strict";
import { resolve, dirname } from "node:path";
import { pathToFileURL } from "node:url";
const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(process.argv[2])));
const scriptPath = resolve(process.argv[3]), key = "native-host/checks/local-operator-check.json";
let launches = 0, stops = 0;
const mf = new Miniflare(convertV4MiniflareOptions({ modules: true, scriptPath,
  modulesRoot: dirname(scriptPath), compatibilityDate: "2026-10-02", compatibilityFlags: ["nodejs_compat"],
  r2Buckets: ["CHECK_REPORTS"], bindings: { CHECK_MODE: "launch", CHECK_RECEIPT_KEY: key,
    CHECK_NOT_BEFORE: new Date(Date.now() - 60000).toISOString(),
    CHECK_NOT_AFTER: new Date(Date.now() + 60000).toISOString(),
    OPERATOR_BUCKET_NAME: "vision-community-staging" }, serviceBindings: { NATIVE_OPERATOR: request => {
      const route = new URL(request.url).pathname;
      if (route === "/operator/status") return Response.json({ activeBundle: null });
      if (route === "/operator/launch-check") {
        launches++;
        return Response.json({ status: "native_launch_check_passed", productionQualified: false,
          runtimeSha256: "a".repeat(64), synthetic: true });
      }
      if (route === "/operator/restart") { stops++; return Response.json({ stopped: true }); }
      return Response.json({ error: "synthetic_unused_route" }, { status: 404 });
    } } }));
try {
  const bucket = await mf.getR2Bucket("CHECK_REPORTS"), worker = await mf.getWorker();
  const publicResponse = await mf.dispatchFetch("https://checker.invalid/operator/launch-check", { method: "POST" });
  assert.equal(publicResponse.status, 404);
  assert.equal(launches, 0);
  await worker.scheduled({ cron: "5,10,15,20,25 13 2 10 *" });
  const marker = await bucket.get(key + ".started"), report = await bucket.get(key);
  assert.ok(marker); assert.ok(report);
  const body = await report.text(), receipt = JSON.parse(body);
  assert.equal(receipt.status, "PRIVATE_NATIVE_LAUNCH_CHECKS_PASSED");
  assert.equal(receipt.productionQualified, false);
  assert.equal(receipt.rawRecordsUploaded, false);
  assert.equal(receipt.acceptedContributions, 0);
  assert.equal(report.customMetadata.receipt, body);
  assert.equal(launches, 1); assert.equal(stops, 1);
  for (let i = 0; i < 4; i++) await worker.scheduled({ cron: "5,10,15,20,25 13 2 10 *" });
  assert.equal(launches, 1); assert.equal(stops, 1);
  assert.equal(await (await bucket.get(key)).text(), body);
  console.log(JSON.stringify({ status: "ACTUAL_WORKERD_PRIVATE_CHECKER_PASSED",
    scheduledEventsDelivered: 5, syntheticLaunches: launches, publicRequestsRejected: true,
    createOnlyMarkerPreventsRepeatedCompute: true, privateReceiptMetadataMatches: true,
    modelInferenceTested: false }));
} finally { await mf.dispose(); }

for (const offset of [-120000, 120000]) {
  let calls = 0;
  const isolated = new Miniflare(convertV4MiniflareOptions({ modules: true, scriptPath,
    modulesRoot: dirname(scriptPath), compatibilityDate: "2026-10-02",
    compatibilityFlags: ["nodejs_compat"], r2Buckets: ["CHECK_REPORTS"],
    bindings: { CHECK_MODE: "launch", CHECK_RECEIPT_KEY: key,
      OPERATOR_BUCKET_NAME: "vision-community-staging",
      CHECK_NOT_BEFORE: new Date(Date.now() + offset).toISOString(),
      CHECK_NOT_AFTER: new Date(Date.now() + offset + 60000).toISOString() },
    serviceBindings: { NATIVE_OPERATOR: () => { calls++; throw Error("unexpected_compute"); } } }));
  try {
    await (await isolated.getWorker()).scheduled({ cron: "* * * * *" });
    assert.equal(calls, 0);
    const bucket = await isolated.getR2Bucket("CHECK_REPORTS");
    assert.equal((await bucket.list()).objects.length, 0);
  } finally { await isolated.dispose(); }
}
console.log(JSON.stringify({ status: "ACTUAL_WORKERD_PRIVATE_CHECK_EXPIRY_PASSED",
  earlyAndExpiredDeliveriesRejected: true, storageUntouched: true, computeStarted: false }));
