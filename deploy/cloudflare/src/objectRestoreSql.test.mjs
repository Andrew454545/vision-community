import assert from 'node:assert/strict';
import test from 'node:test';
import {DatabaseSync} from 'node:sqlite';
import {existsSync,mkdtempSync,readFileSync,rmSync,writeFileSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {prepareObjectRestoreSql,main} from '../tools/object-cancellation-restore-sql.mjs';
import {sqliteLiteralRows} from '../tools/sqlite-value-literals.mjs';
import {makeObjectSqlFixture,account,other,lease,sha,now} from './objectRestoreSql.fixture.mjs';
import {prepareObjectAuditRetention} from '../tools/prepare-object-audit-retention.mjs';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
function temporary(t){const root=mkdtempSync(join(tmpdir(),'os-'));t.after(()=>rmSync(root,{recursive:true}));return root;}
function pins(options){
  const reportPath=join(options.repairedDir,'restore-report.json'),report=JSON.parse(readFileSync(reportPath));
  report.databaseSha256=sha(readFileSync(join(options.repairedDir,'restored.sqlite')));
  report.planSha256=sha(readFileSync(join(options.repairedDir,'object-cancellation-plan.private.json')));
  writeFileSync(reportPath,JSON.stringify(report)+'\n');options.reportSha256=sha(readFileSync(reportPath));
}
test('SQL recovery preserves the optional retirement outbox and its accepted-work journal',async t=>{
  const root=temporary(t),options=await makeObjectSqlFixture(root,'submitted',true,now+2,true);
  const sql=new DatabaseSync(join(options.repairedDir,'restored.sqlite'));let rows;
  try {
    await prepareObjectAuditRetention(sqliteD1(sql));
    sql.prepare("INSERT INTO object_audit_retirements(lease_id,request_sha256,state,failures,next_attempt) VALUES (?,?,'pending',1,?)")
      .run(other,'e'.repeat(64),now+60);
    rows=sql.prepare('SELECT * FROM object_audit_retirements').all();
  }finally{sql.close();}
  pins(options);
  const out=join(root,'sql');assert.equal((await prepareObjectRestoreSql({...options,out})).localRoundtripPassed,true);
  const recovered=new DatabaseSync(join(out,'roundtrip.sqlite'));
  try {
    assert.deepEqual(recovered.prepare('SELECT * FROM object_audit_retirements').all(),rows);
    assert.equal(recovered.prepare('SELECT units FROM accounts WHERE id=?').get(other).units,17);
    assert.throws(()=>recovered.exec("UPDATE object_audit_retirements SET request_sha256='changed'"),/object_retirement_immutable/);
  }finally{recovered.close();}
});
test('exact SQL recovery retains accepted Object evidence, released slots and earned credit',async t=>{
  const root=temporary(t),options=await makeObjectSqlFixture(root,'submitted',true,now+2,true),out=join(root,'sql');
  const original=new DatabaseSync(options.backup,{readOnly:true});let acceptance;
  try{acceptance=original.prepare('SELECT * FROM object_acceptances').all();}finally{original.close();}
  const report=await prepareObjectRestoreSql({...options,out});assert.equal(report.localRoundtripPassed,true);
  const sql=new DatabaseSync(join(out,'roundtrip.sqlite'));
  try{
    assert.deepEqual(sql.prepare('SELECT * FROM object_acceptances').all(),acceptance);
    assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(other).units,17);
    assert.equal(sql.prepare("SELECT units FROM ledger WHERE reference=?").get('lease:'+other).units,10);
    assert.equal(sql.prepare('SELECT last_error FROM object_audit_candidates WHERE lease_id=?').get(other).last_error,'original failure retained');
    assert.equal(sql.prepare('SELECT count(*) n FROM object_dispatch_slots').get().n,0);
    assert.equal(sql.prepare('PRAGMA foreign_key_check').all().length,0);
    assert.throws(()=>sql.exec('DELETE FROM object_acceptances'),/object_acceptance_retained/);
  }finally{sql.close();}
  assert.equal(sha(readFileSync(options.backup)),options.backupSha256);
});
for(const [phase,recovery] of [['submitted',false],['submitted',true],['empty',false]])test(`exact SQL preparation retains ${phase}, retry history=${recovery}`,async t=>{
  const root=temporary(t),options=await makeObjectSqlFixture(root,phase,recovery),out=join(root,'sql'),report=await prepareObjectRestoreSql({...options,out});
  assert.equal(report.localRoundtripPassed,true);assert.equal(report.liveReady,false);assert.equal(report.productionQualified,false);
  assert.equal(report.financialReconciled,false);assert.equal(report.currentDeletionAuthorityRequired,true);
  assert.equal(report.destinationAuthorityRequired,true);assert.equal(report.nativeCleanupPending,true);assert.equal(report.providerFencesPending,true);
  assert.equal(sha(readFileSync(options.backup)),options.backupSha256);
  assert.equal(sha(readFileSync(join(out,'restore.private.sql'))),report.sqlSha256);
  assert.equal(sha(readFileSync(join(out,'query-batch.private.json'))),report.batchSha256);
  const sql=new DatabaseSync(join(out,'roundtrip.sqlite'));
  try{
    assert.equal(sql.prepare('SELECT count(*) AS n FROM object_cancellation_tombstones').get().n,1);
    assert.throws(()=>sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',9999)").run(lease,account));
    if(phase!=='empty'){
      assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(other).units,7);
      assert.equal(sql.prepare('SELECT CAST(seq AS TEXT) AS n FROM sqlite_sequence WHERE name=\'locations\'').get().n,'9007199254740993');
      assert.deepEqual({...sql.prepare('SELECT lat,lon,heading FROM locations WHERE id=2').get()}, {lat:1.0000000000000002,lon:0.10000000000000002,heading:Math.PI});
      assert.equal(sql.prepare('SELECT hex(result_json) AS bytes FROM searches').get().bytes,'00FF27');
      assert.equal(sql.prepare('SELECT hex(CAST(query AS BLOB)) AS bytes FROM searches').get().bytes,Buffer.from("synthetic private ' quote;\nNUL\0 🍀").toString('hex').toUpperCase());
      const row=sql.prepare('SELECT * FROM object_audit_candidates').get();assert.equal(row.state,'cancelled');assert.equal(row.receipt_sha256,null);
      assert.equal(row.last_error,'preserved-native-failure');assert.equal(row.native_attempts,1);
      if(recovery){const intent=sql.prepare('SELECT * FROM object_audit_recoveries').get();assert.equal(intent.state,'applied');assert.equal(intent.prior_error,'preserved-original-connection-failure');}
    }else assert.equal(sql.prepare('SELECT count(*) AS n FROM accounts').get().n,0);
  }finally{sql.close();}
  const marker=readFileSync(join(out,'sql-report.json'));await assert.rejects(prepareObjectRestoreSql({...options,out}));
  assert.deepEqual(readFileSync(join(out,'sql-report.json')),marker);
});
for(const damage of ['report-pin','database-pin','ledger-pin','plan-pin','wrong-resource','stale-ledger','sidecar','unknown-table','unknown-trigger','changed-fence','changed-literal','missing-index','wrong-revision','missing-retry-table','changed-plan','missing-current-cancellation','revived-claim','oversize-row'])test(`SQL recovery refuses ${damage} without a success receipt`,async t=>{
  const root=temporary(t),options=await makeObjectSqlFixture(root,'submitted',true),out=join(root,'refused'),database=join(options.repairedDir,'restored.sqlite');
  if(damage==='report-pin')options.reportSha256='0'.repeat(64);
  else if(damage==='database-pin')writeFileSync(database,Buffer.from('bad source pin'));
  else if(damage==='ledger-pin')options.cancellationsSha256='0'.repeat(64);
  else if(damage==='plan-pin')writeFileSync(join(options.repairedDir,'object-cancellation-plan.private.json'),'{}');
  else if(damage==='wrong-resource')options.environment='production';
  else if(damage==='stale-ledger')options.now=now+603;
  else if(damage==='sidecar')writeFileSync(database+'-wal','synthetic sidecar');
  else if(damage==='changed-plan'){
    const path=join(options.repairedDir,'object-cancellation-plan.private.json'),plan=JSON.parse(readFileSync(path));plan.r2Fences=[];writeFileSync(path,JSON.stringify(plan));pins(options);
  }else if(damage==='missing-current-cancellation'){
    const ledger=JSON.parse(readFileSync(options.cancellations));ledger.cancellations=[];writeFileSync(options.cancellations,JSON.stringify(ledger)+'\n');
    options.cancellationsSha256=sha(readFileSync(options.cancellations));
    const path=join(options.repairedDir,'restore-report.json'),report=JSON.parse(readFileSync(path));report.cancellationLedgerSha256=options.cancellationsSha256;
    writeFileSync(path,JSON.stringify(report));pins(options);
  }else{
    const sql=new DatabaseSync(database);
    try{
      if(damage==='unknown-table')sql.exec('CREATE TABLE unrelated(private TEXT)');
      if(damage==='unknown-trigger')sql.exec("CREATE TRIGGER unrelated AFTER UPDATE ON accounts BEGIN SELECT 1; END");
      if(damage==='changed-fence'){sql.exec("DROP TRIGGER object_cancel_restore_no_delete; CREATE TRIGGER object_cancel_restore_no_delete BEFORE DELETE ON object_cancellation_tombstones BEGIN SELECT RAISE(ABORT,'OBJECT_assignment_cancelled'); END");}
      if(damage==='changed-literal'){
        const definition=sql.prepare("SELECT sql FROM sqlite_master WHERE name='object_dispatch_active_insert'").get().sql;
        sql.exec('DROP TRIGGER object_dispatch_active_insert');sql.exec(definition.replace("NEW.state!='pending'","NEW.state!='PENDING'"));
      }
      if(damage==='missing-index')sql.exec('DROP INDEX object_cancel_restore_intents_lease');
      if(damage==='wrong-revision')sql.exec("UPDATE object_cancel_revision SET contract='future'");
      if(damage==='missing-retry-table')sql.exec('DROP TABLE object_audit_recoveries');
      if(damage==='revived-claim'){
        sql.exec('DROP TRIGGER object_cancel_restore_candidate_update');
        sql.exec("UPDATE object_audit_candidates SET claim_token='stale',claim_until=9999");
        const {OBJECT_CANCEL_RESTORE_SCHEMA}=await import('./objectCancellationRestore.js');
        sql.exec(OBJECT_CANCEL_RESTORE_SCHEMA.find(statement=>statement.includes('TRIGGER IF NOT EXISTS object_cancel_restore_candidate_update')));
      }
      if(damage==='oversize-row')sql.prepare('UPDATE searches SET query=?').run('private-secret'.repeat(10000));
    }finally{sql.close();}
    pins(options);
  }
  await assert.rejects(prepareObjectRestoreSql({...options,out}));assert.equal(existsSync(join(out,'sql-report.json')),false);
  const failed=readFileSync(join(out,'failure-report.json'),'utf8');assert.equal(JSON.parse(failed).liveReady,false);
  assert.equal(failed.includes('private-secret'),false);assert.equal(failed.includes(root),false);
});
test('literal export preserves adjacent REALs and refuses infinity',t=>{
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());sql.exec('CREATE TABLE exact (v REAL)');
  for(const value of [1.0000000000000002,1.0000000000000004,Number.MIN_VALUE,Number.MAX_VALUE])sql.prepare('INSERT INTO exact VALUES (?)').run(value);
  const rows=sqliteLiteralRows(sql,'exact');sql.exec('CREATE TABLE restored (v REAL)');for(const row of rows.rows)sql.exec('INSERT INTO restored VALUES ('+row+')');
  assert.deepEqual(sql.prepare('SELECT v FROM restored ORDER BY v').all(),sql.prepare('SELECT v FROM exact ORDER BY v').all());
  sql.exec('INSERT INTO exact VALUES (1e999)');assert.throws(()=>sqliteLiteralRows(sql,'exact'),/nonfinite/);
});
test('preparation time consumes the captured cancellation authority window',async t=>{
  const root=temporary(t),options=await makeObjectSqlFixture(root),out=join(root,'expired-during-preparation');
  options.now=options.now+600;
  await assert.rejects(prepareObjectRestoreSql({...options,out}));assert.equal(existsSync(join(out,'sql-report.json')),false);
});
test('SQL command requires explicit flags and only prints aggregate, non-ready evidence',async t=>{
  const root=temporary(t),options=await makeObjectSqlFixture(root,'submitted',false,Math.floor(Date.now()/1000)),lines=[],log=console.log;
  console.log=value=>lines.push(value);
  try{
    assert.equal(await main(['--repaired-dir',options.repairedDir,'--report-sha256',options.reportSha256,'--cancellations',options.cancellations,
      '--cancellations-sha256',options.cancellationsSha256,'--writers-stopped-at',String(options.notBefore),'--environment','staging','--out',join(root,'cli')]),0);
    assert.equal(await main(['--unexpected','secret']),1);
  }finally{console.log=log;}
  assert.equal(lines.length,2);for(const line of lines){assert.equal(line.includes(account),false);assert.equal(line.includes(root),false);assert.equal(JSON.parse(line).liveReady,false);}
  assert.equal(JSON.parse(lines[0]).localRoundtripPassed,true);assert.equal(JSON.parse(lines[0]).productionQualified,false);
});
test('linked source files cannot be consumed',async t=>{
  const root=temporary(t),options=await makeObjectSqlFixture(root),linked=join(root,'linked.json');
  try{symlinkSync(options.cancellations,linked);}catch(error){if(['EPERM','EACCES'].includes(error.code)){t.skip('Windows file-symlink privilege unavailable');return;}throw error;}
  await assert.rejects(prepareObjectRestoreSql({...options,cancellations:linked,out:join(root,'linked-refused')}),/linked_or_invalid/);
});
