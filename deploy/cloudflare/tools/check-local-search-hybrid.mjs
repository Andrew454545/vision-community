// Finite actual local workerd/D1 check, with synthetic credits and native scores.
// No Cloudflare credentials, providers, models, public endpoints or real data.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareSearchHybrid} from './prepare-search-hybrid.mjs';
import {localRateLimits} from './local-api-bindings.mjs';
const [runtime,bundle,persistence,phase]=process.argv.slice(2);
if(!phase){
  const checks=[];
  for(const step of ['seed','recover']){
    const child=spawnSync(process.execPath,[fileURLToPath(import.meta.url),runtime,bundle,persistence,step],{
      env:process.env,windowsHide:true,timeout:90000,encoding:'utf8'});
    assert.equal(child.status,0,child.stderr||child.stdout);checks.push(...JSON.parse(child.stdout.trim()).checks);
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_HYBRID_SEARCH_PASSED',checks,checkCount:checks.length,
    separateProcesses:2,syntheticCostsAndScores:true,realAcceptedContributions:0,realEarnedCredits:0,
    providerCalls:0,cloudResourcesAccessed:false,githubActionsRun:false,productionQualified:false}));
}else{
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(runtime)).href);
  const options={modules:true,scriptPath:resolve(bundle),modulesRoot:dirname(resolve(bundle)),
    compatibilityDate:'2026-09-19',compatibilityFlags:['nodejs_compat'],d1Databases:{DB:'00000000-0000-4000-8000-000000000913'},
    ratelimits:localRateLimits(),bindings:{RATE_LIMITS_REQUIRED:'1',SEARCH_DELIVERY:'queued-v1',SEARCH_AGENT_SECRET:'f'.repeat(64),
      SEARCH_CLOUD_AGENT_SECRET:'9'.repeat(64),SEARCH_POLICY_ID:'offline-fixture',SEARCH_RUNTIME_SHA256:'d'.repeat(64),
      SEARCH_SNAPSHOT_SHA256:'e'.repeat(64),SEARCH_COST_UNITS:'100',SEARCH_HYBRID_POLICY:JSON.stringify({version:1,limitCents:6,
        openingCents:0,sceneCents:6,objectCents:8,cloudGraceSeconds:30,maxExecutionSeconds:120})},
    serviceBindings:{ASSETS:()=>new Response('local fixture'),SEARCH_ENGINE:()=>{throw Error('native execution forbidden in fixture');}},
    ...(convertV4MiniflareOptions?{resourcePersistencePath:resolve(persistence)}:{d1Persist:resolve(persistence,'d1')})};
  const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options),checks=[];
  const hash=v=>createHash('sha256').update(v).digest('hex'),account='a'.repeat(32),user='synthetic-hybrid-user';
  const call=(path,credential,body)=>mf.dispatchFetch('https://community.test/api/'+path,{
    method:body===undefined?'GET':'POST',headers:{authorization:'Bearer '+credential,'content-type':'application/json'},
    ...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(15000)});
  const claim=async executor=>{const response=await call(`search-${executor==='cloud'?'cloud-agent':'agent'}/claim`,
    executor==='cloud'?'9'.repeat(64):'f'.repeat(64),{lanes:['scene']});assert.equal(response.status,200);return response.json();};
  const result=job=>{const {query,...head}=JSON.parse(job.requestJson);return {...head,processedLocations:1,
    hits:[{locationId:1,outputSha256:'c'.repeat(64),sourceIndex:0,score:.8,viewOffset:1}]};};
  const complete=job=>call('search-agent/complete','f'.repeat(64),{jobId:job.jobId,claimToken:job.claimToken,result:result(job)});
  try{
    const db=await mf.getD1Database('DB');
    if(phase==='seed'){
      await prepareDatabase(db);
      const schema=new DatabaseSync(':memory:');
      try{
        schema.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));
        schema.exec(readFileSync(new URL('../search-queue.sql',import.meta.url),'utf8'));
        const definitions=schema.prepare(`SELECT sql FROM sqlite_master WHERE name LIKE 'search_jobs%' OR name='search_queue_revision'
          ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END`).all();
        await db.batch([...definitions.map(row=>db.prepare(row.sql)),
          db.prepare("INSERT INTO search_queue_revision VALUES(1,1,'vision-search-queue-v1-20261012')")]);
      }finally{schema.close();}
      await prepareSearchHybrid(db);
      await db.batch([
        db.prepare('INSERT INTO accounts(id,token_hash,units) VALUES(?,?,500)').bind(account,hash(user)),
        db.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES(?,500,'contribution','synthetic-hybrid')").bind(account),
        db.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,lat,lon,heading,country,camera_generation)
          VALUES(1,'abcdefghijklmnopqrstuv','2026-01','scene','scene-model','published','synthetic-contributor',10,20,90,'Italy','gen4')`),
        db.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_key) VALUES(1,'',?,0,'four-view-v4/synthetic.i8')").bind('c'.repeat(64)),
        db.prepare('CREATE TABLE hybrid_fixture(first_job TEXT NOT NULL,paid_key TEXT NOT NULL,paid_result TEXT)'),
      ]);
      const at=Math.floor(Date.now()/1000),key=name=>`q1.${at}.${hash(name).slice(0,32)}`;
      const submit=async name=>{const response=await call('searches',user,{accountId:account,prompt:'red door',resultCount:20,
        idempotencyKey:key(name),maxCostUnits:100});assert.equal(response.status,202);return response.json();};
      await submit('cloud');const claims=await Promise.all(Array.from({length:12},()=>claim('cloud')));
      const jobs=claims.filter(r=>r.job);assert.equal(jobs.length,1);const cloud=jobs[0].job;
      assert.equal(cloud.reservedCents,6);checks.push('concurrent-D1-cloud-reservation-and-claim');
      assert.equal((await claim('local')).job,null);checks.push('uncertain-cloud-not-disclosed-locally');
      await submit('local');assert.equal((await claim('cloud')).job,null);
      const local=(await claim('local')).job;assert.ok(local);assert.notEqual(local.jobId,cloud.jobId);
      checks.push('exhausted-shared-budget-local-overflow');
      assert.equal((await complete(local)).status,200);assert.equal((await complete(local)).status,200);
      const paid=await call('searches/recover?idempotencyKey='+key('local'),user);assert.equal(paid.status,200);
      await db.prepare('INSERT INTO hybrid_fixture VALUES (?,?,?)').bind(JSON.stringify(cloud),key('local'),JSON.stringify(await paid.json())).run();
      assert.equal((await db.prepare("SELECT count(*) n FROM ledger WHERE reason='search'").first()).n,1);
      checks.push('local-once-only-settlement-and-paid-recovery');
    }else{
      const saved=await db.prepare('SELECT * FROM hybrid_fixture').first(),cloud=JSON.parse(saved.first_job);
      assert.equal((await claim('local')).job,null);assert.equal((await claim('cloud')).job,null);
      checks.push('separate-process-retained-cost-and-uncertain-claim');
      const stopped=await call('search-cloud-agent/stopped','9'.repeat(64),{jobId:cloud.jobId,claimToken:cloud.claimToken,shutdownReceiptSha256:'7'.repeat(64)});
      assert.equal(stopped.status,200);const local=(await claim('local')).job;
      assert.equal(local.jobId,cloud.jobId);assert.equal(local.requestJson,cloud.requestJson);assert.notEqual(local.claimToken,cloud.claimToken);
      checks.push('stopped-cloud-same-request-local-recovery');
      const stale=await call('search-cloud-agent/complete','9'.repeat(64),{jobId:cloud.jobId,claimToken:cloud.claimToken,result:result(cloud)});
      assert.equal(stale.status,409);checks.push('stale-cloud-completion-fenced');
      assert.equal((await complete(local)).status,200);assert.equal((await complete(local)).status,200);
      assert.equal((await db.prepare("SELECT count(*) n FROM ledger WHERE reason='search'").first()).n,2);
      assert.equal((await db.prepare('SELECT units FROM accounts WHERE id=?').bind(account).first()).units,300);
      const budget=JSON.parse((await db.prepare('SELECT document FROM search_cloud_budget').first()).document);
      assert.equal(budget.monthly.reservedCents,6);assert.equal(budget.rolling.reservations.length,1);
      const paid=await call('searches/recover?idempotencyKey='+saved.paid_key,user);assert.equal(paid.status,200);
      assert.deepEqual(await paid.json(),JSON.parse(saved.paid_result));checks.push('persistent-paid-replay-and-no-cost-refund');
    }
    console.log(JSON.stringify({phase,checks}));
  }finally{await mf.dispose();}
}
