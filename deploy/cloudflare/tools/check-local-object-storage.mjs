// Actual offline workerd, D1 and R2 over three distinct processes.
import assert from 'node:assert/strict';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {prepareDatabase} from './initialize-schema.mjs';
const [mfPath,persistence,phase]=process.argv.slice(2),script=fileURLToPath(import.meta.url);
if(!phase) {
  let cases=0;
  for(const stage of ['seed','recover','replay']) {
    const child=spawnSync(process.execPath,[script,mfPath,persistence,stage],{
      env:process.env,windowsHide:true,timeout:90000,encoding:'utf8'});
    assert.equal(child.status,0,child.stderr||child.stdout);
    cases+=JSON.parse(child.stdout.trim()).cases;
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OBJECT_STORAGE_RECOVERY_PASSED',cases,
    separateProcesses:3,syntheticInputs:true,objectAdmissionReady:false,nativeInferences:0,earnedCredits:0,liveCalls:0}));
} else {
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(mfPath)).href);
  const root=dirname(dirname(script));
  const paths=['tools/object-storage.fixture.mjs','src/accountPrivacy.js','src/artifactWrites.js',
    'src/objectAuditPrivacy.js','src/scenePipeline.js','src/sceneQuality.js','native-object-verifier-bridge/worker.js',
    'src/objectAdmission.js','src/objectIndex.js','src/objectFeatures.js','src/model.js'];
  const options={modules:paths.map(path=>({type:'ESModule',path:resolve(root,path)})),modulesRoot:root,
    compatibilityDate:'2026-09-19',d1Databases:{DB:'00000000-0000-4000-8000-000000000321'},r2Buckets:['INDEX'],
    ...(convertV4MiniflareOptions ? {resourcePersistencePath:resolve(persistence)}
      : {d1Persist:resolve(persistence,'d1'),r2Persist:resolve(persistence,'r2')})};
  const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
  let cases=0;
  try {
    const db=await mf.getD1Database('DB'),account='a'.repeat(32),lease='d'.repeat(32),pub='e'.repeat(32);
    if(phase==='seed') {
      await prepareDatabase(db);
      await db.batch([
        db.prepare('INSERT INTO accounts(id,token_hash,recovery_hash,units) VALUES (?,?,?,10)').bind(account,'synthetic-session','synthetic-recovery'),
        ...[lease,pub].map(id=>db.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES (?,?,'object',9999,'active')").bind(id,account)),
      ]);
    }
    const call=async path=>{
      const response=await mf.dispatchFetch('https://community.test'+path,{signal:AbortSignal.timeout(15000)});
      assert.equal(response.status,200,path+' '+(response.status===200?'':await response.text()));
      const value=await response.json();
      assert.equal(value.objectAdmissionReady,false);assert.equal(value.nativeInferences,0);assert.equal(value.earnedCredits,0);
      cases++;
      return value;
    };
    const inspect=(value,fenced)=>{
      assert.equal(value.intents,6);assert.equal(value.publications,1);assert.equal(value.deletionDebits,1);
      assert.deepEqual(value.owner,{units:0,deleted_at:1234,recovery_hash:null});
      for(let i=0;i<6;i++) {
        const object=value.objects[i];assert.ok(object);
        assert.equal(object.fence,i<3&&fenced);
        assert.equal(object.sha256,i<3&&fenced?value.fenceSha256:i===2||i===5?value.emptySha256:value.privateSha256);
      }
      assert.equal(value.cleanup.length,5);
      assert.equal(value.cleanup.filter(x=>x.state===(fenced?'fenced':'pending')&&x.artifact_key.startsWith('object-')&&!x.artifact_key.startsWith('object-audit-jobs/')).length,3);
      assert.equal(value.cleanup.filter(x=>x.state===(fenced?'erased':'pending')&&x.artifact_key.startsWith('object-audit-jobs/')).length,2);
      cases++;
    };
    if(phase==='seed') {
      const staged=await call('/stage');assert.equal(staged.intents,6);assert.equal(staged.owner.units,10);
      await call('/stage'); // Exact create-only replay, including zero-byte lanes.
      await db.batch([
        db.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id) VALUES (1,'synthetic','fixture','object','fixture','published',?)").bind(account),
        db.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (1,'','synthetic',1,?)").bind(`object-index-v4/${pub}/`),
      ]);
      inspect(await call('/delete'),false);
    } else if(phase==='recover') {
      inspect(await call('/state'),false);
      inspect(await call('/cleanup'),true);
      inspect(await call('/cleanup'),true);
    } else {
      inspect(await call('/state'),true);
      const late=await call('/late');assert.equal(late.refused,true);inspect(late,true);
      inspect(await call('/delete'),true);inspect(await call('/cleanup'),true);
    }
    console.log(JSON.stringify({phase,cases}));
  } finally {await mf.dispose();}
}
