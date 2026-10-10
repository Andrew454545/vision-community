// Real local workerd/D1, including separate-process restart. No cloud resources.
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
    const result=JSON.parse(child.stdout.trim());
    cases+=result.cases;
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OBJECT_ASSIGNMENT_PRIVACY_PASSED',cases,
    separateProcesses:3,syntheticNativeProvider:true,objectAdmissionReady:false,nativeInferences:0,liveCalls:0}));
} else {
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(mfPath)).href);
  const root=dirname(dirname(script));
  const paths=['tools/object-audit-privacy.fixture.mjs','src/accountPrivacy.js','src/artifactWrites.js',
    'src/objectAuditPrivacy.js','src/scenePipeline.js','src/sceneQuality.js','native-object-verifier-bridge/worker.js',
    'src/objectAdmission.js','src/objectIndex.js','src/objectFeatures.js','src/model.js'];
  const options={modules:paths.map(path=>({type:'ESModule',path:resolve(root,path)})),modulesRoot:root,
    compatibilityDate:'2026-09-19',d1Databases:{DB:'00000000-0000-4000-8000-000000000123'},r2Buckets:['INDEX'],
    ...(convertV4MiniflareOptions ? {resourcePersistencePath:resolve(persistence)}
      : {d1Persist:resolve(persistence,'d1'),r2Persist:resolve(persistence,'r2')})};
  const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
  let cases=0;
  try {
    const db=await mf.getD1Database('DB'),account='a'.repeat(32),other='d'.repeat(32),lease='1'.repeat(32);
    if(phase==='seed') {
      await prepareDatabase(db);
      await db.batch([
        db.prepare('INSERT INTO accounts(id,token_hash,recovery_hash,units) VALUES (?,?,?,20)').bind(account,'synthetic-token','synthetic-recovery'),
        db.prepare('INSERT INTO accounts(id,token_hash,units) VALUES (?,?,30)').bind(other,'synthetic-other'),
        db.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES (?,?,'object',9999,'active')").bind(lease,account),
        db.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES (?,20,'verified_work','synthetic-only')").bind(account),
      ]);
    }
    const call=async(path,state,calls)=>{
      const response=await mf.dispatchFetch('https://community.test'+path,{signal:AbortSignal.timeout(10000)});
      assert.equal(response.status,200,response.status===200?path:path+' '+await response.text());
      const result=await response.json();
      assert.equal(result.calls,calls,path);assert.equal(result.cleanup.state,state,path);
      assert.deepEqual(result.owner,{units:0,deleted_at:1234,recovery_hash:null});
      assert.deepEqual(result.other,{units:30,deleted_at:null});
      assert.equal(result.deletedLedgerRows,1);assert.equal(result.objectAdmissionReady,false);
      assert.equal(result.nativeInferences,0);cases++;
    };
    if(phase==='seed') {
      await call('/delete','pending',0);
      await call('/cleanup/missing','pending',0);
      await call('/cleanup/outage','pending',1);
      await call('/cleanup/wrong-id','pending',1);
      await call('/cleanup/erasing','pending',1);
    } else if(phase==='recover') {
      await call('/cleanup/erasing','pending',1);
      await call('/cleanup/erased','erased',1);
      await call('/cleanup/erased','erased',0);
    } else {
      await call('/delete','erased',0);
      await call('/cleanup/erased','erased',0);
      await assert.rejects(db.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES (?,?,'object',9999,'active')")
        .bind('2'.repeat(32),account).run(),/account_not_active/);cases++;
      await assert.rejects(db.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES (?,1,'verified_work','late-object')")
        .bind(account).run(),/account_not_active/);cases++;
    }
    assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM account_cleanup').first()).n,1);cases++;
    console.log(JSON.stringify({phase,cases}));
  } finally {await mf.dispose();}
}
