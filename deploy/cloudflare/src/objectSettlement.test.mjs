// Real SQLite transaction and stored bytes; all inference/coverage is synthetic.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareObjectAuditDispatch} from '../tools/prepare-object-audit-dispatch.mjs';
import {prepareObjectSettlement} from '../tools/prepare-object-settlement.mjs';
import {stageObjectAudit,advanceObjectAudit} from './objectAuditDispatch.js';
import {advanceObjectContribution} from './objectAuditFlow.js';
import {settleObjectAudit} from './objectSettlement.js';
import {syntheticR2} from './syntheticR2.mjs';
import {sha256Hex,encodeUtf8} from './model.js';
import worker from './worker.js';
import {OBJECT_INDEX_MODEL} from './objectIndex.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {objectCapabilities} from './objectAdmission.js';
import {deleteAccount} from './accountPrivacy.js';
const doc=JSON.parse(readFileSync(new URL('../../../community/tests/fixtures/object-feature-content-v1.json',import.meta.url),'utf8'));
const account='b'.repeat(32),lease=doc.leaseId,job='c'.repeat(32),now=Math.floor(Date.now()/1000);
async function setup(t,install=true) {
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const objects=new Map(),r2=syntheticR2(objects);
  const env={DB:sqliteD1(sql),INDEX_BUCKET_NAME:'vision-community-staging',INDEX:{...r2,async get(key){const obj=await r2.get(key);
    return obj?{...obj,body:new Response(await obj.arrayBuffer()).body}:null;}}};
  await prepareDatabase(env.DB);await prepareObjectAuditDispatch(env.DB);if(install)await prepareObjectSettlement(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-token',0)").run(account);
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',?)").run(lease,account,now+1000);
  for(const item of doc.items) {
    sql.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation,
      lat,lon,heading,pitch,zoom,country) VALUES (?,?,'synthetic','object',?,'leased',?,'gen4',?,?,?,?,?,?)`)
      .run(item.locationId,item.panoId,OBJECT_INDEX_MODEL,lease,item.lat,item.lng,item.heading,item.pitch,item.zoom,item.country);
    sql.prepare('INSERT INTO lease_items VALUES (?,?)').run(lease,item.locationId);
    sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,?)').run(item.locationId,COVERAGE_VALIDATOR,'d'.repeat(64),now);
  }
  const index={manifest:structuredClone(doc.baseline.manifest),sourceTsv:doc.baseline.sourceBase64,files:doc.baseline.filesBase64};
  Object.assign(index.manifest.viewQuality,{policy:'vision-per-view-quality-v1',implementationIdentity:'1'.repeat(64),viewCount:6,
    blurAreaFractionExclusive:.5,tileGrid:8,tunnelVisionProbabilityInclusive:.85,
    tunnelEvidencePolicy:'none-darkness-never-rejects-v1',protectedAuthorityManifestSha256:'2'.repeat(64)});
  index.manifest.sourceTsv='C:/SYNTHETIC-PRIVATE/source.tsv';index.manifest.privateExtension={secret:'SYNTHETIC-PRIVATE'};
  const authority={leaseId:lease,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),
    sourceSha256:await sha256Hex(new Uint8Array(Buffer.from(index.sourceTsv,'base64')))};
  const row=()=>sql.prepare('SELECT * FROM object_audit_candidates WHERE lease_id=?').get(lease);
  const reply=()=>({version:1,jobId:job,leaseId:lease,profileId:authority.profileId,policyId:authority.policyId,
    assignmentSha256:authority.assignmentSha256,submissionSha256:row().submission_sha256,
    candidateManifestSha256:'3'.repeat(64),state:'approved',decision:'approved',attempts:1,retryAt:0,
    receiptSha256:'4'.repeat(64),serverAuthorization:false,productionQualified:false,acceptedContributions:0,searchCreditsCreated:0});
  const pins={policySha256:'5'.repeat(64),runtimeProfileSha256:'6'.repeat(64),qualityImplementationIdentity:'1'.repeat(64),
    protectedAuthoritySha256:'2'.repeat(64),protectedOriginHandoffSha256:'7'.repeat(64)};
  const resource={accountId:'272760294910ef0b246980278aeb36e2',databaseId:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',bucket:'vision-community-staging'};
  env.OBJECT_SETTLEMENT_POLICY=JSON.stringify({version:1,scope:'object-batch-parity-v1',policyId:authority.policyId,
    profiles:[authority.profileId],...pins,resource});
  const evidence=()=>({audit:reply(),...pins,resource,qualificationScope:'batch-only',issuedAt:now,expiresAt:now+30});
  let calls=0,full=0;
  env.OBJECT_VERIFIER={fetch(request){calls++;if(request.url.endsWith('/settlement-evidence')){full++;return Response.json(evidence());}return Response.json(reply());}};
  await stageObjectAudit(env,account,authority,index,now);await advanceObjectAudit(env,account,lease,now);
  const counts=()=>({publications:sql.prepare('SELECT COUNT(*) n FROM published_index').get().n,
    ledger:sql.prepare("SELECT COUNT(*) n FROM ledger WHERE reason='verified_work'").get().n,
    accepted:install?sql.prepare('SELECT COUNT(*) n FROM object_acceptances').get().n:0,
    units:sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units});
  return {sql,env,objects,index,evidence,reply,pins,counts,calls:()=>({calls,full}),
    settle:(time=now,timeout=20000)=>settleObjectAudit(env,account,lease,time,timeout)};
}
const zero=f=>assert.deepEqual(f.counts(),{publications:0,ledger:0,accepted:0,units:0});
test('audited batch publishes sanitized files and awards once; replay skips native service',async t=>{
  const f=await setup(t);assert.equal(f.sql.prepare('SELECT count(*) n FROM object_dispatch_slots').get().n,1);
  const accepted=await advanceObjectContribution(f.env,account,lease,now);
  assert.equal(accepted.accepted,2);assert.equal(accepted.unitsEarned,20);assert.equal(accepted.replayed,false);
  assert.deepEqual(f.counts(),{publications:2,ledger:1,accepted:1,units:20});
  assert.equal(f.sql.prepare('SELECT count(*) n FROM object_dispatch_slots').get().n,0);
  assert.equal(f.sql.prepare('SELECT receipt_sha256 FROM object_audit_candidates').get().receipt_sha256,'4'.repeat(64));
  const manifest=new TextDecoder().decode(f.objects.get(`object-index-v4/${lease}/manifest.json`));
  assert.equal(manifest.includes('SYNTHETIC-PRIVATE'),false);assert.equal(JSON.parse(manifest).sourceTsv,'locations.tsv');
  const before=f.calls();const replay=await f.settle();assert.equal(replay.accepted,2);assert.equal(replay.unitsEarned,0);
  assert.equal(replay.replayed,true);assert.deepEqual(f.calls(),before);
  const advanced=await advanceObjectAudit(f.env,account,lease,now+500);assert.equal(advanced.auditState,'published');assert.equal(advanced.pendingAudit,false);
  assert.deepEqual(f.calls(),before);assert.equal(objectCapabilities(f.env).objectContributions.ready,false);
});

test('a failed slot release rolls back acceptance, publications and credit together',async t=>{
  const f=await setup(t);
  f.sql.exec("CREATE TRIGGER injected_slot_failure BEFORE DELETE ON object_dispatch_slots BEGIN SELECT RAISE(ABORT,'synthetic slot failure'); END");
  await assert.rejects(f.settle());zero(f);
  assert.equal(f.sql.prepare('SELECT count(*) n FROM object_dispatch_slots').get().n,1);
  f.sql.exec('DROP TRIGGER injected_slot_failure');
  assert.equal((await f.settle()).unitsEarned,20);
  assert.equal(f.sql.prepare('SELECT count(*) n FROM object_dispatch_slots').get().n,0);
});
test('two concurrent settlements produce one durable acceptance and one award',async t=>{
  const f=await setup(t),results=await Promise.allSettled([f.settle(),f.settle()]);
  assert.ok(results.some(r=>r.status==='fulfilled' && r.value.accepted===2));
  assert.equal(results.filter(r=>r.status==='fulfilled').reduce((n,r)=>n+r.value.unitsEarned,0),20);
  assert.deepEqual(f.counts(),{publications:2,ledger:1,accepted:1,units:20});
});
test('lost committed database reply recovers with no second award or native read',async t=>{
  const f=await setup(t),batch=f.env.DB.batch.bind(f.env.DB);let lost=false;
  f.env.DB.batch=async statements=>{await batch(statements);lost=true;throw Error('synthetic lost commit reply');};
  await assert.rejects(f.settle());assert.equal(lost,true);const calls=f.calls();
  const recovered=await f.settle();assert.equal(recovered.accepted,2);assert.equal(recovered.unitsEarned,0);assert.deepEqual(f.calls(),calls);
  assert.deepEqual(f.counts(),{publications:2,ledger:1,accepted:1,units:20});
});
test('interrupted R2 upload remains private and resumes create-only files',async t=>{
  const f=await setup(t),put=f.env.INDEX.put;let broken=false;
  f.env.INDEX.put=async(key,...args)=>{if(!broken && key.endsWith('locations.tsv')){broken=true;throw Error('synthetic network failure');}return put(key,...args);};
  await assert.rejects(f.settle());zero(f);assert.ok(f.objects.has(`object-index-v4/${lease}/manifest.json`));
  const result=await f.settle();assert.equal(result.unitsEarned,20);assert.equal(f.calls().full,1);
});
test('missing operator setup, policy or wrong pins cannot publish',async t=>{
  for(const kind of ['schema','missing','profile','policy','quality','origin','resource']){
    const f=await setup(t,kind!=='schema');
    if(kind==='missing')delete f.env.OBJECT_SETTLEMENT_POLICY;
    else if(kind!=='schema') {const p=JSON.parse(f.env.OBJECT_SETTLEMENT_POLICY);
      if(kind==='profile')p.profiles=['9'.repeat(64)];else if(kind==='resource')f.env.INDEX_BUCKET_NAME='vision-community';
      else p[{policy:'policySha256',quality:'qualityImplementationIdentity',origin:'protectedOriginHandoffSha256'}[kind]]='9'.repeat(64);
      f.env.OBJECT_SETTLEMENT_POLICY=JSON.stringify(p);}
    await assert.rejects(f.settle());zero(f);
  }
});
test('stale, rejected, uncorrelated or extra-field full receipts cannot authorize',async t=>{
  for(const kind of ['expired','future','rejected','wrong-job','extension']){
    const f=await setup(t),fetch=f.env.OBJECT_VERIFIER.fetch;
    f.env.OBJECT_VERIFIER.fetch=request=>{if(!request.url.endsWith('/settlement-evidence'))return fetch(request);
      const e=f.evidence();if(kind==='expired'){e.issuedAt=now-31;e.expiresAt=now-1;}
      if(kind==='future'){e.issuedAt=now+10;e.expiresAt=now+40;}
      if(kind==='rejected'){e.audit.state=e.audit.decision='rejected';}
      if(kind==='wrong-job')e.audit.jobId='f'.repeat(32);if(kind==='extension')e.extra=true;
      return Response.json(e);};
    await assert.rejects(f.settle());zero(f);
  }
});
test('account deletion, expiry, pose or coverage changes during final receipt are fenced in transaction',async t=>{
  for(const kind of ['deletion','expiry','pose','coverage','lease-items','proof-expires-at-db']){
    const f=await setup(t),fetch=f.env.OBJECT_VERIFIER.fetch;
    f.env.OBJECT_VERIFIER.fetch=async request=>{if(request.url.endsWith('/settlement-evidence')) {
      if(kind==='deletion')await deleteAccount(f.env,account,{accountId:account,idempotencyKey:'8'.repeat(64),confirmation:'DELETE'},now+1);
      if(kind==='expiry')f.sql.prepare('UPDATE leases SET expires_at=?').run(now-1);
      if(kind==='pose')f.sql.exec('UPDATE locations SET heading=heading+1');
      if(kind==='coverage')f.sql.exec("UPDATE object_coverage SET evidence_sha256='changed'");
      if(kind==='lease-items')f.sql.exec('DELETE FROM lease_items');
      if(kind==='proof-expires-at-db')f.sql.function('unixepoch',()=>now+40);
    }return fetch(request);};
    await assert.rejects(f.settle());zero(f);
    if(kind==='deletion')assert.equal(f.sql.prepare('SELECT deleted_at FROM accounts WHERE id=?').get(account).deleted_at,now+1);
  }
});
test('the settlement deadline covers initial setup and owner/replay database reads',async t=>{
  for(const phase of ['object_settlement_revision','SELECT 1 FROM accounts']){
    const f=await setup(t),prepare=f.env.DB.prepare.bind(f.env.DB);
    f.env.DB.prepare=query=>query.includes(phase)?{first:()=>new Promise(()=>{}),bind(){return this;}}:prepare(query);
    const start=performance.now();await assert.rejects(f.settle(now,20));assert.ok(performance.now()-start<500);zero(f);
  }
});
test('publication error rolls back acceptance, all publications, ledger and balance',async t=>{
  const f=await setup(t);f.sql.exec(`CREATE TRIGGER synthetic_publication_failure BEFORE INSERT ON published_index
    WHEN NEW.location_id=12 BEGIN SELECT RAISE(ABORT,'synthetic final publication failure');END`);
  await assert.rejects(f.settle());zero(f);assert.equal(f.sql.prepare("SELECT COUNT(*) n FROM locations WHERE state='published'").get().n,0);
  f.sql.exec('DROP TRIGGER synthetic_publication_failure');assert.equal((await f.settle()).unitsEarned,20);
});
test('accepted evidence is immutable; deletion keeps anonymous contributions and forfeits credit',async t=>{
  const f=await setup(t);await f.settle();
  assert.throws(()=>f.sql.exec('UPDATE object_acceptances SET units=0'),/immutable/);
  assert.throws(()=>f.sql.exec('DELETE FROM object_acceptances'),/retained/);
  await deleteAccount(f.env,account,{accountId:account,idempotencyKey:'8'.repeat(64),confirmation:'DELETE'},now+1);
  await assert.rejects(f.settle(),/account_not_active/);
  assert.equal(f.counts().publications,2);assert.equal(f.counts().accepted,1);assert.equal(f.counts().units,0);
});
test('authenticated website audit and upload replay connect to the saved Object settlement',async t=>{
  const f=await setup(t),clock=Date.now;Date.now=()=>now*1000;t.after(()=>{Date.now=clock;});
  f.env.RATE_LIMITS_REQUIRED='1';
  for(const name of ['API_RATE_LIMITER','API_INGRESS_LIMITER','API_VIEW_LIMITER'])f.env[name]={limit:async()=>({success:true})};
  const token='synthetic-object-session';f.sql.prepare('UPDATE accounts SET token_hash=? WHERE id=?')
    .run(await sha256Hex(encodeUtf8(token)),account);
  const call=(path,body)=>worker.fetch(new Request('https://community.test'+path,{method:'POST',
    headers:{'content-type':'application/json',authorization:'Bearer '+token},body:JSON.stringify(body)}),f.env);
  const accepted=await call('/api/object-audits',{submissionId:lease,policySha256:'caller ignored'});
  assert.equal(accepted.status,200,await accepted.clone().text());assert.equal((await accepted.json()).unitsEarned,20);
  const calls=f.calls(),replay=await call('/api/submissions',{leaseId:lease,outputs:[]});
  assert.equal(replay.status,200);const r=await replay.json();assert.equal(r.accepted,2);assert.equal(r.unitsEarned,0);
  assert.deepEqual(f.calls(),calls);
  delete f.env.OBJECT_SETTLEMENT_POLICY;
  const closed=await call('/api/object-audits',{submissionId:lease});assert.equal(closed.status,503);
  assert.equal((await closed.json()).error,'object_verification_unavailable');
  assert.deepEqual(f.counts(),{publications:2,ledger:1,accepted:1,units:20});
});
