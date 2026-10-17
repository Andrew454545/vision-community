// Three fresh local workerd processes; synthetic sample evidence only.
// Does not access Cloudflare, execute native inference or start contributor jobs.
import assert from 'node:assert/strict';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectQualification} from './prepare-object-qualification.mjs';
import {localRateLimits} from './local-api-bindings.mjs';
import {policy,evidence} from './fixtures/object-qualification-proof.mjs';
const [runtime,bundle,persistence,phase]=process.argv.slice(2);
const path=resolve(persistence,'policy.json');
if(!phase) {
  mkdirSync(resolve(persistence),{recursive:true});writeFileSync(path,JSON.stringify(policy()),{flag:'wx'});
  let checks=0;
  for(const step of ['seed','recover','deleted']) {
    const child=spawnSync(process.execPath,[fileURLToPath(import.meta.url),runtime,bundle,persistence,step],{
      env:process.env,windowsHide:true,timeout:90000,encoding:'utf8'});
    assert.equal(child.status,0,child.stderr||child.stdout);checks+=JSON.parse(child.stdout.trim()).checks;
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OBJECT_QUALIFICATION_PASSED',checks,separateProcesses:3,
    syntheticNumericalAndRuntimeEvidence:true,realMacExecution:false,nativeInference:false,liveCalls:0,
    realQualifiedAccounts:0,realContributions:0,realCredits:0,publicObjectAdmission:false}));
} else {
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(runtime)).href);
  const p=JSON.parse(readFileSync(path,'utf8')),profile='c'.repeat(64),account='a'.repeat(32),token='synthetic-private-token';
  let comparisons=0,checks=0;
  const options={modules:true,scriptPath:resolve(bundle),modulesRoot:dirname(resolve(bundle)),compatibilityDate:'2026-09-19',
    compatibilityFlags:['nodejs_compat'],d1Databases:{DB:'00000000-0000-4000-8000-000000001013'},r2Buckets:['INDEX'],
    bindings:{DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',RATE_LIMITS_REQUIRED:'1',
      OBJECT_QUALIFICATION_MODE:'saved-sample-v1',OBJECT_QUALIFICATION_POLICY:JSON.stringify(p)},ratelimits:localRateLimits(),
    serviceBindings:{ASSETS:()=>new Response('local fixture'),OBJECT_QUALIFIER:async request=>{
      comparisons++;const q=await request.json();await new Promise(resolve=>setTimeout(resolve,25));
      return Response.json(evidence(q,p,true,Math.floor(Date.now()/1000)));}},
    ...(convertV4MiniflareOptions?{resourcePersistencePath:resolve(persistence)}:{d1Persist:resolve(persistence,'d1'),r2Persist:resolve(persistence,'r2')})};
  const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
  const body=n=>({requestId:n.toString(16).padStart(32,'0'),profileId:profile,artifactSetSha256:'e'.repeat(64)});
  const call=(path,data,auth=token)=>mf.dispatchFetch('https://community.test/api/'+path,{
    method:data===undefined?'GET':'POST',headers:{'content-type':'application/json',...(auth?{authorization:'Bearer '+auth}:{})},
    ...(data===undefined?{}:{body:JSON.stringify(data)}),signal:AbortSignal.timeout(15000)});
  const parsed=async(response,status=200)=>{assert.equal(response.status,status,await response.clone().text());return response.json();};
  try {
    const db=await mf.getD1Database('DB');
    if(phase==='seed') {
      await prepareDatabase(db);await prepareObjectQualification(db);
      await db.prepare('INSERT INTO accounts(id,token_hash,units) VALUES (?,?,0)')
        .bind(account,createHash('sha256').update(token).digest('hex')).run();
      await parsed(await call('object-qualifications',body(1),null),401);checks++;
      const first=await parsed(await call('object-qualifications',body(1)));
      assert.equal(first.qualified,true);assert.equal(comparisons,1);checks++;
      const concurrent=await Promise.all(Array.from({length:4},()=>call('object-qualifications',body(2))));
      assert(concurrent.every(r=>[200,409].includes(r.status)));assert(concurrent.some(r=>r.status===200));
      assert.equal(comparisons,2);checks++;
      await parsed(await call('object-qualifications/revoke',{operationId:'f'.repeat(32),profileId:profile}));
      assert.equal((await parsed(await call('object-qualifications?profileId='+profile))).qualified,false);checks++;
    } else if(phase==='recover') {
      assert.equal((await parsed(await call('object-qualifications?profileId='+profile))).qualified,false);checks++;
      const old=await parsed(await call('object-qualifications',body(1)));
      assert.equal(old.qualified,false);assert.equal(old.replayed,true);assert.equal(comparisons,0);checks++;
      assert.equal((await parsed(await call('object-qualifications',body(3)))).qualified,true);
      await parsed(await call('object-qualifications/revoke',{operationId:'f'.repeat(32),profileId:profile}));
      assert.equal((await parsed(await call('object-qualifications?profileId='+profile))).qualified,true);checks++;
      await parsed(await call('account/delete',{accountId:account,confirmation:'DELETE',idempotencyKey:'9'.repeat(64)}));checks++;
    } else {
      await parsed(await call('object-qualifications?profileId='+profile),401);
      await parsed(await call('object-qualifications',body(3)),401);assert.equal(comparisons,0);checks++;
      assert.equal((await db.prepare('SELECT COUNT(*) n FROM object_qualification_requests').first()).n,3);checks++;
    }
    for(const table of ['published_index','leases'])assert.equal((await db.prepare(`SELECT COUNT(*) n FROM ${table}`).first()).n,0);
    const ledger=(await db.prepare('SELECT units,reason FROM ledger').all()).results;
    assert.deepEqual(ledger,phase==='seed'?[]:[{units:0,reason:'account_deleted'}]);
    const capabilities=await parsed(await call('capabilities'));
    assert.equal(capabilities.objectContributions.ready,false);checks++;
    console.log(JSON.stringify({phase,checks,syntheticComparisons:comparisons}));
  } finally {await mf.dispose();}
}
