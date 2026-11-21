// Restart across four fresh workerd processes with actual persisted D1/R2.
import assert from 'node:assert/strict';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectAuditCancellation} from './prepare-object-audit-cancellation.mjs';
const [mfPath,persistence,phase]=process.argv.slice(2),script=fileURLToPath(import.meta.url);
if(!phase){
  let cases=0;
  for(const stage of ['cancel','partial','finish','replay']){
    const child=spawnSync(process.execPath,[script,mfPath,persistence,stage],{env:process.env,windowsHide:true,timeout:90000,encoding:'utf8'});
    assert.equal(child.status,0,child.stderr||child.stdout);cases+=JSON.parse(child.stdout.trim()).cases;
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OBJECT_CANCELLATION_PASSED',cases,separateProcesses:4,
    syntheticInference:true,nativeInferences:0,earnedCredits:0,liveCalls:0}));
}else{
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(mfPath)).href);
  const root=dirname(dirname(script)),paths=['tools/object-cancellation.fixture.mjs','src/objectAuditCancellation.js','src/objectAuditDispatch.js',
    'src/artifactWrites.js','src/objectAuditPrivacy.js','src/scenePipeline.js','src/sceneQuality.js',
    'native-object-verifier-bridge/worker.js','src/objectCoverage.js','src/model.js'];
  const options={modules:paths.map(path=>({type:'ESModule',path:resolve(root,path)})),modulesRoot:root,compatibilityDate:'2026-09-19',
    d1Databases:{DB:'00000000-0000-4000-8000-000000000324'},r2Buckets:['INDEX'],resourcePersistencePath:resolve(persistence)};
  const mf=new Miniflare(convertV4MiniflareOptions(options));let cases=0;
  try{
    const db=await mf.getD1Database('DB'),account='a'.repeat(32),lease='b'.repeat(32);
    if(phase==='cancel'){
      await prepareDatabase(db);await prepareObjectAuditCancellation(db);
      await db.batch([
        db.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-session',10)").bind(account),
        db.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES (?,?,'object',101000,'active')").bind(lease,account),
        db.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (1,'synthetic','fixture','object','synthetic','leased',?,'gen4')").bind(lease),
        db.prepare('INSERT INTO lease_items VALUES (?,1)').bind(lease),
        db.prepare("INSERT INTO object_coverage VALUES (1,'official-gen4-historical-v2-exact-pano',?,100000)").bind('f'.repeat(64)),
        db.prepare('CREATE TABLE synthetic_native(starts INTEGER,erasures INTEGER,finish INTEGER)'),
        db.prepare('INSERT INTO synthetic_native VALUES (0,0,0)'),
      ]);
    }
    const call=async path=>{
      const response=await mf.dispatchFetch('https://community.test'+path,{signal:AbortSignal.timeout(15000)});
      assert.equal(response.status,200,path+' '+(response.status===200?'':await response.text()));
      const value=await response.json();assert.equal(value.nativeInferences,0);assert.equal(value.liveCalls,0);
      assert.equal(value.ledgerEntries,0);assert.ok(value.publications===0 || value.publications===1);
      if(value.publications===1)assert.equal(value.otherBundlePreserved,true);
      assert.equal(value.owner.units,10);assert.equal(value.owner.deleted_at,null);cases++;return value;
    };
    if(phase==='cancel'){
      await call('/stage');const start=await call('/start');assert.equal(start.native.starts,1);assert.equal(start.candidate.job_id,null);
      const result=await call('/cancel');assert.equal(result.candidate.state,'cancelled');assert.equal(result.cancellation.prior_job_id,null);
      assert.equal(result.cancellation.prior_failures,1);assert.equal(result.native.erasures,0);assert.equal(result.lease.state,'expired');
      assert.equal(result.location.active_lease,null);assert.equal(result.location.queue_state,'pending');
    }else if(phase==='partial'){
      const before=await call('/state');assert.equal(before.cancellation.state,'pending');assert.equal(before.native.erasures,0);
      const reassigned=await call('/reassigned');assert.equal(reassigned.publications,1);assert.equal(reassigned.otherBundlePreserved,true);
      const result=await call('/partial');assert.equal(result.value.cleanupPending,true);assert.equal(result.artifactFence,true);
      assert.equal(result.cancellation.r2_fenced_at,100002);assert.equal(result.cancellation.native_erased_at,null);assert.equal(result.native.erasures,1);
    }else if(phase==='finish'){
      const before=await call('/state');assert.equal(before.artifactFence,true);assert.equal(before.cancellation.state,'pending');
      const result=await call('/finish');assert.equal(result.value.cleanupState,'erased');assert.equal(result.native.erasures,2);
      assert.equal(result.cancellation.r2_fenced_at,100002);assert.equal(result.cancellation.native_erased_at,100032);
    }else{
      const before=await call('/state');assert.equal(before.cancellation.state,'erased');assert.equal(before.artifactFence,true);
      const result=await call('/replay');assert.deepEqual(result.cancellation,before.cancellation);assert.deepEqual(result.native,before.native);
      const late=await call('/late');assert.equal(late.value.cancelled,true);assert.deepEqual(late.native,before.native);
    }
    console.log(JSON.stringify({phase,cases}));
  }finally{await mf.dispose();}
}
