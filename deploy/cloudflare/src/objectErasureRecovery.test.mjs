import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {existsSync,mkdtempSync,readFileSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {exportObjectErasureAuthority,prepareObjectErasureRecovery,main} from '../tools/object-erasure-recovery.mjs';
import {exportDeletionLedger,RESOURCE_PROFILES} from '../tools/account-restore.mjs';
const sha=raw=>createHash('sha256').update(raw).digest('hex');
function fixture(){
  const sql=new DatabaseSync(':memory:');
  sql.exec(`CREATE TABLE accounts(id TEXT,deleted_at INTEGER,units INTEGER,recovery_hash TEXT);
    CREATE TABLE account_deletion_receipts(account_id TEXT,request_key TEXT,deleted_at INTEGER,units_forfeited INTEGER);
    CREATE TABLE leases(id TEXT,account_id TEXT,lane TEXT);
    CREATE TABLE account_cleanup(artifact_key TEXT,account_id TEXT,state TEXT);`);
  const owner='a'.repeat(32),live='b'.repeat(32),lease='1'.repeat(32),other='2'.repeat(32);
  sql.prepare('INSERT INTO accounts VALUES(?,900,0,NULL)').run(owner);
  sql.prepare('INSERT INTO accounts VALUES(?,NULL,7,?)').run(live,'retained-recovery');
  sql.prepare('INSERT INTO account_deletion_receipts VALUES(?,?,900,3)').run(owner,'c'.repeat(64));
  sql.prepare("INSERT INTO leases VALUES(?,?,'object')").run(lease,owner);
  sql.prepare("INSERT INTO leases VALUES(?,?,'object')").run(other,live);
  sql.prepare("INSERT INTO account_cleanup VALUES(?,?,'erased')").run('object-audit-jobs/'+lease,owner);
  const registry={version:1,scope:'private-object-audit-registry',policyId:'staging.object',resource:RESOURCE_PROFILES.staging,
    assignments:[{leaseId:lease,assignment:{sha256:'d'.repeat(64)}},{leaseId:other,assignment:{sha256:'e'.repeat(64)}}]};
  const registryRaw=Buffer.from(JSON.stringify(registry));
  const deletionLedgerRaw=Buffer.from(JSON.stringify(exportDeletionLedger(sql,1000,'staging')));
  const args={registryRaw,registrySha256:sha(registryRaw),policySha256:'f'.repeat(64),deletionLedgerRaw,
    deletionLedgerSha256:sha(deletionLedgerRaw),notBefore:1000,now:1000,environment:'staging'};
  return {sql,args,registry,owner,live,lease,other};
}

function diskFixture(t) {
  const f=fixture(),root=mkdtempSync(join(tmpdir(),'oe-'));
  t.after(()=>{f.sql.close();rmSync(root,{recursive:true,force:true});});
  const current=join(root,'current.sqlite'),registry=join(root,'registry.json'),deletions=join(root,'deletions.json');
  f.sql.prepare('VACUUM INTO ?').run(current);
  writeFileSync(registry,f.args.registryRaw);writeFileSync(deletions,f.args.deletionLedgerRaw);
  return {...f,root,options:{current,currentSha256:sha(readFileSync(current)),registry,
    registrySha256:f.args.registrySha256,policySha256:f.args.policySha256,deletions,
    deletionsSha256:f.args.deletionLedgerSha256,notBefore:1000,now:1000,environment:'staging',out:join(root,'export')}};
}

test('closed pinned database export writes an independently checkable authority without changing inputs',t=>{
  const f=diskFixture(t),report=prepareObjectErasureRecovery(f.options);
  const raw=readFileSync(join(f.options.out,'object-erasure-authority.private.json'));
  assert.equal(report.authoritySha256,sha(raw));assert.equal(report.revokedAssignments,1);
  assert.equal(report.liveReady,false);assert.equal(sha(readFileSync(f.options.current)),f.options.currentSha256);
  assert.equal(existsSync(f.options.current+'-wal'),false);
  assert.equal(sha(readFileSync(join(f.options.out,'current.sqlite'))),f.options.currentSha256);
  assert.deepEqual(JSON.parse(readFileSync(join(f.options.out,'export-report.json'))),report);
  assert.throws(()=>prepareObjectErasureRecovery(f.options));assert.equal(sha(readFileSync(join(f.options.out,'object-erasure-authority.private.json'))),report.authoritySha256);
});

test('operator command parses all pinned inputs and returns only the recovery report',t=>{
  const f=diskFixture(t),now=Math.floor(Date.now()/1000);
  const ledger=Buffer.from(JSON.stringify(exportDeletionLedger(f.sql,now,'staging')));
  writeFileSync(f.options.deletions,ledger);
  const values={'current':f.options.current,'current-sha256':f.options.currentSha256,
    registry:f.options.registry,'registry-sha256':f.options.registrySha256,'policy-sha256':f.options.policySha256,
    deletions:f.options.deletions,'deletions-sha256':sha(ledger),'writers-stopped-at':String(now),
    environment:'staging',out:f.options.out};
  const log=console.log,observed=[];console.log=value=>observed.push(value);
  try{assert.equal(main(Object.entries(values).flatMap(([key,value])=>['--'+key,value])),0);}
  finally{console.log=log;}
  assert.equal(observed.length,1);assert.equal(JSON.parse(observed[0]).complete,true);
  assert.equal(observed[0].includes(f.owner),false);
  assert.equal(JSON.parse(readFileSync(join(f.options.out,'object-erasure-authority.private.json'))).capturedAt,now);
});

for(const [name,alter] of [
  ['database pin',f=>{f.options.currentSha256='0'.repeat(64);}],
  ['database sidecar',f=>{writeFileSync(f.options.current+'-wal','unfinished');}],
  ['ledger pin',f=>{f.options.deletionsSha256='0'.repeat(64);}],
  ['old authority',f=>{f.options.now=1600;}],
  ['database integrity',f=>{writeFileSync(f.options.current,'broken');f.options.currentSha256=sha(readFileSync(f.options.current));}],
]) test(`offline export preserves a failure report and no authority for invalid ${name}`,t=>{
  const f=diskFixture(t);alter(f);assert.throws(()=>prepareObjectErasureRecovery(f.options));
  assert.equal(existsSync(join(f.options.out,'object-erasure-authority.private.json')),false);
  assert.equal(existsSync(join(f.options.out,'export-report.json')),false);
  assert.equal(JSON.parse(readFileSync(join(f.options.out,'failure-report.json'))).complete,false);
});

test('current deletion authority revokes an already-erased hosted assignment again after native restore',()=>{
  const f=fixture();try{
    const result=exportObjectErasureAuthority(f.sql,f.args);
    assert.deepEqual(result.revocations,[{leaseId:f.lease,assignmentSha256:'d'.repeat(64),deletedAt:900}]);
    assert.equal(result.capturedAt,1000);assert.equal(result.expiresAt,1600);
    assert.equal(result.deletionLedgerSha256,f.args.deletionLedgerSha256);
    assert.equal(JSON.stringify(result).includes(f.owner),false);
    assert.equal(f.sql.prepare('SELECT units FROM accounts WHERE id=?').get(f.live).units,7);
  }finally{f.sql.close();}
});

test('production resources cannot relabel a staging policy as production recovery',()=>{
  const f=fixture();try{
    f.registry.resource=RESOURCE_PROFILES.production;
    const registryRaw=Buffer.from(JSON.stringify(f.registry));
    const deletionLedgerRaw=Buffer.from(JSON.stringify(exportDeletionLedger(f.sql,1000,'production')));
    assert.throws(()=>exportObjectErasureAuthority(f.sql,{...f.args,environment:'production',registryRaw,
      registrySha256:sha(registryRaw),deletionLedgerRaw,deletionLedgerSha256:sha(deletionLedgerRaw)}));
  }finally{f.sql.close();}
});

test('extended registry recovery includes historical and new deleted owners beyond 64 assignments',()=>{
  const f=fixture();try{
    const previous=f.args.registryRaw;
    f.registry.version=2;
    f.registry.previousRegistry={path:join(tmpdir(),'preserved-previous-registry.json'),sha256:sha(previous),bytes:previous.length};
    for(let i=3;i<=70;i++){
      const lease=i.toString(16).padStart(32,'0');
      f.sql.prepare("INSERT INTO leases VALUES(?,?,'object')").run(lease,i%2 ? f.owner : f.live);
      f.registry.assignments.push({leaseId:lease,assignment:{sha256:'d'.repeat(64)}});
    }
    const registryRaw=Buffer.from(JSON.stringify(f.registry));
    const args={...f.args,registryRaw,registrySha256:sha(registryRaw)};
    const result=exportObjectErasureAuthority(f.sql,args);
    assert.equal(result.revocations.length,35);
    assert.equal(result.revocations.some(row=>row.leaseId===f.lease),true);
    assert.equal(result.revocations.some(row=>row.leaseId===(69).toString(16).padStart(32,'0')),true);
    assert.equal(result.revocations.some(row=>row.leaseId===(70).toString(16).padStart(32,'0')),false);
    assert.equal(result.registrySha256,sha(registryRaw));
    for(const changed of [{version:1},{version:3},{previousRegistry:null},
      {previousRegistry:{...f.registry.previousRegistry,path:'relative.json'}},
      {previousRegistry:{...f.registry.previousRegistry,bytes:8*1024*1024+1}}]){
      const raw=Buffer.from(JSON.stringify({...f.registry,...changed}));
      assert.throws(()=>exportObjectErasureAuthority(f.sql,{...args,registryRaw:raw,registrySha256:sha(raw)}));
    }
  }finally{f.sql.close();}
});

for(const [name,alter] of [
 ['changed pin',f=>{f.args.registrySha256='0'.repeat(64);}],
 ['stale ledger',f=>{f.args.now=1600;}],
 ['wrong environment',f=>{f.args.environment='production';}],
 ['missing deletion receipt',f=>{f.sql.exec('DELETE FROM account_deletion_receipts');}],
 ['old backup masquerading as current',f=>{f.sql.exec('UPDATE accounts SET deleted_at=NULL');}],
 ['cleanup owner conflict',f=>{f.sql.prepare('UPDATE account_cleanup SET account_id=?').run(f.live);}],
 ['unregistered current lease',f=>{f.sql.prepare('DELETE FROM leases WHERE id=?').run(f.lease);}],
 ['wrong lane',f=>{f.sql.exec("UPDATE leases SET lane='scene'");}],
 ['active account cleanup',f=>{f.sql.prepare("INSERT INTO account_cleanup VALUES(?,?,'pending')").run('object-audit-jobs/'+f.other,f.live);}],
]){
 test(`recovery refuses ${name}`,()=>{
  const f=fixture();try{alter(f);assert.throws(()=>exportObjectErasureAuthority(f.sql,f.args));}
  finally{f.sql.close();}
 });
}
