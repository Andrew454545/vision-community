// Deliberately local: synthetic results exercise the gateway/ledger, never
// claim model quality or enable public contributions. No Cloudflare login.
// Usage: node tools/check-local-runtime.mjs <miniflare-entry> <bundled-worker>
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { pathToFileURL } from "node:url";

const [miniflarePath, bundlePath, compatibilityDate = "2026-09-29"] = process.argv.slice(2);
if (!miniflarePath || !bundlePath) throw Error("Specify the local Miniflare entry and dry-run Worker bundle.");
const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(miniflarePath)).href);
const pins = { SEARCH_POLICY_ID: "synthetic-local-test-only", SEARCH_RUNTIME_SHA256: "b".repeat(64),
  SEARCH_SNAPSHOT_SHA256: "c".repeat(64) };
const options = { modules: true, scriptPath: resolve(bundlePath), compatibilityDate,
  modulesRoot: dirname(resolve(bundlePath)),
  compatibilityFlags: ["nodejs_compat"], d1Databases: ["DB"], r2Buckets: ["INDEX"], bindings: pins,
  serviceBindings: { ASSETS: () => new Response("local test", { status: 404 }),
    SEARCH_ENGINE: async request => Response.json({ ...await request.json(), processedLocations: 1,
      hits: [{ locationId: 1, outputSha256: "a".repeat(64), score: 0.8, viewOffset: 1 }] }) },
};
const mf = new Miniflare(convertV4MiniflareOptions ? convertV4MiniflareOptions(options) : options);

try {
  const db = await mf.getD1Database("DB");
  const schema = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
  for (const statement of schema.split(";").filter(part => part.trim())) await db.prepare(statement).run();
  await db.prepare(`INSERT INTO locations (id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,country,camera_generation)
    VALUES (1,'abcdefghijklmnopqrstuv','2026-01','scene','scene-model','published','local-contributor',10,20,90,'Italy','gen4')`).run();
  await db.prepare("INSERT INTO published_index (location_id,index_text,output_sha256,published_at,four_view_key) VALUES (1,'',?,0,'four-view-v4/local.i8')")
    .bind("a".repeat(64)).run();
  const created = await mf.dispatchFetch("https://community.test/api/accounts", {
    method: "POST", headers: { "content-type": "application/json", origin: "https://community.test" }, body: "{}" });
  assert.equal(created.status, 201);
  const account = (await created.json()).accountId;
  const session = created.headers.get("set-cookie").split(";")[0];
  await db.prepare("UPDATE accounts SET units=200000 WHERE id=?").bind(account).run();
  const request = { accountId: account, idempotencyKey: "concurrent-local-search", lane: "scene", prompt: "red door", resultCount: 200 };
  const post = body => mf.dispatchFetch("https://community.test/api/searches", { method: "POST",
    headers: { "content-type": "application/json", origin: "https://community.test", cookie: session }, body: JSON.stringify(body) });
  const duplicate = await Promise.all(Array.from({ length: 6 }, () => post(request)));
  assert.ok(duplicate.every(response => response.status === 200));
  const results = await Promise.all(duplicate.map(response => response.json()));
  assert.ok(results.every(result => result.searchId === results[0].searchId));
  assert.equal(results[0].map.customCoordinates[0].heading, 180);
  assert.equal((await db.prepare("SELECT units FROM accounts WHERE id=?").bind(account).first()).units, 100000);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM ledger").first()).n, 1);
  const changed = await post({ ...request, resultCount: 1 });
  assert.equal(changed.status, 409);
  assert.equal((await post({ ...request, accountId: "different-account" })).status, 409);
  const competing = await Promise.all([post({ ...request, idempotencyKey: "last-credit-one" }), post({ ...request, idempotencyKey: "last-credit-two" })]);
  assert.deepEqual(competing.map(response => response.status).sort(), [200, 402]);
  assert.equal((await db.prepare("SELECT units FROM accounts WHERE id=?").bind(account).first()).units, 0);
  const replay = await post(request);
  assert.equal(replay.status, 200);
  assert.equal((await replay.json()).searchId, results[0].searchId);
  for (const route of ["published-snapshot", "index-manifest", "index-shard", "scene-indexes", "scene-index-file", "object-indexes", "object-index-file"]) {
    const response = await mf.dispatchFetch(`https://community.test/api/${route}`, { headers: { cookie: session } });
    assert.equal(response.status, 410);
  }
  assert.equal((await post({ ...request, execute: "local" })).status, 410);
  await db.prepare("UPDATE accounts SET units=100000 WHERE id=?").bind(account).run();
  await db.exec("CREATE TRIGGER failed_result BEFORE INSERT ON searches BEGIN SELECT RAISE(ABORT,'simulated storage failure'); END;");
  const failed = await post({ ...request, idempotencyKey: "failed-result-storage" });
  assert.equal(failed.status, 500);
  assert.equal((await failed.json()).error, "internal_error");
  assert.equal((await db.prepare("SELECT units FROM accounts WHERE id=?").bind(account).first()).units, 100000);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM ledger").first()).n, 2);
  console.log("Cloudflare local runtime passed: concurrent search settlement, last-credit spending, request replay, retired downloads and database-failure rollback.");
} finally { await mf.dispose(); }
