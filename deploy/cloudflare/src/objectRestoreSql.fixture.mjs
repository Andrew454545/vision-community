// Synthetic inference/units only. Real files and cancellation repair.
import {DatabaseSync} from 'node:sqlite';
import {join} from 'node:path';
import {readFileSync,writeFileSync} from 'node:fs';
import {makeFixture,ledgerArgs,account,other,lease,sha,now} from './objectCancellationRestore.fixture.mjs';
import {prepareObjectCancellationRestore} from '../tools/object-cancellation-restore.mjs';
import {prepareObjectAuditRecovery} from '../tools/prepare-object-audit-recovery.mjs';
import {recoverObjectAudit} from './objectAuditRecovery.js';
import {prepareObjectSettlement} from '../tools/prepare-object-settlement.mjs';
export {account,other,lease,sha,now};
export async function makeObjectSqlFixture(root,phase='submitted',recovery=false,captureTime=now+2,accepted=false){
  const current=new DatabaseSync(':memory:');await makeFixture(current,'cancelled');const args=ledgerArgs(current);current.close();
  const ledger=JSON.parse(args.ledgerRaw);ledger.exportedAt=captureTime;args.ledgerRaw=Buffer.from(JSON.stringify(ledger)+'\n');
  args.ledgerSha256=sha(args.ledgerRaw);args.notBefore=captureTime;args.now=captureTime;
  const cancellations=join(root,'cancellations.private.json');writeFileSync(cancellations,args.ledgerRaw,{flag:'wx',mode:0o600});
  const backup=join(root,'backup.sqlite'),sql=new DatabaseSync(backup);
  try{
    const fixture=await makeFixture(sql,phase);
    if(phase!=='empty'){
      if(recovery){
        await prepareObjectAuditRecovery(fixture.env.DB);
        sql.exec("UPDATE object_audit_candidates SET transport_failures=8,last_error='preserved-original-connection-failure'");
        await recoverObjectAudit(fixture.env,account,lease,{action:'resume-transport',requestId:'8'.repeat(64)},now+1);
      }
      sql.exec("UPDATE object_audit_candidates SET native_state='approved',receipt_sha256='synthetic-old-approval',native_attempts=1,last_error='preserved-native-failure'");
      sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,queue_state,contributor_id,lat,lon,heading) VALUES (2,'synthetic-kept','fixture','object','synthetic','published','published',?,?,?,?)").run(other,1.0000000000000002,0.10000000000000002,Math.PI);
      sql.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (2,'synthetic','fixture',1000,?)").run('object-index-v4/'+other+'/');
      sql.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES (?,17,'synthetic fixture','synthetic-credit')").run(other);
      sql.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES (?,-10,'synthetic search','synthetic-debit')").run(other);
      sql.prepare("INSERT INTO searches VALUES ('kept',?,'kept',?,X'00FF27')").run(other,"synthetic private ' quote;\nNUL\0 🍀");
      sql.exec("UPDATE sqlite_sequence SET seq=9007199254740993 WHERE name='locations'");
      if(accepted){
        await prepareObjectSettlement(fixture.env.DB);
        sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',999999)").run(other,other);
        sql.prepare('INSERT INTO lease_items VALUES (?,2)').run(other);
        sql.prepare(`INSERT INTO object_audit_candidates(lease_id,account_id,profile_id,policy_id,assignment_sha256,
          source_sha256,submission_sha256,artifact_key,payload_bytes,location_count,created_at,state,
          job_id,candidate_manifest_sha256,native_state,receipt_sha256,native_attempts,last_error)
          VALUES (?,?,'saved-profile','saved-policy','saved-assignment','saved-source','saved-submission',
          'retained-private-key',1,1,?,'pending','saved-job','saved-candidate','approved','saved-receipt',1,'original failure retained')`)
          .run(other,other,now);
        sql.prepare("UPDATE leases SET state='submitted' WHERE id=?").run(other);
        sql.prepare(`INSERT INTO object_acceptances SELECT lease_id,account_id,?,1,10,?,profile_id,policy_id,
          'saved-policy-pin','saved-runtime-pin','saved-quality-pin','saved-protected-pin','saved-origin-pin',
          assignment_sha256,source_sha256,submission_sha256,candidate_manifest_sha256,job_id,native_attempts,
          receipt_sha256,'saved-snapshot-pin','saved-artifacts-pin' FROM object_audit_candidates WHERE lease_id=?`)
          .run('e'.repeat(32),now,other);
        sql.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES (?,10,'verified_work',?)").run(other,'lease:'+other);
        sql.prepare('UPDATE accounts SET units=units+10 WHERE id=?').run(other);
        sql.prepare('DELETE FROM object_dispatch_slots WHERE lease_id=?').run(other);
      }
    }
  }finally{sql.close();}
  const backupSha256=sha(readFileSync(backup)),repairedDir=join(root,'repaired');
  prepareObjectCancellationRestore({backup,backupSha256,cancellations,cancellationsSha256:args.ledgerSha256,
    notBefore:args.notBefore,now:args.now,environment:'staging',out:repairedDir});
  return {repairedDir,reportSha256:sha(readFileSync(join(repairedDir,'restore-report.json'))),cancellations,
    cancellationsSha256:args.ledgerSha256,notBefore:args.notBefore,now:args.now,environment:'staging',backup,backupSha256};
}
