// Synthetic legacy state shared by SQLite and actual workerd/D1 checks.
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { initializeSchema } from '../tools/initialize-schema.mjs';
import { sqliteD1 } from '../tools/sqlite-d1.mjs';

export async function legacyFixture(file, {deployedShape = false} = {}) {
  const sql = new DatabaseSync(file);
  if (deployedShape) {
    sql.exec(readFileSync(new URL('../fixtures/legacy-20261009.sql', import.meta.url), 'utf8'));
  } else {
    await initializeSchema({DB:sqliteD1(sql)});
    for (const {name} of sql.prepare("SELECT name FROM sqlite_master WHERE type='trigger'").all()) sql.exec(`DROP TRIGGER "${name}"`);
    for (const name of ['account_deletion_archives','account_deletion_receipts','account_cleanup','account_artifact_writes','scene_candidates','scene_qualifications','object_coverage']) sql.exec(`DROP TABLE ${name}`);
    sql.exec('ALTER TABLE accounts DROP COLUMN deleted_at; ALTER TABLE leases DROP COLUMN scene_qualification_id');
    for (const name of ['four_view_key','four_view_sha256','object_index_key','object_index_sha256']) {
      if (name === 'four_view_key') sql.exec('DROP INDEX published_index_four_view_key');
      sql.exec(`ALTER TABLE published_index DROP COLUMN ${name}`);
    }
  }
  sql.exec("INSERT INTO accounts(id,token_hash,recovery_hash,units) VALUES('saved','retained-token','retained-code',100001)");
  sql.exec("INSERT INTO ledger(id,account_id,units,reason,reference) VALUES(99,'saved',1,'contribution','earned-once')");
  sql.prepare("INSERT INTO searches VALUES('paid','saved','paid-key',?,?)").run('private café; BEGIN;\0prompt','map;\0Ω');
  sql.exec("INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,output_sha256) VALUES(22,'pano','capture','scene','native','published','saved','original-digest')");
  sql.exec("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,embedding,segment_id) VALUES(22,'retained index','original-digest',100,'retained vector','retained segment')");
  sql.exec("INSERT INTO leases(id,account_id,lane,expires_at,state,generation,pace) VALUES('unfinished','saved','scene',123,'active',4,'medium'); INSERT INTO lease_items VALUES('unfinished',22)");
  sql.exec("INSERT INTO locations(id,asset_id,capture,lane,model) VALUES(100,'deleted-high-water','c','scene','native'); DELETE FROM locations WHERE id=100");
  sql.close();
}
