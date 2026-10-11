// Four fresh workerd processes; persisted recovery intents, real local D1/R2.
import assert from 'node:assert/strict';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectAuditRecovery} from './prepare-object-audit-recovery.mjs';
const [mfPath,persistence,phase]=process.argv.slice(2),script=fileURLToPath(import.meta.url);
if(!phase){
  let cases=0;
  for(const stage of ['seed','recover','delete','replay']){
    const child=spawnSync(process.execPath,[script,mfPath,persistence,stage],{env:process.env,windowsHide:true,timeout:90000,encoding:'utf8'});
    assert.equal(child.status,0,child.stderr||child.stdout);cases+=JSON.parse(child.stdout.trim()).cases;
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OBJECT_RECOVERY_PASSED',cases,separateProcesses:4,
    syntheticInference:true,nativeInferences:0,earnedCredits:0,liveCalls:0}));
}else{
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(mfPath)).href);
  const root=dirname(dirname(script)),paths=['tools/object-recovery.fixture.mjs','src/objectAuditRecovery.js','src/objectAuditDispatch.js',
    'src/accountPrivacy.js','src/artifactWrites.js','src/objectAuditPrivacy.js','src/scenePipeline.js','src/sceneQuality.js',
    'native-object-verifier-bridge/worker.js','src/objectCoverage.js','src/model.js'];
  const options={modules:paths.map(path=>({type:'ESModule',path:resolve(root,path)})),modulesRoot:root,compatibilityDate:'2026-09-19',
    d1Databases:{DB:'00000000-0000-4000-8000-000000000323'},r2Buckets:['INDEX'],resourcePersistencePath:resolve(persistence)};
  const mf=new Miniflare(convertV4MiniflareOptions(options));let cases=0;
  try{
    const db=await mf.getD1Database('DB'),account='a'.repeat(32),lease='b'.repeat(32);
    if(phase==='seed'){
      await prepareDatabase(db);await prepareObjectAuditRecovery(db);
      await db.batch([
        db.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-session',10)").bind(account),
        db.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES (?,?,'object',101000,'active')").bind(lease,account),
        db.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (1,'synthetic','fixture','object','synthetic','leased',?,'gen4')").bind(lease),
        db.prepare('INSERT INTO lease_items VALUES (?,1)').bind(lease),
        db.prepare("INSERT INTO object_coverage VALUES (1,'official-gen4-historical-v2-exact-pano',?,100000)").bind('f'.repeat(64)),
        db.prepare('CREATE TABLE synthetic_retry_intents(request_id TEXT PRIMARY KEY,fingerprint TEXT,posts INTEGER,erased INTEGER)'),
      ]);
    }
    const call=async path=>{
      const response=await mf.dispatchFetch('https://community.test'+path,{signal:AbortSignal.timeout(15000)});
      assert.equal(response.status,200,path+' '+(response.status===200?'':await response.text()));
      const value=await response.json();assert.equal(value.nativeInferences,0);assert.equal(value.earnedCredits,0);
      assert.equal(value.publications,0);cases++;return value;
    };
    if(phase==='seed'){
      assert.equal((await call('/stage')).candidate.job_id,null);
      const resumed=await call('/pause');assert.equal(resumed.value.recoveryState,'applied');assert.equal(resumed.history[0].prior_failures,8);
      assert.equal(resumed.history[0].prior_error,'object_audit_transport_unavailable');assert.equal(resumed.candidate.transport_failures,0);
      const lost=await call('/retry');assert.equal(lost.value.recoveryState,'pending');assert.equal(lost.native[0].posts,1);
      assert.equal(lost.history[1].transport_failures,1);assert.equal(lost.candidate.native_attempts,1);
    }else if(phase==='recover'){
      const before=await call('/state');assert.equal(before.history[1].state,'pending');assert.equal(before.native[0].posts,1);
      const retried=await call('/repeat');assert.equal(retried.value.recoveryState,'applied');assert.equal(retried.native[0].posts,2);
      assert.equal(retried.candidate.native_attempts,2);assert.equal(retried.candidate.native_state,'failed');
      const duplicate=await call('/repeat');assert.equal(duplicate.native[0].posts,2);assert.equal(duplicate.value.freshAuditReply,false);
      const next=await call('/next');assert.equal(next.candidate.native_attempts,3);assert.equal(next.candidate.native_state,'approved');
      assert.equal(next.native.length,2);assert.equal(next.native[1].posts,1);assert.equal(next.owner.units,10);
    }else if(phase==='delete'){
      const before=await call('/state');assert.equal(before.candidate.native_state,'approved');assert.equal(before.history.length,3);
      const deleted=await call('/delete');assert.equal(deleted.candidate.state,'cancelled');assert.equal(deleted.candidate.receipt_sha256,null);
      assert.equal(deleted.owner.units,0);assert.equal(deleted.location.active_lease,null);
      const clean=await call('/cleanup');assert.equal(clean.artifactFence,true);assert.ok(clean.native.every(row=>row.erased===1));
      assert.equal(clean.history[1].prior_receipt,'4'.repeat(64));
    }else{
      const state=await call('/state');assert.equal(state.artifactFence,true);assert.equal(state.history.length,3);
      const late=await call('/late');assert.deepEqual(late.value,{error:'account_not_active',status:401});
      assert.deepEqual(late.native,state.native);assert.deepEqual(late.history,state.history);
    }
    console.log(JSON.stringify({phase,cases}));
  }finally{await mf.dispose();}
}
