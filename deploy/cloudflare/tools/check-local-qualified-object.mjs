// Four finite fresh workerd processes, actual local D1/R2, synthetic authority only.
import assert from 'node:assert/strict';
import {readFileSync,mkdirSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {prepareQualifiedObject} from './prepare-qualified-object.mjs';
const [runtime,bundle,persistence,phase,mode='publication']=process.argv.slice(2);
const root=resolve(persistence),fixturePath=resolve(root,'prepared.sqlite.json');
if(!phase||phase==='all') {
  mkdirSync(root,{recursive:true});
  const seed=spawnSync(process.execPath,[fileURLToPath(new URL('./fixtures/export-qualified-object.mjs',import.meta.url)),
    resolve(root,'prepared.sqlite'),mode==='work'?'work-prepared':'prepared'],{windowsHide:true,timeout:30000,encoding:'utf8',env:process.env});
  assert.equal(seed.status,0,seed.stderr);
  let checks=0;
  for(const step of ['stage','publish','replay-delete','deleted']){
    const child=spawnSync(process.execPath,[fileURLToPath(import.meta.url),runtime,bundle,root,step,mode],{
      windowsHide:true,timeout:45000,encoding:'utf8',env:process.env});
    assert.equal(child.status,0,child.stderr||child.stdout);checks+=JSON.parse(child.stdout.trim()).checks;
  }
  console.log(JSON.stringify({status:mode==='work'?'ACTUAL_WORKERD_PREPARED_OBJECT_WORK_PASSED':'ACTUAL_WORKERD_QUALIFIED_OBJECT_PASSED',checks,separateProcesses:4,
    syntheticAuthorityAndInference:true,nativeInference:false,realQualifiedAccounts:0,realContributions:0,realCredits:0,
    liveCalls:0,publicObjectAdmission:false}));
}else{
  const f=JSON.parse(readFileSync(fixturePath,'utf8')),account='b'.repeat(32),lease=f.authority.leaseId;
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(runtime)).href);
  let protectionCalls=0,checks=0,failPreparation=mode==='work'&&phase==='stage';
  const options={modules:true,scriptPath:resolve(bundle),modulesRoot:dirname(resolve(bundle)),compatibilityDate:'2026-09-19',
    compatibilityFlags:['nodejs_compat'],d1Databases:{DB:'00000000-0000-4000-8000-000000001014'},r2Buckets:['INDEX'],
    bindings:{DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',
      OBJECT_QUALIFICATION_MODE:'saved-sample-v1',OBJECT_QUALIFICATION_POLICY:f.qualificationPolicy,
      OBJECT_QUALIFIED_UPLOAD_MODE:'qualified-device-v1',OBJECT_ELIGIBILITY_POLICY:f.eligibilityPolicy,
      OBJECT_ELIGIBILITY_POLICY_SHA256:f.eligibilitySha256},
    serviceBindings:{OBJECT_ELIGIBILITY:async request=>{protectionCalls++;const now=Math.floor(Date.now()/1000);
      if(failPreparation){failPreparation=false;return new Response(null,{status:503});}
      return Response.json({...f.proof,...await request.json(),issuedAt:now,expiresAt:now+30});}},
    ...(convertV4MiniflareOptions?{resourcePersistencePath:root}:{d1Persist:resolve(root,'d1'),r2Persist:resolve(root,'r2')})};
  const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
  const call=async(action,extra={},expected=200)=>{
    const r=await mf.dispatchFetch('https://community.test/'+action,{method:'POST',headers:{authorization:'Bearer synthetic-local-only',
      'content-type':'application/json'},body:JSON.stringify({account,lease,...extra}),signal:AbortSignal.timeout(25000)});
    assert.equal(r.status,expected,await r.clone().text());return r.json();};
  try {
    const db=await mf.getD1Database('DB');
    if(phase==='stage'){
      // Import closed synthetic seed before installing its exact preserved fences.
      for(const item of f.schema.filter(r=>r.type==='table'))await db.prepare(item.sql).run();
      for(const table of f.tables)for(const row of table.rows){
        const names=Object.keys(row);assert(/^[a-z_][a-z_0-9]*$/.test(table.name)&&names.every(n=>/^[a-z_][a-z_0-9]*$/.test(n)));
        await db.prepare(`INSERT INTO ${table.name}(${names.join(',')}) VALUES (${names.map(()=>'?').join(',')})`).bind(...Object.values(row)).run();
      }
      for(const item of f.schema.filter(r=>r.type!=='table'))await db.prepare(item.sql).run();
      await prepareQualifiedObject(db);checks++;
      if(mode==='work'){
        await call('work',{input:f.workBody},503);
        assert.equal((await db.prepare('SELECT state FROM object_work_requests').first()).state,'preparing');checks++;
        const work=await call('work',{input:f.workBody});assert.equal(work.leaseId,lease);assert.equal(work.unitsEarned,0);checks++;
        const calls=protectionCalls;assert.deepEqual(await call('work',{input:f.workBody}),work);assert.equal(protectionCalls,calls);checks++;
      }
      const result=await call('stage',{authority:f.authority,index:f.index});assert.equal(result.pending,true);assert.equal(result.unitsEarned,0);checks++;
      assert.equal((await db.prepare('SELECT COUNT(*) n FROM qualified_object_candidates').first()).n,1);
      assert.equal((await db.prepare('SELECT COUNT(*) n FROM ledger').first()).n,0);checks++;
    }else if(phase==='publish'){
      if(mode==='work'){assert.equal((await call('work',{input:f.workBody})).alreadySubmitted,true);checks++;}
      const result=await call('settle');assert.equal(result.accepted,2);assert.equal(result.unitsEarned,20);
      assert.equal(result.independentlyRecomputed,false);checks++;
      assert.equal((await db.prepare('SELECT COUNT(*) n FROM qualified_object_acceptances').first()).n,1);
      assert.equal((await db.prepare("SELECT COUNT(*) n FROM published_index WHERE object_index_key IS NOT NULL").first()).n,2);checks++;
      assert.equal((await db.prepare('SELECT units FROM accounts WHERE id=?').bind(account).first()).units,20);checks++;
    }else if(phase==='replay-delete'){
      if(mode==='work'){assert.equal((await call('work',{input:f.workBody})).alreadySubmitted,true);checks++;}
      const r=await call('settle');assert.equal(r.replayed,true);assert.equal(r.unitsEarned,0);assert.equal(protectionCalls,0);checks++;
      await call('delete',{deletion:{accountId:account,idempotencyKey:'8'.repeat(64),confirmation:'DELETE'}});
      assert.equal((await db.prepare('SELECT units FROM accounts WHERE id=?').bind(account).first()).units,0);checks++;
      assert.equal((await db.prepare('SELECT COUNT(*) n FROM qualified_object_acceptances').first()).n,1);checks++;
    }else{
      if(mode==='work'){await call('work',{input:f.workBody},401);checks++;}
      await call('settle',{},401);assert.equal(protectionCalls,0);checks++;
      const ledger=(await db.prepare('SELECT units,reason FROM ledger ORDER BY id').all()).results;
      assert.deepEqual(ledger,[{units:20,reason:'qualified_device_work'},{units:-20,reason:'account_deleted'}]);checks++;
      assert.equal((await db.prepare("SELECT COUNT(*) n FROM published_index WHERE object_index_key IS NOT NULL").first()).n,2);checks++;
    }
    assert.equal((await db.prepare('SELECT COUNT(*) n FROM object_audit_candidates').first()).n,0);
    assert.equal((await db.prepare('SELECT COUNT(*) n FROM object_dispatch_slots').first()).n,0);checks++;
    console.log(JSON.stringify({phase,checks,protectionCalls,synthetic:true}));
  }finally{await mf.dispose();}
}
