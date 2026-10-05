// Generates data-free SQL locally. Does not log in, query or modify Cloudflare.
import {DatabaseSync} from 'node:sqlite';
import {writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {parseArgs} from 'node:util';
import {sqliteD1} from './sqlite-d1.mjs';
import {prepareDatabase} from './initialize-schema.mjs';
import {SCHEMA_REVISION_SQL} from '../src/schemaRevision.js';

export function checkpointPlan() {
  return ['CREATE INDEX IF NOT EXISTS scene_qualifications_lookup ON scene_qualifications(account_id,policy_id,profile_id,expires_at)',...SCHEMA_REVISION_SQL];
}
export async function freshPlan() {
  const sql=new DatabaseSync(':memory:'),statements=[];
  try {
    const db=sqliteD1(sql,q=>{if(/^\s*(CREATE|ALTER|INSERT|UPDATE|DROP)\b/i.test(q))statements.push(q);});
    await prepareDatabase(db);
  } finally {sql.close();}
  // Refuse existing application tables before any setup statement can run.
  return [
    'CREATE TABLE community_schema_install_guard(value INTEGER NOT NULL CHECK(value=1))',
    "INSERT INTO community_schema_install_guard SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%' AND name NOT IN ('d1_migrations','community_schema_install_guard')) THEN 1 ELSE 0 END",
    ...statements,'DROP TABLE community_schema_install_guard'
  ];
}
export function sqlFile(statements) {return '-- Explicit maintenance SQL. Validate the confirmed database binding first.\n'+statements.map(q=>q.trim().replace(/;$/,'')+';').join('\n\n')+'\n';}
if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const {values}=parseArgs({options:{fresh:{type:'boolean'},checkpoint:{type:'boolean'},output:{type:'string'}}});
    if(Boolean(values.fresh)===Boolean(values.checkpoint)||!values.output) throw Error('choose_one_plan');
    const statements=values.fresh?await freshPlan():checkpointPlan();
    writeFileSync(resolve(values.output),sqlFile(statements),{flag:'wx',mode:0o600});
    console.log(JSON.stringify({status:'OFFLINE_SCHEMA_PLAN_SAVED',kind:values.fresh?'fresh-empty-database-only':'checkpoint-existing-current-schema',
      statements:statements.length,cloudResourcesAccessed:false}));
  } catch {console.error('Choose --fresh or --checkpoint and a new --output file. Existing files are preserved.');process.exitCode=1;}
}
