// Private operator check: local workerd/D1 -> loopback native engine -> ledger.
// Every database row/account/credit is disposable. Never point at live resources.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { pathToFileURL } from "node:url";

const [miniflarePath, bundlePath, fixturePath] = process.argv.slice(2);
if (!fixturePath) throw Error("Specify Miniflare, bundled Worker and private local fixture.");
const fixtureBytes = readFileSync(fixturePath);
assert.ok(fixtureBytes.length < 256 * 1024);
const fixture = JSON.parse(fixtureBytes);
assert.equal(fixture.scope, "synthetic-local-native-gateway-only");
assert.ok(fixture.rows.length > 0 && fixture.rows.length <= 100);
const endpoint = new URL(process.env.VISION_LOCAL_ENGINE_URL || "");
assert.equal(endpoint.hostname, "127.0.0.1");
assert.equal(endpoint.protocol, "http:");
assert.equal(endpoint.pathname, "/search");
assert.ok(!endpoint.username && !endpoint.password && !endpoint.search);
const secret = process.env.VISION_SEARCH_ENGINE_SECRET || "";
assert.ok(secret.length >= 32);
const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(miniflarePath)).href);
let failure = false, calls = 0;
const options = { modules: true, scriptPath: resolve(bundlePath), modulesRoot: dirname(resolve(bundlePath)),
  compatibilityDate: "2026-09-19", compatibilityFlags: ["nodejs_compat"],
  d1Databases: ["DB"], r2Buckets: ["INDEX"], bindings: fixture.pins,
  serviceBindings: { ASSETS: () => new Response("local test", { status: 404 }),
    SEARCH_ENGINE: async request => {
      calls += 1;
      if (failure) return new Response("unavailable", { status: 503 });
      return fetch(endpoint, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${secret}` },
        body: await request.text(), signal: AbortSignal.timeout(115000) });
    } },
};
const mf = new Miniflare(convertV4MiniflareOptions ? convertV4MiniflareOptions(options) : options);
try {
  const db = await mf.getD1Database("DB");
  for (const statement of readFileSync(new URL("../schema.sql", import.meta.url), "utf8").split(";").filter(p=>p.trim()))
    await db.prepare(statement).run();
  for (const row of fixture.rows) {
    await db.prepare(`INSERT INTO locations (id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,pitch,zoom,country,camera_generation,output_sha256)
      VALUES (?,?,?,'scene',?,'published','synthetic-local-owner',?,?,?,?,?,?,?,?)`)
      .bind(row.id,row.asset_id,row.capture,row.model,row.lat,row.lon,row.heading,row.pitch,row.zoom,row.country,row.camera_generation,row.output_sha256).run();
    await db.prepare(`INSERT INTO published_index (location_id,index_text,output_sha256,published_at,four_view_key,four_view_sha256)
      VALUES (?,'',?,0,'four-view-v4/local-fixture.i8',?)`).bind(row.id,row.output_sha256,row.output_sha256).run();
  }
  const created = await mf.dispatchFetch("https://community.test/api/accounts", { method:"POST",
    headers:{"content-type":"application/json",origin:"https://community.test"},body:"{}" });
  assert.equal(created.status,201);
  const account = (await created.json()).accountId;
  const cookie = created.headers.get("set-cookie").split(";")[0];
  await db.prepare("UPDATE accounts SET units=500000 WHERE id=?").bind(account).run();
  const post = body => mf.dispatchFetch("https://community.test/api/searches", {method:"POST",
    headers:{"content-type":"application/json",origin:"https://community.test",cookie},body:JSON.stringify(body)});
  for (const [index, example] of fixture.expected.entries()) {
    const request = {accountId:account,idempotencyKey:`real-native-local-${index}`,lane:"scene",prompt:example.prompt,
      outputName:example.name,resultCount:16,maxPerCountry:16};
    const response = await post(request);
    assert.equal(response.status,200);
    const result = await response.json();
    assert.deepEqual(result.results.map(h=>[h.sourceIndex,h.score,h.viewOffset,h.locationId]),
      example.hits.map(h=>[h.sourceIndex,h.score,h.viewOffset,h.locationId]));
    assert.equal(result.map.customCoordinates.length,example.hits.length);
    for (const [rank, coordinate] of result.map.customCoordinates.entries()) {
      const hit=example.hits[rank], source=fixture.rows.find(row=>row.id===hit.locationId);
      assert.equal(coordinate.panoId,source.asset_id);
      assert.equal(coordinate.lat,source.lat);
      assert.equal(coordinate.lng,source.lon);
      const remainder=(source.heading+90*hit.viewOffset)%360;
      assert.equal(coordinate.heading,remainder<0 ? remainder+360 : remainder);
      assert.equal(coordinate.extra.visionQueryMode,"textOnly");
      assert.equal(coordinate.extra.visionSourceIndex,hit.sourceIndex);
      assert.equal(coordinate.extra.visionProcessedLocations,fixture.rows.length);
    }
    const count=calls;
    const replay=await post(request);
    assert.equal(replay.status,200);
    assert.deepEqual(await replay.json(),result);
    assert.equal(calls,count); // No native execution and no second debit.
    assert.equal((await post({...request,prompt:"changed query"})).status,409);
    assert.equal((await post({...request,accountId:"other-account"})).status,409);
  }
  // An actual JSON.stringify exponent differs from Python's float encoder.
  // This checks the exact request fingerprint across both languages/services.
  const exponent=await post({accountId:account,idempotencyKey:"native-exponent-local",lane:"scene",prompt:"a road",
    resultCount:16,maxPerCountry:16,excludeMap:{customCoordinates:[{lat:1e-7,lng:1}]}});
  assert.equal(exponent.status,200);
  assert.deepEqual((await exponent.json()).results.map(h=>[h.sourceIndex,h.score,h.viewOffset,h.locationId]),
    fixture.expected[0].hits.map(h=>[h.sourceIndex,h.score,h.viewOffset,h.locationId]));
  assert.equal((await db.prepare("SELECT units FROM accounts WHERE id=?").bind(account).first()).units,100000);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM ledger WHERE account_id=?").bind(account).first()).n,4);
  failure=true;
  const unavailable=await post({accountId:account,idempotencyKey:"native-outage-local",lane:"scene",prompt:"a road"});
  assert.equal(unavailable.status,503);
  assert.equal((await db.prepare("SELECT units FROM accounts WHERE id=?").bind(account).first()).units,100000);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM searches WHERE account_id=?").bind(account).first()).n,4);
  failure=false;
  // Changing authoritative publication state invalidates a real engine hit;
  // neither a returned score nor its snapshot pin can make an orphan searchable.
  const first=fixture.expected[0].hits[0];
  await db.prepare("UPDATE locations SET contributor_id=NULL WHERE id=?").bind(first.locationId).run();
  const orphan=await post({accountId:account,idempotencyKey:"native-orphan-local",lane:"scene",prompt:"a road",resultCount:16,maxPerCountry:16});
  assert.equal(orphan.status,503);
  assert.equal((await db.prepare("SELECT units FROM accounts WHERE id=?").bind(account).first()).units,100000);
  console.log(JSON.stringify({status:"REAL_NATIVE_LOCAL_GATEWAY_AND_CREDITS_PASSED",nativeQueries:4,scientificCoordinatesPassed:true,
    recoveredWithoutExtraInferenceOrDebit:3,outageSpendsNothing:true,orphanSpendsNothing:true,
    productionQualified:false,liveResourcesChanged:false}));
} finally { await mf.dispose(); }
