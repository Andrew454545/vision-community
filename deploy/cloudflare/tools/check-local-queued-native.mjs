// Actual local workerd/D1/SQLite durable storage, alarms and process restart.
// Fake container transport only: no real inference, provider or account access.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareSearchHybrid} from './prepare-search-hybrid.mjs';
import {queueSearch} from '../src/searchQueue.js';
import {localRateLimits} from './local-api-bindings.mjs';
const [runtime,bundle,persistence,phase]=process.argv.slice(2),checks=[];
if(!phase){
  for(const step of ['seed','recover','alarm']){
    const child=spawnSync(process.execPath,[fileURLToPath(import.meta.url),runtime,bundle,persistence,step],
      {windowsHide:true,timeout:60000,encoding:'utf8',env:process.env});
    assert.equal(child.status,0,child.stderr||child.stdout);checks.push(...JSON.parse(child.stdout.trim()).checks);
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_QUEUED_NATIVE_PASSED',checks,checkCount:checks.length,separateProcesses:3,
    syntheticContainer:true,realInference:false,providerCalls:0,cloudResourcesAccessed:false,githubActionsRun:false,productionQualified:false}));
}else{
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(runtime)).href);
  const env={SEARCH_DELIVERY:'queued-v1',SEARCH_AGENT_SECRET:'f'.repeat(64),SEARCH_CLOUD_AGENT_SECRET:'9'.repeat(64),
    SEARCH_POLICY_ID:'offline-fixture',SEARCH_RUNTIME_SHA256:'d'.repeat(64),SEARCH_SNAPSHOT_SHA256:'e'.repeat(64),SEARCH_COST_UNITS:'100',
    SEARCH_HYBRID_POLICY:JSON.stringify({version:1,limitCents:12,openingCents:0,sceneCents:6,objectCents:8,
      cloudGraceSeconds:30,maxExecutionSeconds:120}),SEARCH_CLOUD_EXECUTION_MODE:'native-host-one-shot-v1',
    DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',
    DELETION_ARCHIVE_DB_ID:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',RATE_LIMITS_REQUIRED:'1'};
  const options={modules:true,scriptPath:resolve(bundle),modulesRoot:dirname(resolve(bundle)),compatibilityDate:'2026-10-02',
    compatibilityFlags:['nodejs_compat'],bindings:env,ratelimits:localRateLimits(),
    d1Databases:{DB:'00000000-0000-4000-8000-000000000914'},durableObjects:{FIXTURE:{className:'LocalQueuedFixture',useSQLite:true}},
    serviceBindings:{ASSETS:()=>new Response('offline fixture'),SEARCH_ENGINE:()=>{throw Error('real inference forbidden');}}};
  const mf=new Miniflare({...convertV4MiniflareOptions(options),resourcePersistencePath:resolve(persistence)});
  const call=(path,body)=>mf.dispatchFetch('https://local-fixture.invalid/'+path,{method:body===undefined?'GET':'POST',
    headers:{'content-type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(20000)});
  const status=async()=>{const response=await call('status');assert.equal(response.status,200);return response.json();};
  try{
    const db=await mf.getD1Database('DB'),account='a'.repeat(32);
    if(phase==='seed'){
      await prepareDatabase(db);const schema=new DatabaseSync(':memory:');
      try{schema.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));
        schema.exec(readFileSync(new URL('../search-queue.sql',import.meta.url),'utf8'));
        const definitions=schema.prepare(`SELECT sql FROM sqlite_master WHERE name LIKE 'search_jobs%' OR name='search_queue_revision'
          ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END`).all();
        await db.batch([...definitions.map(row=>db.prepare(row.sql)),
          db.prepare("INSERT INTO search_queue_revision VALUES(1,1,'vision-search-queue-v1-20261012')")]);
      }finally{schema.close();}
      await prepareSearchHybrid(db);await db.batch([
        db.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic',1000)").bind(account),
        db.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES (?,1000,'contribution','synthetic')").bind(account),
        db.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,country,camera_generation)
          VALUES(1,'abcdefghijklmnopqrstuv','2026-01','scene','scene-model','published','synthetic',10,20,90,'Italy','gen4')`),
        db.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_key) VALUES(1,'',?,0,'four-view-v4/test.i8')").bind('c'.repeat(64))]);
    }
    if(phase!=='recover'){
      const at=Math.floor(Date.now()/1000),key=`q1.${at}.${createHash('sha256').update(phase).digest('hex').slice(0,32)}`;
      await queueSearch({...env,DB:db},account,key,{lane:'scene',prompt:'red door',examples:[],excluded:[],queryName:'Synthetic',
        descriptionWeight:100,viewDirection:'bestOfFour',resultCount:20,maxPerCountry:25,filters:{mode:'all',countries:[],generations:[]},
        objectConfidence:'balanced',rejectRoadNames:false,minimumGlobalLocation:null},{now:at,maxCostUnits:100});
      assert.equal((await call('seed',{dropComplete:phase==='seed',hang:phase==='alarm'})).status,200);
    }
    const response=await call('step',{});
    if(phase==='seed'){
      assert.equal(response.status,503);const saved=await status();assert.equal(saved.phase,'stopped');assert.ok(saved.resultChunks>=3);
      assert.equal(saved.running,false);assert.equal(saved.searches,1);checks.push('durable-multiple-result-chunks-and-confirmed-stop-before-lost-ack');
      assert.equal((await db.prepare("SELECT count(*) n FROM ledger WHERE reason='search'").first()).n,1);
      checks.push('actual-D1-once-only-paid-settlement-before-lost-delivery');
    }else if(phase==='recover'){
      assert.equal(response.status,200);assert.equal((await response.json()).status,'completed');
      const saved=await status();assert.equal(saved.phase,null);assert.equal(saved.searches,1);assert.equal(saved.running,false);
      assert.equal(saved.last.status,'completed');assert.equal(saved.alarm,null);
      checks.push('separate-process-replays-chunks-without-new-native-call');
      assert.equal((await db.prepare("SELECT count(*) n FROM ledger WHERE reason='search'").first()).n,1);
      checks.push('restart-keeps-exactly-one-debit-and-retires-private-outbox');
    }else{
      assert.equal(response.status,200);assert.equal((await response.json()).status,'local_fallback');
      let saved=await status();
      for(let i=0;i<40&&saved.alarmCallbacks<1;i++){await new Promise(r=>setTimeout(r,25));saved=await status();}
      assert.ok(saved.alarmCallbacks>=1);assert.equal(saved.deadlineFailure,true);
      assert.equal(saved.running,false);assert.equal(saved.searches,2);assert.equal(saved.phase,null);
      checks.push('actual-durable-alarm-interrupts-busy-hung-search');
      assert.equal((await db.prepare("SELECT count(*) n FROM ledger WHERE reason='search'").first()).n,1);
      assert.equal(JSON.parse((await db.prepare('SELECT document FROM search_cloud_budget').first()).document).monthly.reservedCents,12);
      checks.push('deadline-failure-no-debit-retained-cost-and-local-release');
    }
    console.log(JSON.stringify({checks}));
  }finally{await mf.dispose();}
}
