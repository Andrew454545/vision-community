// Offline cancellation repair only. Never certifies account deletion, finance,
// provider/native cleanup, or readiness, and never contacts a live binding.
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {closeSync,constants,copyFileSync,existsSync,fsyncSync,lstatSync,mkdirSync,openSync,readFileSync,readSync,writeFileSync} from 'node:fs';
import {dirname,join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {parseArgs} from 'node:util';
import {SCHEMA_CHECK} from '../src/schemaRevision.js';
import {OBJECT_DISPATCH_SCHEMA,OBJECT_DISPATCH_CONTRACT_SQL} from '../src/objectAuditDispatch.js';
import {OBJECT_CANCELLATION_SCHEMA,OBJECT_CANCELLATION_CONTRACT_SQL,objectCancellationPublicationSafe} from '../src/objectAuditCancellation.js';
import {OBJECT_CANCEL_RESTORE_SCHEMA,OBJECT_CANCEL_RESTORE_CONTRACT} from '../src/objectCancellationRestore.js';
import {indexArtifactIdentity,PRIVACY_FENCE} from '../src/artifactWrites.js';
import {RESOURCE_PROFILES} from './account-restore.mjs';
import {validateObjectCancellationLedger,readCancellationTombstones} from './object-cancellation-authority.mjs';

const HEX=/^[0-9a-f]{64}$/,MAX_DATABASE=512*1024**2,MAX_LEDGER=4*1024**2;
const sha=raw=>createHash('sha256').update(raw).digest('hex');
const encoded=value=>Buffer.from(JSON.stringify(value)+'\n');
const normalized=sql=>sql.replace(/IF NOT EXISTS/ig,'').replace(/[\s;]/g,'').toLowerCase();
const fields={requestId:'request_id',leaseId:'lease_id',accountId:'account_id',policyId:'policy_id',
  assignmentSha256:'assignment_sha256',submissionSha256:'submission_sha256',artifactKey:'artifact_key',
  payloadBytes:'payload_bytes',cancelledAt:'created_at'};
function require(value){if(!value)throw Error('invalid_object_cancellation_restore');}
const matches=(row,event)=>Object.entries(fields).every(([key,column])=>row[column]===event[key]);
function install(sql,statements){
  for(const statement of statements){
    const [,kind,name]=statement.match(/^CREATE (TABLE|INDEX|TRIGGER) IF NOT EXISTS (\w+)/);
    const prior=sql.prepare('SELECT type,sql FROM sqlite_master WHERE name=?').get(name);
    require(!prior || prior.type===kind.toLowerCase() && normalized(prior.sql)===normalized(statement));
    sql.exec(statement);
  }
}

// Hash complete protected rows inside the repair transaction. SQLite supplies
// exact type/byte encodings (including NULs, blobs and 64-bit integer literals),
// so unexpected trigger side effects cannot silently alter accepted work or
// money while a copy is labelled repaired. This is preservation, not an audit
// of the original financial history.
function protectedState(sql){
  const hash=createHash('sha256');
  for(const [table,order,where] of [['accounts','id',''],['ledger','id',''],['searches','id',''],
    ['published_index','location_id',''],['index_shards','r2_key',''],['locations','id',"WHERE state='published'"]]){
    const columns=sql.prepare('PRAGMA table_info('+table+')').all().map(row=>row.name);
    require(columns.length>0 && columns.every(name=>/^[a-z_][a-z_0-9]*$/.test(name)));
    const selected=columns.map(name=>"typeof("+name+")||':'||CASE WHEN typeof("+name+")='real' THEN printf('%!.26g',"+name+") ELSE hex(CAST("+name+" AS BLOB)) END AS "+name).join(',');
    hash.update(table+'\n');
    for(const row of sql.prepare('SELECT '+selected+' FROM '+table+' '+where+' ORDER BY '+order).iterate())hash.update(JSON.stringify(row)+'\n');
  }
  return hash.digest('hex');
}
export function applyObjectCancellationLedger(sql,{ledgerRaw,ledgerSha256,notBefore,now,environment}){
  require(Buffer.isBuffer(ledgerRaw) && ledgerRaw.length<=MAX_LEDGER && typeof ledgerSha256==='string'
    && HEX.test(ledgerSha256) && sha(ledgerRaw)===ledgerSha256);
  const ledger=validateObjectCancellationLedger(JSON.parse(ledgerRaw.toString('utf8')),notBefore,now,environment);
  require(ledger.exportedAt<=Number.MAX_SAFE_INTEGER-600);
  sql.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE');
  try{
    require(sql.prepare('SELECT '+SCHEMA_CHECK+' AS valid').get()?.valid===1);
    const preserved=protectedState(sql);
    const historical=readCancellationTombstones(sql),retained=new Set(historical.map(row=>row.leaseId)),
      wanted=new Map(ledger.cancellations.map(row=>[row.leaseId,row]));
    for(const event of historical)require(wanted.has(event.leaseId)
      && Object.entries(event).every(([key,value])=>wanted.get(event.leaseId)[key]===value));
    install(sql,OBJECT_DISPATCH_SCHEMA);sql.exec(OBJECT_DISPATCH_CONTRACT_SQL);
    install(sql,OBJECT_CANCELLATION_SCHEMA);sql.exec(OBJECT_CANCELLATION_CONTRACT_SQL);
    for(const old of sql.prepare('SELECT * FROM object_audit_cancellations ORDER BY lease_id LIMIT 4097').all()){
      require(wanted.has(old.lease_id) && matches(old,wanted.get(old.lease_id)));
    }
    require(sql.prepare('SELECT count(*) AS n FROM object_audit_cancellations').get().n<=4096);
    install(sql,OBJECT_CANCEL_RESTORE_SCHEMA);
    const revision=sql.prepare('SELECT contract FROM object_cancel_restore_revision WHERE slot=1').get();
    require(!revision || revision.contract===OBJECT_CANCEL_RESTORE_CONTRACT);
    sql.prepare('INSERT INTO object_cancel_restore_revision VALUES (1,?) ON CONFLICT(slot) DO NOTHING').run(OBJECT_CANCEL_RESTORE_CONTRACT);
    const targets=new Map();let existingCandidates=0,missingLeases=0;
    for(const event of ledger.cancellations){
      const lease=sql.prepare('SELECT * FROM leases WHERE id=?').get(event.leaseId);
      require(!lease || lease.account_id===event.accountId && lease.lane==='object'
        && ['active','submitted','expired'].includes(lease.state));
      require(!lease || sql.prepare('SELECT 1 FROM accounts WHERE id=?').get(event.accountId));
      const candidate=sql.prepare('SELECT * FROM object_audit_candidates WHERE lease_id=?').get(event.leaseId);
      require(!candidate || lease && candidate.account_id===event.accountId && candidate.policy_id===event.policyId
        && candidate.assignment_sha256===event.assignmentSha256 && candidate.submission_sha256===event.submissionSha256
        && candidate.artifact_key===event.artifactKey && candidate.payload_bytes===event.payloadBytes
        && Number.isSafeInteger(candidate.created_at) && candidate.created_at<=event.cancelledAt);
      const publications=sql.prepare(`SELECT p.object_index_key,p.published_at FROM lease_items i
        JOIN published_index p ON p.location_id=i.location_id WHERE i.lease_id=?`).all(event.leaseId);
      require(publications.every(p=>objectCancellationPublicationSafe(p,event.leaseId,event.cancelledAt))
        && !sql.prepare('SELECT 1 FROM published_index WHERE object_index_key=? LIMIT 1').get('object-index-v4/'+event.leaseId+'/')
        && !sql.prepare(`SELECT 1 FROM locations l LEFT JOIN published_index p ON p.location_id=l.id
          WHERE l.active_lease=? AND l.state='published' AND p.location_id IS NULL LIMIT 1`).get(event.leaseId));
      targets.set(event.artifactKey,{key:event.artifactKey,leaseId:event.leaseId});
      const quarantine='object-quarantine/'+event.leaseId,publication='object-index-v4/'+event.leaseId;
      const intents=sql.prepare(`SELECT * FROM account_artifact_writes WHERE lease_id=?
        OR (artifact_key>=? AND artifact_key<?) OR (artifact_key>=? AND artifact_key<?)
        ORDER BY artifact_key LIMIT 129`).all(event.leaseId,quarantine+'/',quarantine+'0',publication+'/',publication+'0');
      require(intents.length<=128);
      for(const intent of intents){
        const key=indexArtifactIdentity(intent.artifact_key);
        require(intent.account_id===event.accountId && intent.lease_id===event.leaseId && key?.lane==='object' && key.lease===event.leaseId
          && typeof intent.sha256==='string' && HEX.test(intent.sha256) && Number.isSafeInteger(intent.bytes)
          && intent.bytes>=0 && intent.bytes<=32000000
          && (!key.digest || key.digest===intent.sha256) && (key.allowEmpty || intent.bytes>0));
        if(intent.artifact_key===event.artifactKey)require(intent.sha256===event.submissionSha256 && intent.bytes===event.payloadBytes);
        targets.set(intent.artifact_key,{key:intent.artifact_key,leaseId:event.leaseId});
      }
      const keyOwner=sql.prepare('SELECT account_id,lease_id FROM account_artifact_writes WHERE artifact_key=?').get(event.artifactKey);
      require(!keyOwner || keyOwner.account_id===event.accountId && keyOwner.lease_id===event.leaseId);
      require(targets.size<=16384);
      // Clear only authority/claims. Failed native state, attempt counts and
      // original error remain as evidence in this copy as well as the backup.
      if(candidate){
        sql.prepare(`UPDATE object_audit_candidates SET state='cancelled',receipt_sha256=NULL,claim_token=NULL,claim_until=0,next_attempt=0 WHERE lease_id=?`).run(event.leaseId);
        existingCandidates++;
      }
      sql.prepare(`UPDATE locations SET state='pending',queue_state='pending',active_lease=NULL,lease_until=NULL
        WHERE active_lease=? AND state!='published'`).run(event.leaseId);
      if(lease)sql.prepare("UPDATE leases SET state='expired' WHERE id=?").run(event.leaseId);else missingLeases++;
      if(!retained.has(event.leaseId))sql.prepare(`INSERT INTO object_cancellation_tombstones
        (lease_id,request_id,account_id,policy_id,assignment_sha256,submission_sha256,artifact_key,payload_bytes,cancelled_at,source_ledger_sha256)
        VALUES (?,?,?,?,?,?,?,?,?,?)`).run(event.leaseId,event.requestId,event.accountId,event.policyId,event.assignmentSha256,
          event.submissionSha256,event.artifactKey,event.payloadBytes,event.cancelledAt,ledgerSha256);
    }
    require(!sql.prepare('PRAGMA foreign_key_check').all().length && protectedState(sql)===preserved);
    sql.exec('COMMIT');
    return {version:1,scope:'private-object-cancellation-recovery-plan',resource:ledger.resource,
      cancellationLedgerSha256:ledgerSha256,capturedAt:ledger.exportedAt,expiresAt:ledger.exportedAt+600,
      cancelledAssignments:ledger.cancellations.length,existingCandidates,missingLeases,
      nativeRevocations:ledger.cancellations.map(({leaseId,policyId,assignmentSha256,cancelledAt})=>({leaseId,policyId,assignmentSha256,cancelledAt})),
      r2Fences:[...targets.values()].sort((a,b)=>a.key.localeCompare(b.key)).map(row=>({...row,
        sha256:sha(Buffer.from(PRIVACY_FENCE)),bytes:Buffer.byteLength(PRIVACY_FENCE)})),
      nativeCleanupPending:ledger.cancellations.length>0,providerFencesPending:targets.size>0,protectedStatePreserved:true,
      liveReady:false,productionQualified:false};
  }catch(error){sql.exec('ROLLBACK');throw error;}
}

function regular(path,directory=false){
  path=resolve(path);
  for(let p=path;;p=dirname(p)){
    const info=lstatSync(p);require(!info.isSymbolicLink() && (p===path ? directory ? info.isDirectory():info.isFile():info.isDirectory()));
    if(dirname(p)===p)break;
  }
  return path;
}
function pinned(path,pin,maximum){
  regular(path);require((pin===null || typeof pin==='string' && HEX.test(pin)) && lstatSync(path).size<=maximum);
  const fd=openSync(path,'r'),hash=createHash('sha256'),buffer=Buffer.alloc(1024**2);let total=0;
  try{for(let count;(count=readSync(fd,buffer,0,buffer.length,null));){total+=count;require(total<=maximum);hash.update(buffer.subarray(0,count));}}
  finally{closeSync(fd);}
  const digest=hash.digest('hex');require(pin===null || digest===pin);return digest;
}
function closed(path){require(!['-wal','-shm','-journal'].some(suffix=>existsSync(path+suffix)));}
function writeNew(path,raw){writeFileSync(path,raw,{flag:'wx',mode:0o600});sync(path);}
function sync(path){const fd=openSync(path,'r+');try{fsyncSync(fd);}finally{closeSync(fd);}}
export function prepareObjectCancellationRestore({backup,backupSha256,cancellations,cancellationsSha256,notBefore,
  now=Math.floor(Date.now()/1000),environment,out}){
  out=resolve(out);regular(dirname(out),true);mkdirSync(out,{mode:0o700});let sql;
  try{
    const check=()=>{closed(backup);pinned(backup,backupSha256,MAX_DATABASE);pinned(cancellations,cancellationsSha256,MAX_LEDGER);};
    check();const database=join(out,'restored.sqlite');copyFileSync(backup,database,constants.COPYFILE_EXCL);
    sync(database);check();pinned(database,backupSha256,MAX_DATABASE);
    sql=new DatabaseSync(database,{allowExtension:false});sql.exec('PRAGMA trusted_schema=OFF');
    require(sql.prepare('PRAGMA integrity_check').all().every(row=>row.integrity_check==='ok') && !sql.prepare('PRAGMA foreign_key_check').all().length);
    const plan=applyObjectCancellationLedger(sql,{ledgerRaw:readFileSync(cancellations),ledgerSha256:cancellationsSha256,notBefore,now,environment});
    sql.exec('VACUUM');sql.close();sql=null;sync(database);check();
    const raw=encoded(plan);writeNew(join(out,'object-cancellation-plan.private.json'),raw);
    const report={version:1,scope:'offline-object-cancellation-repaired-copy',resource:RESOURCE_PROFILES[environment],
      backupSha256,cancellationLedgerSha256:cancellationsSha256,planSha256:sha(raw),databaseSha256:pinned(database,null,MAX_DATABASE),
      capturedAt:plan.capturedAt,expiresAt:plan.expiresAt,cancelledAssignments:plan.cancelledAssignments,
      existingCandidates:plan.existingCandidates,missingLeases:plan.missingLeases,r2FenceTargets:plan.r2Fences.length,
      nativeCleanupPending:plan.nativeCleanupPending,providerFencesPending:plan.providerFencesPending,
      protectedStatePreserved:plan.protectedStatePreserved,accountDeletionReconciled:false,financialReconciled:false,liveReady:false,productionQualified:false};
    writeNew(join(out,'restore-report.json'),encoded(report));return report;
  }catch(error){sql?.close();writeNew(join(out,'failure-report.json'),encoded({complete:false,
    code:'object_cancellation_restore_failed',liveReady:false,productionQualified:false}));throw error;}
}
export function main(argv=process.argv.slice(2)){
  try{
    const names=['backup','backup-sha256','cancellations','cancellations-sha256','writers-stopped-at','environment','out'];
    const {values}=parseArgs({args:argv,options:Object.fromEntries(names.map(key=>[key,{type:'string'}]))});
    require(names.every(key=>typeof values[key]==='string' && values[key]) && /^\d+$/.test(values['writers-stopped-at']));
    console.log(JSON.stringify(prepareObjectCancellationRestore({backup:values.backup,backupSha256:values['backup-sha256'],
      cancellations:values.cancellations,cancellationsSha256:values['cancellations-sha256'],notBefore:Number(values['writers-stopped-at']),
      environment:values.environment,out:values.out})));return 0;
  }catch{console.log(JSON.stringify({complete:false,code:'object_cancellation_restore_failed',liveReady:false,productionQualified:false}));return 1;}
}
if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href)process.exitCode=main();
