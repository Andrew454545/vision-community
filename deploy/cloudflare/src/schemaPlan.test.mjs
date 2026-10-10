import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {freshPlan,checkpointPlan,sqlFile} from '../tools/schema-plan.mjs';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {requireSchema} from './schemaRevision.js';

test('fresh generated SQL builds an empty database with verified privacy fences and rejects nonempty data atomically',async t=>{
  const plan=await freshPlan();
  for(const populated of [false,true]) {
    const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());const db=sqliteD1(sql);
    if(populated)sql.exec("CREATE TABLE saved_work(code TEXT);INSERT INTO saved_work VALUES('private saved state')");
    if(populated) {
      await assert.rejects(db.batch(plan.map(q=>db.prepare(q))));
      assert.equal(sql.prepare('SELECT code FROM saved_work').get().code,'private saved state');
      assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name='accounts'").get().n,0);
    }else{
      await db.batch(plan.map(q=>db.prepare(q)));await requireSchema({DB:db});
      assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name='community_schema_install_guard'").get().n,0);
    }
  }
});
test('the checked-in current-schema checkpoint is exactly the generated data-free maintenance SQL',()=>{
  assert.equal(readFileSync(new URL('../migrations/0004_schema_revision.sql',import.meta.url),'utf8').replaceAll('\r',''),sqlFile(checkpointPlan()));
});
test('checkpointing an existing current schema preserves recovery, saved paid maps and credit history',async t=>{
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());const db=sqliteD1(sql);
  await db.batch((await freshPlan()).map(q=>db.prepare(q)));
  sql.exec("INSERT INTO accounts(id,token_hash,recovery_hash,units) VALUES('saved','original-token','private-code',100001)");
  sql.exec("INSERT INTO ledger(account_id,units,reason,reference) VALUES('saved',1,'contribution','earned-once')");
  sql.exec("INSERT INTO searches(id,account_id,idempotency_key,query,result_json) VALUES('paid','saved','paid-key','private prompt','saved map')");
  sql.exec('DROP TABLE community_schema_revision');
  const snapshot=()=>['accounts','ledger','searches'].map(table=>sql.prepare('SELECT * FROM '+table).all());
  const before=snapshot();await db.batch(checkpointPlan().map(q=>db.prepare(q)));await requireSchema({DB:db});
  assert.deepEqual(snapshot(),before);
});
