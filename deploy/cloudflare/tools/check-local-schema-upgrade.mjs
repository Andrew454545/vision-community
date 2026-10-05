// Actual local workerd/D1. Synthetic accounts only; no Cloudflare access.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {basename,dirname,join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {legacyFixture} from '../src/schemaUpgrade.fixture.mjs';
import {rehearseUpgrade} from './upgrade-schema.mjs';
import {requireSchema} from '../src/schemaRevision.js';

const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(process.argv[2])));
const parent=resolve(tmpdir()),root=mkdtempSync(join(parent,'vision-local-schema-upgrade-'));
let mf,sql;
try {
  const input=join(root,'legacy.sqlite'),out=join(root,'upgrade');
  await legacyFixture(input);
  const pin=createHash('sha256').update(readFileSync(input)).digest('hex');
  await rehearseUpgrade({database:input,databaseSha256:pin,out});
  const batch=JSON.parse(readFileSync(join(out,'query-batch.private.json'))).batch;
  sql=new DatabaseSync(input,{readOnly:true});
  const tables=sql.prepare("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT GLOB 'sqlite_*' ORDER BY name").all();
  const indexes=sql.prepare("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name").all();
  const seed=tables.map(row=>row.sql);
  for(const {name} of tables) {
    const columns=sql.prepare(`PRAGMA table_info(${name})`).all().map(row=>row.name);
    const values=columns.map(column=>`CASE WHEN typeof(${column})='text' THEN 'CAST(X'''||hex(CAST(${column} AS BLOB))||''' AS TEXT)' ELSE quote(${column}) END AS ${column}`);
    for(const row of sql.prepare(`SELECT ${values.join(',')} FROM ${name}`).all())seed.push(`INSERT INTO ${name} (${columns.join(',')}) VALUES (${columns.map(column=>row[column]).join(',')})`);
  }
  seed.push(...indexes.map(row=>row.sql),"UPDATE sqlite_sequence SET seq=100 WHERE name='locations'");
  sql.close();sql=null;
  mf=new Miniflare(convertV4MiniflareOptions({modules:true,script:'export default {fetch(){return new Response("finite schema check")}}',
    compatibilityDate:'2026-09-19',d1Databases:['DB']}));
  const db=await mf.getD1Database('DB');
  await db.batch(seed.map(query=>db.prepare(query)));
  const snapshot=async()=>({schema:(await db.prepare("SELECT name,sql FROM sqlite_master WHERE name NOT GLOB '_cf_*' ORDER BY name").all()).results,
    account:await db.prepare('SELECT * FROM accounts').first(),paid:await db.prepare('SELECT hex(CAST(query AS BLOB)) AS query,hex(CAST(result_json AS BLOB)) AS result FROM searches').first(),
    publication:await db.prepare('SELECT * FROM published_index').first(),credit:await db.prepare('SELECT * FROM ledger').first(),
    sequence:await db.prepare("SELECT seq FROM sqlite_sequence WHERE name='locations'").first()});
  const before=await snapshot();
  await assert.rejects(db.batch([...batch.map(({sql})=>db.prepare(sql)),db.prepare('INSERT INTO missing_table VALUES(1)')]));
  assert.deepEqual(await snapshot(),before);
  await db.prepare('CREATE TABLE unexpected_schema(value TEXT)').run();
  const changed=await snapshot();
  await assert.rejects(db.batch(batch.map(({sql})=>db.prepare(sql))));
  assert.deepEqual(await snapshot(),changed);
  await db.prepare('DROP TABLE unexpected_schema').run();
  await db.batch(batch.map(({sql})=>db.prepare(sql)));
  await requireSchema({DB:db});
  const after=await snapshot();
  assert.equal(after.account.units,before.account.units);assert.equal(after.account.token_hash,before.account.token_hash);
  assert.equal(after.account.recovery_hash,before.account.recovery_hash);assert.deepEqual(after.paid,before.paid);
  assert.deepEqual(after.credit,before.credit);assert.equal(after.publication.embedding,before.publication.embedding);
  assert.deepEqual(after.sequence,before.sequence);
  await db.prepare("UPDATE accounts SET units=0,recovery_hash=NULL,deleted_at=10 WHERE id='saved'").run();
  await assert.rejects(db.prepare("UPDATE accounts SET deleted_at=NULL WHERE id='saved'").run(),/account_not_active/);
  await assert.rejects(db.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES('saved',1,'late','duplicate-credit')").run(),/account_not_active/);
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_LEGACY_SCHEMA_UPGRADE_PASSED',failedBatchRolledBack:true,schemaMismatchRefused:true,
    creditsCredentialsPaidMapsPublicationsPreserved:true,privacyFencesChecked:true,liveImport:false}));
}finally{
  if(sql)sql.close();if(mf)await mf.dispose();
  if(dirname(resolve(root))!==parent||!basename(root).startsWith('vision-local-schema-upgrade-'))throw Error('unsafe_test_cleanup');
  rmSync(root,{recursive:true});
}
