// Offline legacy upgrade rehearsal. No provider access or live database writes.
import { createHash } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { constants, copyFileSync, existsSync, lstatSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { initializeSchema } from './initialize-schema.mjs';
import { sqliteD1 } from './sqlite-d1.mjs';
import { sqlFile } from './schema-plan.mjs';
import { requireSchema, SCHEMA_REVISION_SQL } from '../src/schemaRevision.js';

const MAX_DATABASE = 512 * 1024 * 1024;
const HEX = /^[a-f0-9]{64}$/;
const TABLES = new Set(['accounts','locations','leases','lease_items','published_index','ledger','searches',
  'pose_catalog','index_shards','object_coverage','scene_qualifications','scene_candidates',
  'account_artifact_writes','account_deletion_receipts','account_cleanup','account_deletion_archives',
  'community_schema_revision']);
const quote = value => "'" + value.replaceAll("'", "''") + "'";
const identifier = value => '"' + value.replaceAll('"', '""') + '"';
const hash = raw => createHash('sha256').update(raw).digest('hex');
const sidecars = file => ['-wal','-shm','-journal'].some(suffix => existsSync(file + suffix));
const encoded = value => JSON.stringify(value) + '\n';
const fail = code => { throw new UpgradeError(code); };
export class UpgradeError extends Error {}

function checkInput(file, pin) {
  if (!HEX.test(pin || '')) fail('invalid_checksum_pin');
  if (!lstatSync(file).isFile() || lstatSync(file).size > MAX_DATABASE) fail('invalid_database_file');
  if (sidecars(file)) fail('database_not_closed');
  if (hash(readFileSync(file)) !== pin) fail('input_checksum_mismatch');
}
function schema(sql) {
  return sql.prepare("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' AND name NOT GLOB '_cf_*' AND name!='d1_migrations' ORDER BY type,name").all();
}
function checkSchema(rows) {
  if (!rows.length || rows.some(row => !['table','index','trigger'].includes(row.type) || !row.sql
      || !TABLES.has(row.tbl_name))) fail('unsupported_upgrade_schema');
  if (!['accounts','locations','leases','lease_items','published_index','ledger','searches','pose_catalog','index_shards']
      .every(name => rows.some(row => row.type === 'table' && row.name === name))) fail('unsupported_upgrade_schema');
}
function validDatabase(sql) {
  if (sql.prepare('PRAGMA integrity_check').all().some(row => row.integrity_check !== 'ok')
      || sql.prepare('PRAGMA foreign_key_check').all().length) fail('database_integrity_failure');
}
function historicalTables(sql, rows) {
  return rows.filter(row => row.type === 'table' && row.name !== 'community_schema_revision').map(row => {
    const columns = sql.prepare(`PRAGMA table_xinfo(${identifier(row.name)})`).all();
    if (columns.some(column => column.hidden !== 0)) fail('unsupported_upgrade_schema');
    return { name: row.name, columns: columns.map(column => column.name) };
  });
}
function fingerprint(sql, table) {
  const expressions = table.columns.map(column => table.name === 'account_cleanup' && column === 'state'
    ? `CASE WHEN ${identifier(column)}='removed' THEN 'pending' ELSE ${identifier(column)} END` : identifier(column));
  // Read text as bytes: some Node SQLite versions truncate embedded NULs.
  const selections = expressions.flatMap((column,index) => [`typeof(${column}) AS t${index}`,
    `CASE WHEN typeof(${column}) IN ('text','blob') THEN hex(CAST(${column} AS BLOB)) ELSE ${column} END AS v${index}`]);
  const query = sql.prepare(`SELECT ${selections.join(',')} FROM ${identifier(table.name)} ORDER BY ${expressions.join(',')}`);
  query.setReadBigInts(true);
  const digest = createHash('sha256');
  let count = 0;
  for (const row of query.iterate()) {
    const values = table.columns.map((column,index) => {
      const type = row[`t${index}`], value = row[`v${index}`];
      if (type === 'integer') return [type,String(value)];
      if (type === 'real') {const bytes=Buffer.alloc(8);bytes.writeDoubleBE(value);return [type,bytes.toString('hex')];}
      return [type,value];
    });
    digest.update(encoded(values)); count++;
  }
  return { rows: count, sha256: digest.digest('hex') };
}
function sequence(sql) {
  const query = sql.prepare("SELECT name,seq FROM sqlite_sequence ORDER BY name");
  query.setReadBigInts(true);
  return query.all().map(row => ({ name:row.name, seq:String(row.seq) }));
}
function same(left, right) { return JSON.stringify(left) === JSON.stringify(right); }

// Guard the complete application schema, including existing trigger bodies.
// Data is deliberately absent: a fresh quiesced backup is still required at rollout.
export function schemaGuard(rows) {
  const predicates = rows.map(row => `EXISTS(SELECT 1 FROM sqlite_master WHERE type=${quote(row.type)} AND name=${quote(row.name)} AND tbl_name=${quote(row.tbl_name)} AND sql=${quote(row.sql)})`);
  return [
    'CREATE TABLE community_schema_upgrade_guard(value INTEGER NOT NULL CHECK(value=1))',
    `INSERT INTO community_schema_upgrade_guard SELECT CASE WHEN (SELECT COUNT(*) FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' AND name NOT GLOB '_cf_*' AND name NOT IN ('d1_migrations','community_schema_upgrade_guard'))=${rows.length} AND ${predicates.join(' AND ')} THEN 1 ELSE 0 END`
  ];
}

export async function rehearseUpgrade({ database, databaseSha256, out }) {
  const destination = resolve(out);
  mkdirSync(destination, { recursive: false, mode: 0o700 });
  let sql;
  try {
    const input = resolve(database);
    checkInput(input, databaseSha256);
    const copy = join(destination, 'upgraded.sqlite');
    copyFileSync(input, copy, constants.COPYFILE_EXCL);
    checkInput(copy, databaseSha256);
    sql = new DatabaseSync(copy, { allowExtension: false });
    sql.exec('PRAGMA trusted_schema=OFF; PRAGMA foreign_keys=ON');
    validDatabase(sql);
    const originalSchema = schema(sql); checkSchema(originalSchema);
    const tables = historicalTables(sql, originalSchema);
    const before = tables.map(table => ({ table:table.name, columns:table.columns, ...fingerprint(sql, table) }));
    const originalSequence = sequence(sql);
    const cleanupRequeued = originalSchema.some(row => row.name === 'account_cleanup')
      ? sql.prepare("SELECT COUNT(*) AS n FROM account_cleanup WHERE state='removed'").get().n : 0;
    const statements = [];
    const db = sqliteD1(sql, query => { if (/^\s*(CREATE|ALTER|INSERT|UPDATE|DROP)\b/i.test(query)) statements.push(query); });
    // Nested migration batches share this one offline transaction.
    db.batch = async items => { const results=[]; for (const item of items) results.push(await item.run()); return results; };
    sql.exec('BEGIN IMMEDIATE');
    try {
      await initializeSchema({ DB:db });
      for (const query of SCHEMA_REVISION_SQL) await db.prepare(query).run();
      await requireSchema({ DB:db });
      validDatabase(sql);
      if (cleanupRequeued && sql.prepare("SELECT 1 FROM account_cleanup WHERE state='removed' LIMIT 1").get()) fail('cleanup_requeue_not_performed');
      const after = tables.map(table => ({ table:table.name, columns:table.columns, ...fingerprint(sql, table) }));
      if (!same(before, after) || !same(originalSequence, sequence(sql))) fail('historical_data_changed');
      sql.exec('COMMIT');
    } catch (error) { sql.exec('ROLLBACK'); throw error; }
    sql.close(); sql = null;
    checkInput(input, databaseSha256);
    const plan = [...schemaGuard(originalSchema), ...statements, 'DROP TABLE community_schema_upgrade_guard'];
    const planFile = sqlFile(plan);
    if (Buffer.byteLength(planFile) > 1024 * 1024 || plan.length > 1000) fail('upgrade_plan_too_large');
    writeFileSync(join(destination,'upgrade.private.sql'), planFile, { flag:'wx', mode:0o600 });
    writeFileSync(join(destination,'query-batch.private.json'), encoded({batch:plan.map(query => ({sql:query,params:[]}))}), {flag:'wx',mode:0o600});
    const report = { version:1, scope:'offline-community-schema-upgrade', complete:true, liveReady:false,
      inputSha256:databaseSha256, databaseSha256:hash(readFileSync(copy)), sourceSchemaSha256:hash(encoded(originalSchema)),
      planSha256:hash(planFile), statements:plan.length, historicalTables:before,
      cleanupRequeued, preservedAutoincrement:true, cloudResourcesAccessed:false };
    writeFileSync(join(destination,'upgrade-report.private.json'), encoded(report), { flag:'wx',mode:0o600 });
    return report;
  } catch (error) {
    if (sql) { try {sql.close();} catch {} }
    const code = error instanceof UpgradeError ? error.message : 'upgrade_rehearsal_failed';
    writeFileSync(join(destination,'failure-report.private.json'), encoded({complete:false,liveReady:false,error:code}), {flag:'wx',mode:0o600});
    throw new UpgradeError(code);
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const {values} = parseArgs({options:{database:{type:'string'},'database-sha256':{type:'string'},out:{type:'string'}}});
    if (!values.database || !values['database-sha256'] || !values.out) fail('invalid_upgrade_arguments');
    const report = await rehearseUpgrade({database:values.database,databaseSha256:values['database-sha256'],out:values.out});
    console.log(encoded({complete:report.complete,liveReady:false,statements:report.statements,historicalTables:report.historicalTables.length,
      historicalRows:report.historicalTables.reduce((sum,table)=>sum+table.rows,0),cloudResourcesAccessed:false}));
  } catch (error) {console.error(encoded({complete:false,liveReady:false,error:error instanceof UpgradeError ? error.message : 'upgrade_rehearsal_failed'}));process.exitCode=1;}
}
