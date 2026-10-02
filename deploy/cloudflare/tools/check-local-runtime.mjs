// Deliberately local: synthetic results exercise the gateway/ledger, never
// claim model quality or enable public contributions. No Cloudflare login.
// Usage: node tools/check-local-runtime.mjs <miniflare-entry> <bundled-worker>
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { pathToFileURL } from "node:url";
import { PRIVACY_FENCE, writeSceneArtifact } from "../src/artifactWrites.js";

const [miniflarePath, bundlePath, compatibilityDate = "2026-09-19"] = process.argv.slice(2);
if (!miniflarePath || !bundlePath) throw Error("Specify the local Miniflare entry and dry-run Worker bundle.");
const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(miniflarePath)).href);
const pins = { SEARCH_POLICY_ID: "synthetic-local-test-only", SEARCH_RUNTIME_SHA256: "b".repeat(64),
  SCENE_POLICY_ID: "synthetic-local-test-only",
  SEARCH_SNAPSHOT_SHA256: "c".repeat(64), DEPLOYMENT_ENVIRONMENT: "staging", INDEX_BUCKET_NAME: "vision-community-staging" };
const options = { modules: true, scriptPath: resolve(bundlePath), compatibilityDate,
  modulesRoot: dirname(resolve(bundlePath)),
  compatibilityFlags: ["nodejs_compat"], d1Databases: ["DB"], r2Buckets: ["INDEX"], bindings: pins,
  serviceBindings: { ASSETS: () => new Response("local test", { status: 404 }),
    SCENE_VERIFIER: async () => Response.json({ error: "synthetic-service-not-used" }, { status: 503 }),
    SEARCH_ENGINE: async request => Response.json({ ...await request.json(), processedLocations: 1,
      hits: [{ locationId: 1, outputSha256: "a".repeat(64), sourceIndex: 0, score: 0.8, viewOffset: 1 }] }) },
};
const mf = new Miniflare(convertV4MiniflareOptions ? convertV4MiniflareOptions(options) : options);

try {
  const db = await mf.getD1Database("DB");
  const schema = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
  for (const statement of schema.split(";").filter(part => part.trim())) await db.prepare(statement).run();
  const emptyStatus = await mf.dispatchFetch("https://community.test/api/status");
  assert.equal(emptyStatus.status, 200);
  const empty = await emptyStatus.json();
  assert.equal(empty.environment, "staging");
  assert.equal(empty.r2.bucket, "vision-community-staging");
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM locations").first()).n, 0,
    "fresh hosted deployments must not invent a prototype work queue");
  await db.prepare(`INSERT INTO locations (id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,country,camera_generation)
    VALUES (1,'abcdefghijklmnopqrstuv','2026-01','scene','scene-model','published','local-contributor',10,20,90,'Italy','gen4')`).run();
  await db.prepare("INSERT INTO published_index (location_id,index_text,output_sha256,published_at,four_view_key) VALUES (1,'',?,0,'four-view-v4/local.i8')")
    .bind("a".repeat(64)).run();
  const created = await mf.dispatchFetch("https://community.test/api/accounts", {
    method: "POST", headers: { "content-type": "application/json", origin: "https://community.test" }, body: "{}" });
  assert.equal(created.status, 201);
  const credentials = await created.json();
  const account = credentials.accountId;
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
  await db.exec("DROP TRIGGER failed_result;");
  assert.equal((await (await mf.dispatchFetch("https://community.test/api/me", { headers: { cookie: session } })).json()).accountDeletionAvailable, true);
  // Establish real ownership before deletion for a legacy quarantine retry.
  await db.prepare("INSERT INTO leases (id,account_id,lane,expires_at,state) VALUES (?,?,'scene',1,'expired')")
    .bind("f".repeat(32), account).run();
  // A deliberately synthetic qualification exercises lease capacity in actual
  // workerd/D1. It does not qualify any runtime or perform native inference.
  await db.prepare("INSERT INTO scene_qualifications VALUES ('synthetic-capacity',?,?,?,?,?,?)")
    .bind(account, "b".repeat(64), pins.SCENE_POLICY_ID, "c".repeat(64), Math.floor(Date.now()/1000)+3600, 1).run();
  for (let id=2; id<=18; id++) {
    await db.prepare("INSERT INTO locations (id,asset_id,capture,lane,model,state,lat,lon,country,camera_generation) VALUES (?,?,'synthetic-only','scene','synthetic-input','pending',10,20,'Italy','gen4')")
      .bind(id, `local-fixture-capacity-${id}`).run();
  }
  const leaseRequest = () => mf.dispatchFetch("https://community.test/api/leases", { method: "POST",
    headers: { "content-type": "application/json", origin: "https://community.test", cookie: session },
    body: JSON.stringify({ accountId: account, lane: "scene", pace: "max", client: "cli", count: 128, profileId: "b".repeat(64) }) });
  const leased = await leaseRequest();
  assert.equal(leased.status, 200, JSON.stringify(await leased.clone().json()));
  const batch = await leased.json();
  assert.equal(batch.items.length, 8, "Max pace cannot exceed the bounded native audit batch");
  assert.equal(batch.resourceBudget, "qualified-runtime");
  const resumedBatch = await (await leaseRequest()).json();
  assert.equal(resumedBatch.leaseId, batch.leaseId);
  assert.equal(resumedBatch.items.length, 8);
  assert.equal(resumedBatch.resumed, true);
  const deletionBody = { accountId: account, confirmation: "DELETE", idempotencyKey: "d".repeat(64) };
  const deletion = (body = deletionBody, origin = "https://community.test", cookie = session) =>
    mf.dispatchFetch("https://community.test/api/account/delete", { method: "POST",
      headers: { "content-type": "application/json", origin, cookie }, body: JSON.stringify(body) });
  assert.equal((await deletion(deletionBody, "https://unrelated.test")).status, 403);
  assert.equal((await deletion({ ...deletionBody, confirmation: "delete" })).status, 400);
  const deleted = await deletion();
  assert.equal(deleted.status, 200);
  assert.match(deleted.headers.get("set-cookie"), /Max-Age=0/);
  assert.equal((await deleted.json()).unitsForfeited, 100000);
  assert.equal((await mf.dispatchFetch("https://community.test/api/me", { headers: { cookie: session } })).status, 401);
  assert.equal((await post(request)).status, 401);
  const recovery = await mf.dispatchFetch("https://community.test/api/recovery", { method: "POST",
    headers: { "content-type": "application/json", origin: "https://community.test" },
    body: JSON.stringify({ recoveryCode: credentials.recoveryCode }) });
  assert.equal(recovery.status, 401);
  // Simulate retry after losing the response, with no session cookie.
  assert.equal((await deletion(deletionBody, "https://community.test", "")).status, 200);
  assert.equal((await deletion({ ...deletionBody, idempotencyKey: "e".repeat(64) }, "https://community.test", "")).status, 401);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM searches WHERE account_id=?").bind(account).first()).n, 0);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='account_deleted'").first()).n, 1);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM published_index").first()).n, 1);
  // Exercise the actual scheduled handler against local R2, with a damaged
  // published path that must be kept and a valid unpublished cleanup retry.
  const r2 = await mf.getR2Bucket("INDEX");
  const key = `scene-quarantine/${"f".repeat(32)}/${"a".repeat(64)}.i8`;
  await r2.put(key, "private quarantine");
  await r2.put("four-view-v4/local.i8", "retained contributed index");
  for (const path of [key, "four-view-v4/local.i8"]) {
    await db.prepare("INSERT INTO account_cleanup VALUES (?,?,1,'pending')").bind(path, account).run();
  }
  const worker = await mf.getWorker();
  await worker.scheduled({ cron: "0 * * * *" });
  assert.equal(await (await r2.get(key)).text(), PRIVACY_FENCE);
  assert.equal((await r2.get(key)).customMetadata.visionPrivacyFence, "1");
  assert.ok(await r2.get("four-view-v4/local.i8"));
  assert.equal((await db.prepare("SELECT state FROM account_cleanup WHERE artifact_key=?").bind(key).first()).state, "fenced");
  assert.equal((await db.prepare("SELECT state FROM account_cleanup WHERE artifact_key='four-view-v4/local.i8'").first()).state, "needs_review");
  // Use actual workerd D1/R2 conditional writes, not a storage mock. Pause the
  // writer on each side of R2 commit and delete through the bundled API.
  for (const [index, phase] of ["before", "after"].flatMap(phase => [[0, phase], [1, phase]])) {
    const response = await mf.dispatchFetch("https://community.test/api/accounts", {
      method: "POST", headers: { "content-type": "application/json", origin: "https://community.test" }, body: "{}" });
    assert.equal(response.status, 201);
    const owner = (await response.json()).accountId, cookie = response.headers.get("set-cookie").split(";")[0];
    const lease = `${phase === "before" ? "1" : "2"}${index}`.repeat(16);
    const artifact = index === 0 ? `scene-quarantine/${lease}/${"a".repeat(64)}.i8` : `four-view-v4/${lease}.i8`;
    await db.prepare("INSERT INTO leases (id,account_id,lane,expires_at,state) VALUES (?,?,'scene',?,'active')")
      .bind(lease, owner, Math.floor(Date.now() / 1000) + 600).run();
    let entered, resume;
    const reached = new Promise(resolve => { entered = resolve; });
    const hold = new Promise(resolve => { resume = resolve; });
    const delayed = { DB: db, INDEX: { get: key => r2.get(key), put: async (...args) => {
      if (phase === "before") { entered(); await hold; }
      const written = await r2.put(...args);
      if (phase === "after") { entered(); await hold; }
      return written;
    } } };
    // Attach rejection handling before racing deletion with the pending upload.
    const outcome = writeSceneArtifact(delayed, owner, lease, artifact, new Uint8Array(3080))
      .then(value => ({ value }), error => ({ error }));
    await Promise.race([reached, outcome.then(result => { throw result.error || Error("upload did not reach R2"); })]);
    assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM account_artifact_writes WHERE account_id=?").bind(owner).first()).n, 1);
    const deleted = await mf.dispatchFetch("https://community.test/api/account/delete", { method: "POST",
      headers: { "content-type": "application/json", origin: "https://community.test", cookie },
      body: JSON.stringify({ accountId: owner, confirmation: "DELETE", idempotencyKey: lease.repeat(2) }) });
    assert.equal(deleted.status, 200);
    resume();
    const result = await outcome;
    assert.match(result.error?.message || "", phase === "before" ? /index_artifact_fenced/ : /account_not_active/);
    const fenced = await r2.get(artifact);
    assert.equal(await fenced.text(), PRIVACY_FENCE);
    assert.equal(fenced.customMetadata.visionPrivacyFence, "1");
    assert.equal(await r2.put(artifact, "late private bytes", { onlyIf: new Headers({ "if-none-match": "*" }) }), null);
    assert.equal((await db.prepare("SELECT state FROM account_cleanup WHERE artifact_key=?").bind(artifact).first()).state, "fenced");
    assert.equal((await db.prepare("SELECT units FROM accounts WHERE id=?").bind(owner).first()).units, 0);
    assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM ledger WHERE account_id=? AND reason='verified_work'").bind(owner).first()).n, 0);
  }
  // A label without a complete historical receipt cannot assign object work.
  // Losing that receipt while a lease is held must block resume and publication
  // before any artifact or credit is written.
  const objectCreated = await mf.dispatchFetch("https://community.test/api/accounts", {
    method: "POST", headers: { "content-type": "application/json", origin: "https://community.test" }, body: "{}" });
  assert.equal(objectCreated.status, 201);
  const objectAccount = (await objectCreated.json()).accountId;
  const objectCookie = objectCreated.headers.get("set-cookie").split(";")[0];
  const objectPost = (route, body) => mf.dispatchFetch("https://community.test/api/" + route, { method: "POST",
    headers: { "content-type": "application/json", origin: "https://community.test", cookie: objectCookie },
    body: JSON.stringify({ accountId: objectAccount, ...body }) });
  await db.prepare(`INSERT INTO locations (id,asset_id,capture,lane,model,state,lat,lon,country,camera_generation)
    VALUES (90001,'ObjectProofOnlyPano1234','2026-01','object','synthetic-object-model','pending',1,2,'Albania','gen4')`).run();
  await db.prepare("INSERT INTO object_coverage VALUES (90001,'official-gen4-historical-v1','',0)").run();
  const objectLeaseRequest = { lane: "object", count: 1, client: "cli", pace: "slow" };
  for (const evidence of ["", "a".repeat(63), "g".repeat(64), "A".repeat(64)]) {
    await db.prepare("UPDATE object_coverage SET evidence_sha256=? WHERE location_id=90001").bind(evidence).run();
    const rejected = await objectPost("leases", objectLeaseRequest);
    assert.equal(rejected.status, 409);
    assert.equal((await rejected.json()).error, "no_available_work");
  }
  await db.prepare("UPDATE object_coverage SET evidence_sha256=? WHERE location_id=90001").bind("d".repeat(64)).run();
  const objectLeased = await objectPost("leases", objectLeaseRequest);
  assert.equal(objectLeased.status, 200);
  const objectLease = await objectLeased.json();
  assert.equal(objectLease.items.length, 1);
  assert.equal(objectLease.items[0].locationId, 90001);
  const r2Before = (await (await mf.getR2Bucket("INDEX")).list()).objects.length;
  for (const [evidence, generation] of [["", "gen4"], ["g".repeat(64), "gen4"], ["d".repeat(64), "gen3"]]) {
    await db.prepare("UPDATE object_coverage SET evidence_sha256=? WHERE location_id=90001").bind(evidence).run();
    await db.prepare("UPDATE locations SET camera_generation=? WHERE id=90001").bind(generation).run();
    for (const [route, body] of [["leases", objectLeaseRequest], ["submissions", {
      leaseId: objectLease.leaseId, objectIndex: {}, outputs: [{ locationId: 90001, outputSha256: "a".repeat(64) }],
    }]]) {
      const rejected = await objectPost(route, body);
      assert.equal(rejected.status, 409);
      assert.equal((await rejected.json()).error, "object_coverage_required");
    }
  }
  assert.equal((await (await mf.getR2Bucket("INDEX")).list()).objects.length, r2Before);
  assert.equal((await db.prepare("SELECT units FROM accounts WHERE id=?").bind(objectAccount).first()).units, 0);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM published_index WHERE location_id=90001").first()).n, 0);
  console.log("Cloudflare local runtime passed: concurrent search settlement, replay, rollback, deletion, recovery revocation, receipt retry, scheduled cleanup, create-only quarantine/final uploads, and strict Gen4 object assignment/resume/publication without artifacts or credits on lost proof.");
} finally { await mf.dispose(); }
