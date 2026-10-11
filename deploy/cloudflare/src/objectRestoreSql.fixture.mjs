// Synthetic inference/units only. Real files and cancellation repair.
import {DatabaseSync} from 'node:sqlite';
import {join} from 'node:path';
import {readFileSync,writeFileSync} from 'node:fs';
import {makeFixture,ledgerArgs,account,other,lease,sha,now} from './objectCancellationRestore.fixture.mjs';
import {prepareObjectCancellationRestore} from '../tools/object-cancellation-restore.mjs';
import {prepareObjectAuditRecovery} from '../tools/prepare-object-audit-recovery.mjs';
import {recoverObjectAudit} from './objectAuditRecovery.js';
export {account,other,lease,sha,now};
export async function makeObjectSqlFixture(root,phase='submitted',recovery=false,captureTime=now+2){
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
    }
  }finally{sql.close();}
  const backupSha256=sha(readFileSync(backup)),repairedDir=join(root,'repaired');
  prepareObjectCancellationRestore({backup,backupSha256,cancellations,cancellationsSha256:args.ledgerSha256,
    notBefore:args.notBefore,now:args.now,environment:'staging',out:repairedDir});
  return {repairedDir,reportSha256:sha(readFileSync(join(repairedDir,'restore-report.json'))),cancellations,
    cancellationsSha256:args.ledgerSha256,notBefore:args.notBefore,now:args.now,environment:'staging',backup,backupSha256};
}
