// Actual closed Node SQLite -> pinned export -> Python restore input.
// Only test fixture identities/payloads; no provider calls or native inference.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectAuditCancellation} from './prepare-object-audit-cancellation.mjs';
import {sqliteD1} from './sqlite-d1.mjs';
import {stageObjectAudit} from '../src/objectAuditDispatch.js';
import {cancelObjectAudit} from '../src/objectAuditCancellation.js';
import {syntheticR2} from '../src/syntheticR2.mjs';
import {COVERAGE_VALIDATOR} from '../src/objectCoverage.js';
import {exportDeletionLedger} from './account-restore.mjs';
import {exportObjectCancellationLedger} from './object-cancellation-authority.mjs';
import {prepareObjectErasureRecovery} from './object-erasure-recovery.mjs';
import {prepareObjectCancellationRestore} from './object-cancellation-restore.mjs';
const [inputPath,out]=process.argv.slice(2),input=JSON.parse(readFileSync(inputPath,'utf8'));
const account='a'.repeat(32),lease=input.authority.leaseId,sha=raw=>createHash('sha256').update(raw).digest('hex');
const encoded=value=>Buffer.from(JSON.stringify(value)+'\n');
mkdirSync(out,{mode:0o700});const current=join(out,'current.sqlite'),sql=new DatabaseSync(current);
let deletionLedgerRaw,cancellationLedgerRaw;
try{
  const env={DB:sqliteD1(sql),INDEX:syntheticR2(new Map())};
  await prepareDatabase(env.DB);await prepareObjectAuditCancellation(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-session',10)").run(account);
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',9999)").run(lease,account);
  for(const item of input.items){
    sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (?,?,'synthetic','object','synthetic','leased',?,'gen4')")
      .run(item.locationId,item.panoId,lease);
    sql.prepare('INSERT INTO lease_items VALUES (?,?)').run(lease,item.locationId);
    sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,1000)').run(item.locationId,COVERAGE_VALIDATOR,'f'.repeat(64));
  }
  await stageObjectAudit(env,account,input.authority,input.objectIndex,1000);
  sql.prepare('VACUUM INTO ?').run(join(out,'old-hosted-copy.sqlite'));
  await cancelObjectAudit(env,account,lease,'7'.repeat(64),1001);
  assert.equal(sql.prepare('SELECT job_id FROM object_audit_candidates').get().job_id,null);
  cancellationLedgerRaw=encoded(exportObjectCancellationLedger(sql,1002,'staging'));
  deletionLedgerRaw=encoded(exportDeletionLedger(sql,1002,'staging'));
}finally{sql.close();}
const deletions=join(out,'current-deletions.private.json'),cancellations=join(out,'current-cancellations.private.json');
writeFileSync(deletions,deletionLedgerRaw,{flag:'wx',mode:0o600});writeFileSync(cancellations,cancellationLedgerRaw,{flag:'wx',mode:0o600});
const currentReport=prepareObjectErasureRecovery({current,currentSha256:sha(readFileSync(current)),registry:input.registry,
  registrySha256:sha(readFileSync(input.registry)),policySha256:input.policySha256,deletions,deletionsSha256:sha(deletionLedgerRaw),
  cancellations,cancellationsSha256:sha(cancellationLedgerRaw),notBefore:1002,now:1002,environment:'staging',out:join(out,'export-current')});
const oldHosted=join(out,'old-hosted-copy.sqlite'),oldHostedSha256=sha(readFileSync(oldHosted));
const restored=join(out,'repaired-hosted');
const repair=prepareObjectCancellationRestore({backup:oldHosted,backupSha256:oldHostedSha256,cancellations,
  cancellationsSha256:sha(cancellationLedgerRaw),notBefore:1002,now:1002,environment:'staging',out:restored});
assert.equal(repair.existingCandidates,1);assert.equal(repair.protectedStatePreserved,true);assert.equal(repair.nativeCleanupPending,true);
const report=prepareObjectErasureRecovery({current:join(restored,'restored.sqlite'),currentSha256:repair.databaseSha256,registry:input.registry,
  registrySha256:sha(readFileSync(input.registry)),policySha256:input.policySha256,deletions,deletionsSha256:sha(deletionLedgerRaw),
  cancellations,cancellationsSha256:sha(cancellationLedgerRaw),notBefore:1002,now:1002,environment:'staging',out:join(out,'export')});
assert.equal(report.authoritySha256,currentReport.authoritySha256);assert.equal(sha(readFileSync(oldHosted)),oldHostedSha256);
const value=JSON.parse(readFileSync(join(out,'export/object-erasure-authority.private.json')));
assert.equal(value.version,2);assert.equal(value.cancellations.length,1);assert.equal(value.revocations.length,0);
const check=new DatabaseSync(current,{readOnly:true});
try{
  const row=check.prepare('SELECT units,deleted_at FROM accounts WHERE id=?').get(account);
  assert.equal(row.units,10);assert.equal(row.deleted_at,null);assert.equal(check.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
}finally{check.close();}
console.log(JSON.stringify({status:'NODE_CURRENT_CANCELLATION_AUTHORITY_EXPORTED',version:2,revokedAssignments:report.revokedAssignments,
  cancelledAssignments:report.cancelledAssignments,authoritySha256:report.authoritySha256,
  oldHostedCopyPreserved:true,oldHostedCopyRepairedBeforeNativeExport:true,oldHostedBackupSha256:oldHostedSha256,
  sameAuthorityAsIndependentCurrent:true,accountActive:true,bankedUnits:10,hostedJobIdUnknown:true,
  liveCalls:0,earnedCredits:0,syntheticInference:true,nativeInferences:0}));
