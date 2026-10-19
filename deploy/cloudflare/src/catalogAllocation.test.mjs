import assert from 'node:assert/strict';
import test from 'node:test';
import {DatabaseSync} from 'node:sqlite';
import {availableCatalogSql, availableLocationSql, freshLeaseItemSql, RETIRED_CATALOG_PREFIXES} from './catalogAllocation.js';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {prepareDatabase} from '../tools/initialize-schema.mjs';

async function fixture() {
  const sql=new DatabaseSync(':memory:'),db=sqliteD1(sql);await prepareDatabase(db);
  await db.prepare("INSERT INTO accounts(id,token_hash,units) VALUES('account','saved-token',17)").run();
  let id=0;
  async function catalog(key,held=0,lane='scene') {
    const shard=++id;
    await db.prepare('INSERT INTO pose_catalog(lane,shard_id,r2_key,row_start,row_count,bytes,sha256,held) VALUES(?,?,?,0,1,1,?,?)')
      .bind(lane,shard,key,'a'.repeat(64),held).run();return shard;
  }
  async function location(shard,options={}) {
    const number=++id;
    await db.prepare('INSERT INTO locations(id,asset_id,capture,lane,model,catalog_shard,state,lease_until,queue_state) VALUES(?,?,?,?,?,?,?,?,?)')
      .bind(number,'fixture-pano-'+number,'unknown',options.lane||'scene','fixture-model',shard,
        options.state||'pending',options.leaseUntil??null,options.queueState||'pending').run();return number;
  }
  return {sql,db,catalog,location};
}

for(const prefix of RETIRED_CATALOG_PREFIXES) test('retired family stays unavailable after a hold is cleared: '+prefix,async()=>{
  const {sql,db,catalog,location}=await fixture();
  try {
    const shard=await catalog(prefix+'immutable/shard.tsv',1);const row=await location(shard);
    for(const held of [1,0]) {
      await db.prepare('UPDATE pose_catalog SET held=? WHERE shard_id=?').bind(held,shard).run();
      assert.equal(await db.prepare(`SELECT id FROM locations WHERE id=? AND ${availableLocationSql()}`).bind(row).first(),null);
      assert.equal(await db.prepare(`SELECT shard_id FROM pose_catalog WHERE ${availableCatalogSql()}`).first(),null);
    }
  } finally {sql.close();}
});

test('pending rows require a same-lane registered non-held allocation; prepared pools remain available',async()=>{
  const {sql,db,catalog,location}=await fixture();
  try {
    const good=await catalog('catalog/official-remaining-v1/pinned/shard.tsv');
    const held=await catalog('catalog/official-remaining-v1/pinned/held.tsv',1);
    const otherLane=await catalog('catalog/official-remaining-v1/pinned/object.tsv',0,'object');
    const allowed=[await location(good),await location(null)];
    for(const shard of [held,otherLane,999]) await location(shard);
    assert.deepEqual((await db.prepare(`SELECT id FROM locations WHERE ${availableLocationSql()} ORDER BY id`).all()).results.map(r=>r.id),allowed);
  } finally {sql.close();}
});

for(const invalidation of ['late-hold','retired-key','competing-lease','skipped','published','registration-removed'])
  test('lease transaction rolls back every row after '+invalidation,async()=>{
    const {sql,db,catalog,location}=await fixture();
    try {
      const shard=await catalog('catalog/official-remaining-v1/pinned/part.tsv');
      const first=await location(null),second=await location(shard);
      if(invalidation==='late-hold') await db.prepare('UPDATE pose_catalog SET held=1 WHERE shard_id=?').bind(shard).run();
      if(invalidation==='retired-key') await db.prepare('UPDATE pose_catalog SET r2_key=? WHERE shard_id=?').bind(RETIRED_CATALOG_PREFIXES[0]+'old.tsv',shard).run();
      if(invalidation==='registration-removed') await db.prepare('DELETE FROM pose_catalog WHERE shard_id=?').bind(shard).run();
      if(invalidation==='competing-lease') await db.prepare("UPDATE locations SET state='leased',active_lease='other',lease_until=2000 WHERE id=?").bind(second).run();
      if(invalidation==='skipped') await db.prepare("UPDATE locations SET queue_state='skipped' WHERE id=?").bind(second).run();
      if(invalidation==='published') await db.prepare("UPDATE locations SET state='published' WHERE id=?").bind(second).run();
      const before=(await db.prepare('SELECT * FROM locations ORDER BY id').all()).results;
      const statements=[db.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES('fresh','account','scene',3000,'active')")];
      for(const id of [first,second]) {
        statements.push(db.prepare(freshLeaseItemSql()).bind('fresh',id,1000));
        statements.push(db.prepare("UPDATE locations SET state='leased',active_lease='fresh',lease_until=3000 WHERE id=?").bind(id));
      }
      await assert.rejects(db.batch(statements),/NOT NULL constraint failed: lease_items.location_id/);
      assert.deepEqual((await db.prepare('SELECT * FROM locations ORDER BY id').all()).results,before);
      for(const table of ['leases','lease_items','ledger','published_index']) assert.equal((await db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).first()).n,0);
      assert.equal((await db.prepare("SELECT units FROM accounts WHERE id='account'").first()).units,17);
    } finally {sql.close();}
  });

test('an expired eligible row can be leased again atomically',async()=>{
  const {sql,db,catalog,location}=await fixture();
  try {
    const shard=await catalog('catalog/official-remaining-v1/pinned/part.tsv');
    const id=await location(shard,{state:'leased',leaseUntil:999});
    await db.batch([db.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES('new','account','scene',3000,'active')"),
      db.prepare(freshLeaseItemSql()).bind('new',id,1000)]);
    assert.equal((await db.prepare("SELECT location_id FROM lease_items WHERE lease_id='new'").first()).location_id,id);
  }finally{sql.close();}
});

test('SQL aliases cannot inject query text',()=>{
  assert.throws(()=>availableCatalogSql('allocation; DROP TABLE accounts'));
  assert.throws(()=>availableLocationSql('locations WHERE 1=1'));
});
