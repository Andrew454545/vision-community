import assert from 'node:assert/strict';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, copyFileSync, mkdtempSync, rmSync, existsSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname, basename } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { checkCreditRecovery, verifyCreditRecovery } from '../tools/credit-recovery.mjs';
import { RESOURCE_PROFILES } from '../tools/account-restore.mjs';
import { PRIVACY_TABLES, deleteAccount } from './accountPrivacy.js';
import { settleSearch, replaySearch } from './searchLedger.js';
import { sqliteD1 } from '../tools/sqlite-d1.mjs';
import {queueSearch,claimQueuedSearch} from './searchQueue.js';

const account = 'a'.repeat(32), second = 'b'.repeat(32);
const sha = p => createHash('sha256').update(readFileSync(p)).digest('hex');
function root(t) {
  const parent = resolve(tmpdir()), p = mkdtempSync(join(parent,'vision-credit-recovery-'));
  t.after(() => {
    assert.equal(dirname(p),parent); assert.ok(basename(p).startsWith('vision-credit-recovery-'));
    rmSync(p,{recursive:true});
  });
  return p;
}
function open(t,p) { const db = new DatabaseSync(p); t.after(() => { if(db.isOpen) db.close(); }); return db; }
function credit(sql, owner, lease, lane, ids) {
  // Clearly synthetic accepted-publication fixture. No native model or hosted admission.
  sql.exec('BEGIN IMMEDIATE');
  sql.prepare("INSERT INTO leases (id,account_id,lane,expires_at,state) VALUES (?,?,?,1000,'submitted')").run(lease,owner,lane);
  for (const id of ids) {
    const hash = createHash('sha256').update(`synthetic-only:${id}`).digest('hex');
    sql.prepare(`INSERT INTO locations (id,asset_id,capture,lane,model,state,contributor_id,output_sha256)
      VALUES (?,?,'fixture',?,'synthetic-only','published',?,?)`).run(id,`fixture-${id}`,lane,owner,hash);
    sql.prepare('INSERT INTO lease_items VALUES (?,?)').run(lease,id);
    sql.prepare(`INSERT INTO published_index (location_id,index_text,output_sha256,published_at)
      VALUES (?,'synthetic-only',?,100)`).run(id,hash);
  }
  const units = ids.length*(lane==='scene'?1:10);
  sql.prepare("INSERT INTO ledger (account_id,units,reason,reference) VALUES (?,?,'verified_work',?)").run(owner,units,`lease:${lease}`);
  sql.prepare('UPDATE accounts SET units=units+? WHERE id=?').run(units,owner);
  sql.exec('COMMIT');
}
async function fixture(t) {
  const p = root(t), backup = join(p,'backup.sqlite'), current = join(p,'current.sqlite'), recovered = join(p,'recovered.sqlite');
  const b = open(t,backup);
  b.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));
  for (const s of PRIVACY_TABLES) b.exec(s);
  b.exec('ALTER TABLE pose_catalog ADD COLUMN assignee TEXT; ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER;');
  b.prepare('INSERT INTO accounts (id,token_hash,recovery_hash) VALUES (?,?,?)').run(account,'synthetic-session','synthetic-recovery');
  credit(b,account,'baseline-scene','scene',[1,2]); credit(b,account,'baseline-object','object',[3]);
  const result = {searchId:'baseline-search',map:{name:'synthetic paid reply'},results:[]};
  await settleSearch(sqliteD1(b),account,'baseline-key','sha256:fixture',result,3);
  b.close(); copyFileSync(backup,current);
  const c = open(t,current);
  credit(c,account,'post-backup-scene','scene',[4]);
  await settleSearch(sqliteD1(c),account,'later-key','sha256:later',
    {searchId:'later-search',map:{name:'later private reply'},results:[]},2);
  c.prepare('UPDATE accounts SET token_hash=?,recovery_hash=? WHERE id=?').run('rotated-session','rotated-recovery',account);
  c.close(); copyFileSync(current,recovered);
  const authority = join(p,'authority.json');
  writeFileSync(authority,JSON.stringify({version:1,scope:'vision-community-credit-recovery',
    resource:RESOURCE_PROFILES.staging,capturedAt:200,writersStopped:true,backupSha256:sha(backup),currentSha256:sha(current)}));
  const options = {backup,current,recovered,authority,authoritySha256:sha(authority),recoveredSha256:sha(recovered),
    authorityNotBefore:150,now:210,environment:'staging',out:join(p,'report')};
  return {p,backup,current,recovered,authority,options,dbs:()=>[backup,current,recovered].map(x=>open(t,x))};
}
function audit(f) { const dbs=f.dbs(); try{return verifyCreditRecovery(...dbs);}finally{dbs.forEach(d=>d.close());} }
function mutate(t,file,sql) { const db=open(t,file);db.exec(sql);db.close(); }
function repin(f) {
  const d=JSON.parse(readFileSync(f.authority));d.backupSha256=sha(f.backup);d.currentSha256=sha(f.current);
  writeFileSync(f.authority,JSON.stringify(d));f.options.authoritySha256=sha(f.authority);f.options.recoveredSha256=sha(f.recovered);
}

test('three pinned snapshots reconcile post-backup work, search debit, rotation and unchanged originals',async t=>{
  const f=await fixture(t), before=[f.backup,f.current,f.recovered].map(sha);
  const result=checkCreditRecovery(f.options);
  assert.equal(result.accountingCopyVerified,true); assert.equal(result.liveReady,false);
  assert.equal(result.creditRecoveryVerified,false);assert.equal(result.productionQualified,false);
  assert.equal(result.pinnedCopiesVerified,true);assert.equal(result.sourceCopiesRetained,true);
  assert.equal(result.postBackupEarnedUnits,'1');assert.equal(result.postBackupSearchUnits,'-2');
  assert.equal(result.postBackupLedgerEntries,2);assert.equal(result.creditedPublications,4);
  assert.equal(result.savedPaidSearches,2);assert.deepEqual([f.backup,f.current,f.recovered].map(sha),before);
  assert.deepEqual(['backup','current','recovered'].map(name=>sha(join(f.options.out,`${name}.private.sqlite`))),before);
});

test('actual saved settlement replays after reopening without another debit or ledger row',async t=>{
  const f=await fixture(t),db=open(t,f.recovered),d1=sqliteD1(db);
  const saved=await replaySearch(d1,account,'later-key','sha256:later');
  const balance=db.prepare('SELECT units FROM accounts WHERE id=?').get(account).units;
  const count=db.prepare('SELECT COUNT(*) AS n FROM ledger').get().n;
  assert.deepEqual(await settleSearch(d1,account,'later-key','sha256:later',
    {searchId:'would-charge-again'},2),saved);
  assert.equal(db.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,balance);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM ledger').get().n,count);db.close();
  assert.equal(audit(f).accountingCopyVerified,true);
});

test('actual deletion after backup retains publications and debits while refusing restored private searches',async t=>{
  const f=await fixture(t),db=open(t,f.current);
  const body={accountId:account,idempotencyKey:'c'.repeat(64),confirmation:'DELETE'};
  const env={DB:sqliteD1(db)};
  const first=await deleteAccount(env,account,body,180);
  assert.equal(first.unitsForfeited,8);
  assert.deepEqual(await deleteAccount(env,null,body,190),first);
  db.close();copyFileSync(f.current,f.recovered);repin(f);
  const result=checkCreditRecovery(f.options);assert.equal(result.deletedAccounts,1);
  assert.equal(result.postBackupDeletionUnits,'-8');assert.equal(result.savedPaidSearches,0);
  mutate(t,f.recovered,`INSERT INTO searches VALUES ('baseline-search','${account}','baseline-key','sha256:fixture',
    '{"searchId":"baseline-search"}')`);
  assert.throws(()=>audit(f),/missing_or_deleted_paid_search|invalid_saved_search/);
});

test('post-backup new accounts and their actual deletion are retained',async t=>{
  const f=await fixture(t),db=open(t,f.current);
  db.prepare('INSERT INTO accounts (id,token_hash) VALUES (?,?)').run(second,'second-session');
  credit(db,second,'second-work','object',[5]);
  await deleteAccount({DB:sqliteD1(db)},second,{accountId:second,idempotencyKey:'d'.repeat(64),confirmation:'DELETE'},190);
  db.close();copyFileSync(f.current,f.recovered);
  const result=audit(f);assert.equal(result.accounts,2);assert.equal(result.deletedAccounts,1);
  assert.equal(result.postBackupEarnedUnits,'11');assert.equal(result.postBackupDeletionUnits,'-10');
});

for(const [name,change,error] of [
  ['rolled-back credit and debit history',`DELETE FROM ledger WHERE reference IN ('lease:post-backup-scene','search:later-search');
    DELETE FROM searches WHERE id='later-search';UPDATE accounts SET units=9 WHERE id='${account}';`,/uncredited_publication/],
  ['balance without ledger',`UPDATE accounts SET units=units+1 WHERE id='${account}'`,/balance_ledger_mismatch/],
  ['missing paid result',"DELETE FROM searches WHERE id='later-search'",/missing_or_deleted_paid_search/],
  ['changed paid result',"UPDATE searches SET result_json='{\"searchId\":\"later-search\",\"map\":\"changed\"}' WHERE id='later-search'",/recovered_searches_mismatch/],
  ['old credential resurrection',`UPDATE accounts SET token_hash='synthetic-session',recovery_hash='synthetic-recovery' WHERE id='${account}'`,/recovered_accounts_mismatch/],
  ['changed retained publication',"UPDATE published_index SET index_text='changed' WHERE location_id=1",/recovered_publications_mismatch/],
  ['unsupported synthetic top-up',`INSERT INTO ledger (account_id,units,reason,reference) VALUES ('${account}',1,'gift','fake-credit');
    UPDATE accounts SET units=units+1 WHERE id='${account}'`,/unsupported_credit_reason/],
]) test(`refuses ${name}`,async t=>{const f=await fixture(t);mutate(t,f.recovered,change);assert.throws(()=>audit(f),error);});

test('a second lease cannot credit an already paid publication even with balanced arithmetic',async t=>{
  const f=await fixture(t);
  mutate(t,f.recovered,`INSERT INTO leases (id,account_id,lane,expires_at,state) VALUES ('double','${account}','scene',1000,'submitted');
    INSERT INTO lease_items VALUES ('double',4);
    INSERT INTO ledger (account_id,units,reason,reference) VALUES ('${account}',1,'verified_work','lease:double');
    UPDATE accounts SET units=units+1 WHERE id='${account}'`);
  assert.throws(()=>audit(f),/missing_or_double_credited_publication/);
});

test('a consistently repinned current/recovered snapshot cannot erase baseline debit history',async t=>{
  const f=await fixture(t),change=`DELETE FROM ledger WHERE reference='search:baseline-search';
    DELETE FROM searches WHERE id='baseline-search';UPDATE accounts SET units=units+3 WHERE id='${account}'`;
  mutate(t,f.current,change);mutate(t,f.recovered,change);
  assert.throws(()=>audit(f),/backup_ledger_history_changed/);
});

test('a consistently repinned current/recovered result cannot rewrite a baseline paid reply',async t=>{
  const f=await fixture(t),change=`UPDATE searches SET result_json='{"searchId":"baseline-search","changed":true}' WHERE id='baseline-search'`;
  mutate(t,f.current,change);mutate(t,f.recovered,change);
  assert.throws(()=>audit(f),/backup_saved_search_history_changed/);
});

test('an otherwise valid but outdated restored snapshot refuses post-backup activity',async t=>{
  const f=await fixture(t);copyFileSync(f.backup,f.recovered);repin(f);
  assert.throws(()=>checkCreditRecovery(f.options),/recovered_accounts_mismatch/);
  const failure=JSON.parse(readFileSync(join(f.options.out,'credit-recovery-failure.json')));
  assert.equal(failure.complete,false);assert.equal(existsSync(join(f.options.out,'credit-recovery-report.json')),false);
  assert.ok(!JSON.stringify(failure).includes(account));assert.ok(!JSON.stringify(failure).includes('private reply'));
});

for(const [name,patch] of [
  ['wrong resource',{environment:'production'}],['stale authority',{authorityNotBefore:201}],
  ['future authority',{now:199}],['wrong authority pin',{authoritySha256:'0'.repeat(64)}],
  ['wrong restored pin',{recoveredSha256:'0'.repeat(64)}],
]) test(`CLI wrapper refuses ${name}`,async t=>{
  const f=await fixture(t);assert.throws(()=>checkCreditRecovery({...f.options,...patch}),
    /invalid_or_stale_authority|input_checksum_mismatch/);
  assert.equal(existsSync(join(f.options.out,'credit-recovery-report.json')),false);
});

test('unclosed WAL/journal snapshots are rejected',async t=>{
  const f=await fixture(t);writeFileSync(f.current+'-wal','uncheckpointed');
  assert.throws(()=>checkCreditRecovery(f.options),/snapshot_has_sidecars/);
});

test('closed WAL-mode snapshots use isolated copies and retain unchanged original bytes',async t=>{
  const f=await fixture(t);
  for(const file of [f.backup,f.current,f.recovered]){
    const db=open(t,file);db.exec('PRAGMA journal_mode=WAL');db.close();
    assert.equal(existsSync(file+'-wal'),false);assert.equal(existsSync(file+'-shm'),false);
  }
  repin(f);
  const before=[f.backup,f.current,f.recovered].map(sha);
  assert.equal(checkCreditRecovery(f.options).pinnedCopiesVerified,true);
  assert.deepEqual([f.backup,f.current,f.recovered].map(sha),before);
  for(const name of ['backup','current','recovered']){
    assert.equal(existsSync(join(f.options.out,`${name}.private.sqlite-wal`)),false);
    assert.equal(existsSync(join(f.options.out,`${name}.private.sqlite-shm`)),false);
  }
});

test('private copy paths containing URI punctuation retain the intended destination',async t=>{
  const f=await fixture(t);f.options.out=join(f.p,'report #&% space');
  assert.equal(checkCreditRecovery(f.options).pinnedCopiesVerified,true);
  assert.equal(sha(join(f.options.out,'recovered.private.sqlite')),f.options.recoveredSha256);
});

test('linked input snapshots are rejected',async t=>{
  const f=await fixture(t),linked=join(f.p,'linked.sqlite');
  try{symlinkSync(f.current,linked);}catch(e){if(process.platform==='win32'&&e.code==='EPERM'){t.skip('file symlink privilege unavailable');return;}throw e;}
  assert.throws(()=>checkCreditRecovery({...f.options,current:linked}),/invalid_or_oversized_input/);
});

test('completed report directories cannot be overwritten or mixed with a new attempt',async t=>{
  const f=await fixture(t);checkCreditRecovery(f.options);
  const before=sha(join(f.options.out,'credit-recovery-report.json'));
  assert.throws(()=>checkCreditRecovery(f.options),/EEXIST/);
  assert.equal(sha(join(f.options.out,'credit-recovery-report.json')),before);
});

test('a pinned authority changed during database verification cannot obtain a completion marker',async t=>{
  const f=await fixture(t),original=DatabaseSync.prototype.prepare;let changed=false;
  DatabaseSync.prototype.prepare=function(sql,...args){
    if(!changed && sql==='PRAGMA quick_check'){
      changed=true;writeFileSync(f.authority,readFileSync(f.authority,'utf8')+'\n');
    }
    return original.call(this,sql,...args);
  };
  try{assert.throws(()=>checkCreditRecovery(f.options),/input_checksum_mismatch/);}
  finally{DatabaseSync.prototype.prepare=original;}
  assert.equal(changed,true);assert.equal(existsSync(join(f.options.out,'credit-recovery-report.json')),false);
});

test('a transient source WAL cannot supply unpinned recovered search results',async t=>{
  const f=await fixture(t);
  mutate(t,f.recovered,`UPDATE searches SET result_json='{"searchId":"later-search","changed":true}' WHERE id='later-search'`);
  repin(f);
  const originalBytes=readFileSync(f.recovered), current=open(t,f.current);
  const approvedReply=current.prepare("SELECT result_json FROM searches WHERE id='later-search'").get().result_json;
  current.close();
  const originalPrepare=DatabaseSync.prototype.prepare, originalClose=DatabaseSync.prototype.close;
  let checked=0, reader, writer, injected=false, restored=false;
  function restoreSource() {
    if(writer?.isOpen) originalClose.call(writer);
    if(injected&&!restored){writeFileSync(f.recovered,originalBytes);restored=true;}
  }
  DatabaseSync.prototype.prepare=function(sql,...args){
    if(sql==='PRAGMA quick_check'&&++checked===3){
      reader=this;injected=true;
      writer=new DatabaseSync(f.recovered);
      writer.exec('PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0');
      originalPrepare.call(writer,"UPDATE searches SET result_json=? WHERE id='later-search'").run(approvedReply);
      assert.ok(existsSync(f.recovered+'-wal'));
    }
    return originalPrepare.call(this,sql,...args);
  };
  DatabaseSync.prototype.close=function(...args){
    const result=originalClose.apply(this,args);
    if(this===reader)restoreSource();
    return result;
  };
  try{assert.throws(()=>checkCreditRecovery(f.options),/recovered_searches_mismatch/);}
  finally{
    DatabaseSync.prototype.prepare=originalPrepare;DatabaseSync.prototype.close=originalClose;
    restoreSource();
  }
  assert.equal(injected,true);assert.equal(restored,true);
  assert.equal(sha(f.recovered),f.options.recoveredSha256);
  assert.equal(existsSync(f.recovered+'-wal'),false);
  assert.equal(existsSync(join(f.options.out,'credit-recovery-report.json')),false);
});

test('a copied snapshot changed during comparison cannot obtain a completion marker',async t=>{
  const f=await fixture(t),original=DatabaseSync.prototype.prepare;let changed=false;
  DatabaseSync.prototype.prepare=function(sql,...args){
    if(!changed&&sql==='SELECT * FROM searches ORDER BY id'){
      changed=true;
      const copy=join(f.options.out,'backup.private.sqlite');
      writeFileSync(copy,Buffer.concat([readFileSync(copy),Buffer.from('changed during comparison')]));
    }
    return original.call(this,sql,...args);
  };
  try{assert.throws(()=>checkCreditRecovery(f.options),/input_checksum_mismatch/);}
  finally{DatabaseSync.prototype.prepare=original;}
  assert.equal(changed,true);assert.equal(existsSync(join(f.options.out,'credit-recovery-report.json')),false);
  assert.equal(existsSync(join(f.options.out,'credit-recovery-failure.json')),true);
});

test('source snapshots without a stop-writers assertion cannot authorize accounting recovery',async t=>{
  const f=await fixture(t),d=JSON.parse(readFileSync(f.authority));d.writersStopped=false;
  writeFileSync(f.authority,JSON.stringify(d));f.options.authoritySha256=sha(f.authority);
  assert.throws(()=>checkCreditRecovery(f.options),/invalid_or_stale_authority/);
});

test('actual command-line entrypoint returns only a private aggregate report',async t=>{
  const f=await fixture(t),script=new URL('../tools/credit-recovery.mjs',import.meta.url);
  const result=spawnSync(process.execPath,[fileURLToPath(script),'--backup',f.backup,'--current',f.current,
    '--recovered',f.recovered,'--authority',f.authority,'--authority-sha256',f.options.authoritySha256,
    '--recovered-sha256',f.options.recoveredSha256,'--authority-not-before','150',
    '--environment','staging','--out',f.options.out],{encoding:'utf8',windowsHide:true});
  assert.equal(result.status,0,result.stderr);assert.equal(JSON.parse(result.stdout).accountingCopyVerified,true);
  assert.ok(!result.stdout.includes(account));assert.ok(!result.stdout.includes('private reply'));
});

const queueSql=readFileSync(new URL('../search-queue.sql',import.meta.url),'utf8');
async function queuedFixture(t,{claim=false,empty=false}={}) {
  const f=await fixture(t),sql=open(t,f.current);sql.exec(queueSql);
  const env={DB:sqliteD1(sql),SEARCH_DELIVERY:'queued-v1',SEARCH_POLICY_ID:'synthetic.queue',
    SEARCH_RUNTIME_SHA256:'d'.repeat(64),SEARCH_SNAPSHOT_SHA256:'e'.repeat(64),SEARCH_AGENT_SECRET:'f'.repeat(64),SEARCH_COST_UNITS:'2'};
  const key='q1.0000000190.'+'c'.repeat(32),query={lane:'scene',prompt:'PRIVATE queue prompt',excluded:[{lat:1e-7,lng:2}],resultCount:1};
  let pending,job;
  if(!empty) {
    pending=await queueSearch(env,account,key,query,{now:190,maxCostUnits:2});
    if(claim)job=(await claimQueuedSearch(env,190)).job;
  }
  sql.close();copyFileSync(f.current,f.recovered);repin(f);
  return {...f,key,query,pending,job};
}

test('current and recovered queues preserve private holds alongside accepted work and paid replies',async t=>{
  const f=await queuedFixture(t,{claim:true}),before=[f.backup,f.current,f.recovered].map(sha);
  const result=checkCreditRecovery(f.options);
  assert.equal(result.queuedSearches,1);assert.equal(result.activeSearchReservations,1);
  assert.equal(result.reservedSearchUnits,2);assert.equal(result.queuedSearchSchemaPreserved,true);
  assert.equal(result.liveReady,false);assert.equal(result.creditRecoveryVerified,false);
  assert.deepEqual([f.backup,f.current,f.recovered].map(sha),before);
  const report=readFileSync(join(f.options.out,'credit-recovery-report.json'),'utf8');
  for(const text of [account,f.key,f.job.claimToken,'PRIVATE queue prompt'])assert.ok(!report.includes(text));
});

test('lost reservations fail recovery even when all banked balances and ledger entries match',async t=>{
  const f=await queuedFixture(t);mutate(t,f.recovered,'DELETE FROM search_jobs');
  assert.throws(()=>audit(f),/recovered_search_jobs_mismatch/);
});

test('lost or changed claim identity cannot revive an earlier owner after restore',async t=>{
  const f=await queuedFixture(t,{claim:true});
  mutate(t,f.recovered,"UPDATE search_jobs SET claim_token='"+'0'.repeat(64)+"'");
  assert.throws(()=>audit(f),/recovered_search_jobs_mismatch/);
});

test('invalid raw query digest fails before financial recovery can approve a copied hold',async t=>{
  const f=await queuedFixture(t);const sql=open(t,f.recovered);
  const definition=sql.prepare("SELECT sql FROM sqlite_master WHERE name='search_jobs_identity'").get().sql;
  sql.exec('DROP TRIGGER search_jobs_identity');
  sql.prepare('UPDATE search_jobs SET query_json=?').run('PRIVATE changed payload');sql.exec(definition);sql.close();
  assert.throws(()=>audit(f),/invalid_queued_accounting_state/);
});

test('missing empty queue schema and weakened guards both refuse recovery',async t=>{
  const f=await queuedFixture(t,{empty:true});
  const sql=open(t,f.recovered);
  sql.exec('DROP TRIGGER search_jobs_credit_guard');sql.close();
  assert.throws(()=>audit(f),/queued_accounting_schema_invalid/);
  copyFileSync(f.current,f.recovered);const restored=open(t,f.recovered);
  for(const row of restored.prepare("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'search_jobs%'").all())
    restored.exec('DROP TRIGGER '+row.name);
  restored.exec('DROP TABLE search_jobs;DROP TABLE search_queue_revision');restored.close();
  assert.throws(()=>audit(f),/recovered_search_queue_mismatch/);
});

test('durable terminal keys cannot disappear while account balances remain unchanged',async t=>{
  const f=await queuedFixture(t);
  mutate(t,f.current,"UPDATE search_jobs SET state='cancelled',query_json=NULL,error_code='search_cancelled'");
  copyFileSync(f.current,f.recovered);assert.equal(audit(f).reservedSearchUnits,0);
  mutate(t,f.recovered,'DELETE FROM search_jobs');assert.throws(()=>audit(f),/recovered_search_jobs_mismatch/);
});

test('settled queue metadata must retain the exact saved price, debit and paid reply',async t=>{
  const f=await queuedFixture(t,{claim:true}),sql=open(t,f.current);
  const row=sql.prepare('SELECT * FROM search_jobs').get();
  sql.exec('BEGIN IMMEDIATE');
  sql.prepare("UPDATE search_jobs SET state='settled',query_json=NULL,claim_token=NULL,claim_until=NULL,completion_nonce=?")
    .run('0'.repeat(64));
  sql.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES(?,-2,'search',?)").run(account,'search:'+row.id);
  sql.prepare('INSERT INTO searches(id,account_id,idempotency_key,query,result_json) VALUES(?,?,?,?,?)')
    .run(row.id,account,row.idempotency_key,row.query_digest,JSON.stringify({searchId:row.id,costUnits:2,map:{name:'PRIVATE queued paid reply'}}));
  sql.prepare('UPDATE accounts SET units=units-2 WHERE id=?').run(account);sql.exec('COMMIT');sql.close();
  copyFileSync(f.current,f.recovered);
  const result=audit(f);assert.equal(result.reservedSearchUnits,0);assert.equal(result.savedPaidSearches,3);
  const bad=open(t,f.recovered);bad.prepare('UPDATE searches SET result_json=? WHERE id=?')
    .run(JSON.stringify({searchId:row.id,costUnits:1}),row.id);bad.close();
  assert.throws(()=>audit(f),/invalid_queued_accounting_state/);
});

test('queue immutable identity history cannot be changed between backup and current authority',async t=>{
  const f=await queuedFixture(t);copyFileSync(f.current,f.backup);
  const sql=open(t,f.current);const definition=sql.prepare("SELECT sql FROM sqlite_master WHERE name='search_jobs_identity'").get().sql;
  sql.exec('DROP TRIGGER search_jobs_identity;UPDATE search_jobs SET cost_units=3');sql.exec(definition);sql.close();
  copyFileSync(f.current,f.recovered);assert.throws(()=>audit(f),/backup_search_job_identity_changed/);
});

test('a recovery failure keeps fixed private-safe evidence and no success marker',async t=>{
  const f=await queuedFixture(t);mutate(t,f.recovered,'DROP TRIGGER search_jobs_credit_guard');repin(f);
  assert.throws(()=>checkCreditRecovery(f.options),/queued_accounting_schema_invalid/);
  const report=readFileSync(join(f.options.out,'credit-recovery-failure.json'),'utf8');
  assert.ok(!existsSync(join(f.options.out,'credit-recovery-report.json')));
  for(const text of [account,f.key,'PRIVATE queue prompt',f.p])assert.ok(!report.includes(text));
});

test('an unreviewed queue trigger cannot change restored reservation behavior',async t=>{
  const f=await queuedFixture(t,{empty:true});
  mutate(t,f.recovered,"CREATE TRIGGER search_jobs_extra AFTER UPDATE ON search_jobs BEGIN DELETE FROM search_jobs; END");
  assert.throws(()=>audit(f),/queued_accounting_schema_invalid/);
});

test('retained cancelled and exhausted claim history cannot be revived by a current cutoff',async t=>{
  const f=await queuedFixture(t);
  copyFileSync(f.current,f.backup);
  mutate(t,f.backup,"UPDATE search_jobs SET state='cancelled',query_json=NULL,error_code='search_cancelled'");
  assert.throws(()=>audit(f),/backup_search_job_identity_changed/);
  copyFileSync(f.current,f.backup);
  mutate(t,f.backup,"UPDATE search_jobs SET state='claimed',claim_token='"+'0'.repeat(64)+"',claim_until=300,attempts=2");
  assert.throws(()=>audit(f),/backup_search_job_identity_changed/);
});
