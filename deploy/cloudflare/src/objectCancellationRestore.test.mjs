import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync,readFileSync,writeFileSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {makeFixture,ledgerArgs,account,other,lease,now,authority,objectIndex,encoded,sha} from './objectCancellationRestore.fixture.mjs';
import {applyObjectCancellationLedger,prepareObjectCancellationRestore,main} from '../tools/object-cancellation-restore.mjs';
import {exportObjectCancellationLedger,readCancellationTombstones} from '../tools/object-cancellation-authority.mjs';
import {fenceRestoredObjectArtifact} from './objectCancellationRestore.js';
import {writeObjectArtifact,PRIVACY_FENCE} from './artifactWrites.js';
import {stageObjectAudit,advanceObjectAudit,OBJECT_DISPATCH_LEGACY_SCHEMA,OBJECT_DISPATCH_LEGACY_CONTRACT,OBJECT_DISPATCH_CONTRACT} from './objectAuditDispatch.js';
import {exportDeletionLedger,RESOURCE_PROFILES} from '../tools/account-restore.mjs';
import {exportObjectErasureAuthority} from '../tools/object-erasure-recovery.mjs';
import {planPrivacyStorage} from '../tools/privacy-storage-restore.mjs';
async function fixture(t,phase='submitted'){
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());return makeFixture(sql,phase);
}
async function pair(t,phase='submitted'){
  const old=await fixture(t,phase),current=await fixture(t,'cancelled');return {...old,args:ledgerArgs(current.sql)};
}
const image=sql=>JSON.stringify({accounts:sql.prepare('SELECT * FROM accounts ORDER BY id').all(),
  ledger:sql.prepare('SELECT * FROM ledger ORDER BY id').all(),searches:sql.prepare('SELECT * FROM searches ORDER BY id').all(),
  published:sql.prepare('SELECT * FROM published_index ORDER BY location_id').all()});

test('current cancellation revokes an old native approval without changing accounts, credit, searches or original failure fields',async t=>{
  const s=await pair(t);s.sql.exec("UPDATE object_audit_candidates SET native_state='approved',receipt_sha256='saved-synthetic-approval',native_attempts=1,transport_failures=8,last_error='preserved-original-failure'");
  s.sql.prepare("INSERT INTO searches VALUES ('saved',?,'saved','synthetic','{}')").run(other);
  const before=image(s.sql),plan=applyObjectCancellationLedger(s.sql,s.args),row=s.sql.prepare('SELECT * FROM object_audit_candidates').get();
  assert.equal(row.state,'cancelled');assert.equal(row.receipt_sha256,null);assert.equal(row.native_state,'approved');
  assert.equal(row.native_attempts,1);assert.equal(row.transport_failures,8);assert.equal(row.last_error,'preserved-original-failure');
  assert.equal(s.sql.prepare('SELECT state FROM leases WHERE id=?').get(lease).state,'expired');
  assert.equal(s.sql.prepare('SELECT active_lease,queue_state FROM locations').get().active_lease,null);
  assert.equal(image(s.sql),before);assert.equal(plan.existingCandidates,1);assert.equal(plan.nativeCleanupPending,true);
  assert.equal(plan.providerFencesPending,true);assert.equal(plan.liveReady,false);assert.equal(plan.r2Fences.length,1);
  const late=await advanceObjectAudit(s.env,account,lease,now+3);assert.equal(late.cancelled,true);assert.equal(late.freshAuditReply,false);
});

test('offline cancellation repairs an exact v1 backup through the shared slot migration',async t=>{
  const s=await pair(t),before=image(s.sql);
  const names=s.sql.prepare("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'object_dispatch_slot_%'").all();
  for(const {name} of names)s.sql.exec('DROP TRIGGER '+name);
  s.sql.exec('DROP TRIGGER object_dispatch_capacity;DROP TABLE object_dispatch_slots');
  s.sql.exec(OBJECT_DISPATCH_LEGACY_SCHEMA.find(sql=>sql.startsWith('CREATE TRIGGER IF NOT EXISTS object_dispatch_capacity')));
  s.sql.prepare('UPDATE object_dispatch_revision SET contract=?').run(OBJECT_DISPATCH_LEGACY_CONTRACT);
  applyObjectCancellationLedger(s.sql,s.args);
  assert.equal(s.sql.prepare('SELECT contract FROM object_dispatch_revision').get().contract,OBJECT_DISPATCH_CONTRACT);
  assert.equal(s.sql.prepare('SELECT count(*) n FROM object_dispatch_slots').get().n,0);
  assert.equal(s.sql.prepare('SELECT state FROM object_audit_candidates').get().state,'cancelled');
  assert.equal(image(s.sql),before);assert.equal(s.sql.prepare('PRAGMA foreign_key_check').all().length,0);
});

test('backup before candidate records revocation and expires its active lease without inventing a job or accepted work',async t=>{
  const s=await pair(t,'active'),before=image(s.sql),plan=applyObjectCancellationLedger(s.sql,s.args);
  assert.equal(plan.existingCandidates,0);assert.equal(plan.missingLeases,0);assert.equal(plan.r2Fences.length,1);
  assert.equal(s.sql.prepare('SELECT count(*) AS n FROM object_audit_candidates').get().n,0);
  await assert.rejects(stageObjectAudit(s.env,account,authority,objectIndex,now+3),/lease_lost/);
  assert.equal(image(s.sql),before);
});

test('backup before account or lease saves an immutable tombstone, fences the exact quarantine and exports native revocation',async t=>{
  const s=await pair(t,'empty'),plan=applyObjectCancellationLedger(s.sql,s.args),event=JSON.parse(s.args.ledgerRaw).cancellations[0];
  assert.equal(plan.missingLeases,1);assert.equal(s.sql.prepare('SELECT count(*) AS n FROM accounts').get().n,0);
  assert.equal(s.sql.prepare('SELECT count(*) AS n FROM leases').get().n,0);
  const fenced=await fenceRestoredObjectArtifact(s.env,lease,event.artifactKey);assert.equal(fenced.fenced,true);assert.equal(fenced.nativeCleanupPending,true);
  const saved=await s.env.INDEX.get(event.artifactKey);assert.equal(saved.customMetadata.visionPrivacyFence,'1');assert.equal(new TextDecoder().decode(await saved.arrayBuffer()),PRIVACY_FENCE);
  const registryRaw=encoded({version:1,scope:'private-object-audit-registry',policyId:authority.policyId,resource:RESOURCE_PROFILES.staging,
    assignments:[{leaseId:lease,assignment:{sha256:authority.assignmentSha256}}]});
  const deletionLedgerRaw=encoded(exportDeletionLedger(s.sql,now+2,'staging'));
  const result=exportObjectErasureAuthority(s.sql,{registryRaw,registrySha256:sha(registryRaw),policySha256:'e'.repeat(64),
    deletionLedgerRaw,deletionLedgerSha256:sha(deletionLedgerRaw),cancellationLedgerRaw:s.args.ledgerRaw,
    cancellationLedgerSha256:s.args.ledgerSha256,notBefore:now+2,now:now+2,environment:'staging'});
  assert.equal(result.version,2);assert.equal(result.cancellations.length,1);assert.equal(result.revocations.length,0);
  const {cancellationLedgerRaw,cancellationLedgerSha256,...legacy}={registryRaw,registrySha256:sha(registryRaw),policySha256:'e'.repeat(64),
    deletionLedgerRaw,deletionLedgerSha256:sha(deletionLedgerRaw),cancellationLedgerRaw:s.args.ledgerRaw,cancellationLedgerSha256:s.args.ledgerSha256,
    notBefore:now+2,now:now+2,environment:'staging'};
  assert.throws(()=>exportObjectErasureAuthority(s.sql,legacy),/object_cancellation_recovery_required/);
});

test('saved cancellation cannot be removed or reinterpreted by a newer empty/changed ledger and exact replay is idempotent',async t=>{
  const s=await pair(t);applyObjectCancellationLedger(s.sql,s.args);const before=JSON.stringify(readCancellationTombstones(s.sql));
  const again=applyObjectCancellationLedger(s.sql,s.args);assert.equal(again.r2Fences.length,1);assert.equal(JSON.stringify(readCancellationTombstones(s.sql)),before);
  for(const change of [v=>{v.cancellations=[];},v=>{v.cancellations[0].assignmentSha256='9'.repeat(64);},v=>{v.cancellations[0].requestId='8'.repeat(64);}]){
    const value=JSON.parse(s.args.ledgerRaw);change(value);const ledgerRaw=encoded(value);
    assert.throws(()=>applyObjectCancellationLedger(s.sql,{...s.args,ledgerRaw,ledgerSha256:sha(ledgerRaw)}));
    assert.equal(JSON.stringify(readCancellationTombstones(s.sql)),before);
  }
  assert.deepEqual(exportObjectCancellationLedger(s.sql,now+2,'staging'),JSON.parse(s.args.ledgerRaw));
  assert.throws(()=>s.sql.exec('DELETE FROM object_cancellation_tombstones'),/object_cancel_restore_immutable/);
  assert.throws(()=>s.sql.exec('UPDATE object_cancellation_tombstones SET cancelled_at=0'),/object_cancel_restore_immutable/);
});

test('current and restored copies of the same cancellation merge into one event without replacing original journals',async t=>{
  const s=await fixture(t,'cancelled'),args=ledgerArgs(s.sql),prior=JSON.stringify(s.sql.prepare('SELECT * FROM object_audit_cancellations').get());
  applyObjectCancellationLedger(s.sql,args);
  assert.equal(JSON.stringify(s.sql.prepare('SELECT * FROM object_audit_cancellations').get()),prior);
  assert.equal(exportObjectCancellationLedger(s.sql,now+2,'staging').cancellations.length,1);
});

test('restored SQL fences block late lease, location, candidate, artifact and publication writes',async t=>{
  const s=await pair(t);applyObjectCancellationLedger(s.sql,s.args);
  const attempts=[()=>s.sql.prepare("UPDATE leases SET state='active' WHERE id=?").run(lease),
    ()=>s.sql.prepare("UPDATE locations SET active_lease=?,state='leased' WHERE id=1").run(lease),
    ()=>s.sql.exec("UPDATE object_audit_candidates SET state='pending'"),
    ()=>s.sql.exec("UPDATE object_audit_candidates SET receipt_sha256='late'"),
    ()=>s.sql.prepare("INSERT INTO account_artifact_writes VALUES (?,?,?,?,1,1003)").run('object-index-v4/'+lease+'/manifest.json',account,lease,'f'.repeat(64)),
    ()=>s.sql.prepare("INSERT INTO account_artifact_writes VALUES (?,?,?,?,1,1003)").run('object-quarantine/'+lease+'/'+'f'.repeat(64)+'.json',other,other,'f'.repeat(64)),
    ()=>s.sql.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (1,'synthetic','fixture',1003,?)").run('object-index-v4/'+lease+'/'),
    ()=>s.sql.prepare('INSERT INTO lease_items VALUES (?,99)').run(lease)];
  for(const attempt of attempts)assert.throws(attempt,/object_assignment_cancelled|object_dispatch_owner_lost/);
});

test('unknown revoked lease cannot later become active even after its account is created',async t=>{
  const s=await pair(t,'empty');applyObjectCancellationLedger(s.sql,s.args);
  s.sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-future',0)").run(account);
  assert.throws(()=>s.sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',9999)").run(lease,account),/object_assignment_cancelled/);
  assert.equal(s.sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
});

test('same-lease, unknown or older published work refuses; later other-lease publication and bytes remain intact',async t=>{
  for(const prefix of ['object-index-v4/'+lease+'/',null,'unknown']){
    const s=await pair(t);s.sql.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (1,'synthetic','fixture',1002,?)").run(prefix);
    assert.throws(()=>applyObjectCancellationLedger(s.sql,s.args));assert.equal(s.sql.prepare('SELECT state FROM object_audit_candidates').get().state,'pending');
  }
  const s=await pair(t);s.sql.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (1,'synthetic','fixture',1002,?)").run('object-index-v4/'+other+'/');
  s.sql.exec("UPDATE locations SET state='published',queue_state='published',active_lease=NULL");
  const before=image(s.sql);applyObjectCancellationLedger(s.sql,s.args);assert.equal(image(s.sql),before);
  assert.equal(s.sql.prepare('SELECT state FROM locations').get().state,'published');
});

test('wrong existing owner/assignment, malformed owned intent, or changed schema refuses without committing revocation',async t=>{
  for(const damage of [s=>s.sql.prepare('UPDATE leases SET account_id=? WHERE id=?').run(other,lease),
    s=>s.sql.exec("UPDATE object_dispatch_revision SET contract='future'"),
    s=>s.sql.exec('DROP TRIGGER object_dispatch_immutable; UPDATE object_audit_candidates SET assignment_sha256=\''+'9'.repeat(64)+"';"),
    s=>s.sql.prepare('INSERT INTO account_artifact_writes VALUES (?,?,?,?,1,1000)').run('../outside',account,lease,'f'.repeat(64))]){
    const s=await pair(t);damage(s);assert.throws(()=>applyObjectCancellationLedger(s.sql,s.args));
    assert.equal(s.sql.prepare("SELECT 1 FROM sqlite_master WHERE name='object_cancellation_tombstones'").get(),undefined);
  }
});

test('an injected final-statement failure rolls back lease, candidate, location and newly installed schema together',async t=>{
  const s=await pair(t),before=JSON.stringify(s.sql.prepare('SELECT * FROM object_audit_candidates').get());
  const failing={exec:q=>s.sql.exec(q),prepare(q){if(q.startsWith('INSERT INTO object_cancellation_tombstones'))return {run(){s.sql.exec('INSERT INTO nonexistent_restore_fault VALUES (1)');}};return s.sql.prepare(q);}};
  assert.throws(()=>applyObjectCancellationLedger(failing,s.args),/nonexistent_restore_fault/);
  assert.equal(JSON.stringify(s.sql.prepare('SELECT * FROM object_audit_candidates').get()),before);
  assert.equal(s.sql.prepare('SELECT state FROM leases WHERE id=?').get(lease).state,'submitted');
  assert.equal(s.sql.prepare('SELECT active_lease FROM locations').get().active_lease,lease);
  assert.equal(s.sql.prepare("SELECT 1 FROM sqlite_master WHERE name='object_cancellation_tombstones'").get(),undefined);
});

test('an unknown side-effect trigger cannot change banked units while recovery reports preservation',async t=>{
  const s=await pair(t),before=image(s.sql);
  s.sql.exec("CREATE TRIGGER synthetic_financial_side_effect AFTER UPDATE OF state ON leases WHEN NEW.state='expired' BEGIN UPDATE accounts SET units=units+1; END");
  assert.throws(()=>applyObjectCancellationLedger(s.sql,s.args));assert.equal(image(s.sql),before);
  assert.equal(s.sql.prepare('SELECT state FROM object_audit_candidates').get().state,'pending');
  assert.equal(s.sql.prepare("SELECT 1 FROM sqlite_master WHERE name='object_cancellation_tombstones'").get(),undefined);
});

test('protected published coordinates distinguish adjacent floating-point values and roll back hidden changes',async t=>{
  const s=await pair(t);
  s.sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,lat) VALUES (2,'synthetic-retained','fixture','object','synthetic','published',?)").run(1.0000000000000002);
  s.sql.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (2,'synthetic','fixture',1000,?)").run('object-index-v4/'+other+'/');
  s.sql.exec("CREATE TRIGGER synthetic_coordinate_side_effect AFTER UPDATE OF state ON leases WHEN NEW.state='expired' BEGIN UPDATE locations SET lat=1.0000000000000004 WHERE id=2; END");
  assert.throws(()=>applyObjectCancellationLedger(s.sql,s.args));
  assert.equal(s.sql.prepare('SELECT lat FROM locations WHERE id=2').get().lat,1.0000000000000002);
  assert.equal(s.sql.prepare('SELECT state FROM object_audit_candidates').get().state,'pending');
});

test('preservation retains exact NUL/blob and 64-bit values without interpreting historical units as valid earned credit',async t=>{
  const s=await pair(t);
  s.sql.prepare('UPDATE accounts SET token_hash=?,units=9007199254740993 WHERE id=?').run('synthetic\0private',other);
  s.sql.prepare("INSERT INTO searches VALUES ('binary',?,'binary','synthetic',X'00FF27')").run(other);
  applyObjectCancellationLedger(s.sql,s.args);
  assert.equal(s.sql.prepare('SELECT CAST(units AS TEXT) AS units,hex(token_hash) AS token FROM accounts WHERE id=?').get(other).units,'9007199254740993');
  assert.equal(s.sql.prepare('SELECT hex(result_json) AS bytes FROM searches').get().bytes,'00FF27');
  assert.equal(s.sql.prepare('SELECT token_hash FROM accounts WHERE id=?').get(other).token_hash,'synthetic\0private');
});

test('owned partial bundle intents join the fence plan; arbitrary/foreign keys are never fenced',async t=>{
  const s=await pair(t),key='object-index-v4/'+lease+'/semantic.bin';
  await writeObjectArtifact(s.env,account,lease,key,new Uint8Array(),now);
  const plan=applyObjectCancellationLedger(s.sql,s.args);assert.equal(plan.r2Fences.length,2);
  await fenceRestoredObjectArtifact(s.env,lease,key);assert.equal(new TextDecoder().decode(await (await s.env.INDEX.get(key)).arrayBuffer()),PRIVACY_FENCE);
  await assert.rejects(fenceRestoredObjectArtifact(s.env,lease,'object-index-v4/'+lease+'/unowned.bin'),/ownership_unconfirmed/);
  await assert.rejects(fenceRestoredObjectArtifact(s.env,lease,'object-index-v4/'+other+'/manifest.json'),/invalid_object_restore_fence/);
  await assert.rejects(fenceRestoredObjectArtifact(s.env,lease,'../outside'),/invalid_object_restore_fence/);
});

test('R2 outage, forged readback and bounded timeout cannot report a completed fence; retry preserves tombstone',async t=>{
  const s=await pair(t),plan=applyObjectCancellationLedger(s.sql,s.args),key=plan.r2Fences[0].key;
  await assert.rejects(fenceRestoredObjectArtifact({...s.env,INDEX:{...s.env.INDEX,put:async()=>null}},lease,key),/fence_unconfirmed/);
  await assert.rejects(fenceRestoredObjectArtifact({...s.env,INDEX:{...s.env.INDEX,get:async()=>({size:PRIVACY_FENCE.length,customMetadata:{visionPrivacyFence:'1'},body:new Response('forged').body})}},lease,key),/fence_changed/);
  await assert.rejects(fenceRestoredObjectArtifact({...s.env,INDEX:{put:()=>new Promise(()=>{})}},lease,key,5),/object_restore_fence_timeout/);
  assert.equal((await fenceRestoredObjectArtifact(s.env,lease,key)).fenced,true);
  assert.equal(readCancellationTombstones(s.sql).length,1);
});

test('wrong checksum, stale or malformed cancellation ledger refuses before schema/state mutation',async t=>{
  const s=await pair(t),original=s.sql.prepare('SELECT * FROM object_audit_candidates').get();
  for(const options of [{ledgerSha256:'0'.repeat(64)},{now:now+602},{environment:'production'},
    {ledgerRaw:Buffer.from('{}'),ledgerSha256:sha(Buffer.from('{}'))}])assert.throws(()=>applyObjectCancellationLedger(s.sql,{...s.args,...options}));
  assert.deepEqual(s.sql.prepare('SELECT * FROM object_audit_candidates').get(),original);
});

test('closed pinned file preparation preserves backup, emits private pending-cleanup plan and completion marker last',async t=>{
  const s=await pair(t),root=mkdtempSync(join(tmpdir(),'dr-'));t.after(()=>rmSync(root,{recursive:true,force:true}));
  const backup=join(root,'old.sqlite'),cancellations=join(root,'current.json');s.sql.prepare('VACUUM INTO ?').run(backup);writeFileSync(cancellations,s.args.ledgerRaw);
  const pin=sha(readFileSync(backup)),options={backup,backupSha256:pin,cancellations,cancellationsSha256:s.args.ledgerSha256,
    notBefore:now+2,now:now+2,environment:'staging',out:join(root,'prepared')};
  const report=prepareObjectCancellationRestore(options);assert.equal(sha(readFileSync(backup)),pin);
  assert.equal(report.liveReady,false);assert.equal(report.financialReconciled,false);assert.equal(report.accountDeletionReconciled,false);
  assert.equal(report.providerFencesPending,true);assert.equal(report.nativeCleanupPending,true);
  assert.equal(sha(readFileSync(join(options.out,'object-cancellation-plan.private.json'))),report.planSha256);
  assert.equal(sha(readFileSync(join(options.out,'restored.sqlite'))),report.databaseSha256);
  assert.throws(()=>planPrivacyStorage({current:join(options.out,'restored.sqlite'),currentSha256:report.databaseSha256,
    notBefore:now+2,now:now+2,environment:'staging',out:join(root,'r2-only')}),/object_cancellation_recovery_required/);
  assert.throws(()=>prepareObjectCancellationRestore(options));
  for(const change of [{backupSha256:'0'.repeat(64)},{cancellationsSha256:'0'.repeat(64)}]){
    const out=join(root,'bad-'+Math.random());assert.throws(()=>prepareObjectCancellationRestore({...options,...change,out}));
    assert.equal(JSON.parse(readFileSync(join(out,'failure-report.json'))).complete,false);assert.equal(existsSync(join(out,'restore-report.json')),false);
  }
  writeFileSync(backup+'-wal','synthetic sidecar');const out=join(root,'wal');assert.throws(()=>prepareObjectCancellationRestore({...options,out}));
  assert.equal(existsSync(join(out,'restore-report.json')),false);
});

test('operator command requires exact offline flags and keeps account/key data out of public console output',async t=>{
  const s=await pair(t),root=mkdtempSync(join(tmpdir(),'dc-'));t.after(()=>rmSync(root,{recursive:true,force:true}));
  const backup=join(root,'old.sqlite'),cancellations=join(root,'current.json');s.sql.prepare('VACUUM INTO ?').run(backup);
  const time=Math.floor(Date.now()/1000),value=JSON.parse(s.args.ledgerRaw);value.exportedAt=time;writeFileSync(cancellations,encoded(value));
  const flags={backup,'backup-sha256':sha(readFileSync(backup)),cancellations,'cancellations-sha256':sha(readFileSync(cancellations)),
    'writers-stopped-at':String(time),environment:'staging',out:join(root,'command')};
  const log=console.log,lines=[];console.log=x=>lines.push(x);
  try{assert.equal(main(Object.entries(flags).flatMap(([k,v])=>['--'+k,v])),0);assert.equal(main(['--unexpected','value']),1);}finally{console.log=log;}
  assert.equal(lines.length,2);assert.equal(lines[0].includes(account),false);assert.equal(lines[0].includes('object-quarantine/'),false);
});

test('expired or cancelled lease cannot reuse a durable upload intent before the R2 fence exists',async t=>{
  const s=await fixture(t),key=s.sql.prepare('SELECT artifact_key FROM object_audit_candidates').get().artifact_key;
  s.sql.prepare("UPDATE leases SET state='expired' WHERE id=?").run(lease);
  let writes=0;const env={...s.env,INDEX:{...s.env.INDEX,put:async()=>{writes++;throw Error('unexpected R2 write');}}};
  await assert.rejects(writeObjectArtifact(env,account,lease,key,Buffer.from(JSON.stringify(objectIndex)),now+3),/lease_lost/);
  assert.equal(writes,0);
});

test('lease cancellation after an R2 write cannot acknowledge a successful upload',async t=>{
  const s=await fixture(t),put=s.env.INDEX.put,key='object-index-v4/'+lease+'/semantic.bin';
  const env={...s.env,INDEX:{...s.env.INDEX,async put(...args){const result=await put(...args);s.sql.prepare("UPDATE leases SET state='expired' WHERE id=?").run(lease);return result;}}};
  await assert.rejects(writeObjectArtifact(env,account,lease,key,new Uint8Array(),now+3),/lease_lost/);
});
