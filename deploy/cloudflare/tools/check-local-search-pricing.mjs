// Actual local workerd/D1 restarts with explicitly synthetic publications and
// balances. No provider, model, live account or contribution is used.
// Usage: node check-local-search-pricing.mjs <miniflare-entry> <bundled-worker>
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { prepareDatabase } from "./initialize-schema.mjs";
import { localRateLimits } from "./local-api-bindings.mjs";

const [runtime, bundle] = process.argv.slice(2);
if (!runtime || !bundle) throw Error("Specify existing local Miniflare and Worker bundle paths.");
const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(runtime)).href);
const root = mkdtempSync(join(tmpdir(), "vision-price-"));
let mf, db, cookie, account, calls = 0;
const scenarios = [];
function options(price) {
  const scriptPath = resolve(bundle);
  const value = {
    modules: true, scriptPath, modulesRoot: dirname(scriptPath), compatibilityDate: "2026-09-19",
    compatibilityFlags: ["nodejs_compat"], resourcePersistencePath: root,
    d1Databases: ["DB"], r2Buckets: ["INDEX"], ratelimits: localRateLimits(),
    bindings: { RATE_LIMITS_REQUIRED: "1", DEPLOYMENT_ENVIRONMENT: "staging",
      INDEX_BUCKET_NAME: "vision-community-staging", SEARCH_POLICY_ID: "synthetic-price-fixture-only",
      SEARCH_RUNTIME_SHA256: "b".repeat(64), SEARCH_SNAPSHOT_SHA256: "c".repeat(64),
      ...(price === undefined ? {} : { SEARCH_COST_UNITS: price }) },
    serviceBindings: { ASSETS: () => new Response("private local fixture", { status: 404 }),
      SEARCH_ENGINE: async request => {
        calls++;
        return Response.json({ ...await request.json(), processedLocations: 1,
          hits: [{ locationId: 1, outputSha256: "a".repeat(64), sourceIndex: 0, score: 0.8, viewOffset: 1 }] });
      } },
  };
  return convertV4MiniflareOptions ? convertV4MiniflareOptions(value) : value;
}
async function restart(price) {
  await mf?.dispose();
  mf = new Miniflare(options(price));
  db = await mf.getD1Database("DB");
}
const balance = async () => (await db.prepare("SELECT units FROM accounts WHERE id=?").bind(account).first()).units;
const ledgerCount = async () => (await db.prepare("SELECT COUNT(*) n FROM ledger").first()).n;
async function me() {
  const reply = await mf.dispatchFetch("https://community.test/api/me?lite=1", { headers: { cookie } });
  assert.equal(reply.status, 200);
  return reply.json();
}
function post(body) {
  return mf.dispatchFetch("https://community.test/api/searches", { method: "POST",
    headers: { "content-type": "application/json", origin: "https://community.test", cookie },
    body: JSON.stringify(body) });
}
async function refused(body, status, code) {
  const before = [await balance(), await ledgerCount(), calls];
  const reply = await post(body);
  assert.equal(reply.status, status);
  assert.equal((await reply.json()).error, code);
  assert.deepEqual([await balance(), await ledgerCount(), calls], before);
}

try {
  await restart();
  const schema = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
  for (const statement of schema.split(";").filter(part => part.trim())) await db.prepare(statement).run();
  await prepareDatabase(db);
  await db.prepare(`INSERT INTO locations
    (id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,country,camera_generation)
    VALUES (1,'abcdefghijklmnopqrstuv','2026-01','scene','synthetic-fixture','published','synthetic-contributor',10,20,90,'Italy','gen4')`).run();
  await db.prepare(`INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_key)
    VALUES(1,'',?,0,'four-view-v4/synthetic-price.i8')`).bind("a".repeat(64)).run();
  const created = await mf.dispatchFetch("https://community.test/api/accounts", { method: "POST",
    headers: { "content-type": "application/json", origin: "https://community.test" }, body: "{}" });
  assert.equal(created.status, 201);
  account = (await created.json()).accountId;
  cookie = created.headers.get("set-cookie").split(";")[0];
  await db.prepare("UPDATE accounts SET units=200000 WHERE id=?").bind(account).run();
  assert.equal((await me()).searchCost, 100000);
  const original = { accountId: account, idempotencyKey: "historical-paid-price", lane: "scene", prompt: "red door", maxCostUnits: 100000 };
  const paid = await post(original);
  assert.equal(paid.status, 200);
  const saved = await paid.json();
  assert.equal(saved.costUnits, 100000);
  const savedBytes = (await db.prepare("SELECT result_json FROM searches").first()).result_json;
  assert.equal(await balance(), 100000);
  assert.equal(await ledgerCount(), 1);
  scenarios.push("historical-default-and-actual-debit");

  await restart("100");
  const status = await me();
  assert.equal(status.searchCost, 100);
  assert.equal(status.searchesAvailable, 1000);
  assert.equal(status.units, 100000);
  const beforeReplay = calls;
  const replay = await post({ ...original, maxCostUnits: 1 });
  assert.equal(replay.status, 200);
  assert.deepEqual(await replay.json(), saved);
  assert.equal(calls, beforeReplay);
  assert.equal((await db.prepare("SELECT result_json FROM searches").first()).result_json, savedBytes);
  scenarios.push("disk-restart-preserves-historic-paid-reply-and-balance");

  const current = { ...original, idempotencyKey: "current-reviewed-price", maxCostUnits: 50 };
  await refused(current, 409, "search_price_changed");
  await refused({ ...current, maxCostUnits: null }, 400, "invalid_search_quote");
  const replies = await Promise.all(Array.from({ length: 6 }, () => post({ ...current, maxCostUnits: 500 })));
  assert.ok(replies.every(reply => reply.status === 200));
  const results = await Promise.all(replies.map(reply => reply.json()));
  assert.ok(results.every(result => result.searchId === results[0].searchId && result.costUnits === 100));
  assert.equal(await balance(), 99900);
  assert.equal(await ledgerCount(), 2);
  scenarios.push("stale-quotes-refused-and-six-concurrent-reviewed-deliveries-debit-once");

  await restart("");
  const unavailable = await me();
  assert.equal(unavailable.searchCost, null);
  assert.equal(unavailable.searchOnSite, false);
  assert.equal(unavailable.searchReady, false);
  assert.equal(unavailable.searchesAvailable, 0);
  assert.equal(unavailable.units, 99900);
  await refused({ ...original, idempotencyKey: "invalid-config-search" }, 503, "search_unavailable");
  const currentReplay = await post({ ...current, maxCostUnits: null });
  assert.equal(currentReplay.status, 200);
  assert.deepEqual(await currentReplay.json(), results[0]);
  assert.equal(await balance(), 99900);
  assert.equal(await ledgerCount(), 2);
  scenarios.push("invalid-operator-price-closes-new-work-but-preserves-paid-recovery");

  await restart("200000");
  const { maxCostUnits, ...legacy } = { ...original, idempotencyKey: "legacy-new-request" };
  await refused(legacy, 409, "search_price_changed");
  await refused({ ...legacy, maxCostUnits: 200000 }, 402, "insufficient_credit");
  const originalReplay = await post(original);
  assert.equal(originalReplay.status, 200);
  assert.deepEqual(await originalReplay.json(), saved);
  assert.equal(await balance(), 99900);
  assert.equal(await ledgerCount(), 2);
  scenarios.push("raised-price-fences-legacy-clients-and-keeps-original-paid-result");
  console.log(JSON.stringify({ status: "LOCAL_SEARCH_PRICE_RECOVERY_PASSED", scenarios,
    actualWorkerd: true, actualD1: true, durableRestarts: 3, syntheticPublicationsAndBalance: true,
    nativeInference: false, providerWrites: false, productionQualified: false }, null, 2));
} finally {
  await mf?.dispose();
  // Retain this bounded synthetic fixture on disk, including on failure.
}
