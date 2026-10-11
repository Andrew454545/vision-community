import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {writeObjectArtifact,writeSceneArtifact,indexArtifactIdentity,PRIVACY_FENCE} from './artifactWrites.js';
import {deleteAccount,cleanupAccountArtifacts,migrateAccountPrivacy} from './accountPrivacy.js';
import {syntheticR2} from './syntheticR2.mjs';
import {sha256Hex,encodeUtf8} from './model.js';

const account='a'.repeat(32),other='b'.repeat(32),lease='d'.repeat(32),publishedLease='e'.repeat(32);
const prefix=`object-index-v4/${lease}/`,publishedPrefix=`object-index-v4/${publishedLease}/`;
const data=encodeUtf8('private synthetic Object source\n');
const deletion={accountId:account,confirmation:'DELETE',idempotencyKey:'c'.repeat(64)};
async function fixture(t) {
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  sql.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));
  sql.exec('ALTER TABLE pose_catalog ADD COLUMN assignee TEXT; ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER;');
  const objects=new Map(),env={DB:sqliteD1(sql),INDEX:syntheticR2(objects)};
  await migrateAccountPrivacy(env);
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES (?,?,10)').run(account,'synthetic-session');
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES (?,?,20)').run(other,'synthetic-other');
  for(const id of [lease,publishedLease]) sql.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES (?,?,'object',9999,'active')").run(id,account);
  return {sql,env,objects};
}
async function cleanup(env) {
  await cleanupAccountArtifacts({...env,OBJECT_VERIFIER:{async fetch(request) {
    const id=/object-assignments\/([0-9a-f]{32})\/erase$/.exec(request.url)[1];
    return Response.json({version:1,leaseId:id,policyId:'staging.synthetic',assignmentSha256:'f'.repeat(64),
      state:'erased',serverAuthorization:false,productionQualified:false});
  }}},account,64);
}
const saved=(sql,key)=>sql.prepare('SELECT * FROM account_artifact_writes WHERE artifact_key=?').get(key);

test('only exact one-file Object keys resolve to their own lease and publication prefix',()=>{
  assert.equal(indexArtifactIdentity(prefix+'manifest.json').reference,prefix);
  assert.equal(indexArtifactIdentity(prefix+'semantic.bin').allowEmpty,true);
  assert.equal(indexArtifactIdentity(prefix+'locations.tsv').allowEmpty,false);
  for(const key of [prefix+'../outside.bin',prefix+'nested/class.bin',prefix+'manifest.json/extra',
    prefix+'semantic.bin?token',prefix+'semantic.bin#fragment',prefix+'UPPER.bin','object-index-v4/'+lease+'0/semantic.bin',
    prefix+'manifest.json\0',prefix+'unknown.json',prefix+'..bin']) {
    assert.equal(indexArtifactIdentity(key),null,key);
  }
});

test('Object intent is durable before R2, exact retries do not rewrite and empty lanes are valid',async t=>{
  const {sql,env,objects}=await fixture(t),original=env.INDEX.put;
  let creates=0;
  env.INDEX.put=async(key,bytes,options)=>{
    const row=saved(sql,key);assert.equal(row.account_id,account);assert.equal(row.lease_id,lease);
    assert.equal(row.sha256,await sha256Hex(bytes));assert.equal(row.bytes,bytes.length);
    assert.equal(options.onlyIf.get('if-none-match'),'*');creates++;
    return original(key,bytes,options);
  };
  const key=prefix+'locations.tsv';
  await writeObjectArtifact(env,account,lease,key,data,100);
  await writeObjectArtifact(env,account,lease,key,data,200);
  await writeObjectArtifact(env,account,lease,prefix+'semantic.bin',new Uint8Array(),100);
  assert.equal(creates,3);assert.equal(saved(sql,key).created_at,100);
  assert.deepEqual(objects.get(key),data);
  assert.equal(objects.get(prefix+'semantic.bin').length,0);
  assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,10);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
});

test('changed bytes, lane, owner, lease, quarantine digest and oversized input fail before any write',async t=>{
  const {sql,env}=await fixture(t),key=prefix+'locations.tsv';
  await writeObjectArtifact(env,account,lease,key,data);
  let writes=0;env.INDEX.put=async()=>{writes++;throw Error('must not write');};
  const bad=[
    ()=>writeObjectArtifact(env,account,lease,key,new Uint8Array(data.length)),
    ()=>writeObjectArtifact(env,other,lease,key,data),
    ()=>writeObjectArtifact(env,account,publishedLease,key,data),
    ()=>writeSceneArtifact(env,account,lease,key,data),
    ()=>writeObjectArtifact(env,account,lease,`object-quarantine/${lease}/${'f'.repeat(64)}.json`,data),
    ()=>writeObjectArtifact(env,account,lease,prefix+'manifest.json',new Uint8Array()),
    ()=>writeObjectArtifact(env,account,lease,prefix+'manifest.json',new Uint8Array(4*1024*1024+1)),
    ()=>writeObjectArtifact(env,account,lease,prefix+'semantic.bin',new Uint8Array(32000001)),
  ];
  for(const run of bad) await assert.rejects(run);
  assert.equal(writes,0);assert.equal(sql.prepare('SELECT count(*) AS n FROM account_artifact_writes').get().n,1);
  sql.prepare("UPDATE leases SET lane='scene' WHERE id=?").run(lease);
  await assert.rejects(writeObjectArtifact(env,account,lease,prefix+'metadata.bin',data),/lease_lost/);
  assert.equal(writes,0);
});

test('lost R2 acknowledgement recovers exactly and preserves the original intent',async t=>{
  const {sql,env,objects}=await fixture(t),key=prefix+'locations.tsv',put=env.INDEX.put;
  env.INDEX.put=async(...args)=>{await put(...args);throw Error('synthetic lost reply');};
  await assert.rejects(writeObjectArtifact(env,account,lease,key,data,100),/synthetic lost reply/);
  assert.deepEqual(objects.get(key),data);assert.equal(saved(sql,key).created_at,100);
  env.INDEX.put=put;
  await writeObjectArtifact(env,account,lease,key,data,200);
  assert.equal(saved(sql,key).created_at,100);
  objects.set(key,new Uint8Array(data.length));
  await assert.rejects(writeObjectArtifact(env,account,lease,key,data),/index_artifact_changed/);
});

test('deletion fences an intent-only delayed Object create before it can resurrect private bytes',async t=>{
  const {sql,env,objects}=await fixture(t),key=prefix+'locations.tsv',put=env.INDEX.put;
  let release,entered;
  const enteredPromise=new Promise(resolve=>{entered=resolve;});
  env.INDEX.put=async(k,bytes,options)=>{
    if(k===key && bytes instanceof Uint8Array) {entered();await new Promise(resolve=>{release=resolve;});}
    return put(k,bytes,options);
  };
  const upload=writeObjectArtifact(env,account,lease,key,data);
  const outcome=upload.then(()=>null,error=>error);
  await enteredPromise;assert.ok(saved(sql,key));assert.equal(objects.has(key),false);
  await deleteAccount(env,account,deletion,1234);await cleanup(env);
  assert.equal(new TextDecoder().decode(objects.get(key)),PRIVACY_FENCE);
  release();assert.equal((await outcome).message,'index_artifact_fenced');
  assert.equal(new TextDecoder().decode(objects.get(key)),PRIVACY_FENCE);
  assert.equal(sql.prepare('SELECT state FROM account_cleanup WHERE artifact_key=?').get(key).state,'fenced');
  await assert.rejects(writeObjectArtifact(env,account,lease,key,data),/account_not_active/);
});

test('deletion between an R2 write and its acknowledgement cannot return a successful upload',async t=>{
  const {env,objects}=await fixture(t),key=prefix+'locations.tsv',put=env.INDEX.put;
  let once=true;
  env.INDEX.put=async(...args)=>{
    const result=await put(...args);
    if(once){once=false;await deleteAccount(env,account,deletion,1234);await cleanup(env);}
    return result;
  };
  await assert.rejects(writeObjectArtifact(env,account,lease,key,data),/account_not_active/);
  assert.equal(new TextDecoder().decode(objects.get(key)),PRIVACY_FENCE);
});

test('partial Object bundles and hash-named quarantine are fenced; published bundle members stay intact',async t=>{
  const {sql,env,objects}=await fixture(t);
  const quarantine=`object-quarantine/${lease}/${await sha256Hex(data)}.json`;
  const pending=[quarantine,prefix+'manifest.json',prefix+'semantic.bin'];
  for(const key of pending) await writeObjectArtifact(env,account,lease,key,key.endsWith('.bin')?new Uint8Array():data);
  const kept=[publishedPrefix+'manifest.json',publishedPrefix+'locations.tsv',publishedPrefix+'semantic.bin'];
  for(const key of kept) await writeObjectArtifact(env,account,publishedLease,key,key.endsWith('.bin')?new Uint8Array():data);
  sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id) VALUES (1,'synthetic','fixture','object','fixture','published',?)").run(account);
  sql.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (1,'','synthetic',1,?)").run(publishedPrefix);
  await deleteAccount(env,account,deletion,1234);await cleanup(env);
  for(const key of pending) assert.equal(new TextDecoder().decode(objects.get(key)),PRIVACY_FENCE,key);
  for(const key of kept) {
    assert.deepEqual(objects.get(key),key.endsWith('.bin')?new Uint8Array():data,key);
    assert.equal(sql.prepare('SELECT state FROM account_cleanup WHERE artifact_key=?').get(key),undefined,key);
  }
  // A replayed/manual cleanup item for the exact published prefix is retained.
  sql.prepare("INSERT INTO account_cleanup VALUES (?,?,1234,'pending')").run(kept[0],account);
  await cleanup(env);
  assert.equal(sql.prepare('SELECT state FROM account_cleanup WHERE artifact_key=?').get(kept[0]).state,'retained');
  assert.deepEqual(objects.get(kept[0]),data);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM ledger').get().n,1);
  assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(other).units,20);
});

test('missing Object intent, mismatched owner and wrong lane require review without touching storage',async t=>{
  for(const mutation of ['missing','owner','lane']) {
    const {sql,env,objects}=await fixture(t),key=prefix+'locations.tsv';
    await writeObjectArtifact(env,account,lease,key,data);
    await deleteAccount(env,account,deletion,1234);
    if(mutation==='missing') sql.prepare('DELETE FROM account_artifact_writes WHERE artifact_key=?').run(key);
    if(mutation==='owner') sql.prepare('UPDATE leases SET account_id=? WHERE id=?').run(other,lease);
    if(mutation==='lane') sql.prepare("UPDATE leases SET lane='scene' WHERE id=?").run(lease);
    await cleanup(env);
    assert.equal(sql.prepare('SELECT state FROM account_cleanup WHERE artifact_key=?').get(key).state,'needs_review',mutation);
    assert.deepEqual(objects.get(key),data,mutation);
  }
});

test('cleanup outages retain an Object outbox item for exact retry',async t=>{
  const {sql,env,objects}=await fixture(t),key=prefix+'locations.tsv';
  await writeObjectArtifact(env,account,lease,key,data);await deleteAccount(env,account,deletion,1234);
  const put=env.INDEX.put;env.INDEX.put=async()=>{throw Error('synthetic storage outage');};
  await cleanup(env);
  assert.equal(sql.prepare('SELECT state FROM account_cleanup WHERE artifact_key=?').get(key).state,'pending');
  assert.deepEqual(objects.get(key),data);env.INDEX.put=put;await cleanup(env);
  assert.equal(sql.prepare('SELECT state FROM account_cleanup WHERE artifact_key=?').get(key).state,'fenced');
});
