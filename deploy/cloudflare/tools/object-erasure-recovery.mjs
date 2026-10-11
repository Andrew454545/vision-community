// Offline operator export from a closed current D1 copy and an independent,
// freshly pinned deletion ledger. Never reads a live binding or uploads data.
import { createHash } from 'node:crypto';
import {closeSync,constants,copyFileSync,existsSync,fsyncSync,lstatSync,mkdirSync,openSync,readFileSync,readSync,writeFileSync} from 'node:fs';
import {dirname,join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {parseArgs} from 'node:util';
import {DatabaseSync} from 'node:sqlite';
import { validateLedger, RESOURCE_PROFILES } from './account-restore.mjs';

const HEX = /^[0-9a-f]{64}$/, ID = /^[0-9a-f]{32}$/;
const sha = raw => createHash('sha256').update(raw).digest('hex');
function require(value) { if (!value) throw Error('invalid_object_erasure_recovery_source'); }

export function exportObjectErasureAuthority(sql, { registryRaw, registrySha256, policySha256,
  deletionLedgerRaw, deletionLedgerSha256, notBefore, now = Math.floor(Date.now()/1000), environment }) {
  require(Buffer.isBuffer(registryRaw) && registryRaw.length <= 1024*1024 && HEX.test(registrySha256)
    && sha(registryRaw) === registrySha256 && typeof policySha256 === 'string' && HEX.test(policySha256)
    && Buffer.isBuffer(deletionLedgerRaw) && deletionLedgerRaw.length <= 4*1024*1024
    && HEX.test(deletionLedgerSha256) && sha(deletionLedgerRaw) === deletionLedgerSha256
    && ['staging','production'].includes(environment));
  const registry = JSON.parse(registryRaw.toString('utf8'));
  const ledger = validateLedger(JSON.parse(deletionLedgerRaw.toString('utf8')), notBefore, now, environment);
  require(now-ledger.exportedAt < 600 && registry.version === 1
    && registry.scope === 'private-object-audit-registry'
    && typeof registry.policyId === 'string' && /^[A-Za-z0-9_.-]{1,128}$/.test(registry.policyId)
    && (environment !== 'production' || !registry.policyId.startsWith('staging.'))
    && registry.resource && Object.keys(registry.resource).length === 3
    && Object.entries(RESOURCE_PROFILES[environment]).every(([k,v]) => registry.resource[k] === v)
    && Array.isArray(registry.assignments) && registry.assignments.length > 0 && registry.assignments.length <= 64);
  const seen = new Set();
  for (const entry of registry.assignments) {
    require(entry && typeof entry.leaseId === 'string' && ID.test(entry.leaseId)
      && !seen.has(entry.leaseId) && typeof entry.assignment?.sha256 === 'string' && HEX.test(entry.assignment.sha256));
    seen.add(entry.leaseId);
  }
  const receipts = new Map(ledger.receipts.map(row => [row.accountId,row]));
  sql.exec('BEGIN');
  try {
    // V1 authority contains account deletion only. An active owner's cancelled
    // submission needs independent current cancellation authority too; never
    // export an apparently complete manifest that would omit that revocation.
    if (sql.prepare("SELECT 1 FROM sqlite_master WHERE name='object_audit_cancellations'").get()
        && sql.prepare('SELECT 1 FROM object_audit_cancellations LIMIT 1').get()) {
      throw Error('object_cancellation_recovery_required');
    }
    // The complete current database and independent ledger must agree. A
    // post-backup deletion may not be erased by relabeling the old copy current.
    const deleted = sql.prepare('SELECT id,deleted_at,units,recovery_hash FROM accounts WHERE deleted_at IS NOT NULL').all();
    require(deleted.length === receipts.size);
    for (const account of deleted) {
      const row = receipts.get(account.id);
      const saved = sql.prepare('SELECT * FROM account_deletion_receipts WHERE account_id=?').get(account.id);
      require(row && row.deletedAt === account.deleted_at && account.units === 0 && account.recovery_hash === null
        && saved?.deleted_at === row.deletedAt && saved?.request_key === row.requestKey && saved?.units_forfeited === row.unitsForfeited);
    }
    require(Number(sql.prepare('SELECT COUNT(*) n FROM account_deletion_receipts').get().n) === receipts.size);
    const revocations = [];
    for (const entry of registry.assignments) {
      const lease = sql.prepare('SELECT id,account_id,lane FROM leases WHERE id=?').get(entry.leaseId);
      require(lease && lease.lane === 'object' && ID.test(lease.account_id));
      const account = sql.prepare('SELECT id,deleted_at FROM accounts WHERE id=?').get(lease.account_id);
      require(account);
      const cleanup = sql.prepare('SELECT account_id,state FROM account_cleanup WHERE artifact_key=?')
        .get('object-audit-jobs/'+entry.leaseId);
      if (cleanup) require(cleanup.account_id === account.id && account.deleted_at !== null
        && ['pending','erased','needs_review'].includes(cleanup.state));
      if (account.deleted_at !== null) {
        require(receipts.get(account.id)?.deletedAt === account.deleted_at);
        revocations.push({leaseId:entry.leaseId,assignmentSha256:entry.assignment.sha256,deletedAt:account.deleted_at});
      }
    }
    sql.exec('COMMIT');
    return {version:1,scope:'private-object-erasure-recovery-v1',resource:registry.resource,
      policySha256,registrySha256,deletionLedgerSha256,capturedAt:ledger.exportedAt,
      expiresAt:ledger.exportedAt+600,revocations:revocations.sort((a,b)=>a.leaseId.localeCompare(b.leaseId))};
  } catch (error) { sql.exec('ROLLBACK'); throw error; }
}

function regular(path,directory=false) {
  path=resolve(path);
  for(let p=path;;p=dirname(p)) {
    const stat=lstatSync(p);
    require(!stat.isSymbolicLink() && (p===path ? directory ? stat.isDirectory() : stat.isFile() : stat.isDirectory()));
    if(dirname(p)===p) break;
  }
  return path;
}
function pinned(path,pin,max) {
  regular(path); require(typeof pin==='string' && HEX.test(pin) && lstatSync(path).size<=max);
  const fd=openSync(path,'r'),buffer=Buffer.alloc(1024*1024),hash=createHash('sha256');let total=0;
  try { for(let count;(count=readSync(fd,buffer,0,buffer.length,null));) {
    total+=count;require(total<=max);hash.update(buffer.subarray(0,count));
  }}finally{closeSync(fd);}
  require(hash.digest('hex')===pin);
}
function closed(path) {require(!['-wal','-shm','-journal'].some(suffix=>existsSync(path+suffix)));}
function writeNew(path,raw) {
  writeFileSync(path,raw,{flag:'wx',mode:0o600});
  const fd=openSync(path,'r+');try{fsyncSync(fd);}finally{closeSync(fd);}
}

export function prepareObjectErasureRecovery({current,currentSha256,registry,registrySha256,policySha256,
  deletions,deletionsSha256,notBefore,now=Math.floor(Date.now()/1000),environment,out}) {
  out=resolve(out);regular(dirname(out),true);mkdirSync(out,{mode:0o700});
  let sql;
  try {
    current=regular(current);registry=regular(registry);deletions=regular(deletions);
    const check=()=>{closed(current);pinned(current,currentSha256,512*1024**2);
      pinned(registry,registrySha256,1024**2);pinned(deletions,deletionsSha256,4*1024**2);};
    check();
    const copy=join(out,'current.sqlite');copyFileSync(current,copy,constants.COPYFILE_EXCL);
    const fd=openSync(copy,'r+');try{fsyncSync(fd);}finally{closeSync(fd);}
    pinned(copy,currentSha256,512*1024**2);
    sql=new DatabaseSync(pathToFileURL(copy).href+'?immutable=1',{readOnly:true,allowExtension:false});
    sql.exec('PRAGMA trusted_schema=OFF;PRAGMA foreign_keys=ON');
    require(sql.prepare('PRAGMA integrity_check').all().every(row=>row.integrity_check==='ok')
      && sql.prepare('PRAGMA foreign_key_check').all().length===0);
    const authority=exportObjectErasureAuthority(sql,{registryRaw:readFileSync(registry),registrySha256,policySha256,
      deletionLedgerRaw:readFileSync(deletions),deletionLedgerSha256:deletionsSha256,notBefore,now,environment});
    sql.close();sql=null;check();pinned(copy,currentSha256,512*1024**2);
    const raw=Buffer.from(JSON.stringify(authority)+'\n');
    writeNew(join(out,'object-erasure-authority.private.json'),raw);
    const report={complete:true,scope:'offline-object-erasure-recovery-export-v1',currentSha256,
      authoritySha256:sha(raw),registrySha256,deletionLedgerSha256:deletionsSha256,
      revokedAssignments:authority.revocations.length,capturedAt:authority.capturedAt,expiresAt:authority.expiresAt,
      liveReady:false,productionQualified:false};
    writeNew(join(out,'export-report.json'),Buffer.from(JSON.stringify(report)+'\n'));
    return report;
  }catch(error){
    sql?.close();writeNew(join(out,'failure-report.json'),Buffer.from(JSON.stringify({complete:false,
      code:'object_erasure_recovery_export_failed',liveReady:false,productionQualified:false})+'\n'));throw error;
  }
}

export function main(argv=process.argv.slice(2)) {
  try {
    const names=['current','current-sha256','registry','registry-sha256','policy-sha256',
      'deletions','deletions-sha256','writers-stopped-at','environment','out'];
    const {values}=parseArgs({args:argv,options:Object.fromEntries(names.map(name=>[name,{type:'string'}]))});
    require(names.every(name=>typeof values[name]==='string' && values[name]) && /^\d+$/.test(values['writers-stopped-at']));
    const report=prepareObjectErasureRecovery({current:values.current,currentSha256:values['current-sha256'],
      registry:values.registry,registrySha256:values['registry-sha256'],policySha256:values['policy-sha256'],
      deletions:values.deletions,deletionsSha256:values['deletions-sha256'],
      notBefore:Number(values['writers-stopped-at']),environment:values.environment,out:values.out});
    console.log(JSON.stringify(report));return 0;
  }catch{
    console.log(JSON.stringify({complete:false,code:'object_erasure_recovery_export_failed',liveReady:false,
      productionQualified:false}));return 1;
  }
}
if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href) process.exitCode=main();
