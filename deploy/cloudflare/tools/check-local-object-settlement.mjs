// Three real fresh local workerd processes; all inference/coverage is synthetic.
import assert from 'node:assert/strict';
import {resolve,dirname} from 'node:path';
import {readFileSync} from 'node:fs';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectAuditDispatch} from './prepare-object-audit-dispatch.mjs';
const [mfPath,persistence,phase]=process.argv.slice(2),script=fileURLToPath(import.meta.url);
if(!phase){
  let cases=0;
  for(const stage of ['seed','recover','deleted']){
    const child=spawnSync(process.execPath,[script,mfPath,persistence,stage],{env:process.env,windowsHide:true,timeout:90000,encoding:'utf8'});
    assert.equal(child.status,0,child.stderr||child.stdout);cases+=JSON.parse(child.stdout.trim()).cases;
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OBJECT_SETTLEMENT_CHECK_PASSED',cases,separateProcesses:3,
    syntheticInference:true,publicAdmission:false,acceptedContributions:0,creditsCreated:0,liveCalls:0}));
}else{
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(mfPath)).href);
  const root=dirname(dirname(script)),paths=['tools/object-settlement.fixture.mjs','src/objectSettlementCheck.js',
    'src/objectAuditDispatch.js','src/artifactWrites.js','src/scenePipeline.js','src/sceneQuality.js',
    'src/objectIndex.js','src/objectFeatures.js','src/objectCoverage.js','src/model.js','src/objectAdmission.js',
    'native-object-verifier-bridge/worker.js'];
  const options={modules:paths.map(path=>({type:'ESModule',path:resolve(root,path)})),modulesRoot:root,
    compatibilityDate:'2026-09-19',d1Databases:{DB:'00000000-0000-4000-8000-000000000332'},r2Buckets:['INDEX'],
    ...(convertV4MiniflareOptions?{resourcePersistencePath:resolve(persistence)}:{d1Persist:resolve(persistence,'d1'),r2Persist:resolve(persistence,'r2')})};
  const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);let cases=0;
  try{
    const db=await mf.getD1Database('DB');
    const call=async mode=>{
      const response=await mf.dispatchFetch('https://community.test/'+mode,{signal:AbortSignal.timeout(15000),
        ...(mode==='seed'?{method:'POST',body:readFileSync(resolve(root,'../../community/tests/fixtures/object-feature-content-v1.json'))}:{})});
      assert.equal(response.status,200,mode);const result=await response.json();
      assert.equal(result.objectAdmissionReady,false);assert.equal(result.publications,0);assert.equal(result.ledger,0);
      assert.equal(result.nativeInferences,0);assert.equal(result.liveCalls,0);assert.equal(result.owner.units,0);cases++;return result;
    };
    const refused=r=>assert.deepEqual(r.value,{error:'object_settlement_evidence_unavailable',status:503});
    const checked=r=>{assert.equal(r.value.status,'CHECKED_NOT_AUTHORIZED');assert.equal(r.value.records,2);
      assert.equal(r.value.serverAuthorization,false);assert.equal(r.value.accepted,0);assert.equal(r.value.credits,0);};
    if(phase==='seed'){
      await prepareDatabase(db);await prepareObjectAuditDispatch(db);
      assert.equal((await call('seed')).value.freshAuditReply,true);checked(await call('good'));
    }else if(phase==='recover'){
      const before=await call('good');checked(before);assert.equal(before.gets,2);
      refused(await call('wrong-pin'));refused(await call('unavailable'));refused(await call('coverage-late'));
      checked(await call('restore'));const gets=(await db.prepare('SELECT gets FROM synthetic_settlement').first()).gets;
      const changed=await call('tamper');refused(changed);assert.equal(changed.gets,gets);
      checked(await call('restore'));refused(await call('fence'));checked(await call('restore'));
      const deleted=await call('delete-late');refused(deleted);assert.equal(deleted.owner.deleted_at,100001);
    }else{
      const gets=(await db.prepare('SELECT gets FROM synthetic_settlement').first()).gets;
      const result=await call('good');refused(result);assert.equal(result.gets,gets);assert.equal(result.owner.deleted_at,100001);
    }
    console.log(JSON.stringify({phase,cases}));
  }finally{await mf.dispose();}
}
