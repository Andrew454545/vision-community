import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { pipelineCapabilities } from "./scenePipeline.js";

const scope = { AbortSignal, crypto };
runInNewContext(readFileSync(new URL("../../../community/web/service-readiness.js", import.meta.url), "utf8"), scope);
runInNewContext(readFileSync(new URL("../../../community/web/search-journal.js", import.meta.url), "utf8"), scope);
const Readiness = scope.VisionServiceReadiness;
const Pricing = scope.VisionSearchPricing;

test("credit guidance follows the actual price and never treats an absent price as free", () => {
  assert.equal(Pricing.cost({ searchCost: 100 }), 100);
  assert.equal(Pricing.canAfford({ searchCost: 100, units: 100 }), true);
  assert.equal(Pricing.canAfford({ searchCost: 100, units: 99 }), false);
  assert.match(Pricing.message({ searchCost: 100, units: 90 }), /100 units.*10 more needed/);
  assert.match(Pricing.message({ searchCost: 200, units: 100 }), /200 units.*100 more needed/);
  for (const searchCost of [undefined, null, 0, -1, "100", NaN, Infinity, 1.5]) {
    const status = { searchCost, units: 200000 };
    assert.equal(Pricing.cost(status), null);
    assert.equal(Pricing.canAfford(status), false);
    assert.match(Pricing.message(status), /unavailable.*credits stay saved/);
  }
});
const capabilities = () => ({ version: 1, sceneContributions: {
  ready: true, scope: "audited-new-locations", deviceQualificationRequired: true,
  canaryLocations: 112, verification: "trusted-profile-canary-and-submission-audit",
  model: "vision-four-view-v4", policyId: "approved-policy",
} });

test("the browser accepts the real qualified Scene contract without calling it independently audited", () => {
  const receipt = pipelineCapabilities({ SCENE_POLICY_ID: "approved-policy", SCENE_ADMISSION_MODE: "qualified-device-v1" });
  const readiness = new Readiness();
  readiness.update({ operational: true, searchOnSite: false }, receipt);
  assert.equal(readiness.canContribute(["scene"]), true);
  assert.equal(readiness.canContribute(["object"]), false);
  assert.equal(readiness.canContribute(["scene", "object"]), false);
  assert.equal(readiness.canSearch(), false);
  assert.equal(readiness.canSearch(true), true);
  assert.equal(receipt.sceneContributions.verification, "trusted-profile-canary-and-upload-integrity");
  assert.match(readiness.message(["scene"]), /computer check.*Scenes/);
  receipt.sceneContributions.ready = false;
  assert.equal(readiness.canContribute(["scene"]), false);
});

test("the real audited Scene contract and its legacy mode stay supported", () => {
  const receipt = pipelineCapabilities({ SCENE_POLICY_ID: "approved-policy" });
  const readiness = new Readiness();
  readiness.update({ operational: true }, receipt);
  assert.equal(readiness.canContribute(["scene"]), true);
  delete receipt.sceneContributions.admissionMode;
  assert.equal(readiness.canContribute(["scene"]), true);
});

test("qualified Scene admission requires matching mode, scope, verification and reference-check identity", () => {
  const make = () => pipelineCapabilities({ SCENE_POLICY_ID: "approved-policy", SCENE_ADMISSION_MODE: "qualified-device-v1" });
  for (const patch of [
    { admissionMode: undefined }, { admissionMode: "audited-v1" }, { admissionMode: "trusted" },
    { scope: "audited-new-locations" }, { verification: "trusted-profile-canary-and-submission-audit" },
    { verification: "structural-only" }, { deviceQualificationRequired: false }, { canaryLocations: 100 },
    { model: "other-model" }, { policyId: " " }, { ready: "true" },
  ]) {
    const receipt = make(); Object.assign(receipt.sceneContributions, patch);
    const readiness = new Readiness(); readiness.update({ operational: true }, receipt);
    assert.equal(readiness.canContribute(["scene"]), false, JSON.stringify(patch));
  }
  const receipt = pipelineCapabilities({ SCENE_POLICY_ID: "approved-policy" });
  receipt.sceneContributions.admissionMode = "qualified-device-v1";
  const readiness = new Readiness(); readiness.update({ operational: true }, receipt);
  assert.equal(readiness.canContribute(["scene"]), false);
});

test("Scene-only launch blocks new Object searches while preserving old requests and paid replies", () => {
  const values = new Map(), account = "a".repeat(32);
  const journal = new scope.VisionSearchJournal({ getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) });
  const original = journal.prepare(account, { lane: "object", prompt: "red door", maxCostUnits: 100 });
  const readiness = new Readiness();
  readiness.update({ operational: true, searchOnSite: true }, capabilities());
  assert.equal(readiness.canSearch(false, "scene"), true);
  for (const lane of ["object", "both", "other"]) assert.equal(readiness.canSearch(false, lane), false);
  readiness.update({ operational: true, searchOnSite: false }, capabilities());
  assert.equal(readiness.canSearch(true, "object"), true);
  assert.equal(JSON.stringify(journal.prepare(account, { lane: "scene", prompt: "new input" }).body), JSON.stringify(original.body));
  const reply = { searchId: "b".repeat(32), results: [], map: { customCoordinates: [] } };
  journal.complete(account, original.body.idempotencyKey, reply);
  assert.equal(journal.read(account), null);
  assert.equal(journal.result(account).searchId, reply.searchId);
  assert.equal(readiness.canSearch(false, "object"), false);
  readiness.fail();
  assert.equal(readiness.canSearch(true, "object"), false);
});

test("the actual search action refuses a new Object request but recovers the saved request without resubmitting", async () => {
  const app = readFileSync(new URL("../../../community/web/app.js", import.meta.url), "utf8");
  const source = app.slice(app.indexOf('$("run-search").addEventListener'), app.indexOf("$('cancel-search')?.addEventListener"));
  const values = new Map(), account = "a".repeat(32), calls = [], elements = new Map();
  let click;
  const element = id => {
    if (!elements.has(id)) elements.set(id, { value: "", textContent: "",
      addEventListener(event, handler) { if (id === "run-search" && event === "click") click = handler; } });
    return elements.get(id);
  };
  const journal = new scope.VisionSearchJournal({ getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) });
  const readiness = new Readiness();
  readiness.update({ operational: true, searchOnSite: true }, capabilities());
  const context = { $: element, deletionBlocksSearch: () => false, saveJobFromForm() {}, updateReady() {},
    signedIn: true, state: { accountId: account, units: 100, searchCost: 100, searchOnSite: true },
    searchJournal: journal, serviceReadiness: readiness, VisionSearchPricing: Pricing, searchPriceReview: null,
    selectedLane: () => "object", ERRORS: { search_unavailable: "Search unavailable" }, queryMap: null,
    typedPrompt: () => "new input", selectedDescriptionWeight: () => 100, countryMode: () => "all",
    selectedCountries: () => [], selectedGenerations: () => ["gen4"], selectedImportCutoff: () => null,
    document: { querySelector: () => null }, refresh: async () => {},
    api: async (path, method, body) => { calls.push({ path, method, body }); return { queued: true, state: "claimed" }; } };
  runInNewContext(source, context);
  await click();
  assert.equal(calls.length, 0); assert.equal(journal.read(account), null);
  assert.match(element("search-status").textContent, /Objects will follow later/);
  const original = journal.prepare(account, { lane: "object", prompt: "original input", maxCostUnits: 100 });
  readiness.update({ operational: true, searchOnSite: false }, capabilities());
  context.state.searchOnSite = false;
  await click();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, `/api/searches/recover?idempotencyKey=${encodeURIComponent(original.body.idempotencyKey)}`);
  assert.equal(calls[0].method, undefined);
  assert.equal(JSON.stringify(journal.read(account)), JSON.stringify(original.body));
  assert.match(element("search-status").textContent, /running.*Recover search later/);
});

test("unreachable service blocks new processing/search while preserving recovery guidance", () => {
  const readiness = new Readiness();
  assert.match(readiness.message(["scene"]), /Checking/);
  assert.equal(readiness.canContribute(["scene"]), false);
  assert.equal(readiness.canSearch(true), false);
  readiness.update({ operational: true, searchOnSite: true, units: 100000 }, capabilities());
  assert.equal(readiness.canContribute(["scene"]), true);
  readiness.fail();
  assert.equal(readiness.canContribute(["scene"]), false);
  assert.equal(readiness.canSearch(true), false);
  assert.equal(readiness.status.units, 100000);
  assert.match(readiness.message(["scene"]), /browser data/);
  assert.equal(readiness.update({ unexpected: "broken status" }, null), false);
  assert.equal(readiness.status.units, 100000);
  readiness.update({ operational: true, searchOnSite: true }, capabilities());
  assert.equal(readiness.canSearch(), true);
});

test("unreadable successful responses cannot complete or discard a saved paid-search request", async () => {
  const values = new Map();
  const journal = new scope.VisionSearchJournal({
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key),
  });
  const account = "a".repeat(32);
  const original = journal.prepare(account, { prompt: "red door" });
  for (const response of [
    { json: async () => { throw new SyntaxError("truncated response"); } },
    { json: async () => null }, { json: async () => [] }, { json: async () => "unexpected page" },
    { json: async () => ({}) }, { json: async () => ({ searchId: "bad", results: [], map: { customCoordinates: [] } }) },
    { json: async () => ({ searchId: account, results: [], map: null }) },
  ]) {
    await assert.rejects(async () => {
      const result = await Readiness.readResponse({ ...response, ok: true }, "/api/searches");
      journal.complete(account, original.body.idempotencyKey, result);
    }, /invalid_service_response/);
    assert.equal(journal.read(account).idempotencyKey, original.body.idempotencyKey);
  }
  assert.equal(journal.prepare(account, { prompt: "different input" }).recovering, true);
  assert.equal(JSON.stringify(journal.prepare(account, {}).body), JSON.stringify(original.body));
  const recovered = { searchId: account, results: [], map: { customCoordinates: [] } };
  const result = await Readiness.readResponse({ ok: true, json: async () => recovered }, "/api/searches");
  journal.complete(account, original.body.idempotencyKey, result);
  assert.equal(journal.read(account), null);
  assert.equal(journal.result(account).searchId, recovered.searchId);
});

test("legacy, malformed and unapproved admission contracts never enable scene commands", () => {
  for (const invalid of [null, {}, { version: "1" }, { version: 2 },
    { version: 1, sceneContributions: { ready: true, scope: "preapproved-locations-only" } }]) {
    const readiness = new Readiness();
    readiness.update({ operational: true }, invalid);
    assert.equal(readiness.canContribute(["scene"]), false);
  }
  for (const [key, invalid] of Object.entries({ ready: "true", scope: "preapproved-locations-only",
    deviceQualificationRequired: false, canaryLocations: 100, verification: "structural-only",
    model: "other-model", policyId: " " })) {
    const receipt = capabilities();
    receipt.sceneContributions[key] = invalid;
    const readiness = new Readiness();
    readiness.update({ operational: true }, receipt);
    assert.equal(readiness.canContribute(["scene"]), false, key);
  }
});

test("object and both never advertise an unqualified portable processing profile", () => {
  const readiness = new Readiness();
  readiness.update({ operational: true, searchOnSite: true }, capabilities());
  assert.equal(readiness.canContribute(["scene"]), true);
  assert.equal(readiness.canContribute(["object"]), false);
  assert.equal(readiness.canContribute(["scene", "object"]), false);
  assert.equal(readiness.canContribute([]), false);
  assert.match(readiness.message(["object"]), /follow later/);
  readiness.update({ operational: "true", searchOnSite: true }, capabilities());
  assert.equal(readiness.connected, false);
});

test("search outage keeps scene qualification available and permits saved-request recovery", () => {
  const readiness = new Readiness();
  readiness.update({ operational: true, searchOnSite: false }, capabilities());
  assert.equal(readiness.canContribute(["scene"]), true);
  assert.equal(readiness.canSearch(), false);
  assert.equal(readiness.canSearch(true), true);
  assert.match(readiness.message(["scene"]), /unused credits stay saved/);
});

test("capability check bounds the request and safely handles missing endpoints, bad JSON and network errors", async () => {
  let seen;
  const receipt = capabilities();
  const result = await Readiness.capabilities(async (path, options) => {
    seen = { path, options };
    return { ok: true, json: async () => receipt };
  });
  assert.equal(result, receipt);
  assert.equal(seen.path, "/api/capabilities");
  assert.equal(seen.options.cache, "no-store");
  assert.equal(seen.options.credentials, "same-origin");
  assert.ok(seen.options.signal instanceof AbortSignal);
  assert.equal(await Readiness.capabilities(async () => ({ ok: false })), null);
  assert.equal(await Readiness.capabilities(async () => ({ ok: true, json: async () => { throw new SyntaxError(); } })), null);
  assert.equal(await Readiness.capabilities(async () => { throw new TypeError("offline"); }), null);
});
