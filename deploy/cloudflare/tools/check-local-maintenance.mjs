// Actual local workerd/D1/R2. No Cloudflare account, real data or network.
import assert from "node:assert/strict";
import { resolve, dirname } from "node:path";
import { pathToFileURL } from "node:url";
const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(process.argv[2])));
const scriptPath = resolve(process.argv[3]);
const routes = ["status", "capabilities", "me", "recovery", "accounts", "account/delete",
  "searches", "leases", "leases/renew", "leases/release", "scene-qualifications", "scene-audits",
  "submissions", "views", "published-snapshot", "scene-index-file", "object-index-file", "unknown"];
for (const flag of ["1", "mistyped-operator-value"]) {
  const mf = new Miniflare(convertV4MiniflareOptions({ modules: true, scriptPath,
    modulesRoot: dirname(scriptPath), compatibilityDate: "2026-09-19", compatibilityFlags: ["nodejs_compat"],
    d1Databases: ["DB"], r2Buckets: ["INDEX"], bindings: { RESTORE_MAINTENANCE: flag,
      DEPLOYMENT_ENVIRONMENT: "staging", INDEX_BUCKET_NAME: "vision-community-staging" },
    serviceBindings: { ASSETS: () => new Response("synthetic unchanged guide") } }));
  try {
    const db = await mf.getD1Database("DB"), bucket = await mf.getR2Bucket("INDEX");
    await db.prepare("CREATE TABLE private_restore_canary (value TEXT)").run();
    await db.prepare("INSERT INTO private_restore_canary VALUES ('synthetic preserved state')").run();
    await bucket.put("synthetic-private-canary", "synthetic preserved object");
    const before = (await db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all()).results;
    for (const route of routes) for (const method of ["GET", "POST"]) {
      const response = await mf.dispatchFetch("https://community.invalid/api/" + route,
        { method, ...(method === "POST" ? { body: "deliberately not JSON" } : {}) });
      assert.equal(response.status, 503, method + " " + route);
      assert.deepEqual(await response.json(), { error: "service_maintenance" });
      assert.equal(response.headers.get("retry-after"), "60");
      assert.equal(response.headers.get("cache-control"), "no-store");
      assert.equal(response.headers.get("referrer-policy"), "no-referrer");
    }
    await (await mf.getWorker()).scheduled({ cron: "0 * * * *" });
    assert.deepEqual((await db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all()).results, before);
    assert.equal((await db.prepare("SELECT value FROM private_restore_canary").first()).value, "synthetic preserved state");
    assert.deepEqual((await bucket.list()).objects.map(o => o.key), ["synthetic-private-canary"]);
    const guide = await mf.dispatchFetch("https://community.invalid/getting-started");
    assert.equal(guide.status, 200);
    assert.equal(await guide.text(), "synthetic unchanged guide");
    assert.equal(guide.headers.get("x-frame-options"), "DENY");
    assert.equal(guide.headers.get("referrer-policy"), "no-referrer");
    assert.match(guide.headers.get("content-security-policy"), /frame-ancestors 'none'/);
  } finally { await mf.dispose(); }
}
console.log(JSON.stringify({ status: "ACTUAL_WORKERD_RESTORE_MAINTENANCE_PASSED",
  blockedHttpRequests: routes.length * 2 * 2, malformedConfigurationClosed: true,
  databaseAndStorageUnchanged: true, scheduledWritesStopped: true, guideAvailable: true,
  inFlightWritersDrained: false, liveRestore: false }));
