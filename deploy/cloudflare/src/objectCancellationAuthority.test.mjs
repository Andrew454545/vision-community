import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync,readFileSync,writeFileSync,rmSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareObjectAuditCancellation} from '../tools/prepare-object-audit-cancellation.mjs';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {stageObjectAudit} from './objectAuditDispatch.js';
import {cancelObjectAudit,advanceObjectCancellation} from './objectAuditCancellation.js';
import {syntheticR2} from './syntheticR2.mjs';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {exportDeletionLedger,RESOURCE_PROFILES} from '../tools/account-restore.mjs';
import {exportObjectCancellationLedger,validateObjectCancellationLedger} from '../tools/object-cancellation-authority.mjs';
import {exportObjectErasureAuthority,prepareObjectErasureRecovery,main} from '../tools/object-erasure-recovery.mjs';
import {deleteAccount} from './accountPrivacy.js';
const account='a'.repeat(32),other='c'.repeat(32),lease='b'.repeat(32),now=1000;
const encoded=value=>Buffer.from(JSON.stringify(value)+'\n'),sha=raw=>createHash('sha256').update(raw).digest('hex');
async function setup(t,cancel=true){
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());const r2=syntheticR2(new Map());
  const env={DB:sqliteD1(sql),INDEX:{...r2,async get(key){const v=await r2.get(key);return v?{...v,body:new Response(await v.arrayBuffer()).body}:null;}},
    OBJECT_VERIFIER:{fetch:()=>Response.json({version:1,leaseId:lease,policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),
      state:'erased',serverAuthorization:false,productionQualified:false})}};
  await prepareDatabase(env.DB);await prepareObjectAuditCancellation(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic',10)").run(account);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-other',7)").run(other);
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',9999)").run(lease,account);
  sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (1,'synthetic','fixture','object','synthetic','leased',?,'gen4')").run(lease);
  sql.prepare('INSERT INTO lease_items VALUES (?,1)').run(lease);
  sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,?)').run(1,COVERAGE_VALIDATOR,'f'.repeat(64),now);
  const source=Buffer.from('synthetic source\n'),authority={leaseId:lease,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),sourceSha256:sha(source)};
  await stageObjectAudit(env,account,authority,{manifest:{synthetic:true},files:{'synthetic.bin':''},sourceTsv:source.toString('base64')},now);
  if(cancel)await cancelObjectAudit(env,account,lease,'7'.repeat(64),now);
  const registry={version:1,scope:'private-object-audit-registry',policyId:authority.policyId,resource:RESOURCE_PROFILES.staging,
    assignments:[{leaseId:lease,assignment:{sha256:authority.assignmentSha256}}]};
  const args=()=>{const registryRaw=encoded(registry),deletionLedgerRaw=encoded(exportDeletionLedger(sql,now,'staging')),
    cancellationLedgerRaw=encoded(exportObjectCancellationLedger(sql,now,'staging'));
    return {registryRaw,registrySha256:sha(registryRaw),policySha256:'e'.repeat(64),deletionLedgerRaw,
      deletionLedgerSha256:sha(deletionLedgerRaw),cancellationLedgerRaw,cancellationLedgerSha256:sha(cancellationLedgerRaw),
      notBefore:now,now,environment:'staging'};};
  return {sql,env,registry,args};
}
test('v2 independently pinned current cancellation revokes active-owner work without exporting account/path data',async t=>{
  const s=await setup(t),args=s.args(),value=exportObjectErasureAuthority(s.sql,args);
  assert.equal(value.version,2);assert.equal(value.scope,'private-object-erasure-recovery-v2');assert.deepEqual(value.revocations,[]);
  assert.deepEqual(value.cancellations,[{leaseId:lease,assignmentSha256:'2'.repeat(64),requestId:'7'.repeat(64),cancelledAt:now}]);
  assert.equal(value.cancellationLedgerSha256,args.cancellationLedgerSha256);
  assert.equal(JSON.stringify(value).includes(account),false);assert.equal(JSON.stringify(value).includes('object-quarantine/'),false);
  assert.equal(s.sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,10);
  assert.equal(s.sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
});
test('legacy export stays valid without cancellation; omitted or one-sided cancellation pins refuse a current cancellation',async t=>{
  const s=await setup(t,false),{cancellationLedgerRaw,cancellationLedgerSha256,...old}=s.args();
  assert.equal(exportObjectErasureAuthority(s.sql,old).version,1);
  await cancelObjectAudit(s.env,account,lease,'7'.repeat(64),now);
  assert.throws(()=>exportObjectErasureAuthority(s.sql,old),/object_cancellation_recovery_required/);
  assert.throws(()=>exportObjectErasureAuthority(s.sql,{...old,cancellationLedgerRaw}));
  assert.throws(()=>exportObjectErasureAuthority(s.sql,{...old,cancellationLedgerSha256}));
});
test('complete current ledger detects an older backup masquerading as current and extra or omitted events',async t=>{
  const current=await setup(t),old=await setup(t,false),args=current.args();
  assert.throws(()=>exportObjectErasureAuthority(old.sql,args),/invalid_object_cancellation_authority/);
  for(const rows of [[],[...JSON.parse(args.cancellationLedgerRaw).cancellations,{...JSON.parse(args.cancellationLedgerRaw).cancellations[0],leaseId:'d'.repeat(32),requestId:'8'.repeat(64),artifactKey:'object-quarantine/'+'d'.repeat(32)+'/'+JSON.parse(args.cancellationLedgerRaw).cancellations[0].submissionSha256+'.json'}]]){
    const raw=encoded({...JSON.parse(args.cancellationLedgerRaw),cancellations:rows});
    assert.throws(()=>exportObjectErasureAuthority(current.sql,{...args,cancellationLedgerRaw:raw,cancellationLedgerSha256:sha(raw)}));
  }
});
test('erased rows still export revocation; a subsequent account deletion keeps both independent authorities',async t=>{
  const s=await setup(t);await advanceObjectCancellation(s.env,account,lease,now);
  const before=s.args();assert.equal(exportObjectErasureAuthority(s.sql,before).cancellations.length,1);
  await deleteAccount(s.env,account,{accountId:account,confirmation:'DELETE',idempotencyKey:'8'.repeat(64)},now);
  const result=exportObjectErasureAuthority(s.sql,s.args());assert.equal(result.cancellations.length,1);assert.equal(result.revocations.length,1);
  assert.equal(s.sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,0);
});
test('unrelated registry authority cannot reinterpret a cancellation policy or assignment hash',async t=>{
  const s=await setup(t),args=s.args();
  for(const change of [v=>{v.policyId='staging.other';},v=>{v.assignments[0].assignment.sha256='8'.repeat(64);}]){
    const value=structuredClone(s.registry);change(value);const raw=encoded(value);
    assert.throws(()=>exportObjectErasureAuthority(s.sql,{...args,registryRaw:raw,registrySha256:sha(raw)}));
  }
});
test('malformed, stale, duplicate, wrong-resource and changed cancellation records fail before authority emission',async t=>{
  const s=await setup(t),args=s.args(),original=JSON.parse(args.cancellationLedgerRaw);
  for(const damage of [v=>{v.version=2;},v=>{v.extra=true;},v=>{v.resource.bucket='unknown';},v=>{v.exportedAt=1600;},
    v=>{v.cancellations.push(v.cancellations[0]);},v=>{v.cancellations[0].cancelledAt=true;},v=>{v.cancellations[0].cancelledAt=1001;},
    v=>{v.cancellations[0].artifactKey='../outside';},v=>{v.cancellations[0].accountId=other;},v=>{v.cancellations[0].submissionSha256='0'.repeat(64);}]){
    const value=structuredClone(original);damage(value);const raw=encoded(value);
    assert.throws(()=>exportObjectErasureAuthority(s.sql,{...args,cancellationLedgerRaw:raw,cancellationLedgerSha256:sha(raw)}));
  }
  assert.throws(()=>exportObjectErasureAuthority(s.sql,{...args,cancellationLedgerSha256:'0'.repeat(64)}));
  assert.throws(()=>validateObjectCancellationLedger(original,now,now+600,'staging'));
});
test('broken current ownership, unknown schema and unjournalled cancellations cannot be exported',async t=>{
  for(const damage of [s=>s.sql.exec('DELETE FROM account_artifact_writes'),
    s=>s.sql.exec("UPDATE object_cancel_revision SET contract='future'"),s=>s.sql.exec('DELETE FROM object_audit_cancellations'),
    s=>s.sql.exec("INSERT INTO published_index(location_id,index_text,output_sha256,published_at) VALUES (1,'synthetic','unknown',1001)")]){
    const s=await setup(t);damage(s);assert.throws(()=>exportObjectCancellationLedger(s.sql,now,'staging'));
  }
});
test('a later accepted bundle from another lease does not erase cancellation recovery authority',async t=>{
  const s=await setup(t);s.sql.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (1,'synthetic','fixture',1001,?)")
    .run('object-index-v4/'+other+'/');
  assert.equal(exportObjectErasureAuthority(s.sql,s.args()).cancellations.length,1);
});
test('both ledger freshness windows bound v2 expiry without extending either independent cutoff',async t=>{
  const s=await setup(t),args=s.args(),value=JSON.parse(args.cancellationLedgerRaw);value.exportedAt=1001;const raw=encoded(value);
  const result=exportObjectErasureAuthority(s.sql,{...args,now:1001,cancellationLedgerRaw:raw,cancellationLedgerSha256:sha(raw)});
  assert.equal(result.capturedAt,1001);assert.equal(result.expiresAt,1600);
});
test('closed pinned v2 export and CLI require the cancellation file/hash pair and preserve failures',async t=>{
  const s=await setup(t),root=mkdtempSync(join(tmpdir(),'cr-'));t.after(()=>rmSync(root,{recursive:true,force:true}));
  const args=s.args(),current=join(root,'current.sqlite');s.sql.prepare('VACUUM INTO ?').run(current);
  const registry=join(root,'registry.json'),deletions=join(root,'deletions.json'),cancellations=join(root,'cancellations.json');
  writeFileSync(registry,args.registryRaw);writeFileSync(deletions,args.deletionLedgerRaw);writeFileSync(cancellations,args.cancellationLedgerRaw);
  const options={current,currentSha256:sha(readFileSync(current)),registry,registrySha256:args.registrySha256,
    policySha256:args.policySha256,deletions,deletionsSha256:args.deletionLedgerSha256,cancellations,
    cancellationsSha256:args.cancellationLedgerSha256,notBefore:now,now,environment:'staging',out:join(root,'success')};
  const report=prepareObjectErasureRecovery(options);assert.equal(report.revokedAssignments,1);assert.equal(report.cancelledAssignments,1);
  assert.equal(report.liveReady,false);assert.equal(JSON.parse(readFileSync(join(options.out,'object-erasure-authority.private.json'))).version,2);
  for(const change of [{cancellationsSha256:null},{cancellations:null},{cancellationsSha256:'0'.repeat(64)}]){
    const out=join(root,'failure'+Math.random());assert.throws(()=>prepareObjectErasureRecovery({...options,...change,out}));
    assert.equal(JSON.parse(readFileSync(join(out,'failure-report.json'))).complete,false);
    assert.equal(existsSync(join(out,'object-erasure-authority.private.json')),false);
  }
  const time=Math.floor(Date.now()/1000),dl=encoded(exportDeletionLedger(s.sql,time,'staging')),cl=encoded(exportObjectCancellationLedger(s.sql,time,'staging'));
  writeFileSync(deletions,dl);writeFileSync(cancellations,cl);
  const flags={current,'current-sha256':options.currentSha256,registry,'registry-sha256':args.registrySha256,
    'policy-sha256':args.policySha256,deletions,'deletions-sha256':sha(dl),cancellations,'cancellations-sha256':sha(cl),
    'writers-stopped-at':String(time),environment:'staging',out:join(root,'command')};
  const log=console.log,results=[];console.log=value=>results.push(value);
  try{assert.equal(main(Object.entries(flags).flatMap(([key,value])=>['--'+key,value])),0);}finally{console.log=log;}
  assert.equal(results.length,1);assert.equal(JSON.parse(results[0]).cancelledAssignments,1);assert.equal(results[0].includes(account),false);
});
