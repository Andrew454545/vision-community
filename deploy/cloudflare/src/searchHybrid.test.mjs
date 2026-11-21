// Actual local SQLite and Worker handlers; synthetic costs, features and engines.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,mkdtempSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareSearchHybrid} from '../tools/prepare-search-hybrid.mjs';
import {checkSearchQueue} from '../tools/check-search-queue.mjs';
import {checkSearchHybrid} from '../tools/check-search-hybrid.mjs';
import {queueSearch,claimQueuedSearch,renewQueuedSearch,completeQueuedSearch,queuedSearchStatus,
  recoverSearch,cancelQueuedSearch,failQueuedSearch,searchCredit,requireSearchAgent,authorizeCloudSearch} from './searchQueue.js';
import {acknowledgeCloudStop} from './searchHybrid.js';
import worker from './worker.js';
const ACCOUNT='a'.repeat(32),NOW=2000000000;
const key=(name,at=NOW)=>`q1.${at}.${createHash('sha256').update(name).digest('hex').slice(0,32)}`;
const policy=changes=>JSON.stringify({version:1,limitCents:12,openingCents:0,sceneCents:6,objectCents:8,
  cloudGraceSeconds:30,maxExecutionSeconds:120,...changes});
function d1(sql){return {prepare(query){const bind=(args=[])=>({bind:(...values)=>bind(values),
  first:async()=>sql.prepare(query).get(...args)||null,all:async()=>({results:sql.prepare(query).all(...args)}),
  run:async()=>bind(args).execute(),execute:()=>({meta:{changes:Number(sql.prepare(query).run(...args).changes)}})});return bind();},
  async batch(statements){sql.exec('BEGIN IMMEDIATE');try{const out=statements.map(s=>s.execute());sql.exec('COMMIT');return out;}
    catch(error){sql.exec('ROLLBACK');throw error;}}};}
async function fixture(t,{hybrid=true,file=':memory:'}={}){
  const sql=new DatabaseSync(file);t.after(()=>{if(sql.isOpen)sql.close();});
  const env={DB:d1(sql),SEARCH_DELIVERY:'queued-v1',SEARCH_AGENT_SECRET:'f'.repeat(64),SEARCH_CLOUD_AGENT_SECRET:'9'.repeat(64),
    SEARCH_POLICY_ID:'offline-fixture',SEARCH_RUNTIME_SHA256:'d'.repeat(64),SEARCH_SNAPSHOT_SHA256:'e'.repeat(64),SEARCH_COST_UNITS:'100',
    SEARCH_HYBRID_POLICY:policy(),SEARCH_ENGINE:{fetch(){throw Error('no provider/model calls');}}};
  await prepareDatabase(env.DB);sql.exec(readFileSync(new URL('../search-queue.sql',import.meta.url),'utf8'));
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'fixture',1000)").run(ACCOUNT);
  sql.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES (?,1000,'contribution','fixture')").run(ACCOUNT);
  sql.exec(`INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,country,camera_generation)
    VALUES(1,'abcdefghijklmnopqrstuv','2026-01','scene','scene-model','published','contributor',10,20,90,'Italy','gen4');
    INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_key)
    VALUES(1,'','${'c'.repeat(64)}',0,'four-view-v4/test.i8');`);
  if(hybrid)await prepareSearchHybrid(env.DB);
  const query={lane:'scene',prompt:'red door',examples:[],excluded:[],queryName:'My map',descriptionWeight:100,
    viewDirection:'bestOfFour',resultCount:20,maxPerCountry:25,filters:{mode:'all',countries:[],generations:[]},
    objectConfidence:'balanced',rejectRoadNames:false,minimumGlobalLocation:null};
  const enqueue=(name='request',at=NOW,changes={})=>queueSearch(env,ACCOUNT,key(name,at),{...query,...changes},{now:at,maxCostUnits:100});
  const claim=(executor='local',at=NOW)=>claimQueuedSearch(env,at,['scene'],undefined,executor);
  const budget=()=>{const v=sql.prepare('SELECT document FROM search_cloud_budget').get();return v&&v.document!=='uninitialized-v1'?JSON.parse(v.document):null;};
  const debits=()=>sql.prepare("SELECT count(*) n FROM ledger WHERE reason='search'").get().n;
  return {sql,env,query,enqueue,claim,budget,debits};
}
function computed(job){const {query,...head}=JSON.parse(job.requestJson);return {...head,processedLocations:1,
  hits:[{locationId:1,outputSha256:'c'.repeat(64),sourceIndex:0,score:.8,viewOffset:1}]};}
const code=wanted=>e=>e.code===wanted;
const stopBody=job=>({jobId:job.jobId,claimToken:job.claimToken,shutdownReceiptSha256:'7'.repeat(64)});
const nonce=(at=NOW,tail='2')=>at.toString(16).padStart(16,'0')+tail.repeat(48);

test('durable cloud nonce recovers one identical grant after lost acknowledgement without new cost or attempt',async t=>{
  const f=await fixture(t);await f.enqueue();const token=nonce();
  const claim=at=>claimQueuedSearch(f.env,at,['scene'],undefined,'cloud',token);
  const grants=await Promise.all(Array.from({length:8},()=>claim(NOW)));
  assert.ok(grants.every(r=>r.job&&r.job.claimToken===token));
  assert.ok(grants.every(r=>r.job.jobId===grants[0].job.jobId));
  assert.equal(f.budget().monthly.reservedCents,6);assert.equal(f.budget().claims.length,1);
  assert.equal(f.sql.prepare('SELECT attempts FROM search_jobs').get().attempts,1);
  assert.deepEqual(await claim(NOW+121),grants[0]); // Recovery discloses only the prior grant; fresh authorize refuses it.
  await assert.rejects(authorizeCloudSearch(f.env,{jobId:grants[0].job.jobId,claimToken:token},NOW+121),code('search_claim_lost'));
});

test('cloud nonce cannot retarget after stop, account deletion, changed pins or settlement',async t=>{
  for(const action of ['stopped','deleted','binding','paid']){
    const f=await fixture(t);await f.enqueue();const token=nonce();
    const first=await claimQueuedSearch(f.env,NOW,['scene'],undefined,'cloud',token);
    if(action==='stopped')await acknowledgeCloudStop(f.env,stopBody(first.job),NOW+1);
    if(action==='deleted'){
      f.sql.prepare('UPDATE accounts SET deleted_at=? WHERE id=?').run(NOW+1,ACCOUNT);
      f.sql.exec('DELETE FROM search_jobs');
      f.sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'next',1000)").run('b'.repeat(32));
      await queueSearch(f.env,'b'.repeat(32),key('next',NOW+1),f.query,{now:NOW+1,maxCostUnits:100});
    }else await f.enqueue('next',NOW+1);
    if(action==='binding')f.env.SEARCH_SNAPSHOT_SHA256='6'.repeat(64);
    if(action==='paid')await completeQueuedSearch(f.env,first.job.jobId,token,computed(first.job),NOW+1,'cloud');
    assert.equal((await claimQueuedSearch(f.env,NOW+2,['scene'],undefined,'cloud',token)).job,null,action);
    assert.equal(f.budget().monthly.reservedCents,6);assert.equal(f.budget().claims.length,1);
    assert.equal(JSON.stringify(f.budget()).includes(ACCOUNT),false);
  }
});

test('nonce retry refuses missing or corrupt spending authority before recovering an execution grant',async t=>{
  const f=await fixture(t);await f.enqueue();const token=nonce();
  await claimQueuedSearch(f.env,NOW,['scene'],undefined,'cloud',token);
  const original=f.budget();
  for(const document of ['{',JSON.stringify({...original,claims:[]})]){
    f.sql.prepare('UPDATE search_cloud_budget SET document=?').run(document);
    await assert.rejects(claimQueuedSearch(f.env,NOW+1,['scene'],undefined,'cloud',token),code('search_cloud_budget_unavailable'));
  }
  assert.equal(f.debits(),0);assert.equal(f.sql.prepare('SELECT attempts FROM search_jobs').get().attempts,1);
});

test('simultaneous different lane capabilities cannot reuse one durable nonce for two grants',async t=>{
  const f=await fixture(t);await f.enqueue('scene');await f.enqueue('object',NOW,{lane:'object'});
  const grants=await Promise.all(['scene','object'].map(lane=>claimQueuedSearch(f.env,NOW,[lane],undefined,'cloud',nonce())));
  assert.equal(grants.filter(r=>r.job).length,1);
  assert.equal(f.budget().rolling.reservations.length,1);assert.equal(f.budget().claims.length,1);
  assert.equal(f.sql.prepare("SELECT count(*) n FROM search_jobs WHERE state='claimed'").get().n,1);
});

test('nonce validation and legacy budget upgrade preserve sealed usage',async t=>{
  const f=await fixture(t);await f.enqueue();
  for(const token of [null,'bad',nonce(NOW-3601),nonce(NOW+301)])
    await assert.rejects(claimQueuedSearch(f.env,NOW,['scene'],undefined,'cloud',token),code('invalid_cloud_claim_request'));
  assert.equal(f.budget(),null);
  const first=await f.claim('cloud');await acknowledgeCloudStop(f.env,stopBody(first.job),NOW+1);
  const legacy=f.budget();delete legacy.claims;legacy.version=1;
  f.sql.prepare('UPDATE search_cloud_budget SET document=?').run(JSON.stringify(legacy));
  await f.enqueue('second',NOW+2);
  const second=await claimQueuedSearch(f.env,NOW+2,['scene'],undefined,'cloud',nonce(NOW+2));
  assert.ok(second.job);assert.equal(f.budget().version,2);assert.equal(f.budget().monthly.reservedCents,12);
  assert.equal(f.budget().claims.length,1);assert.equal(checkSearchHybrid(f.sql,NOW+3).passed,true);
});

test('fresh cloud authorization is read-only, staging-bound, Scene-only and rejects changed authority',async t=>{
  const f=await fixture(t);await f.enqueue();const {job}=await f.claim('cloud');
  const body={jobId:job.jobId,claimToken:job.claimToken};
  await assert.rejects(authorizeCloudSearch(f.env,body,NOW+1));
  Object.assign(f.env,{SEARCH_CLOUD_EXECUTION_MODE:'native-host-one-shot-v1',DEPLOYMENT_ENVIRONMENT:'staging',
    INDEX_BUCKET_NAME:'vision-community-staging',DELETION_ARCHIVE_DB_ID:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05'});
  const before=JSON.stringify(f.budget());const authorized=await authorizeCloudSearch(f.env,body,NOW+1);
  assert.deepEqual(authorized.job,job);assert.equal(authorized.resource.bucket,'vision-community-staging');
  assert.equal(JSON.stringify(f.budget()),before);assert.equal(f.debits(),0);
  f.env.INDEX_BUCKET_NAME='other';await assert.rejects(authorizeCloudSearch(f.env,body,NOW+1));
  f.env.INDEX_BUCKET_NAME='vision-community-staging';f.env.SEARCH_SNAPSHOT_SHA256='6'.repeat(64);
  await assert.rejects(authorizeCloudSearch(f.env,body,NOW+1),code('search_claim_lost'));
});

test('cloud claim reserves maximum cost before disclosure; local grace and nonrenewable deadline are explicit',async t=>{
  const f=await fixture(t);await f.enqueue();
  assert.equal((await f.claim()).job,null);assert.equal(f.budget(),null);
  const {job}=await f.claim('cloud');assert.equal(job.reservedCents,6);assert.equal(job.executionDeadline,NOW+120);
  assert.equal(f.budget().monthly.reservedCents,6);assert.equal(f.budget().rolling.reservations.length,1);
  assert.equal((await f.claim('local',NOW+121)).job,null);
  assert.deepEqual(await renewQueuedSearch(f.env,job.jobId,job.claimToken,NOW+100,'cloud'),{claimUntil:NOW+120});
  await assert.rejects(renewQueuedSearch(f.env,job.jobId,job.claimToken,NOW+120,'cloud'),code('search_claim_lost'));
  assert.equal(f.debits(),0);assert.equal((await searchCredit(f.env.DB,ACCOUNT)).reservedUnits,100);
});

test('stopped cloud claim hands the identical queued query to local execution, preserving cost and once-only debit',async t=>{
  const f=await fixture(t);await f.enqueue();const {job:cloud}=await f.claim('cloud');
  assert.deepEqual(await acknowledgeCloudStop(f.env,stopBody(cloud),NOW+121),{stopped:true});
  assert.deepEqual(await acknowledgeCloudStop(f.env,stopBody(cloud),NOW+122),{stopped:true});
  const {job:local}=await f.claim('local',NOW+122);
  assert.equal(local.jobId,cloud.jobId);assert.notEqual(local.claimToken,cloud.claimToken);
  assert.equal(local.requestJson,cloud.requestJson);assert.equal(Object.hasOwn(local,'reservedCents'),false);
  await assert.rejects(completeQueuedSearch(f.env,cloud.jobId,cloud.claimToken,computed(cloud),NOW+123,'cloud'),code('search_claim_lost'));
  await completeQueuedSearch(f.env,local.jobId,local.claimToken,computed(local),NOW+123);
  assert.equal(f.debits(),1);assert.equal(f.budget().monthly.reservedCents,6);
  const row=f.sql.prepare('SELECT * FROM search_hybrid_claims').get();
  assert.equal(row.cloud_token,cloud.claimToken);assert.equal(row.shutdown_sha256,'7'.repeat(64));
  delete f.env.SEARCH_HYBRID_POLICY;delete f.env.SEARCH_AGENT_SECRET;
  assert.equal((await recoverSearch(f.env,ACCOUNT,key('request'),NOW+124)).searchId,local.jobId);
});

test('budget exhaustion routes new work locally at once without cloud cost or a second reservation',async t=>{
  const f=await fixture(t);f.env.SEARCH_HYBRID_POLICY=policy({limitCents:6});
  await f.enqueue('first');const {job}=await f.claim('cloud');await completeQueuedSearch(f.env,job.jobId,job.claimToken,computed(job),NOW+1,'cloud');
  await f.enqueue('second',NOW+2);assert.equal((await f.claim('cloud',NOW+2)).job,null);
  const {job:local}=await f.claim('local',NOW+2);assert.ok(local);
  assert.equal(f.budget().monthly.reservedCents,6);assert.equal(f.budget().rolling.reservations.length,1);
  assert.equal(f.debits(),1);
});

test('unavailable cloud receives a finite preference window; local-only execution consumes zero compute cents',async t=>{
  const f=await fixture(t);await f.enqueue();assert.equal((await f.claim('local',NOW+29)).job,null);
  const {job}=await f.claim('local',NOW+30);assert.ok(job);
  assert.equal(f.budget().monthly.reservedCents,0);assert.deepEqual(f.budget().rolling.reservations,[]);
  const replacement=(await f.claim('local',NOW+331)).job;assert.ok(replacement);
  await assert.rejects(completeQueuedSearch(f.env,job.jobId,job.claimToken,computed(job),NOW+332),code('search_claim_lost'));
});

test('simultaneous cloud hosts and local agents cannot own one query or overspend the common allowance',async t=>{
  const f=await fixture(t);f.env.SEARCH_HYBRID_POLICY=policy({cloudGraceSeconds:0,limitCents:6});
  await f.enqueue('a');await f.enqueue('b');await f.enqueue('c');
  const grants=await Promise.all(Array.from({length:12},(_,i)=>f.claim(i%3?'cloud':'local')));
  const jobs=grants.flatMap(r=>r.job?[r.job]:[]);assert.equal(new Set(jobs.map(j=>j.jobId)).size,jobs.length);
  assert.ok(f.budget().monthly.reservedCents<=6);assert.ok(f.budget().rolling.reservations.length<=1);
  assert.ok(jobs.length>=1);assert.equal(f.debits(),0);
});

test('competing cloud executors share one allowance across separate queued jobs',async t=>{
  const f=await fixture(t);f.env.SEARCH_HYBRID_POLICY=policy({limitCents:6});
  await f.enqueue('a');await f.enqueue('b');await f.enqueue('c');
  const claims=await Promise.all(Array.from({length:12},()=>f.claim('cloud')));
  assert.equal(claims.filter(r=>r.job).length,1);assert.equal(f.budget().monthly.reservedCents,6);
  assert.equal(f.budget().rolling.reservations.length,1);assert.equal(f.debits(),0);
});

test('Scene and Object search claims consume the same allocation with separately sealed cost weights',async t=>{
  const f=await fixture(t);await f.enqueue('object',NOW,{lane:'object'});await f.enqueue('scene');
  const {job}=await claimQueuedSearch(f.env,NOW,['object'],undefined,'cloud');assert.equal(job.reservedCents,8);
  assert.equal((await f.claim('cloud')).job,null);assert.ok((await f.claim('local')).job);
  assert.equal(f.budget().monthly.reservedCents,8);assert.equal(f.budget().rolling.reservations.length,1);
  // This is claim accounting only, not authentic Object inference or admission.
  assert.equal(f.debits(),0);
});

test('zero allocation and prior-usage floors refuse cloud work without charging the user',async t=>{
  for(const changes of [{limitCents:0},{openingCents:7}]){
    const f=await fixture(t);f.env.SEARCH_HYBRID_POLICY=policy(changes);await f.enqueue();
    assert.equal((await f.claim('cloud')).job,null);assert.ok((await f.claim('local')).job);
    assert.equal(f.budget().monthly.reservedCents,changes.openingCents||0);assert.equal(f.debits(),0);
  }
});

test('month boundary, policy raises and cheaper job estimates cannot reset the shared allocation',async t=>{
  const f=await fixture(t);f.env.SEARCH_HYBRID_POLICY=policy({limitCents:6});
  const end=Date.UTC(2026,9,31,23,59,59)/1000;
  await f.enqueue('end',end);const {job}=await f.claim('cloud',end);
  await completeQueuedSearch(f.env,job.jobId,job.claimToken,computed(job),end,'cloud');
  f.env.SEARCH_HYBRID_POLICY=policy({limitCents:300,sceneCents:1});
  await f.enqueue('next',end+1);assert.equal((await f.claim('cloud',end+1)).job,null);
  assert.equal(f.budget().rolling.limitCents,6);assert.equal(f.budget().rolling.requestCents,6);
  assert.ok((await f.claim('local',end+1)).job);
});

test('cancellation and deletion release held credits but never refund uncertain compute reservations',async t=>{
  for(const deleted of [false,true]){
    const f=await fixture(t);await f.enqueue();const {job}=await f.claim('cloud');
    if(deleted)f.sql.exec(`UPDATE accounts SET deleted_at=${NOW+1},units=0 WHERE id='${ACCOUNT}'`);
    else await cancelQueuedSearch(f.env,ACCOUNT,key('request'),NOW+1);
    await assert.rejects(completeQueuedSearch(f.env,job.jobId,job.claimToken,computed(job),NOW+2,'cloud'),code('search_claim_lost'));
    assert.equal(f.budget().monthly.reservedCents,6);assert.equal(f.debits(),0);
    if(deleted)assert.equal(f.sql.prepare('SELECT count(*) n FROM search_hybrid_claims').get().n,0);
    else assert.equal((await searchCredit(f.env.DB,ACCOUNT)).reservedUnits,0);
  }
});

test('lost transaction reply preserves reserved cost and fences competing local work until stop acknowledgement',async t=>{
  const f=await fixture(t);await f.enqueue();const batch=f.env.DB.batch;
  f.env.DB.batch=async statements=>{const r=await batch(statements);if(statements.length===3)throw Error('synthetic lost durable reply');return r;};
  await assert.rejects(f.claim('cloud'),/synthetic lost durable reply/);
  f.env.DB.batch=batch;assert.equal(f.budget().monthly.reservedCents,6);
  assert.equal((await f.claim('local',NOW+121)).job,null);assert.equal((await f.claim('cloud',NOW+121)).job,null);
  assert.equal(f.debits(),0);
});

test('failed SQL rolls back both compute reservation and claim with no execution grant',async t=>{
  const f=await fixture(t);await f.enqueue();
  f.sql.exec("CREATE TRIGGER injected_claim_failure BEFORE INSERT ON search_hybrid_claims BEGIN SELECT RAISE(ABORT,'synthetic claim SQL failure'); END");
  await assert.rejects(f.claim('cloud'),/synthetic claim SQL failure/);assert.equal(f.budget(),null);
  assert.equal(f.sql.prepare('SELECT attempts FROM search_jobs').get().attempts,0);assert.equal(f.debits(),0);
});

test('local and cloud authentication and claim authority are distinct',async t=>{
  const f=await fixture(t);const auth=secret=>new Request('https://community.test/api/search-cloud-agent/claim',{headers:{authorization:`Bearer ${secret}`}});
  await requireSearchAgent(f.env,auth(f.env.SEARCH_AGENT_SECRET));
  await requireSearchAgent(f.env,auth(f.env.SEARCH_CLOUD_AGENT_SECRET),'cloud');
  await assert.rejects(requireSearchAgent(f.env,auth(f.env.SEARCH_AGENT_SECRET),'cloud'),code('unauthorized'));
  await assert.rejects(requireSearchAgent(f.env,auth(f.env.SEARCH_CLOUD_AGENT_SECRET)),code('unauthorized'));
  await f.enqueue();const {job}=await f.claim('cloud');
  await assert.rejects(completeQueuedSearch(f.env,job.jobId,job.claimToken,computed(job),NOW+1),code('search_claim_lost'));
  await assert.rejects(failQueuedSearch(f.env,job.jobId,job.claimToken,NOW+1),code('search_claim_lost'));
});

test('malformed/removed policies and corrupt budget state cannot reopen cloud work; local work preserves corruption',async t=>{
  const f=await fixture(t);await f.enqueue();const original=f.env.SEARCH_HYBRID_POLICY;
  for(const raw of [undefined,'{}','null',policy({limitCents:301}),policy({maxExecutionSeconds:241})]){
    if(raw===undefined)delete f.env.SEARCH_HYBRID_POLICY;else f.env.SEARCH_HYBRID_POLICY=raw;
    await assert.rejects(f.claim('cloud'));assert.equal(f.budget(),null);
  }
  f.env.SEARCH_HYBRID_POLICY=original;
  f.sql.prepare('UPDATE search_cloud_budget SET document=?,operation_token=?').run('{','1'.repeat(64));
  await assert.rejects(f.claim('cloud'),code('search_cloud_budget_unavailable'));
  assert.ok((await f.claim('local')).job);
  assert.equal(f.sql.prepare('SELECT document FROM search_cloud_budget').get().document,'{');
});

test('missing retained budget state requires reconciliation and is never silently recreated on request/setup',async t=>{
  const f=await fixture(t);await f.enqueue();const {job}=await f.claim('cloud');
  await failQueuedSearch(f.env,job.jobId,job.claimToken,NOW+1,'cloud');await f.enqueue('next',NOW+2);
  f.sql.exec('DROP TRIGGER search_cloud_budget_retained; DELETE FROM search_cloud_budget');
  await assert.rejects(f.claim('cloud',NOW+2),code('search_cloud_budget_unavailable'));
  await assert.rejects(prepareSearchHybrid(f.env.DB),/hybrid_budget_reconciliation_required/);
  assert.ok((await f.claim('local',NOW+2)).job);assert.equal(f.sql.prepare('SELECT count(*) n FROM search_cloud_budget').get().n,0);
});

test('optional migration preserves queue guards, refuses running legacy claims and blocks unbudgeted legacy claiming',async t=>{
  const f=await fixture(t,{hybrid:false});delete f.env.SEARCH_HYBRID_POLICY;
  await f.enqueue();const {job}=await f.claim();
  await assert.rejects(prepareSearchHybrid(f.env.DB),/hybrid_running_claims_require_reconciliation/);
  await failQueuedSearch(f.env,job.jobId,job.claimToken,NOW+1);await prepareSearchHybrid(f.env.DB);
  assert.equal(checkSearchQueue(f.sql).passed,true);
  f.env.SEARCH_HYBRID_POLICY=policy();await f.enqueue('new',NOW+2);
  assert.throws(()=>f.sql.prepare("UPDATE search_jobs SET state='claimed',claim_token=?,claim_until=?,attempts=attempts+1 WHERE state='queued'")
    .run('8'.repeat(64),NOW+300),/hybrid_claim_required/);
  assert.ok((await f.claim('cloud',NOW+2)).job);
  assert.throws(()=>f.sql.exec('DELETE FROM search_cloud_budget'),/cloud_budget_retained/);
});

test('worker cloud routes authenticate before private body/database access and do not run engines',async t=>{
  const f=await fixture(t);let touched=0;
  const env={...f.env,DB:{prepare(){touched++;throw Error('private database should not be touched');}}};
  const response=await worker.fetch(new Request('https://community.test/api/search-cloud-agent/claim',{
    method:'POST',headers:{authorization:`Bearer ${f.env.SEARCH_AGENT_SECRET}`,'content-type':'application/json'},body:'{'}),env);
  assert.equal(response.status,401);assert.equal(touched,0);
});

test('actual Worker routes enforce cloud/local roles, stop recovery and exact once-only paid replay',async t=>{
  const f=await fixture(t),at=Math.floor(Date.now()/1000);await f.enqueue('http',at);
  const post=async(role,action,body)=>worker.fetch(new Request(`https://community.test/api/search-${role==='cloud'?'cloud-agent':'agent'}/${action}`,{
    method:'POST',headers:{authorization:`Bearer ${role==='cloud'?f.env.SEARCH_CLOUD_AGENT_SECRET:f.env.SEARCH_AGENT_SECRET}`,
      'content-type':'application/json'},body:JSON.stringify(body)}),f.env);
  const claim=await post('cloud','claim',{lanes:['scene'],executor:'local'});assert.equal(claim.status,200);
  const {job}=await claim.json();assert.equal(job.reservedCents,6);assert.equal(f.budget().monthly.reservedCents,6);
  assert.equal((await post('local','renew',{jobId:job.jobId,claimToken:job.claimToken})).status,409);
  assert.equal((await post('cloud','stopped',stopBody(job))).status,200);
  const next=await post('local','claim',{lanes:['scene'],executor:'cloud'});assert.equal(next.status,200);
  const local=(await next.json()).job;assert.equal(local.jobId,job.jobId);assert.equal(Object.hasOwn(local,'reservedCents'),false);
  const body={jobId:local.jobId,claimToken:local.claimToken,result:computed(local)};
  assert.equal((await post('local','complete',body)).status,200);assert.equal((await post('local','complete',body)).status,200);
  assert.equal(f.debits(),1);assert.equal(f.budget().monthly.reservedCents,6);
});

test('cloud settlement/stop acknowledgement replay cannot refund cost, double-charge or replace shutdown evidence',async t=>{
  const f=await fixture(t);await f.enqueue();const {job}=await f.claim('cloud');
  const replies=await Promise.all(Array.from({length:3},()=>completeQueuedSearch(f.env,job.jobId,job.claimToken,computed(job),NOW+1,'cloud')));
  assert.equal(new Set(replies.map(r=>r.searchId)).size,1);assert.equal(f.debits(),1);
  await acknowledgeCloudStop(f.env,stopBody(job),NOW+2);
  await acknowledgeCloudStop(f.env,stopBody(job),NOW+3);
  await assert.rejects(acknowledgeCloudStop(f.env,{...stopBody(job),shutdownReceiptSha256:'6'.repeat(64)},NOW+4),code('cloud_stop_conflict'));
  assert.equal(f.debits(),1);assert.equal(f.budget().monthly.reservedCents,6);assert.equal((await f.claim('local',NOW+5)).job,null);
});

test('concurrent conflicting stop acknowledgements retain exactly one receipt and reject the other',async t=>{
  const f=await fixture(t);await f.enqueue();const {job}=await f.claim('cloud');
  const replies=await Promise.allSettled([acknowledgeCloudStop(f.env,stopBody(job),NOW+1),
    acknowledgeCloudStop(f.env,{...stopBody(job),shutdownReceiptSha256:'6'.repeat(64)},NOW+1)]);
  assert.equal(replies.filter(r=>r.status==='fulfilled').length,1);
  assert.equal(replies.find(r=>r.status==='rejected').reason.code,'cloud_stop_conflict');
  assert.equal(f.budget().monthly.reservedCents,6);assert.equal(f.debits(),0);
});

test('stored shared budget survives SQLite close/reopen without a new allowance',async t=>{
  const dir=mkdtempSync(join(tmpdir(),'hybrid-'));let reopened;
  t.after(()=>{if(reopened?.isOpen)reopened.close();rmSync(dir,{recursive:true,force:true});});
  const path=join(dir,'private.sqlite'),f=await fixture(t,{file:path});f.env.SEARCH_HYBRID_POLICY=policy({limitCents:6});
  await f.enqueue();const {job}=await f.claim('cloud');await failQueuedSearch(f.env,job.jobId,job.claimToken,NOW+1,'cloud');
  f.sql.close();reopened=new DatabaseSync(path);f.env.DB=d1(reopened);
  await f.enqueue('after-restart',NOW+2);assert.equal((await f.claim('cloud',NOW+2)).job,null);
  assert.equal(JSON.parse(reopened.prepare('SELECT document FROM search_cloud_budget').get().document).monthly.reservedCents,6);
});

test('offline hybrid preflight checks untouched guards, retained reservations and shutdown authority without writes',async t=>{
  const f=await fixture(t);assert.equal(checkSearchHybrid(f.sql,NOW).initialized,false);
  await f.enqueue();const {job}=await f.claim('cloud');
  const state=()=>JSON.stringify(f.sql.prepare('SELECT * FROM search_cloud_budget').all());
  const before=state();assert.equal(checkSearchHybrid(f.sql,NOW).monthlyReservedCents,6);assert.equal(state(),before);
  await acknowledgeCloudStop(f.env,stopBody(job),NOW+1);await f.claim('local',NOW+1);
  assert.equal(checkSearchHybrid(f.sql,NOW+1).passed,true);
  const budget=f.sql.prepare('SELECT document FROM search_cloud_budget').get().document;
  assert.throws(()=>f.sql.prepare("UPDATE search_cloud_budget SET document='uninitialized-v1',operation_token=?").run('0'.repeat(64)),/cloud_budget_reset/);
  const lost=JSON.parse(budget);lost.monthly.reservedCents=0;lost.rolling.reservations=[];
  f.sql.prepare('UPDATE search_cloud_budget SET document=?,operation_token=?').run(JSON.stringify(lost),'0'.repeat(64));
  assert.throws(()=>checkSearchHybrid(f.sql,NOW+1),/search_hybrid_preflight_failed/);
  f.sql.prepare('UPDATE search_cloud_budget SET document=?,operation_token=?').run(budget,'8'.repeat(64));
  f.sql.exec('DROP TRIGGER search_hybrid_claim_guard');assert.throws(()=>checkSearchHybrid(f.sql,NOW+1),/search_hybrid_preflight_failed/);
  await assert.rejects(prepareSearchHybrid(f.env.DB));
});
