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
  const values = new Map(), account = "a".repeat(32), calls = [], refreshes = [], elements = new Map();
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
    document: { querySelector: () => null }, refresh: async options => { refreshes.push(options); },
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
  assert.equal(refreshes.length,1);assert.equal(refreshes[0].accountOnly,true);
});

function controlResponse(patch={}) {
  return {accountControlVersion:1,creditContractVersion:1,operational:true,environment:'preview',model:'community-visual-v1',
    accountId:'a'.repeat(32),units:80,searchesAvailable:4,searchCost:20,searchBackend:'online',searchOnSite:true,searchReady:true,
    searchDelivery:'immediate',searchResultLimits:{scene:64,object:1000},indexDownloads:false,accountDeletionAvailable:true,...patch};
}
function refreshHarness(next,{unauthorized=false}={}) {
  const app=readFileSync(new URL('../../../community/web/app.js',import.meta.url),'utf8');
  const source=app.slice(app.indexOf('async function refresh(options'),app.indexOf('async function mapPool('));
  const elements=new Map(),calls=[],readiness=new Readiness();let capabilitiesCalls=0;
  const previous={operational:true,accountId:'a'.repeat(32),units:100,searchCost:100,searchOnSite:true,
    countries:['Italy'],cameraGenerations:['gen2'],counts:{scene:{pending:2,published:10}},
    work:{privateAccountWork:true},workByLane:{scene:{privateAccountWork:true}},r2:{bucket:'fixture'},privateOnly:'old account'};
  const element=id=>{
    if(!elements.has(id))elements.set(id,{dataset:{},textContent:'',hidden:false,disabled:false,
      options:[{}],replaceChildren(){this.cleared=true;}});
    return elements.get(id);
  };
  const context={$:element,state:previous,signedIn:true,searchPriceReview:{old:true},lastMap:{customCoordinates:[{panoId:'private'}]},
    document:{hidden:false,title:''},serviceReadiness:readiness,
    VisionServiceReadiness:{mergeAccountControls:Readiness.mergeAccountControls,
      capabilities:async()=>{capabilitiesCalls++;return capabilities();}},VisionSearchPricing:Pricing,
    api:async path=>{calls.push(path);if(unauthorized&&path.startsWith('/api/me'))throw Error('unauthorized');return next;},
    markServiceUnavailable(){readiness.fail();},closePriceReview(){},showResultActions(){},
    searchJournal:{result(){return null;}},number:n=>String(n||0),paintBalance(){},updateAccountPrivacy(){},
    processPrompt:()=>'',saveJobFromForm(){},renderCountries(){throw Error('must retain filter choices');},
    updateFilterHelp(){},updateQueue(){},updateReady(){},updateCliCommand(){},ERRORS:{search_unavailable:'unavailable'}};
  runInNewContext(source,context);
  return {context,previous,calls,elements,readiness,capabilitiesCalls:()=>capabilitiesCalls};
}

test('actual browser credit refresh requests only current controls and retains corpus filters',async()=>{
  const f=refreshHarness(controlResponse());await f.context.refresh({accountOnly:true});
  assert.deepEqual(f.calls,['/api/me?controls=1']);assert.equal(f.capabilitiesCalls(),1);
  assert.equal(f.context.state.units,80);assert.equal(f.context.state.searchCost,20);
  assert.equal(f.context.state.countries,f.previous.countries);assert.equal(f.context.state.counts,f.previous.counts);
  assert.equal(f.context.state.work,f.previous.work);assert.equal(f.readiness.canSearch(),true);
});

test('browser refresh respects reservations, paused availability and free saved-result recovery',async()=>{
  const f=refreshHarness(controlResponse({searchDelivery:'queued',bankedUnits:100,reservedUnits:20,searchOnSite:false,searchReady:false}));
  await f.context.refresh({accountOnly:true});
  assert.equal(f.context.state.units,80);assert.equal(f.context.state.reservedUnits,20);
  assert.equal(f.readiness.canSearch(),false);assert.equal(f.readiness.canSearch(true),true);
  const closed=refreshHarness(controlResponse({searchCost:null,searchesAvailable:0,searchReady:false,searchOnSite:false}));
  await closed.context.refresh({accountOnly:true});assert.equal(Pricing.canAfford(closed.context.state),false);
});

test('changed account controls discard prior private work, results and price approval',async()=>{
  const f=refreshHarness(controlResponse({accountId:'b'.repeat(32)}));await f.context.refresh({accountOnly:true});
  assert.equal(f.context.state.accountId,'b'.repeat(32));assert.equal('work' in f.context.state,false);
  assert.equal('workByLane' in f.context.state,false);assert.equal('privateOnly' in f.context.state,false);
  assert.equal(f.context.state.countries,f.previous.countries);assert.equal(f.context.lastMap,null);
  assert.equal(f.context.searchPriceReview,null);assert.equal(f.elements.get('results').cleared,true);
});

test('revoked browser sessions use anonymous controls without a dashboard fallback',async()=>{
  const f=refreshHarness(controlResponse({accountId:null,units:0,searchesAvailable:0,searchReady:false,searchOnSite:false}),{unauthorized:true});
  await f.context.refresh({accountOnly:true});assert.deepEqual(f.calls,['/api/me?controls=1','/api/status?controls=1']);
  assert.equal(f.context.signedIn,false);assert.equal(f.context.state.units,0);assert.equal('work' in f.context.state,false);
  assert.equal(f.context.lastMap,null);assert.equal(f.context.state.accountDeletionAvailable,true);
});

test('malformed current controls fail closed without full scans or discarding the old account state',async()=>{
  for(const patch of [{accountControlVersion:2},{creditContractVersion:true},{units:'80'},{searchesAvailable:99},
    {searchCost:0},{searchCost:null},{counts:{}},{searchReady:false},{searchDelivery:'queued'},
    {searchDelivery:'queued',bankedUnits:100,reservedUnits:10},{bankedUnits:80},{searchResultLimits:{scene:0,object:1000}}]){
    const f=refreshHarness(controlResponse(patch));
    await assert.rejects(f.context.refresh({accountOnly:true}),/invalid_service_response/);
    assert.deepEqual(f.calls,['/api/me?controls=1']);assert.equal(f.context.state,f.previous);
    assert.equal(f.readiness.connected,false);
  }
});

test('changing delivery mode drops obsolete reservation fields',()=>{
  const merged=Readiness.mergeAccountControls({accountId:'a'.repeat(32),bankedUnits:100,reservedUnits:20},controlResponse());
  assert.equal('bankedUnits' in merged,false);assert.equal('reservedUnits' in merged,false);
});

test('an older credit response cannot overwrite a newer account refresh',async()=>{
  const f=refreshHarness(controlResponse()),newer={accountId:'b'.repeat(32),units:999,operational:true};
  f.context.VisionServiceReadiness.capabilities=async()=>{f.context.state=newer;return capabilities();};
  await f.context.refresh({accountOnly:true});assert.equal(f.context.state,newer);
});

test('price-change recovery refreshes controls without approving or resubmitting the saved request',async()=>{
  const app=readFileSync(new URL('../../../community/web/app.js',import.meta.url),'utf8');
  const source=app.slice(app.indexOf('$("run-search").addEventListener'),app.indexOf("$('cancel-search')?.addEventListener"));
  const values=new Map(),account='a'.repeat(32),elements=new Map(),calls=[],refreshes=[];let click;
  const element=id=>{
    if(!elements.has(id))elements.set(id,{value:id==='result-count'?'64':id==='max-per-country'?'25':'',textContent:'',
      addEventListener(event,handler){if(id==='run-search'&&event==='click')click=handler;}});
    return elements.get(id);
  };
  const journal=new scope.VisionSearchJournal({getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)});
  const readiness=new Readiness();readiness.update({operational:true,searchOnSite:true},capabilities());
  const context={$:element,deletionBlocksSearch:()=>false,saveJobFromForm(){},updateReady(){},signedIn:true,
    state:{accountId:account,units:100,searchCost:100,searchOnSite:true},searchJournal:journal,
    serviceReadiness:readiness,VisionSearchPricing:Pricing,searchPriceReview:null,selectedLane:()=> 'scene',
    ERRORS:{search_unavailable:'unavailable'},queryMap:null,typedPrompt:()=> 'road',selectedDescriptionWeight:()=>100,
    countryMode:()=> 'all',selectedCountries:()=>[],selectedGenerations:()=>['gen4'],selectedImportCutoff:()=>null,
    document:{querySelector:()=>null},explain:e=>e.message,
    api:async(path,method,body)=>{calls.push({path,method,body});throw Object.assign(Error('search_price_changed'),{status:409});},
    refresh:async options=>{refreshes.push(options);context.state.searchCost=200;}};
  runInNewContext(source,context);await click();
  const pending=journal.read(account);assert.equal(pending.maxCostUnits,100);
  assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/searches');assert.equal(refreshes[0].accountOnly,true);
  assert.equal(context.searchPriceReview.accountId,account);assert.equal(context.searchPriceReview.approvedCost,undefined);
  assert.match(element('search-status').textContent,/Recover search to review the price/);
});

test('actual cancellation releases the saved pending search then refreshes only account controls',async()=>{
  const app=readFileSync(new URL('../../../community/web/app.js',import.meta.url),'utf8');
  const source=app.slice(app.indexOf("$('cancel-search')?.addEventListener"),app.indexOf('$("download-map").addEventListener'));
  const values=new Map(),account='a'.repeat(32),elements=new Map(),calls=[],refreshes=[];let click;
  const journal=new scope.VisionSearchJournal({getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)});
  const pending=journal.prepare(account,{lane:'scene',prompt:'road',maxCostUnits:100});
  const element=id=>{
    if(!elements.has(id))elements.set(id,{hidden:false,disabled:false,textContent:'',
      addEventListener(event,handler){if(id==='cancel-search'&&event==='click')click=handler;}});
    return elements.get(id);
  };
  runInNewContext(source,{$:element,state:{accountId:account},searchJournal:journal,updateReady(){},explain:e=>e.message,
    api:async(path,method,body)=>{calls.push({path,method,body});return {queued:true,state:'cancelled'};},
    refresh:async options=>{refreshes.push(options);}});
  await click();assert.equal(journal.read(account),null);assert.equal(calls.length,1);
  assert.equal(calls[0].path,'/api/search-jobs/cancel');assert.equal(calls[0].body.idempotencyKey,pending.body.idempotencyKey);
  assert.equal(refreshes[0].accountOnly,true);assert.match(element('search-status').textContent,/No credits were spent/);
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
