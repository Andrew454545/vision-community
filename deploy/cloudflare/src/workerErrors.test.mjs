import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';
import worker from './worker.js';
import { prepareDatabase } from '../tools/initialize-schema.mjs';

function database(sql) {
  let failure = null;
  return { fail(pattern) {failure=pattern;}, prepare(query) {
    const statement = (args=[]) => ({bind:(...bound)=>statement(bound),
      first:async()=>sql.prepare(query).get(...args)||null,
      all:async()=>({results:sql.prepare(query).all(...args)}),
      run:async()=>{
        if (failure?.test(query)) throw Error('PRIVATE database diagnostic and synthetic credential');
        const result=sql.prepare(query).run(...args);
        return {success:true,meta:{changes:Number(result.changes)}};
      }});
    return statement();
  },async batch(statements) {
    sql.exec('BEGIN IMMEDIATE');
    try {const values=[];for(const statement of statements) values.push(await statement.run());sql.exec('COMMIT');return values;}
    catch(error) {sql.exec('ROLLBACK');throw error;}
  }};
}
function post(path, body) {
  return new Request('https://community.test/api/'+path,{method:'POST',
    headers:{'content-type':'application/json',origin:'https://community.test'},body:JSON.stringify(body)});
}
test('asynchronous account-write failures return redacted JSON and do not create an account',async t=>{
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const db=database(sql);await prepareDatabase(db);db.fail(/^INSERT INTO accounts /);
  const response=await worker.fetch(post('accounts',{}),{DB:db});
  assert.equal(response.status,500);assert.deepEqual(await response.json(),{error:'internal_error'});
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM accounts').get().n,0);
});
test('asynchronous recovery failure preserves existing access and credit without raw diagnostics',async t=>{
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const db=database(sql),env={DB:db};
  await prepareDatabase(db);
  const created=await worker.fetch(post('accounts',{}),env);
  assert.equal(created.status,201);
  const account=await created.json();
  const original=sql.prepare('SELECT token_hash,units FROM accounts WHERE id=?').get(account.accountId);
  db.fail(/^UPDATE accounts SET token_hash=/);
  const response=await worker.fetch(post('recovery',{recoveryCode:account.recoveryCode}),env);
  assert.equal(response.status,500);assert.deepEqual(await response.json(),{error:'internal_error'});
  assert.deepEqual(sql.prepare('SELECT token_hash,units FROM accounts WHERE id=?').get(account.accountId),original);
});
