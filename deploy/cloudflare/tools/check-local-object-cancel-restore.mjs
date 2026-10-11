// Real offline repair -> actual persisted local D1/R2 -> three fresh workerd
// processes. The SQL image below is test-fixture transport, never live import.
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {makeFixture,ledgerArgs,account,other,lease,sha} from '../src/objectCancellationRestore.fixture.mjs';
import {prepareObjectCancellationRestore} from './object-cancellation-restore.mjs';
const [mfPath,persistence,phase]=process.argv.slice(2),script=fileURLToPath(import.meta.url);
const inputs=join(resolve(persistence),'inputs');
function fixtureBatch(file){
  const sql=new DatabaseSync(file,{readOnly:true,allowExtension:false});
  try{
    const schema=sql.prepare("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").all();
    const batch=[{sql:'PRAGMA defer_foreign_keys=ON',params:[]}];
    for(const row of schema.filter(row=>row.type==='table'))batch.push({sql:row.sql,params:[]});
    for(const row of schema.filter(row=>row.type==='table')){
      assert.match(row.name,/^[a-z_]+$/);
      const columns=sql.prepare('PRAGMA table_info('+row.name+')').all().map(row=>row.name);
      for(const item of sql.prepare('SELECT * FROM '+row.name).all())batch.push({sql:'INSERT INTO '+row.name+' ('+columns.join(',')+') VALUES ('+columns.map(()=>'?').join(',')+')',params:columns.map(c=>item[c])});
    }
    for(const row of schema.filter(row=>row.type==='index'||row.type==='trigger'))batch.push({sql:row.sql,params:[]});
    return batch;
  }finally{sql.close();}
}
if(!phase){
  mkdirSync(inputs,{recursive:true});
  const current=new DatabaseSync(':memory:');await makeFixture(current,'cancelled');const args=ledgerArgs(current);current.close();
  const cancellations=join(inputs,'current-cancellations.private.json');writeFileSync(cancellations,args.ledgerRaw,{flag:'wx',mode:0o600});
  const originals=[];
  for(const kind of ['submitted','empty']){
    const backup=join(inputs,kind+'-backup.sqlite'),sql=new DatabaseSync(backup);await makeFixture(sql,kind);
    if(kind==='submitted'){
      sql.exec("UPDATE object_audit_candidates SET native_state='approved',receipt_sha256='synthetic-old-approval',native_attempts=1,last_error='preserved-native-failure'");
      sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,queue_state) VALUES (2,'synthetic-kept','fixture','object','synthetic','published','published')").run();
      sql.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (2,'synthetic','fixture',1000,?)").run('object-index-v4/'+other+'/');
    }
    sql.close();const pin=sha(readFileSync(backup)),out=join(inputs,kind+'-restored');
    const report=prepareObjectCancellationRestore({backup,backupSha256:pin,cancellations,cancellationsSha256:args.ledgerSha256,
      notBefore:args.notBefore,now:args.now,environment:'staging',out});
    assert.equal(report.nativeCleanupPending,true);assert.equal(report.providerFencesPending,true);assert.equal(report.liveReady,false);
    originals.push({backup,pin});writeFileSync(join(inputs,kind+'-fixture-batch.private.json'),JSON.stringify(fixtureBatch(join(out,'restored.sqlite'))),{flag:'wx',mode:0o600});
  }
  let cases=0;
  for(const stage of ['loaded','fence','replay']){
    const child=spawnSync(process.execPath,[script,mfPath,persistence,stage],{env:process.env,windowsHide:true,timeout:90000,encoding:'utf8'});
    assert.equal(child.status,0,child.stderr||child.stdout);cases+=JSON.parse(child.stdout.trim()).cases;
  }
  for(const {backup,pin} of originals)assert.equal(sha(readFileSync(backup)),pin);
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OLD_D1_CANCELLATION_RESTORE_PASSED',cases,separateProcesses:3,
    repairedCopies:2,backupBeforeLease:true,oldApprovalRevoked:true,failedBatchRolledBack:true,lateSqlWritesBlocked:true,
    lateR2Writes:0,retainedBundlePreserved:true,originalBackupsPreserved:true,syntheticInference:true,nativeInferences:0,
    earnedCredits:0,liveCalls:0,nativeCleanupAttested:false,productionQualified:false}));
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
      const db=await mf.getD1Database(binding),batch=JSON.parse(readFileSync(join(inputs,kind+'-fixture-batch.private.json'))),statements=()=>batch.map(row=>db.prepare(row.sql).bind(...row.params));
      await db.prepare('CREATE TABLE provider_owned_synthetic(value INTEGER)').run();await db.prepare('INSERT INTO provider_owned_synthetic VALUES (99)').run();
      await assert.rejects(db.batch([...statements(),db.prepare('INSERT INTO nonexistent_restore_fault VALUES (1)')]));
      assert.equal(await db.prepare("SELECT 1 FROM sqlite_master WHERE name='accounts'").first(),null);cases++;
      await db.batch(statements());assert.equal((await db.prepare('SELECT value FROM provider_owned_synthetic').first()).value,99);cases++;
      assert.equal((await db.prepare('PRAGMA foreign_key_check').all()).results.length,0);
      const bucket=await mf.getR2Bucket(bucketName);await bucket.put('object-index-v4/'+other+'/manifest.json','synthetic retained bundle');
    }
    const call=async path=>{
      const response=await mf.dispatchFetch('https://community.test'+path,{signal:AbortSignal.timeout(15000)});
      assert.equal(response.status,200,path+' '+(response.status===200?'':await response.text()));const value=await response.json();
      assert.equal(value.liveCalls,0);assert.equal(value.nativeInferences,0);assert.equal(value.ledgerEntries,0);assert.equal(value.otherBundlePreserved,true);
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
