// Private offline SQL preparation. This never executes a provider import and
// cannot certify live cutover, current account deletion, finance or native/R2
// cleanup. A batch is one transaction; never apply its statements separately.
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {closeSync,constants,copyFileSync,existsSync,fsyncSync,lstatSync,mkdirSync,openSync,readFileSync,readSync,writeFileSync} from 'node:fs';
import {dirname,join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {parseArgs} from 'node:util';
import {prepareDatabase} from './initialize-schema.mjs';
import {sqliteD1} from './sqlite-d1.mjs';
import {sqliteLiteralRows} from './sqlite-value-literals.mjs';
import {OBJECT_DISPATCH_SCHEMA,OBJECT_DISPATCH_CONTRACT_SQL} from '../src/objectAuditDispatch.js';
import {OBJECT_CANCELLATION_SCHEMA,OBJECT_CANCELLATION_CONTRACT_SQL} from '../src/objectAuditCancellation.js';
import {OBJECT_RECOVERY_SCHEMA,OBJECT_RECOVERY_CONTRACT_SQL} from '../src/objectAuditRecovery.js';
import {OBJECT_SETTLEMENT_SCHEMA,OBJECT_SETTLEMENT_CONTRACT_SQL,OBJECT_SETTLEMENT_CONTRACT} from '../src/objectSettlement.js';
import {OBJECT_CANCEL_RESTORE_SCHEMA,OBJECT_CANCEL_RESTORE_CONTRACT} from '../src/objectCancellationRestore.js';
import {applyObjectCancellationLedger} from './object-cancellation-restore.mjs';
import {validateObjectCancellationLedger} from './object-cancellation-authority.mjs';
import {RESOURCE_PROFILES} from './account-restore.mjs';

const HEX=/^[0-9a-f]{64}$/,MAX_DATABASE=512*1024**2,MAX_SQL=16*1024**2,MAX_STATEMENTS=10000,MAX_STATEMENT=100000;
const sha=raw=>createHash('sha256').update(raw).digest('hex');
const encoded=value=>Buffer.from(JSON.stringify(value)+'\n');
const quote=name=>'"'+name.replaceAll('"','""')+'"';
function require(value,code='invalid_object_restore_sql'){if(!value)throw Error(code);}
function regular(path,directory=false){
  path=resolve(path);
  for(let p=path;;p=dirname(p)){
    const info=lstatSync(p);require(!info.isSymbolicLink() && (p===path ? directory ? info.isDirectory():info.isFile():info.isDirectory()),'linked_or_invalid_restore_input');
    if(dirname(p)===p)break;
  }
  return path;
}
function pinned(path,pin,maximum){
  regular(path);require(HEX.test(pin||'') && lstatSync(path).size<=maximum,'input_checksum_mismatch');
  const fd=openSync(path,'r'),hash=createHash('sha256'),buffer=Buffer.alloc(1024**2);let total=0;
  try{for(let count;(count=readSync(fd,buffer,0,buffer.length,null));){total+=count;require(total<=maximum,'input_too_large');hash.update(buffer.subarray(0,count));}}
  finally{closeSync(fd);}
  require(hash.digest('hex')===pin,'input_checksum_mismatch');
}
function closed(path){require(!['-wal','-shm','-journal'].some(suffix=>existsSync(path+suffix)),'backup_not_closed');}
function writeNew(path,raw){writeFileSync(path,raw,{flag:'wx',mode:0o600});const fd=openSync(path,'r+');try{fsyncSync(fd);}finally{closeSync(fd);}}
function schema(db){
  require(db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").get().n<=256
    && !db.prepare("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND length(CAST(sql AS BLOB))>100000 LIMIT 1").get(),'unsupported_object_restore_schema');
  return db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").all();
}
// Normalize only unquoted SQL. Literal contents and quoted identifiers retain
// their exact bytes; case/space changes inside a guard must never be ignored.
function normalize(sql){
  let result='',quoted=null;
  for(let i=0;i<sql.length;i++){
    const ch=sql[i];
    if(quoted){result+=ch;if(ch===quoted){if(sql[i+1]===quoted)result+=sql[++i];else quoted=null;}}
    else if("'\"`[".includes(ch)){quoted=ch==='['?']':ch;result+=ch;}
    else if(!/\s|;/.test(ch))result+=ch.toLowerCase();
  }
  return result.replace(/^create(table|index|uniqueindex|trigger)ifnotexists/,'create$1');
}
function image(db,tables){
  const hash=createHash('sha256');
  for(const table of [...tables,'sqlite_sequence'])hash.update(table+'\n'+JSON.stringify(sqliteLiteralRows(db,table))+'\n');
  return hash.digest('hex');
}
async function canonicalSchema(source){
  const reference=new DatabaseSync(':memory:',{allowExtension:false});
  try{
    await prepareDatabase(sqliteD1(reference));
    for(const statement of OBJECT_DISPATCH_SCHEMA)reference.exec(statement);reference.exec(OBJECT_DISPATCH_CONTRACT_SQL);
    for(const statement of OBJECT_CANCELLATION_SCHEMA)reference.exec(statement);reference.exec(OBJECT_CANCELLATION_CONTRACT_SQL);
    for(const statement of OBJECT_CANCEL_RESTORE_SCHEMA)reference.exec(statement);
    reference.prepare('INSERT INTO object_cancel_restore_revision VALUES (1,?)').run(OBJECT_CANCEL_RESTORE_CONTRACT);
    if(source.some(row=>row.name==='object_recovery_revision')){
      for(const statement of OBJECT_RECOVERY_SCHEMA)reference.exec(statement);reference.exec(OBJECT_RECOVERY_CONTRACT_SQL);
    }
    if(source.some(row=>row.name==='object_settlement_revision')){
      for(const statement of OBJECT_SETTLEMENT_SCHEMA)reference.exec(statement);reference.exec(OBJECT_SETTLEMENT_CONTRACT_SQL);
    }
    const wanted=schema(reference);
    require(source.length===wanted.length && source.every((row,i)=>row.type===wanted[i].type && row.name===wanted[i].name
      && row.tbl_name===wanted[i].tbl_name && typeof row.sql==='string' && normalize(row.sql)===normalize(wanted[i].sql)), 'unsupported_object_restore_schema');
    return wanted;
  }finally{reference.close();}
}
function dropOrder(db,tables){
  const result=[],visiting=new Set(),done=new Set();
  const visit=table=>{
    require(!visiting.has(table),'unsupported_object_restore_schema');if(done.has(table))return;
    visiting.add(table);
    for(const row of db.prepare('PRAGMA foreign_key_list('+quote(table)+')').all()){
      require(tables.includes(row.table),'unsupported_object_restore_schema');visit(row.table);
    }
    visiting.delete(table);done.add(table);result.push(table);
  };
  for(const table of tables)visit(table);
  return result.reverse();
}
function integrity(db){
  require(db.prepare('PRAGMA integrity_check').all().every(row=>row.integrity_check==='ok')
    && !db.prepare('PRAGMA foreign_key_check').all().length,'backup_integrity_failure');
}

export async function prepareObjectRestoreSql({repairedDir,reportSha256,cancellations,cancellationsSha256,notBefore,
  now=Math.floor(Date.now()/1000),environment,out}){
  out=resolve(out);regular(dirname(out),true);mkdirSync(out,{mode:0o700});let source,checked,roundtrip;
  try{
    const started=performance.now();
    const resource=RESOURCE_PROFILES[environment];require(resource,'invalid_restore_environment');
    regular(repairedDir,true);
    const reportPath=join(resolve(repairedDir),'restore-report.json'),planPath=join(resolve(repairedDir),'object-cancellation-plan.private.json'),database=join(resolve(repairedDir),'restored.sqlite');
    pinned(reportPath,reportSha256,16384);const report=JSON.parse(readFileSync(reportPath,'utf8'));
    require(report.version===1 && report.scope==='offline-object-cancellation-repaired-copy' && report.protectedStatePreserved===true
      && report.liveReady===false && report.productionQualified===false && report.accountDeletionReconciled===false && report.financialReconciled===false
      && report.cancellationLedgerSha256===cancellationsSha256 && JSON.stringify(report.resource)===JSON.stringify(resource),'invalid_repaired_copy_report');
    const check=()=>{
      closed(database);pinned(database,report.databaseSha256,MAX_DATABASE);pinned(reportPath,reportSha256,16384);
      pinned(planPath,report.planSha256,4*1024**2);pinned(cancellations,cancellationsSha256,4*1024**2);
    };
    check();const input=join(out,'input.sqlite'),verification=join(out,'checked.sqlite');
    copyFileSync(database,input,constants.COPYFILE_EXCL);check();pinned(input,report.databaseSha256,MAX_DATABASE);
    source=new DatabaseSync(input,{readOnly:true,allowExtension:false});source.exec('PRAGMA trusted_schema=OFF; BEGIN');
    integrity(source);const objects=schema(source),canonical=await canonicalSchema(objects),tables=objects.filter(row=>row.type==='table').map(row=>row.name);
    for(const revision of ['community_schema_revision','object_dispatch_revision','object_cancel_revision','object_cancel_restore_revision',
      ...(tables.includes('object_recovery_revision')?['object_recovery_revision']:[]),
      ...(tables.includes('object_settlement_revision')?['object_settlement_revision']:[])]){
      // installed_at is a historical receipt; contract/revision/slot are exact.
      const row=source.prepare('SELECT * FROM '+quote(revision)).all();
      require(row.length===1 && row[0].slot===1,'invalid_object_restore_revision');
      if(revision==='community_schema_revision')require(row[0].revision===1 && row[0].contract==='vision-community-d1-v1-20261004','invalid_object_restore_revision');
      else require(row[0].contract===({object_dispatch_revision:'private-object-dispatch-v2-20261012',object_cancel_revision:'private-object-cancellation-v1-20261011',
        object_cancel_restore_revision:OBJECT_CANCEL_RESTORE_CONTRACT,object_recovery_revision:'private-object-recovery-v1-20261011',
        object_settlement_revision:OBJECT_SETTLEMENT_CONTRACT})[revision],'invalid_object_restore_revision');
    }
    const preserved=image(source,tables);
    copyFileSync(input,verification,constants.COPYFILE_EXCL);checked=new DatabaseSync(verification,{allowExtension:false});checked.exec('PRAGMA trusted_schema=OFF');
    const plan=applyObjectCancellationLedger(checked,{ledgerRaw:readFileSync(cancellations),ledgerSha256:cancellationsSha256,notBefore,now,environment});
    require(image(checked,tables)===preserved && JSON.stringify(plan)===JSON.stringify(JSON.parse(readFileSync(planPath,'utf8'))),'repaired_cancellation_state_changed');
    require(report.capturedAt===plan.capturedAt && report.expiresAt===plan.expiresAt && report.cancelledAssignments===plan.cancelledAssignments
      && report.existingCandidates===plan.existingCandidates && report.missingLeases===plan.missingLeases && report.r2FenceTargets===plan.r2Fences.length
      && report.nativeCleanupPending===plan.nativeCleanupPending && report.providerFencesPending===plan.providerFencesPending,'invalid_repaired_copy_report');
    checked.close();checked=null;
    const statements=[];let bytes=0;
    const add=sql=>{const statement=sql.replace(/;\s*$/,'')+';',size=Buffer.byteLength(statement+'\n');bytes+=size;
      require(size<=MAX_STATEMENT && bytes<=MAX_SQL && statements.length<MAX_STATEMENTS,'sql_export_limit_exceeded');statements.push(statement);};
    add('PRAGMA defer_foreign_keys=ON');
    for(const row of objects.filter(row=>row.type==='trigger'))add('DROP TRIGGER IF EXISTS '+quote(row.name));
    for(const table of dropOrder(source,tables))add('DROP TABLE IF EXISTS '+quote(table));
    for(const row of objects.filter(row=>row.type==='table'))add(row.sql);
    for(const table of tables){const content=sqliteLiteralRows(source,table);for(const row of content.rows)add('INSERT INTO '+quote(table)+' ('+content.columns+') VALUES ('+row+')');}
    require(!source.prepare("SELECT 1 FROM sqlite_sequence WHERE name NOT IN ('locations','ledger') LIMIT 1").get(),'unsupported_object_restore_schema');
    add("DELETE FROM sqlite_sequence WHERE name IN ('locations','ledger')");const sequence=sqliteLiteralRows(source,'sqlite_sequence');
    for(const row of sequence.rows)add('INSERT INTO sqlite_sequence ('+sequence.columns+') VALUES ('+row+')');
    for(const row of objects.filter(row=>row.type==='index'||row.type==='trigger'))add(row.sql);
    const rawSql=Buffer.from(statements.join('\n')+'\n'),batch=encoded({batch:statements.map(sql=>({sql,params:[]}))});
    roundtrip=new DatabaseSync(join(out,'roundtrip.sqlite'),{allowExtension:false});roundtrip.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE');
    for(const statement of statements)roundtrip.exec(statement);roundtrip.exec('COMMIT');integrity(roundtrip);
    await canonicalSchema(schema(roundtrip));require(image(roundtrip,tables)===preserved,'sql_roundtrip_mismatch');roundtrip.close();roundtrip=null;
    source.exec('COMMIT');source.close();source=null;check();pinned(input,report.databaseSha256,MAX_DATABASE);
    // Preparation time consumes the original freshness window. A long export
    // cannot extend the independently captured cancellation authority.
    const fresh=()=>validateObjectCancellationLedger(JSON.parse(readFileSync(cancellations,'utf8')),notBefore,now+Math.ceil((performance.now()-started)/1000),environment);
    fresh();
    writeNew(join(out,'restore.private.sql'),rawSql);writeNew(join(out,'query-batch.private.json'),batch);
    const result={version:1,scope:'offline-object-cancellation-d1-sql-preparation',resource,reportSha256,planSha256:report.planSha256,
      databaseSha256:report.databaseSha256,cancellationLedgerSha256:cancellationsSha256,expiresAt:plan.expiresAt,
      sqlSha256:sha(rawSql),batchSha256:sha(batch),schemaSha256:sha(encoded(canonical)),stateSha256:preserved,
      applicationTables:tables.length,statements:statements.length,bytes:rawSql.length,localRoundtripPassed:true,
      protectedStatePreserved:true,replacesApplicationTables:true,providerFencesPending:plan.providerFencesPending,nativeCleanupPending:plan.nativeCleanupPending,
      destinationAuthorityRequired:true,currentDeletionAuthorityRequired:true,accountDeletionReconciled:false,financialReconciled:false,liveReady:false,productionQualified:false};
    check();fresh();writeNew(join(out,'sql-report.json'),encoded(result));return result;
  }catch(error){source?.close();checked?.close();roundtrip?.close();writeNew(join(out,'failure-report.json'),encoded({complete:false,
    code:'object_restore_sql_preparation_failed',liveReady:false,productionQualified:false}));throw error;}
}
export async function main(argv=process.argv.slice(2)){
  try{
    const names=['repaired-dir','report-sha256','cancellations','cancellations-sha256','writers-stopped-at','environment','out'];
    const {values}=parseArgs({args:argv,options:Object.fromEntries(names.map(key=>[key,{type:'string'}]))});
    require(names.every(key=>typeof values[key]==='string' && values[key]) && /^\d+$/.test(values['writers-stopped-at']));
    console.log(JSON.stringify({complete:true,...await prepareObjectRestoreSql({repairedDir:values['repaired-dir'],reportSha256:values['report-sha256'],
      cancellations:values.cancellations,cancellationsSha256:values['cancellations-sha256'],notBefore:Number(values['writers-stopped-at']),environment:values.environment,out:values.out})}));return 0;
  }catch{console.log(JSON.stringify({complete:false,code:'object_restore_sql_preparation_failed',liveReady:false,productionQualified:false}));return 1;}
}
if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href)process.exitCode=await main();
