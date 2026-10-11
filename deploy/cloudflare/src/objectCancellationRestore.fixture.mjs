// Explicit synthetic source/units. Real SQLite, dispatch and cancellation code;
// no inference, provider calls or credited location contributions.
import {createHash} from 'node:crypto';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareObjectAuditCancellation} from '../tools/prepare-object-audit-cancellation.mjs';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {stageObjectAudit} from './objectAuditDispatch.js';
import {cancelObjectAudit} from './objectAuditCancellation.js';
import {syntheticR2} from './syntheticR2.mjs';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {exportObjectCancellationLedger} from '../tools/object-cancellation-authority.mjs';
export const account='a'.repeat(32),other='c'.repeat(32),lease='b'.repeat(32),now=1000;
export const encoded=value=>Buffer.from(JSON.stringify(value)+'\n');
export const sha=raw=>createHash('sha256').update(raw).digest('hex');
export const source=Buffer.from('synthetic source\n');
export const authority={leaseId:lease,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),sourceSha256:sha(source)};
export const objectIndex={manifest:{synthetic:true},files:{'synthetic.bin':''},sourceTsv:source.toString('base64')};
export async function makeFixture(sql,phase='submitted'){
  const r2=syntheticR2(new Map()),env={DB:sqliteD1(sql),OBJECT_VERIFIER:{fetch(){throw Error('unexpected native inference');}},
    INDEX:{...r2,async get(key){const v=await r2.get(key);return v?{...v,body:new Response(await v.arrayBuffer()).body}:null;}}};
  await prepareDatabase(env.DB);
  if(phase==='empty')return {sql,env};
  await prepareObjectAuditCancellation(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic',10)").run(account);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-other',7)").run(other);
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',9999)").run(lease,account);
  sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (1,'synthetic','fixture','object','synthetic','leased',?,'gen4')").run(lease);
  sql.prepare('INSERT INTO lease_items VALUES (?,1)').run(lease);
  sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,?)').run(1,COVERAGE_VALIDATOR,'f'.repeat(64),now);
  if(phase!=='active')await stageObjectAudit(env,account,authority,objectIndex,now);
  if(phase==='cancelled')await cancelObjectAudit(env,account,lease,'7'.repeat(64),now+1);
  return {sql,env};
}
export function ledgerArgs(sql){
  const ledgerRaw=encoded(exportObjectCancellationLedger(sql,now+2,'staging'));
  return {ledgerRaw,ledgerSha256:sha(ledgerRaw),notBefore:now+2,now:now+2,environment:'staging'};
}
