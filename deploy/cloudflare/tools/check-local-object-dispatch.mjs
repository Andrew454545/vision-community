// Four fresh workerd processes: lost acknowledgement, recovered job, deletion,
// and late-reply replay. Real local D1/R2; no actual native inference or credit.
import assert from 'node:assert/strict';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectAuditDispatch} from './prepare-object-audit-dispatch.mjs';
const [mfPath,persistence,phase]=process.argv.slice(2),script=fileURLToPath(import.meta.url);
if(!phase) {
  let cases=0;
  for(const stage of ['seed','recover','delete','replay']) {
    const child=spawnSync(process.execPath,[script,mfPath,persistence,stage],{
      env:process.env,windowsHide:true,timeout:90000,encoding:'utf8'});
    assert.equal(child.status,0,child.stderr||child.stdout);cases+=JSON.parse(child.stdout.trim()).cases;
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OBJECT_DISPATCH_RECOVERY_PASSED',cases,
    separateProcesses:4,syntheticInference:true,objectAdmissionReady:false,nativeInferences:0,earnedCredits:0,liveCalls:0}));
} else {
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(mfPath)).href);
  const root=dirname(dirname(script)),paths=['tools/object-dispatch.fixture.mjs','src/objectAuditDispatch.js',
    'src/accountPrivacy.js','src/artifactWrites.js','src/objectAuditPrivacy.js','src/scenePipeline.js','src/sceneQuality.js',
    'native-object-verifier-bridge/worker.js','src/objectAdmission.js','src/objectIndex.js','src/objectFeatures.js','src/objectCoverage.js','src/model.js'];
  const options={modules:paths.map(path=>({type:'ESModule',path:resolve(root,path)})),modulesRoot:root,
    compatibilityDate:'2026-09-19',d1Databases:{DB:'00000000-0000-4000-8000-000000000322'},r2Buckets:['INDEX'],
    ...(convertV4MiniflareOptions?{resourcePersistencePath:resolve(persistence)}:{d1Persist:resolve(persistence,'d1'),r2Persist:resolve(persistence,'r2')})};
  const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);let cases=0;
  try {
    const db=await mf.getD1Database('DB'),account='a'.repeat(32),lease='b'.repeat(32);
    if(phase==='seed') {
      await prepareDatabase(db);await prepareObjectAuditDispatch(db);
      await db.batch([
        db.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-session',10)").bind(account),
        db.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES (?,?,'object',101000,'active')").bind(lease,account),
        db.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (1,'synthetic','fixture','object','synthetic','leased',?,'gen4')").bind(lease),
        db.prepare('INSERT INTO lease_items VALUES (?,1)').bind(lease),
        db.prepare("INSERT INTO object_coverage VALUES (1,'official-gen4-historical-v2-exact-pano',?,100000)").bind('f'.repeat(64)),
        db.prepare('CREATE TABLE synthetic_native_jobs(id TEXT PRIMARY KEY,fingerprint TEXT,posts INTEGER,gets INTEGER,erased INTEGER)'),
      ]);
    }
    const call=async path=>{
      const response=await mf.dispatchFetch('https://community.test'+path,{signal:AbortSignal.timeout(15000)});
      assert.equal(response.status,200,path+' '+(response.status===200?'':await response.text()));
      const value=await response.json();assert.equal(value.objectAdmissionReady,false);assert.equal(value.nativeInferences,0);
      assert.equal(value.earnedCredits,0);assert.equal(value.publications,0);cases++;return value;
    };
    if(phase==='seed') {
      const staged=await call('/stage');assert.equal(staged.value.pending,1);assert.equal(staged.candidate.job_id,null);
      assert.equal(staged.location.queue_state,'quarantined');assert.equal(staged.owner.units,10);
      const started=await call('/start');assert.equal(started.candidate.job_id,null);assert.equal(started.native.posts,1);
      assert.equal(started.candidate.transport_failures,1);assert.equal(started.candidate.next_attempt,100030);
    } else if(phase==='recover') {
      const before=await call('/state');assert.equal(before.native.posts,1);assert.equal(before.candidate.job_id,null);
      const recovered=await call('/recover');assert.equal(recovered.native.posts,2);assert.equal(recovered.value.freshAuditReply,true);
      assert.equal(recovered.candidate.native_state,'approved');assert.equal(recovered.value.accepted,0);assert.equal(recovered.owner.units,10);
    } else if(phase==='delete') {
      const observed=await call('/observe');assert.equal(observed.native.posts,2);assert.equal(observed.native.gets,1);
      assert.equal(observed.value.freshAuditReply,true);
      const deleted=await call('/delete');assert.equal(deleted.candidate.state,'cancelled');assert.equal(deleted.candidate.receipt_sha256,null);
      assert.equal(deleted.owner.units,0);assert.equal(deleted.location.active_lease,null);
      const cleanup=await call('/cleanup');assert.equal(cleanup.artifactFence,true);assert.equal(cleanup.native.erased,1);
    } else {
      const before=await call('/state');assert.equal(before.artifactFence,true);assert.equal(before.candidate.state,'cancelled');
      const late=await call('/late');assert.deepEqual(late.value,{error:'account_not_active',status:401});
      assert.equal(late.native.posts,2);assert.equal(late.native.gets,1);
      const cleaned=await call('/cleanup');assert.equal(cleaned.artifactFence,true);assert.equal(cleaned.native.erased,1);
    }
    console.log(JSON.stringify({phase,cases}));
  } finally {await mf.dispose();}
}
