import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { onlineSearch, onlineSearchConfigured, searchDigest, INDEX_DOWNLOAD_ROUTES } from "./onlineSearch.js";
import { replaySearch, settleSearch } from "./searchLedger.js";

function d1(database) {
  return { prepare(query) {
    const statement = (args = []) => ({ bind: (...bound) => statement(bound),
      first: async () => database.prepare(query).get(...args) || null,
      all: async () => ({ results: database.prepare(query).all(...args) }),
      execute: () => ({ success: true, meta: { changes: Number(database.prepare(query).run(...args).changes) } }),
    });
    return statement();
  }, async batch(statements) {
    database.exec("BEGIN IMMEDIATE");
    try { const results = statements.map(s => s.execute()); database.exec("COMMIT"); return results; }
    catch (failure) { database.exec("ROLLBACK"); throw failure; }
  } };
}

function fixture(t, units = 200000) {
  const sql = new DatabaseSync(":memory:");
  t.after(() => sql.close());
  sql.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  sql.prepare("INSERT INTO accounts (id,token_hash,units) VALUES ('anonymous','hash',?)").run(units);
  sql.exec(`INSERT INTO locations (id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,country,camera_generation)
    VALUES (1,'abcdefghijklmnopqrstuv','2026-01','scene','scene-model','published','contributor',10,20,90,'Italy','gen4');
    INSERT INTO published_index (location_id,index_text,output_sha256,published_at,four_view_key)
    VALUES (1,'','${"a".repeat(64)}',0,'four-view-v4/test.i8');`);
  const query = { lane: "scene", prompt: "red door", examples: [], excluded: [], queryName: "My map",
    descriptionWeight: 100, viewDirection: "bestOfFour", resultCount: 200, maxPerCountry: 25,
    filters: { mode: "all", countries: [], generations: [] }, objectConfidence: "balanced",
    rejectRoadNames: false, minimumGlobalLocation: null };
  const env = { DB: d1(sql), SEARCH_POLICY_ID: "test-only", SEARCH_RUNTIME_SHA256: "b".repeat(64),
    SEARCH_SNAPSHOT_SHA256: "c".repeat(64), SEARCH_ENGINE: { async fetch(request) {
      const body = await request.json();
      return Response.json({ ...body, processedLocations: 1,
        hits: [{ locationId: 1, outputSha256: "a".repeat(64), sourceIndex: 0, score: 0.8, viewOffset: 1 }] });
    } } };
  return { sql, env, query };
}

function balance(sql) { return sql.prepare("SELECT units FROM accounts WHERE id='anonymous'").get().units; }
function count(sql, table) { return sql.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n; }

test("the configured current price is charged once, rather than the browser's maximum", async t => {
  const { sql, env, query } = fixture(t, 120);
  env.SEARCH_COST_UNITS = "100";
  const result = await onlineSearch(env, "anonymous", "quoted-new-price", query, { maxCostUnits: 110 });
  assert.equal(result.costUnits, 100);
  assert.equal(balance(sql), 20);
  assert.equal(sql.prepare("SELECT units FROM ledger").get().units, -100);
  env.SEARCH_COST_UNITS = "200";
  delete env.SEARCH_ENGINE;
  assert.deepEqual(await onlineSearch(env, "anonymous", "quoted-new-price", query, { maxCostUnits: 1 }), result);
  assert.equal(balance(sql), 20);
  assert.equal(count(sql, "ledger"), 1);
});

test("a stale maximum refuses inference and debit, then explicit review can reuse the saved key", async t => {
  const { sql, env, query } = fixture(t, 500);
  env.SEARCH_COST_UNITS = "200";
  let calls = 0;
  const engine = env.SEARCH_ENGINE.fetch;
  env.SEARCH_ENGINE.fetch = request => { calls++; return engine(request); };
  await assert.rejects(onlineSearch(env, "anonymous", "stale-price-key", query, { maxCostUnits: 100 }),
    error => error.code === "search_price_changed" && error.status === 409);
  assert.equal(calls, 0);
  assert.equal(balance(sql), 500);
  assert.equal(count(sql, "searches"), 0);
  assert.equal(count(sql, "ledger"), 0);
  const result = await onlineSearch(env, "anonymous", "stale-price-key", query, { maxCostUnits: 200 });
  assert.equal(result.costUnits, 200);
  assert.equal(calls, 1);
  assert.equal(balance(sql), 300);
  assert.deepEqual(await onlineSearch(env, "anonymous", "stale-price-key", query, { maxCostUnits: 100 }), result);
  assert.equal(calls, 1);
});

test("malformed quotes and invalid configured prices fail before engine work without losing paid replay", async t => {
  const { sql, env, query } = fixture(t);
  let calls = 0;
  const engine = env.SEARCH_ENGINE.fetch;
  env.SEARCH_ENGINE.fetch = request => { calls++; return engine(request); };
  for (const maxCostUnits of [null, true, "100000", 0, -1, 1.5, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    await assert.rejects(onlineSearch(env, "anonymous", "invalid-quote-key", query, { maxCostUnits }),
      error => error.code === "invalid_search_quote" && error.status === 400);
  }
  assert.equal(calls, 0);
  const result = await onlineSearch(env, "anonymous", "original-price-key", query);
  assert.equal(result.costUnits, 100000);
  const savedBytes = sql.prepare("SELECT result_json FROM searches").get().result_json;
  for (const value of ["", "0", "1e2", "9007199254740992"]) {
    env.SEARCH_COST_UNITS = value;
    await assert.rejects(onlineSearch(env, "anonymous", "invalid-config-key", query), /search_unavailable/);
    assert.deepEqual(await onlineSearch(env, "anonymous", "original-price-key", query, { maxCostUnits: null }), result);
  }
  assert.equal(calls, 1);
  assert.equal(balance(sql), 100000);
  assert.equal(count(sql, "ledger"), 1);
  assert.equal(sql.prepare("SELECT result_json FROM searches").get().result_json, savedBytes);
});

test("legacy unquoted clients cannot be silently charged above the old known price", async t => {
  const { sql, env, query } = fixture(t, 500000);
  env.SEARCH_COST_UNITS = "200000";
  const engine = env.SEARCH_ENGINE.fetch;
  env.SEARCH_ENGINE.fetch = () => { throw Error("unapproved inference"); };
  await assert.rejects(onlineSearch(env, "anonymous", "legacy-price-key", query), /search_price_changed/);
  assert.equal(balance(sql), 500000);
  assert.equal(count(sql, "ledger"), 0);
  env.SEARCH_ENGINE.fetch = engine;
  env.SEARCH_COST_UNITS = "100";
  assert.equal((await onlineSearch(env, "anonymous", "legacy-price-key", query)).costUnits, 100);
  assert.equal(balance(sql), 499900);
});

test("old paid replies retain their exact original bytes and debit after a price change", async t => {
  const { sql, env, query } = fixture(t);
  const old = { searchId: "e".repeat(32), lane: "scene", results: [], map: { customCoordinates: [] } };
  await settleSearch(env.DB, "anonymous", "historic-paid-key", await searchDigest(query), old, 100000);
  const before = sql.prepare("SELECT result_json FROM searches").get().result_json;
  env.SEARCH_COST_UNITS = "100";
  delete env.SEARCH_ENGINE;
  assert.deepEqual(await onlineSearch(env, "anonymous", "historic-paid-key", query, { maxCostUnits: 100 }), old);
  assert.equal(sql.prepare("SELECT result_json FROM searches").get().result_json, before);
  assert.equal(sql.prepare("SELECT units FROM ledger").get().units, -100000);
  assert.equal(balance(sql), 100000);
});

test("the authorized price is captured before inference and cannot drift before settlement", async t => {
  const { sql, env, query } = fixture(t, 500);
  env.SEARCH_COST_UNITS = "100";
  const engine = env.SEARCH_ENGINE.fetch;
  env.SEARCH_ENGINE.fetch = request => { env.SEARCH_COST_UNITS = "500"; return engine(request); };
  const result = await onlineSearch(env, "anonymous", "price-during-flight", query, { maxCostUnits: 100 });
  assert.equal(result.costUnits, 100);
  assert.equal(balance(sql), 400);
  assert.equal(sql.prepare("SELECT units FROM ledger").get().units, -100);
});

test("concurrent configured-price requests preserve the last balance and once-only debit", async t => {
  const { sql, env, query } = fixture(t, 100);
  env.SEARCH_COST_UNITS = "100";
  const duplicate = await Promise.all([
    onlineSearch(env, "anonymous", "new-price-duplicate", query, { maxCostUnits: 100 }),
    onlineSearch(env, "anonymous", "new-price-duplicate", query, { maxCostUnits: 200 }),
  ]);
  assert.deepEqual(duplicate[0], duplicate[1]);
  assert.equal(balance(sql), 0);
  assert.equal(count(sql, "ledger"), 1);
  sql.prepare("UPDATE accounts SET units=100 WHERE id='anonymous'").run();
  const different = await Promise.allSettled([
    onlineSearch(env, "anonymous", "new-price-distinct-one", query, { maxCostUnits: 100 }),
    onlineSearch(env, "anonymous", "new-price-distinct-two", query, { maxCostUnits: 100 }),
  ]);
  assert.equal(different.filter(r => r.status === "fulfilled").length, 1);
  assert.equal(different.find(r => r.status === "rejected").reason.code, "insufficient_credit");
  assert.equal(balance(sql), 0);
  assert.equal(count(sql, "ledger"), 2);
});

test("closed object admission still recovers an owned paid result without inference or a debit", async t => {
  const { sql,env,query }=fixture(t);
  query.lane="object";
  const result={searchId:"d".repeat(32),lane:"object",results:[],map:{customCoordinates:[]}};
  await settleSearch(env.DB,"anonymous","saved-object-search",await searchDigest(query),result,100000);
  env.SEARCH_ENGINE.fetch=()=>{throw Error("must not run unqualified inference");};
  assert.deepEqual(await onlineSearch(env,"anonymous","saved-object-search",query,{allowNew:false}),result);
  await assert.rejects(onlineSearch(env,"anonymous","new-object-search",query,{allowNew:false}),/object_verification_unavailable/);
  assert.equal(balance(sql),100000);assert.equal(count(sql,"ledger"),1);
});

test("online results use authoritative poses and replay without charging again", async t => {
  const { sql, env, query } = fixture(t);
  const result = await onlineSearch(env, "anonymous", "request-one", query);
  assert.equal(balance(sql), 100000);
  assert.equal(result.map.customCoordinates[0].heading, 180);
  assert.equal(result.map.customCoordinates[0].panoId, "abcdefghijklmnopqrstuv");
  assert.equal(result.map.customCoordinates[0].extra.visionMinScore, 0.01);
  assert.equal(result.map.customCoordinates[0].extra.visionQueryMode, "textOnly");
  assert.equal(result.map.customCoordinates[0].extra.visionQuery, query.prompt);
  assert.equal(result.map.customCoordinates[0].extra.visionSourceIndex, 0);
  assert.equal(result.map.customCoordinates[0].extra.visionModel, "SigLIP B/16 224");
  delete env.SEARCH_ENGINE;
  assert.deepEqual(await onlineSearch(env, "anonymous", "request-one", query), result);
  assert.equal(balance(sql), 100000);
  assert.equal(count(sql, "ledger"), 1);
  const stored = sql.prepare("SELECT query FROM searches").get().query;
  assert.match(stored, /^sha256:[0-9a-f]{64}$/);
  assert.ok(!stored.includes(query.prompt));
});

test("simultaneous duplicate searches spend one credit and return the same result", async t => {
  const { sql, env, query } = fixture(t);
  const results = await Promise.all([onlineSearch(env, "anonymous", "duplicate", query), onlineSearch(env, "anonymous", "duplicate", query)]);
  assert.deepEqual(results[0], results[1]);
  assert.equal(balance(sql), 100000);
  assert.equal(count(sql, "searches"), 1);
  assert.equal(count(sql, "ledger"), 1);
});

test("account deletion during the engine call prevents settlement and private result recreation", async t => {
  const { sql, env, query } = fixture(t);
  const engine = env.SEARCH_ENGINE.fetch;
  env.SEARCH_ENGINE.fetch = async request => {
    const result = await engine(request);
    sql.exec(`UPDATE accounts SET deleted_at=1,units=0,token_hash='revoked',recovery_hash=NULL
      WHERE id='anonymous'; DELETE FROM searches WHERE account_id='anonymous';`);
    return result;
  };
  await assert.rejects(onlineSearch(env, "anonymous", "deleted-in-flight", query),
    error => error.code === "unauthorized" && error.status === 401);
  assert.equal(balance(sql), 0);
  assert.equal(count(sql, "searches"), 0);
  assert.equal(count(sql, "ledger"), 0);
  assert.equal(count(sql, "published_index"), 1);
});

test("a deleted account cannot replay retained private results or issue a new search", async t => {
  const { sql, env, query } = fixture(t);
  await onlineSearch(env, "anonymous", "before-deletion", query);
  const digest = await searchDigest(query);
  // Leave a saved row deliberately: replay itself must enforce the tombstone,
  // independently of the account-deletion handler's search cleanup.
  sql.exec("UPDATE accounts SET deleted_at=1,units=0 WHERE id='anonymous'");
  assert.equal(await replaySearch(env.DB, "anonymous", "before-deletion", digest), null);
  let engineCalls = 0;
  env.SEARCH_ENGINE.fetch = async () => { engineCalls++; throw Error("must not query"); };
  for (const key of ["before-deletion", "after-deletion"]) {
    await assert.rejects(onlineSearch(env, "anonymous", key, query),
      error => error.code === "unauthorized" && error.status === 401);
  }
  assert.equal(engineCalls, 0);
  assert.equal(count(sql, "ledger"), 1);
  assert.equal(balance(sql), 0);
});

test("a retained search ledger reference cannot resurrect a deleted account's private result", async t => {
  const { sql, env, query } = fixture(t);
  const result = await onlineSearch(env, "anonymous", "before-deletion", query);
  const digest = await searchDigest(query);
  sql.exec(`UPDATE accounts SET deleted_at=1,units=0 WHERE id='anonymous';
    DELETE FROM searches WHERE account_id='anonymous';`);
  // Simulate an old in-flight worker settling the exact already-paid result.
  // The ledger is intentionally retained for anonymous accounting history.
  await assert.rejects(settleSearch(env.DB, "anonymous", "before-deletion", digest, result, 100000),
    error => error.code === "unauthorized" && error.status === 401);
  assert.equal(count(sql, "searches"), 0);
  assert.equal(count(sql, "ledger"), 1);
  assert.equal(balance(sql), 0);
});

test("different searches cannot overspend the last banked credit", async t => {
  const { sql, env, query } = fixture(t, 100000);
  const results = await Promise.allSettled([onlineSearch(env, "anonymous", "request-one", query), onlineSearch(env, "anonymous", "request-two", query)]);
  assert.equal(results.filter(r => r.status === "fulfilled").length, 1);
  assert.equal(results.find(r => r.status === "rejected").reason.code, "insufficient_credit");
  assert.equal(balance(sql), 0);
  assert.equal(count(sql, "ledger"), 1);
});

test("changed request fields conflict instead of silently replaying an unrelated map", async t => {
  const { sql, env, query } = fixture(t);
  await onlineSearch(env, "anonymous", "request-one", query);
  for (const changed of [{ resultCount: 1 }, { maxPerCountry: 1 }, { prompt: "blue door" },
    { excluded: [{ lat: 10, lng: 20, panoId: "other" }] }, { examples: [{ heading: 90 }] },
    { filters: { mode: "include", countries: ["Italy"], generations: ["gen4"] } },
    { rejectRoadNames: true }, { minimumGlobalLocation: 42 }, { objectConfidence: "precise" }]) {
    await assert.rejects(onlineSearch(env, "anonymous", "request-one", { ...query, ...changed }), /idempotency_conflict/);
  }
  assert.equal(balance(sql), 100000);
});

test("database failure rolls back the ledger, result and debit together", async t => {
  const { sql, env, query } = fixture(t);
  sql.exec("CREATE TRIGGER failed_result BEFORE INSERT ON searches BEGIN SELECT RAISE(ABORT,'simulated disk failure'); END;");
  await assert.rejects(onlineSearch(env, "anonymous", "request-one", query), /simulated disk failure/);
  assert.equal(balance(sql), 200000);
  assert.equal(count(sql, "searches"), 0);
  assert.equal(count(sql, "ledger"), 0);
});

test("a concurrent idempotency conflict never spends a second credit", async t => {
  const { sql, env, query } = fixture(t);
  const digest = await searchDigest(query);
  const results = await Promise.allSettled([
    settleSearch(env.DB, "anonymous", "same-key", digest, { searchId: "first" }, 100000),
    settleSearch(env.DB, "anonymous", "same-key", "sha256:different", { searchId: "second" }, 100000),
  ]);
  assert.equal(results.filter(r => r.status === "fulfilled").length, 1);
  assert.equal(results.find(r => r.status === "rejected").reason.code, "idempotency_conflict");
  assert.equal(balance(sql), 100000);
  assert.equal(count(sql, "ledger"), 1);
});

test("an unavailable, malformed or oversized engine cannot spend credit", async t => {
  const { sql, env, query } = fixture(t);
  assert.equal(onlineSearchConfigured(env), true);
  for (const response of [new Response("failure", { status: 503 }), Response.json({}),
    new Response("x".repeat(4 * 1024 * 1024 + 1)), new Response("bad json")]) {
    env.SEARCH_ENGINE.fetch = async () => response;
    await assert.rejects(onlineSearch(env, "anonymous", "request-one", query), /search_unavailable/);
  }
  env.SEARCH_RUNTIME_SHA256 = "unpinned";
  assert.equal(onlineSearchConfigured(env), false);
  await assert.rejects(onlineSearch(env, "anonymous", "request-one", query), /search_unavailable/);
  assert.equal(balance(sql), 200000);
  assert.equal(count(sql, "ledger"), 0);
});

test("private and uncredited locations or changed artifacts cannot appear in results", async t => {
  const { sql, env, query } = fixture(t);
  for (const mutation of ["UPDATE locations SET contributor_id=NULL", "UPDATE locations SET state='pending'",
    "UPDATE published_index SET four_view_key=NULL", "UPDATE published_index SET output_sha256='different'"]) {
    sql.exec("SAVEPOINT before_mutation");
    sql.exec(mutation);
    await assert.rejects(onlineSearch(env, "anonymous", "request-one", query), /search_unavailable/);
    sql.exec("ROLLBACK TO before_mutation; RELEASE before_mutation;");
  }
  assert.equal(balance(sql), 200000);
});

test("object results require official Gen4 historical evidence", async t => {
  const { sql, env, query } = fixture(t);
  query.lane = "object";
  query.filters.generations = ["gen4"];
  sql.exec("UPDATE locations SET lane='object'; UPDATE published_index SET object_index_key='object-index-v4/test/';");
  env.SEARCH_ENGINE.fetch = async request => Response.json({ ...await request.json(), processedLocations: 1,
    hits: [{ locationId: 1, outputSha256: "a".repeat(64), sourceIndex: 0, score: 0.8, viewOffset: 0, heading: 45, pitch: 5, zoom: 1,
      object: { lane: "common", className: "car", classId: 3, confidence: 0.8, supportCount: 2, bboxArea: 0.1 } }] });
  await assert.rejects(onlineSearch(env, "anonymous", "request-one", query), /search_unavailable/);
  sql.exec(`INSERT INTO object_coverage VALUES (1,'official-gen4-historical-v2-exact-pano','${"d".repeat(64)}',0);`);
  sql.exec("UPDATE locations SET camera_generation='gen3'");
  await assert.rejects(onlineSearch(env, "anonymous", "request-one", query), /search_unavailable/);
  sql.exec("UPDATE locations SET camera_generation='gen4'");
  const result = await onlineSearch(env, "anonymous", "request-one", query);
  assert.equal(result.map.customCoordinates[0].heading, 45);
  assert.equal(result.map.customCoordinates[0].extra.visionModel, "RF-DETR Medium 1.10.0");
  assert.equal(result.map.customCoordinates[0].extra.visionMinScore, 0.08);
  assert.equal(result.map.customCoordinates[0].extra.visionObjectSupport, 2);
  assert.equal(balance(sql), 100000);
});

test("wrong pins, filters, poses, scores and exclusions are rejected before settlement", async t => {
  const { sql, env, query } = fixture(t);
  const hit = { locationId: 1, outputSha256: "a".repeat(64), sourceIndex: 0, score: 0.8, viewOffset: 1 };
  for (const changed of [{ policyId: "other" }, { runtimeSha256: "e".repeat(64) }, { snapshotSha256: "e".repeat(64) },
    { requestSha256: "e".repeat(64) }, { hits: [hit, hit] }, { hits: [{ ...hit, score: null }] },
    { hits: [{ ...hit, viewOffset: 9 }] }, { contractVersion: 1 },
    { hits: [null] }, { hits: [{ ...hit, sourceIndex: -1 }] }, { hits: [{ ...hit, sourceIndex: 1 }] },
    { hits: [{ ...hit, score: 0.001 }] }]) {
    env.SEARCH_ENGINE.fetch = async request => Response.json({ ...await request.json(), processedLocations: 1, hits: [hit], ...changed });
    await assert.rejects(onlineSearch(env, "anonymous", "request-one", query), /search_unavailable/);
  }
  env.SEARCH_ENGINE.fetch = async request => Response.json({ ...await request.json(), processedLocations: 1, hits: [hit] });
  for (const changed of [{ filters: { mode: "exclude", countries: ["Italy"], generations: [] } },
    { filters: { mode: "all", countries: [], generations: ["gen1"] } }, { viewDirection: "original" },
    { excluded: [{ panoId: "other", lat: 10, lng: 20 }] }, { minimumGlobalLocation: 1 }]) {
    await assert.rejects(onlineSearch(env, "anonymous", "request-one", { ...query, ...changed }), /search_unavailable/);
  }
  assert.equal(balance(sql), 200000);
});

test("all historical index distribution routes are retired for online credits", () => {
  assert.equal(INDEX_DOWNLOAD_ROUTES.size, 7);
  assert.ok(INDEX_DOWNLOAD_ROUTES.has("/api/scene-index-file"));
  assert.ok(INDEX_DOWNLOAD_ROUTES.has("/api/object-index-file"));
});

test("equal scores follow the sealed registry order rather than database IDs", async t => {
  const { sql, env, query } = fixture(t);
  sql.exec(`INSERT INTO locations (id,asset_id,capture,lane,model,state,contributor_id,lat,lon,country,camera_generation)
    VALUES (2,'another-contributed-pano','2026-01','scene','scene-model','published','contributor',11,20,'Italy','gen4');
    INSERT INTO published_index (location_id,index_text,output_sha256,published_at,four_view_key)
    VALUES (2,'','${"d".repeat(64)}',0,'four-view-v4/second.i8');`);
  const hits = [{ locationId: 2, outputSha256: "d".repeat(64), sourceIndex: 0, score: 0.8, viewOffset: 0 },
    { locationId: 1, outputSha256: "a".repeat(64), sourceIndex: 1, score: 0.8, viewOffset: 1 }];
  env.SEARCH_ENGINE.fetch = async request => Response.json({ ...await request.json(), processedLocations: 2, hits: [...hits].reverse() });
  await assert.rejects(onlineSearch(env, "anonymous", "wrong-order", query), /search_unavailable/);
  assert.equal(balance(sql), 200000);
  env.SEARCH_ENGINE.fetch = async request => Response.json({ ...await request.json(), processedLocations: 2, hits });
  const result = await onlineSearch(env, "anonymous", "right-order", query);
  assert.deepEqual(result.results.map(hit => hit.locationId), [2, 1]);
  assert.deepEqual(result.map.customCoordinates.map(hit => hit.extra.visionSourceIndex), [0, 1]);
});

test("missing or malformed object evidence cannot produce a paid map", async t => {
  const { sql, env, query } = fixture(t);
  query.lane = "object";
  sql.exec(`UPDATE locations SET lane='object'; UPDATE published_index SET object_index_key='object-index-v4/test/';
    INSERT INTO object_coverage VALUES (1,'official-gen4-historical-v2-exact-pano','${"d".repeat(64)}',0);`);
  const object = { lane: "common", className: "car", classId: 3, confidence: 0.8, supportCount: 2, bboxArea: 0.1 };
  for (const changed of [null, { ...object, confidence: 0.01 }, { ...object, lane: "unknown" },
    { ...object, supportCount: 0 }, { ...object, bboxArea: 3 }]) {
    env.SEARCH_ENGINE.fetch = async request => Response.json({ ...await request.json(), processedLocations: 1,
      hits: [{ locationId: 1, outputSha256: "a".repeat(64), sourceIndex: 0, score: 0.8, viewOffset: 0,
        heading: 45, pitch: 5, zoom: 1, object: changed }] });
    await assert.rejects(onlineSearch(env, "anonymous", "invalid-object", query), /search_unavailable/);
    assert.equal(balance(sql), 200000);
  }
});

test("semantic object hits support the reference runtime's zenith and nadir faces", async t => {
  const { sql, env, query } = fixture(t);
  query.lane = "object";
  sql.exec(`UPDATE locations SET lane='object'; UPDATE published_index SET object_index_key='object-index-v4/test/';
    INSERT INTO object_coverage VALUES (1,'official-gen4-historical-v2-exact-pano','${"d".repeat(64)}',0);`);
  for (const viewOffset of [4, 5]) {
    env.SEARCH_ENGINE.fetch = async request => Response.json({ ...await request.json(), processedLocations: 1,
      hits: [{ locationId: 1, outputSha256: "a".repeat(64), sourceIndex: 0, score: 0.8, viewOffset,
        heading: 45, pitch: viewOffset === 4 ? 85 : -85, zoom: 1,
        object: { lane: "semantic", className: "red door", confidence: 0.8, supportCount: 1, bboxArea: 0.1 } }] });
    const result = await onlineSearch(env, "anonymous", `semantic-face-${viewOffset}`, query);
    assert.equal(result.results[0].viewOffset, viewOffset);
    assert.equal(result.map.customCoordinates[0].extra.visionHeadingOffset, 0);
    assert.equal(result.map.customCoordinates[0].extra.visionModel, "OWLv2 Base Patch16 + PQ128");
  }
  assert.equal(balance(sql), 0);
});
