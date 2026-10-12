// Finite real Cloudflare runtime/persistence checks; no live services or models.
import assert from 'node:assert/strict';
import {resolve,dirname} from 'node:path';
import {readFileSync} from 'node:fs';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectAuditDispatch} from './prepare-object-audit-dispatch.mjs';
import {prepareObjectSettlement} from './prepare-object-settlement.mjs';
import {OBJECT_DISPATCH_LEGACY_SCHEMA,OBJECT_DISPATCH_LEGACY_CONTRACT,OBJECT_DISPATCH_CONTRACT} from '../src/objectAuditDispatch.js';
const [mfPath,persistence,phase]=process.argv.slice(2),script=fileURLToPath(import.meta.url);
if(!phase){
  let cases=0;
  for(const stage of ['seed','recover','deleted']){
    const child=spawnSync(process.execPath,[script,mfPath,persistence,stage],{env:process.env,windowsHide:true,timeout:90000,encoding:'utf8'});
    assert.equal(child.status,0,child.stderr||child.stdout);cases+=JSON.parse(child.stdout.trim()).cases;
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OBJECT_ACCEPTANCE_PASSED',cases,separateProcesses:3,
    syntheticInference:true,syntheticAcceptedLocations:2,syntheticCreditAward:20,publicAdmission:false,
    realAcceptedContributions:0,realEarnedCredits:0,liveCalls:0}));
}else{
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(mfPath)).href);
  const root=dirname(dirname(script)),paths=['tools/object-acceptance.fixture.mjs','tools/object-settlement.fixture.mjs',
    'src/objectSettlement.js','src/objectSettlementCheck.js','src/objectAuditFlow.js','src/objectAuditDispatch.js',
    'src/artifactWrites.js','src/scenePipeline.js','src/sceneQuality.js','src/objectIndex.js','src/objectFeatures.js',
    'src/objectPublicManifest.js','src/objectCoverage.js','src/model.js','src/objectAdmission.js',
    'src/accountPrivacy.js','src/objectAuditPrivacy.js','native-object-verifier-bridge/worker.js'];
  const options={modules:paths.map(path=>({type:'ESModule',path:resolve(root,path)})),modulesRoot:root,
    compatibilityDate:'2026-09-19',d1Databases:{DB:'00000000-0000-4000-8000-000000000442'},r2Buckets:['INDEX'],
    ...(convertV4MiniflareOptions?{resourcePersistencePath:resolve(persistence)}:{d1Persist:resolve(persistence,'d1'),r2Persist:resolve(persistence,'r2')})};
  const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);let cases=0;
  try{
    const db=await mf.getD1Database('DB');
    const call=async mode=>{
      const response=await mf.dispatchFetch('https://community.test/'+mode,{signal:AbortSignal.timeout(25000),
        ...(mode==='seed'?{method:'POST',body:readFileSync(resolve(root,'../../community/tests/fixtures/object-feature-content-v1.json'))}:{})});
      assert.equal(response.status,200,mode);const r=await response.json();
      assert.equal(r.objectAdmissionReady,false);assert.equal(r.nativeInferences,0);assert.equal(r.liveCalls,0);cases++;return r;
    };
    const zero=r=>{assert.equal(r.publications,0);assert.equal(r.ledger,0);assert.equal(r.acceptances,0);assert.equal(r.owner.units,0);
      assert.equal(r.waitingSlots,1);assert.equal(r.retainedCandidates,1);};
    const complete=r=>{assert.equal(r.publications,2);assert.equal(r.ledger,1);assert.equal(r.acceptances,1);assert.equal(r.sanitized,true);
      assert.equal(r.waitingSlots,0);assert.equal(r.retainedCandidates,1);};
    if(phase==='seed'){
      await prepareDatabase(db);await prepareObjectAuditDispatch(db);await prepareObjectSettlement(db);
      zero(await call('seed'));const partial=await call('partial');zero(partial);assert.equal(partial.value.status,503);assert.equal(partial.sanitized,true);
      const pose=await call('pose-late');zero(pose);assert.equal(pose.value.status,409);
      await db.prepare('UPDATE locations SET heading=heading-1').run();
      const wrong=await call('wrong-policy');zero(wrong);assert.equal(wrong.value.error,'object_settlement_policy_mismatch');
      await db.prepare(`CREATE TRIGGER synthetic_publication_failure BEFORE INSERT ON published_index
        WHEN NEW.location_id=12 BEGIN SELECT RAISE(ABORT,'synthetic publication failure');END`).run();
      const rollback=await call('good');zero(rollback);assert.equal(rollback.value.status,503);
      await db.prepare('DROP TRIGGER synthetic_publication_failure').run();
      const lost=await call('lost-commit');complete(lost);assert.equal(lost.value.status,503);assert.equal(lost.owner.units,20);
      // Simulate the exact prior dispatch schema around preserved settlement
      // evidence, then migrate only after starting a fresh workerd process.
      const names=(await db.prepare("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'object_dispatch_slot_%'").all()).results;
      await db.batch([...names.map(({name})=>db.prepare('DROP TRIGGER '+name)),
        db.prepare('DROP TRIGGER object_dispatch_capacity'),db.prepare('DROP TABLE object_dispatch_slots'),
        db.prepare(OBJECT_DISPATCH_LEGACY_SCHEMA.find(sql=>sql.startsWith('CREATE TRIGGER IF NOT EXISTS object_dispatch_capacity'))),
        db.prepare('UPDATE object_dispatch_revision SET contract=?').bind(OBJECT_DISPATCH_LEGACY_CONTRACT)]);
    }else if(phase==='recover'){
      assert.equal((await db.prepare('SELECT contract FROM object_dispatch_revision').first()).contract,OBJECT_DISPATCH_LEGACY_CONTRACT);
      const candidates=(await db.prepare('SELECT * FROM object_audit_candidates').all()).results;
      const acceptances=(await db.prepare('SELECT * FROM object_acceptances').all()).results;
      await prepareObjectAuditDispatch(db);
      assert.equal((await db.prepare('SELECT contract FROM object_dispatch_revision').first()).contract,OBJECT_DISPATCH_CONTRACT);
      assert.deepEqual((await db.prepare('SELECT * FROM object_audit_candidates').all()).results,candidates);
      assert.deepEqual((await db.prepare('SELECT * FROM object_acceptances').all()).results,acceptances);cases++;
      const before=await db.prepare('SELECT * FROM synthetic_acceptance_calls').first();
      for(const mode of ['good','advance']){
        const replay=await call(mode);complete(replay);assert.equal(replay.value.accepted,2);
        assert.equal(replay.value.unitsEarned,0);assert.equal(replay.value.pendingAudit,false);
        assert.equal(replay.owner.units,20);assert.deepEqual(replay.calls,before);
      }
      const deleted=await call('delete');complete(deleted);assert.equal(deleted.owner.units,0);assert.ok(deleted.owner.deleted_at>0);
    }else{
      const before=await db.prepare('SELECT * FROM synthetic_acceptance_calls').first();
      const refused=await call('good');complete(refused);assert.equal(refused.value.error,'account_not_active');
      assert.equal(refused.value.status,401);assert.equal(refused.owner.units,0);assert.deepEqual(refused.calls,before);
    }
    console.log(JSON.stringify({phase,cases}));
  }finally{await mf.dispose();}
}
