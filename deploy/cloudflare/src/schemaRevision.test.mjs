import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import test from 'node:test';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {requireSchema,SCHEMA_READ,SCHEMA_REVISION_SQL} from './schemaRevision.js';

test('unprepared and unknown revisions fail closed with one read and no database mutation',async t=>{
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const calls=[],env={DB:sqliteD1(sql,q=>calls.push(q))};
  await assert.rejects(requireSchema(env),{message:'schema_update_required',status:503});
  assert.deepEqual(calls,[SCHEMA_READ]);assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM sqlite_master').get().n,0);
  await prepareDatabase(env.DB);
  for(const [revision,contract] of [[2,'vision-community-d1-v2'],[1,'mistyped']]) {
    sql.prepare('UPDATE community_schema_revision SET revision=?,contract=?').run(revision,contract);
    calls.length=0;await assert.rejects(requireSchema(env),{message:'schema_update_required'});
    assert.deepEqual(calls,[SCHEMA_READ]);
  }
});
test('ordinary readiness reads never install tables, rebuild indexes or change saved state',async t=>{
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const calls=[],db=sqliteD1(sql,q=>calls.push(q));await prepareDatabase(db);
  sql.exec("INSERT INTO accounts(id,token_hash,recovery_hash,units) VALUES('saved','original-token','saved-code',123456)");
  sql.exec("INSERT INTO searches(id,account_id,idempotency_key,query,result_json) VALUES('paid','saved','saved-request','private prompt','saved map')");
  const before=sql.prepare("SELECT * FROM accounts").all(),result=sql.prepare('SELECT * FROM searches').all();
  calls.length=0;await Promise.all(Array.from({length:100},()=>requireSchema({DB:db})));
  assert.equal(calls.length,100);assert.ok(calls.every(q=>q===SCHEMA_READ));
  assert.deepEqual(sql.prepare('SELECT * FROM accounts').all(),before);assert.deepEqual(sql.prepare('SELECT * FROM searches').all(),result);
});
test('explicit checkpoint validates complete columns and exact deletion fences before marking readiness',async t=>{
  for(const damage of [
    sql=>sql.exec('DROP TRIGGER ledger_active_account_insert'),
    sql=>{sql.exec('DROP TRIGGER ledger_active_account_insert');sql.exec("CREATE TRIGGER ledger_active_account_insert BEFORE INSERT ON ledger BEGIN SELECT 1; END");},
    sql=>sql.exec('ALTER TABLE account_artifact_writes RENAME COLUMN sha256 TO missing_digest')
  ]) {
    const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());const db=sqliteD1(sql);
    await prepareDatabase(db);sql.exec('DELETE FROM community_schema_revision');damage(sql);
    await assert.rejects(db.batch(SCHEMA_REVISION_SQL.map(q=>db.prepare(q))));
    assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM community_schema_revision').get().n,0);
    await assert.rejects(requireSchema({DB:db}),{message:'schema_update_required'});
  }
});
test('repeated explicit checkpoint preserves credits, deletion and future revisions',async t=>{
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());const db=sqliteD1(sql);
  await prepareDatabase(db);
  sql.exec("INSERT INTO accounts(id,token_hash,units,deleted_at) VALUES('deleted','revoked',0,10)");
  await db.batch(SCHEMA_REVISION_SQL.map(q=>db.prepare(q)));await requireSchema({DB:db});
  assert.equal(sql.prepare("SELECT deleted_at FROM accounts WHERE id='deleted'").get().deleted_at,10);
  sql.exec("UPDATE community_schema_revision SET revision=2");
  await assert.rejects(db.batch(SCHEMA_REVISION_SQL.map(q=>db.prepare(q))));
  assert.equal(sql.prepare('SELECT revision FROM community_schema_revision').get().revision,2);
});
