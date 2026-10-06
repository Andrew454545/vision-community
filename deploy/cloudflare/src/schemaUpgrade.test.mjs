import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { rehearseUpgrade } from '../tools/upgrade-schema.mjs';
import { sqliteD1 } from '../tools/sqlite-d1.mjs';
import { requireSchema, SCHEMA_REVISION_SQL } from './schemaRevision.js';
import { legacyFixture } from './schemaUpgrade.fixture.mjs';

const checksum = file => createHash('sha256').update(readFileSync(file)).digest('hex');
function fixture(t) {
  const root=mkdtempSync(join(tmpdir(),'vision-upgrade-test-'));
  const databases=[];
  // Hooks run in registration order. Close files before removing their folder;
  // Windows refuses deletion while a SQLite connection still owns the file.
  t.after(()=>{for(const database of databases)database.close();rmSync(root,{recursive:true,force:true});});
  const open=(file,options={})=>{const database=new DatabaseSync(file,options);databases.push(database);return database;};
  return {root,input:join(root,'legacy.sqlite'),out:join(root,'upgrade'),open};
}
function rows(sql,table) { return sql.prepare(`SELECT * FROM ${table}`).all(); }
test('legacy upgrade preserves credentials, balances, paid maps, publications, leases and deleted ID high-water marks',async t=>{
  const {input,out,open}=fixture(t); await legacyFixture(input); const pin=checksum(input);
  const report=await rehearseUpgrade({database:input,databaseSha256:pin,out});
  assert.equal(checksum(input),pin); assert.equal(report.liveReady,false); assert.equal(report.complete,true);
  const sql=open(join(out,'upgraded.sqlite'));
  await requireSchema({DB:sqliteD1(sql)});
  assert.equal(rows(sql,'accounts')[0].units,100001);
  assert.equal(rows(sql,'accounts')[0].recovery_hash,'retained-code');
  assert.equal(sql.prepare('SELECT hex(CAST(result_json AS BLOB)) AS bytes FROM searches').get().bytes,Buffer.from('map;\0Ω').toString('hex').toUpperCase());
  assert.equal(rows(sql,'published_index')[0].embedding,'retained vector');
  assert.equal(rows(sql,'leases')[0].id,'unfinished');
  sql.exec("INSERT INTO locations(asset_id,capture,lane,model) VALUES('new','c','scene','native')");
  assert.equal(sql.prepare("SELECT id FROM locations WHERE asset_id='new'").get().id,101);
  const plan=JSON.parse(readFileSync(join(out,'query-batch.private.json'))).batch;
  assert.ok(!JSON.stringify(plan).includes('retained-token'));
  assert.ok(!JSON.stringify(plan).includes('private café'));
  assert.deepEqual(readdirSync(out).sort(),['query-batch.private.json','upgrade-report.private.json','upgrade.private.sql','upgraded.sqlite']);
});
test('generated exact-schema plan applies atomically and mismatch/late failure preserves original rows and schema',async t=>{
  const {root,input,out,open}=fixture(t); await legacyFixture(input);
  await rehearseUpgrade({database:input,databaseSha256:checksum(input),out});
  const plan=JSON.parse(readFileSync(join(out,'query-batch.private.json'))).batch.map(item=>item.sql);
  for (const mode of ['success','schema-changed','late-failure']) {
    const copy=join(root,mode+'.sqlite');copyFileSync(input,copy);
    const sql=open(copy);const db=sqliteD1(sql);
    if(mode==='schema-changed')sql.exec('CREATE TABLE unexpected(value TEXT)');
    const before=sql.prepare('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').all();
    const saved=['accounts','searches','locations','published_index','ledger','leases'].map(table=>rows(sql,table));
    const queries=mode==='late-failure'?[...plan,'INSERT INTO unavailable_table VALUES(1)']:plan;
    if(mode==='success') {await db.batch(queries.map(query=>db.prepare(query)));await requireSchema({DB:db});}
    else {
      await assert.rejects(db.batch(queries.map(query=>db.prepare(query))));
      assert.deepEqual(sql.prepare('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').all(),before);
      assert.deepEqual(['accounts','searches','locations','published_index','ledger','leases'].map(table=>rows(sql,table)),saved);
    }
  }
});
test('wrong pins, linked inputs, open journals and unknown schemas preserve failures without completing',async t=>{
  const {root,input}=fixture(t);await legacyFixture(input);const pin=checksum(input);
  for(const mode of ['pin','journal','linked','schema']) {
    const out=join(root,mode);
    let linkedInput=join(root,'linked.sqlite');
    if(mode==='journal')writeFileSync(input+'-wal','private unfinished state');
    if(mode==='linked'){
      rmSync(input+'-wal');
      if(process.platform==='win32') {
        const target=join(root,'linked-target');mkdirSync(target);copyFileSync(input,join(target,'legacy.sqlite'));
        symlinkSync(target,join(root,'redirected-input'),'junction');linkedInput=join(root,'redirected-input','legacy.sqlite');
      }else symlinkSync(input,linkedInput);
    }
    if(mode==='schema'){const sql=new DatabaseSync(input);sql.exec('CREATE TABLE unrecognized(value TEXT)');sql.close();}
    await assert.rejects(rehearseUpgrade({database:mode==='linked'?linkedInput:input,databaseSha256:mode==='pin'?'0'.repeat(64):checksum(input),out}));
    assert.equal(existsSync(join(out,'upgrade-report.private.json')),false);
    assert.equal(JSON.parse(readFileSync(join(out,'failure-report.private.json'))).complete,false);
  }
  assert.ok(pin);
});
test('existing outputs are preserved and a current schema can be rehearsed again without altering historical data',async t=>{
  const {root,input,out,open}=fixture(t);await legacyFixture(input);
  const report=await rehearseUpgrade({database:input,databaseSha256:checksum(input),out});
  const before=checksum(join(out,'upgrade-report.private.json'));
  await assert.rejects(rehearseUpgrade({database:input,databaseSha256:checksum(input),out}));
  assert.equal(checksum(join(out,'upgrade-report.private.json')),before);
  const again=await rehearseUpgrade({database:join(out,'upgraded.sqlite'),databaseSha256:report.databaseSha256,out:join(root,'again')});
  const old = open(join(out,'upgraded.sqlite'),{readOnly:true});
  const current = open(join(root,'again','upgraded.sqlite'),{readOnly:true});
  for(const table of again.historicalTables)assert.deepEqual(rows(old,table.table),rows(current,table.table));
});
test('historical data mutation, including bytes after a NUL, aborts and rolls back the rehearsal',async t=>{
  const {root,input,open}=fixture(t);await legacyFixture(input);
  const sql=new DatabaseSync(input);
  sql.exec(SCHEMA_REVISION_SQL[0]);
  sql.exec("CREATE TRIGGER unexpected_history_change AFTER INSERT ON community_schema_revision BEGIN UPDATE searches SET result_json=CAST(X'6D61703B0058' AS TEXT); END");
  const original=sql.prepare('SELECT hex(CAST(result_json AS BLOB)) AS bytes FROM searches').get().bytes;
  sql.close();const pin=checksum(input),out=join(root,'mutation');
  await assert.rejects(rehearseUpgrade({database:input,databaseSha256:pin,out}),{message:'historical_data_changed'});
  assert.equal(checksum(input),pin);assert.equal(existsSync(join(out,'upgrade-report.private.json')),false);
  const failed=open(join(out,'upgraded.sqlite'),{readOnly:true});
  assert.equal(failed.prepare('SELECT hex(CAST(result_json AS BLOB)) AS bytes FROM searches').get().bytes,original);
  assert.equal(failed.prepare('PRAGMA table_info(accounts)').all().some(column=>column.name==='deleted_at'),false);
});

test('redirected input and output parents are refused without changing the closed source or link target',async t=>{
  const {root,input,out}=fixture(t);await legacyFixture(input);const pin=checksum(input);
  const target=join(root,'regular-folder');mkdirSync(target);copyFileSync(input,join(target,'closed.sqlite'));
  const redirected=join(root,'redirect');symlinkSync(target,redirected,process.platform==='win32'?'junction':'dir');
  await assert.rejects(rehearseUpgrade({database:join(redirected,'closed.sqlite'),databaseSha256:pin,out}),{message:'unsafe_upgrade_path'});
  assert.equal(JSON.parse(readFileSync(join(out,'failure-report.private.json'))).error,'unsafe_upgrade_path');
  assert.equal(existsSync(join(out,'upgraded.sqlite')),false);
  await assert.rejects(rehearseUpgrade({database:input,databaseSha256:pin,out:join(redirected,'attempt')}),{message:'unsafe_upgrade_path'});
  assert.equal(existsSync(join(target,'attempt')),false);
  assert.equal(checksum(input),pin);assert.equal(checksum(join(target,'closed.sqlite')),pin);
});
