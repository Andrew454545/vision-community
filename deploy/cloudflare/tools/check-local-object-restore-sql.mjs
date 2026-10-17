// Offline production-source SQL preparer -> actual persisted local D1/R2.
// Three fresh processes, exact numeric/private values and injected batch failure.
// All identities, inference and units are synthetic; no provider execution.
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {makeObjectSqlFixture,account,other,lease,sha} from '../src/objectRestoreSql.fixture.mjs';
import {prepareObjectRestoreSql} from './object-cancellation-restore-sql.mjs';
const [mfPath,persistence,phase]=process.argv.slice(2),script=fileURLToPath(import.meta.url);
const inputs=join(resolve(persistence),'inputs');
if(!phase){
  mkdirSync(inputs,{recursive:true});
  const originals=[];
  for(const kind of ['submitted','empty']){
    const fixture=join(inputs,kind);mkdirSync(fixture);
    const options=await makeObjectSqlFixture(fixture,kind,kind==='submitted',undefined,kind==='submitted'),out=join(fixture,'sql');
    const report=await prepareObjectRestoreSql({...options,out});
    assert.equal(report.nativeCleanupPending,true);assert.equal(report.providerFencesPending,true);assert.equal(report.liveReady,false);
    originals.push({backup:options.backup,pin:options.backupSha256});
    writeFileSync(join(inputs,kind+'-prepared-batch.private.json'),readFileSync(join(out,'query-batch.private.json')),{flag:'wx',mode:0o600});
  }
  let cases=0;
  for(const stage of ['loaded','fence','replay']){
    const child=spawnSync(process.execPath,[script,mfPath,persistence,stage],{env:process.env,windowsHide:true,timeout:90000,encoding:'utf8'});
    assert.equal(child.status,0,child.stderr||child.stdout);cases+=JSON.parse(child.stdout.trim()).cases;
  }
  for(const {backup,pin} of originals)assert.equal(sha(readFileSync(backup)),pin);
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OBJECT_SQL_RESTORE_PASSED',cases,separateProcesses:3,
    repairedCopies:2,backupBeforeLease:true,oldApprovalRevoked:true,failedBatchRolledBack:true,lateSqlWritesBlocked:true,
    lateR2Writes:0,retainedBundlePreserved:true,originalBackupsPreserved:true,syntheticInference:true,nativeInferences:0,
    earnedCredits:0,liveCalls:0,nativeCleanupAttested:false,productionQualified:false,exactCoordinates:true,
    exactNulBlobAndHighWater:true,populatedDestinationRollback:true,repeatedImportOnceOnlyUnits:true}));
}else{
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(mfPath)).href),root=dirname(dirname(script));
  const paths=['tools/object-cancel-restore.fixture.mjs','src/objectCancellationRestore.js','src/objectAuditCancellation.js',
    'src/objectAuditDispatch.js','src/artifactWrites.js','src/objectAuditPrivacy.js','src/scenePipeline.js','src/sceneQuality.js',
    'native-object-verifier-bridge/worker.js','src/objectCoverage.js','src/model.js'];
  const mf=new Miniflare(convertV4MiniflareOptions({modules:paths.map(path=>({type:'ESModule',path:resolve(root,path)})),modulesRoot:root,
    compatibilityDate:'2026-09-19',d1Databases:{DB:'00000000-0000-4000-8000-000000000325',EARLY:'00000000-0000-4000-8000-000000000326'},
    r2Buckets:['INDEX','EARLY_INDEX'],resourcePersistencePath:join(resolve(persistence),'store')}));let cases=0;
  try{
    if(phase==='loaded')for(const [binding,kind,bucketName] of [['DB','submitted','INDEX'],['EARLY','empty','EARLY_INDEX']]){
      const db=await mf.getD1Database(binding),batch=JSON.parse(readFileSync(join(inputs,kind+'-prepared-batch.private.json'))).batch,statements=()=>batch.map(row=>db.prepare(row.sql).bind(...row.params));
      await db.prepare('CREATE TABLE provider_owned_synthetic(value INTEGER)').run();await db.prepare('INSERT INTO provider_owned_synthetic VALUES (99)').run();
      await assert.rejects(db.batch([...statements(),db.prepare('INSERT INTO nonexistent_restore_fault VALUES (1)')]));
      assert.equal(await db.prepare("SELECT 1 FROM sqlite_master WHERE name='accounts'").first(),null);cases++;
      await db.batch(statements());assert.equal((await db.prepare('SELECT value FROM provider_owned_synthetic').first()).value,99);cases++;
      assert.equal((await db.prepare('PRAGMA foreign_key_check').all()).results.length,0);
      const snapshot=async()=>({
        accounts:(await db.prepare('SELECT id,units,deleted_at FROM accounts ORDER BY id').all()).results,
        candidate:await db.prepare('SELECT state,receipt_sha256,last_error,native_attempts FROM object_audit_candidates').first(),
        money:(await db.prepare('SELECT * FROM ledger ORDER BY id').all()).results,
        acceptances:kind==='submitted'?(await db.prepare('SELECT * FROM object_acceptances').all()).results:[],
        waitingSlots:(await db.prepare('SELECT * FROM object_dispatch_slots').all()).results,
        search:await db.prepare('SELECT hex(CAST(query AS BLOB)) AS query,hex(result_json) AS reply FROM searches').first(),
        coordinates:await db.prepare('SELECT lat,lon,heading FROM locations WHERE id=2').first(),
        highWater:await db.prepare("SELECT CAST(seq AS TEXT) AS seq FROM sqlite_sequence WHERE name='locations'").first(),
        journal:await db.prepare("SELECT 1 FROM sqlite_master WHERE name='object_audit_recoveries'").first()
      });
      const before=await snapshot();
      if(kind==='submitted'){
        assert.deepEqual(before.coordinates,{lat:1.0000000000000002,lon:0.10000000000000002,heading:Math.PI});
        assert.equal(before.highWater.seq,'9007199254740993');assert.equal(before.money.length,3);assert.equal(before.search.reply,'00FF27');
        assert.equal(before.acceptances.length,1);assert.equal(before.acceptances[0].receipt_sha256,'saved-receipt');
        assert.equal(before.waitingSlots.length,0);
        assert.equal(before.search.query,Buffer.from("synthetic private ' quote;\nNUL\0 🍀").toString('hex').toUpperCase());
        assert.equal((await db.prepare('SELECT prior_error,state FROM object_audit_recoveries').first()).prior_error,'preserved-original-connection-failure');cases++;
      }
      await assert.rejects(db.batch([...statements(),db.prepare('INSERT INTO nonexistent_restore_fault VALUES (1)')]));
      assert.deepEqual(await snapshot(),before);cases++;
      await db.batch(statements());assert.deepEqual(await snapshot(),before);cases++;
      assert.equal((await db.prepare('SELECT value FROM provider_owned_synthetic').first()).value,99);cases++;

      const bucket=await mf.getR2Bucket(bucketName);await bucket.put('object-index-v4/'+other+'/manifest.json','synthetic retained bundle');
    }
    // Read exact values again in every fresh process, including after fences
    // and replay. SQL uses literals so >53-bit high-water values never cross
    // the D1 JSON boundary as a lossy JS number.
    const restored=await mf.getD1Database('DB'),early=await mf.getD1Database('EARLY');
    assert.deepEqual(await restored.prepare('SELECT lat,lon,heading FROM locations WHERE id=2').first(),
      {lat:1.0000000000000002,lon:0.10000000000000002,heading:Math.PI});
    assert.equal((await restored.prepare("SELECT CAST(seq AS TEXT) AS seq FROM sqlite_sequence WHERE name='locations'").first()).seq,'9007199254740993');
    assert.equal((await restored.prepare('SELECT hex(result_json) AS value FROM searches').first()).value,'00FF27');
    assert.equal((await restored.prepare('SELECT COUNT(*) AS n FROM ledger').first()).n,3);
    assert.equal((await restored.prepare('SELECT receipt_sha256 FROM object_acceptances').first()).receipt_sha256,'saved-receipt');
    assert.equal((await restored.prepare('SELECT units FROM accounts WHERE id=?').bind(other).first()).units,17);
    assert.equal((await restored.prepare('SELECT COUNT(*) n FROM object_dispatch_slots').first()).n,0);cases++;
    // /early/late deliberately registers an account before trying the revoked
    // lease. Registration is allowed; recovery itself created no account, and
    // the subsequent new account still cannot resurrect that assignment.
    assert.equal((await early.prepare('SELECT COUNT(*) AS n FROM accounts').first()).n,phase==='loaded'?0:1);
    if(phase!=='loaded'){
      assert.equal((await early.prepare('SELECT units FROM accounts WHERE id=?').bind(account).first()).units,0);
      assert.equal(await early.prepare('SELECT 1 FROM leases WHERE id=?').bind(lease).first(),null);
    }
    assert.equal((await early.prepare('SELECT COUNT(*) AS n FROM object_cancellation_tombstones').first()).n,1);cases++;
    const call=async path=>{
      const response=await mf.dispatchFetch('https://community.test'+path,{signal:AbortSignal.timeout(15000)});
      assert.equal(response.status,200,path+' '+(response.status===200?'':await response.text()));const value=await response.json();
      assert.equal(value.liveCalls,0);assert.equal(value.nativeInferences,0);assert.equal(value.ledgerEntries,value.early?0:3);assert.equal(value.otherBundlePreserved,true);
      assert.equal(value.publications,value.early?0:1);
      if(!value.early){assert.equal(value.owner.units,10);assert.equal(value.owner.deleted_at,null);assert.equal(value.candidate.state,'cancelled');
        assert.equal(value.candidate.receipt_sha256,null);assert.equal(value.candidate.last_error,'preserved-native-failure');assert.equal(value.candidate.native_attempts,1);assert.equal(value.lease.state,'expired');}
      cases++;return value;
    };
    for(const prefix of ['','/early']){
      const before=await call(prefix+'/state');
      if(phase==='loaded'){
        assert.equal(before.artifactFenced,false);if(prefix)assert.equal(before.owner,null);
        const late=await call(prefix+'/late');assert.equal(late.value.blockedLateStatements,prefix?5:6);assert.equal(late.value.lateR2Writes,0);
      }else{
        if(phase==='replay')assert.equal(before.artifactFenced,true);
        const fenced=await call(prefix+'/fence');assert.equal(fenced.artifactFenced,true);assert.equal(fenced.value.nativeCleanupPending,true);
        const unowned=await call(prefix+'/unowned');assert.equal(unowned.value.unownedRefused,true);
        const after=await call(prefix+'/state');assert.deepEqual(after.tombstone,before.tombstone);
      }
    }
    console.log(JSON.stringify({phase,cases}));
  }finally{await mf.dispose();}
}
