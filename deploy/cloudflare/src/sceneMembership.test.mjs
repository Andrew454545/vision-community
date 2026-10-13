import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {sealedSceneRows,MAX_SEALED_SCENE_HITS} from './sceneMembership.js';
import {verifiedSearchResult,searchDigest,onlineSearch} from './onlineSearch.js';
import {queueSearch,claimQueuedSearch,cancelQueuedSearch,searchCredit,queuedSearchConfigured} from './searchQueue.js';
import {deleteAccount} from './accountPrivacy.js';
import worker from './worker.js';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {sha256Hex,encodeUtf8} from './model.js';
import {treeFixture,packetFixture,accountingFixture,ACCOUNT,NOW} from './sceneMembership.fixture.mjs';

const code=expected=>error=>error.code===expected;
const clone=value=>JSON.parse(JSON.stringify(value));
async function prepared(t,count=3){const tree=treeFixture(count),f=await accountingFixture(tree);t.after(()=>f.sql.close());
  const digest=await searchDigest(f.query),packet=packetFixture(tree,digest.slice(7));return{...f,digest,packet};}
function check(f,packet=f.packet){return verifiedSearchResult(f.env,f.query,f.digest,packet,
  f.tree.header.snapshotSha256,'saved-test-id',100);}

test('bounded sealed Scene proofs supply authoritative poses with zero per-location catalog SQL',async t=>{
  const f=await prepared(t);const response=await check(f);
  assert.equal(response.results.length,3);assert.equal(response.results[0].pose.country,'Côte d’Ivoire');
  assert.equal(response.results[0].pose.heading,180);assert.equal(response.results[0].pose.cameraGeneration,'gen1');
  assert.equal(f.queries.some(query=>/FROM published_index i/.test(query)),false);
  assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM locations').get().n,0);
  assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM published_index').get().n,0);
});

test('one-leaf and odd-sized trees use exact sibling depth and duplicate final nodes',async t=>{
  for(const count of [1,3,5]){const f=await prepared(t,count);f.query.resultCount=3;
    const digest=await searchDigest(f.query);f.digest=digest;f.packet.requestSha256=digest.slice(7);
    assert.equal((await check(f)).results.length,Math.min(3,count));
    const broken=clone(f.packet);broken.membership[0].siblings.push('e'.repeat(64));
    await assert.rejects(check(f,broken),code('search_unavailable'));
  }
});

test('changing pose, output, location ID, ordinal, proof, root or snapshot cannot authorize a hit',async t=>{
  const f=await prepared(t);
  const changes=[p=>{const m=JSON.parse(p.membership[0].memberJson);m.pose.lat+=1;p.membership[0].memberJson=JSON.stringify(m);},
    p=>p.hits[0].locationId++,p=>p.hits[0].outputSha256='e'.repeat(64),p=>p.hits[0].sourceIndex++,
    p=>p.membership[0].siblings[0]='e'.repeat(64),p=>p.membership.pop(),p=>p.snapshotSha256='e'.repeat(64),
    p=>p.processedLocations++,p=>{p.membership[2].siblings[0]='e'.repeat(64);},p=>p.hits[0]=null];
  for(const change of changes){const packet=clone(f.packet);change(packet);await assert.rejects(check(f,packet),code('search_unavailable'));}
  const before=f.env.SEARCH_SCENE_MEMBERSHIP;const header=JSON.parse(before);header.rootSha256='e'.repeat(64);
  f.env.SEARCH_SCENE_MEMBERSHIP=JSON.stringify(header);await assert.rejects(check(f),code('search_unavailable'));
  assert.equal(f.queries.some(query=>/FROM published_index i/.test(query)),false);
});

test('seal configuration is exact, environment/resource bound and never falls back',async t=>{
  const f=await prepared(t),original=f.env.SEARCH_SCENE_MEMBERSHIP;
  const changes=[h=>h.version=true,h=>h.lane='object',h=>h.scope='uploader-self-report',h=>h.locations=0,
    h=>h.locations=100001,h=>h.locations=1.1,h=>h.environment='__proto__',h=>h.policyId='wrong',
    h=>h.runtimeSha256='e'.repeat(64),h=>h.snapshotSha256='e'.repeat(64),h=>h.extra='PRIVATE',
    h=>h.resource.bucket='geonections-images',h=>h.resource.databaseId='unrelated',h=>h.rootSha256='A'.repeat(64)];
  for(const change of changes){const h=JSON.parse(original);change(h);f.env.SEARCH_SCENE_MEMBERSHIP=JSON.stringify(h);
    await assert.rejects(check(f),code('search_unavailable'));}
  for(const invalid of ['',null,'[1]','x'.repeat(4097)]){f.env.SEARCH_SCENE_MEMBERSHIP=invalid;
    await assert.rejects(check(f),code('search_unavailable'));}
  f.env.SEARCH_SCENE_MEMBERSHIP=original;f.env.DEPLOYMENT_ENVIRONMENT='production';
  await assert.rejects(check(f),code('search_unavailable'));
  assert.equal(f.queries.some(query=>/FROM published_index i/.test(query)),false);
});

test('proof/member limits and invalid values refuse before a catalog lookup',async t=>{
  const f=await prepared(t);
  const changes=[p=>p.membership[0].memberJson='x'.repeat(8193),p=>p.membership[0].siblings=Array(18).fill('e'.repeat(64)),
    p=>p.membership[0].extra='PRIVATE',p=>p.membership[0].siblings[0]='NO',p=>delete p.membership];
  for(const change of changes){const p=clone(f.packet);change(p);await assert.rejects(check(f,p),code('search_unavailable'));}
  for(const [field,value] of [['lat',91],['lng',181],['pitch',91],['zoom',6],['panoId',''],['country','private\nname']]){
    const p=clone(f.packet),m=JSON.parse(p.membership[0].memberJson);m.pose[field]=value;p.membership[0].memberJson=JSON.stringify(m);
    await assert.rejects(check(f,p),code('search_unavailable'));
  }
  f.query.resultCount=MAX_SEALED_SCENE_HITS+1;await assert.rejects(check(f),code('search_unavailable'));
});

test('ordering, duplicate ordinal, filters, exclusions and pruning still use the shared search rules',async t=>{
  const f=await prepared(t);
  for(const change of [p=>p.hits[1].score=1,p=>{p.hits[1]=clone(p.hits[0]);p.membership[1]=clone(p.membership[0]);},
    p=>p.hits[0].score=-1,p=>p.hits[0].viewOffset=6]){
    const packet=clone(f.packet);change(packet);await assert.rejects(check(f,packet),code('search_unavailable'));
  }
  for(const changes of [{maxPerCountry:1},{filters:{mode:'include',countries:['USA'],generations:[]}},
    {excluded:[{lat:10,lng:20,panoId:'synthetic-scene-0'}]},{minimumGlobalLocation:1}]){
    const old=f.query;f.query={...old,...changes};f.digest=await searchDigest(f.query);f.packet.requestSha256=f.digest.slice(7);
    await assert.rejects(check(f),code('search_unavailable'));f.query=old;
  }
});

test('optional Scene root does not replace Object official-Gen4 publication authority',async t=>{
  const f=await prepared(t),query={...f.query,lane:'object'};
  assert.equal(await sealedSceneRows(f.env,query,f.packet,f.tree.header.snapshotSha256),null);
  f.query=query;f.digest=await searchDigest(query);f.packet.requestSha256=f.digest.slice(7);
  await assert.rejects(check(f),code('search_unavailable'));
  assert.equal(f.queries.some(q=>/FROM published_index i/.test(q)&&q.includes('object_coverage')&&q.includes('official-gen4-historical-v2-exact-pano')),true);
});

test('queued settlement with no per-location catalog rows debits exactly once and replays paid replies after root removal',async t=>{
  const f=await prepared(t);await f.enqueue();assert.equal((await searchCredit(f.env.DB,ACCOUNT)).reservedUnits,100);
  const {job}=await f.claim();const first=await f.complete(job,f.packet);const second=await f.complete(job,f.packet);
  assert.deepEqual(second,first);assert.equal(f.sql.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='search'").get().n,1);
  assert.equal(f.sql.prepare('SELECT units FROM accounts WHERE id=?').get(ACCOUNT).units,100);
  f.env.SEARCH_SCENE_MEMBERSHIP='broken';delete f.env.SEARCH_AGENT_SECRET;
  assert.deepEqual(await f.complete(job,f.packet),first);
  assert.equal(f.queries.some(q=>/FROM published_index i/.test(q)),false);
});

test('invalid root or over-limit result request reserves nothing and discloses no new Scene claim',async t=>{
  const f=await prepared(t);f.query.resultCount=65;
  await assert.rejects(f.enqueue(),code('search_result_count_limit'));
  assert.equal((await searchCredit(f.env.DB,ACCOUNT)).reservedUnits,0);f.query.resultCount=3;
  await f.enqueue();f.env.SEARCH_SCENE_MEMBERSHIP='broken';
  assert.equal(queuedSearchConfigured(f.env,'scene'),false);
  await assert.rejects(f.claim(),code('search_binding_changed'));
  const row=f.sql.prepare('SELECT attempts,state,query_json FROM search_jobs').get();
  assert.equal(row.attempts,0);assert.equal(row.state,'queued');assert.ok(row.query_json);
});

test('bad sealed Scene configuration cannot block a healthy independent Object lane',async t=>{
  const f=await prepared(t);delete f.env.SEARCH_SCENE_MEMBERSHIP;
  const identity={contractVersion:2,policyId:f.env.SEARCH_POLICY_ID,runtimeSha256:f.env.SEARCH_RUNTIME_SHA256,
    snapshotSha256:f.env.SEARCH_SNAPSHOT_SHA256};
  f.env.SEARCH_QUEUE_BINDINGS=JSON.stringify({version:1,lanes:{scene:identity,object:identity}});
  for(const key of ['SEARCH_POLICY_ID','SEARCH_RUNTIME_SHA256','SEARCH_SNAPSHOT_SHA256'])delete f.env[key];
  await queueSearch(f.env,ACCOUNT,`q1.${NOW}.`+'2'.repeat(32),{...f.query,lane:'object'},{now:NOW,maxCostUnits:100});
  f.env.SEARCH_SCENE_MEMBERSHIP='broken';
  const claim=await claimQueuedSearch(f.env,NOW+1,['scene','object'],{scene:identity,object:identity});
  assert.equal(JSON.parse(claim.job.requestJson).query.lane,'object');
  assert.equal(queuedSearchConfigured(f.env,'object'),true);
});

test('root change, cancellation and deletion fence late replies without charging',async t=>{
  for(const action of ['root','cancel','delete']){
    const f=await prepared(t);await f.enqueue();const {job}=await f.claim();
    if(action==='root'){const h=JSON.parse(f.env.SEARCH_SCENE_MEMBERSHIP);h.rootSha256='e'.repeat(64);f.env.SEARCH_SCENE_MEMBERSHIP=JSON.stringify(h);}
    if(action==='cancel')await cancelQueuedSearch(f.env,ACCOUNT,f.key,NOW+2);
    if(action==='delete')await deleteAccount(f.env,ACCOUNT,{accountId:ACCOUNT,idempotencyKey:'e'.repeat(64),confirmation:'DELETE'},NOW+2);
    await assert.rejects(f.complete(job,f.packet),code(action==='root'?'search_unavailable':'search_claim_lost'));
    assert.equal(f.sql.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='search'").get().n,0);
  }
});

test('synchronous optional path preflights its bounds and saved paid replay survives a broken seal',async t=>{
  const f=await prepared(t);let calls=0;
  f.env.SEARCH_ENGINE={async fetch(request){calls++;const requestBody=await request.json();return Response.json({...f.packet,
    requestSha256:requestBody.requestSha256});}};
  f.query.resultCount=65;await assert.rejects(onlineSearch(f.env,ACCOUNT,'test-private-synchronous',f.query),code('search_result_count_limit'));
  assert.equal(calls,0);f.query.resultCount=3;
  const paid=await onlineSearch(f.env,ACCOUNT,'test-private-synchronous',f.query);assert.equal(calls,1);
  f.env.SEARCH_SCENE_MEMBERSHIP='broken';f.env.SEARCH_ENGINE.fetch=()=>{throw Error('No recompute');};
  assert.deepEqual(await onlineSearch(f.env,ACCOUNT,'test-private-synchronous',f.query),paid);
});

test('HTTP status advertises the optional Scene limit without reducing Object results or needing catalog rows',async t=>{
  const f=await prepared(t);await prepareDatabase(f.env.DB);
  f.env.RATE_LIMITS_REQUIRED='1';
  for(const name of ['API_RATE_LIMITER','API_INGRESS_LIMITER','API_VIEW_LIMITER'])
    f.env[name]={async limit(){return{success:true};}}; // Fictional local bindings, no provider.
  f.sql.prepare('UPDATE accounts SET token_hash=? WHERE id=?').run(await sha256Hex(encodeUtf8('user-token')),ACCOUNT);
  const response=await worker.fetch(new Request('https://fixture.invalid/api/me?lite=1',{
    headers:{authorization:'Bearer user-token'}}),f.env);
  assert.equal(response.status,200);
  assert.deepEqual((await response.json()).searchResultLimits,{scene:64,object:1000});
  delete f.env.SEARCH_SCENE_MEMBERSHIP;delete f.env.SEARCH_DELIVERY;
  const old=await worker.fetch(new Request('https://fixture.invalid/api/me?lite=1',{
    headers:{authorization:'Bearer user-token'}}),f.env);
  assert.deepEqual((await old.json()).searchResultLimits,{scene:10000,object:10000});
});

test('actual browser readiness shows lane limits before new work and never edits an old recovery request',()=>{
  const app=readFileSync(new URL('../../../community/web/app.js',import.meta.url),'utf8');
  const source=app.slice(app.indexOf('function updateReady()'),app.indexOf('function coordinatesFrom('));
  const elements=new Map(),element=id=>{if(!elements.has(id))elements.set(id,{value:'',classList:{toggle(){}}});return elements.get(id);};
  const saved={idempotencyKey:'saved-request',resultCount:200},before=JSON.stringify(saved);
  let lane='scene',pending=false;
  const scope={$:element,number:String,state:{searchOnSite:true,searchResultLimits:{scene:64,object:1000}},signedIn:true,
    selectedLane:()=>lane,countryMode:()=> 'all',selectedGenerations:()=>['gen4'],hasQueryInput:()=>true,
    VisionSearchPricing:{canAfford:()=>true},searchJournal:{read:()=>pending?saved:null},
    serviceReadiness:{canSearch:()=>true},deletionBlocksSearch:()=>false};
  runInNewContext(source,scope);element('result-count').value='200';scope.updateReady();
  assert.equal(element('result-count').value,'200');assert.equal(element('result-count').max,64);
  assert.equal(element('run-search').disabled,true);assert.equal(element('ready-badge').textContent,'Choose 1–64 places');
  element('result-count').value='64';scope.updateReady();assert.equal(element('run-search').disabled,false);
  element('result-count').value='65';scope.updateReady();assert.equal(element('run-search').disabled,true);
  pending=true;scope.updateReady();assert.equal(element('run-search').disabled,false);
  assert.equal(element('run-search').textContent,'Recover search');assert.equal(JSON.stringify(saved),before);
  lane='object';pending=false;element('result-count').value='200';scope.updateReady();
  assert.equal(element('result-count').max,1000);assert.equal(element('run-search').disabled,false);
});
