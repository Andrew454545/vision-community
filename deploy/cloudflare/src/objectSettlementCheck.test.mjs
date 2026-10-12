// Actual local SQLite/files, synthetic native replies and coverage only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareObjectAuditDispatch} from '../tools/prepare-object-audit-dispatch.mjs';
import {stageObjectAudit,advanceObjectAudit} from './objectAuditDispatch.js';
import {checkObjectSettlement} from './objectSettlementCheck.js';
import {syntheticR2} from './syntheticR2.mjs';
import {sha256Hex,encodeUtf8} from './model.js';
import {OBJECT_INDEX_MODEL} from './objectIndex.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {objectCapabilities} from './objectAdmission.js';
const doc=JSON.parse(readFileSync(new URL('../../../community/tests/fixtures/object-feature-content-v1.json',import.meta.url),'utf8'));
const account='b'.repeat(32),lease=doc.leaseId,job='c'.repeat(32),now=100000;
async function setup(t) {
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const objects=new Map(),r2=syntheticR2(objects);
  const env={DB:sqliteD1(sql),INDEX:{...r2,async get(key){const obj=await r2.get(key);
    return obj?{...obj,body:new Response(await obj.arrayBuffer()).body}:null;}}};
  await prepareDatabase(env.DB);await prepareObjectAuditDispatch(env.DB);
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
    blurAreaFractionExclusive:0.5,tileGrid:8,tunnelVisionProbabilityInclusive:0.85,
    tunnelEvidencePolicy:'none-darkness-never-rejects-v1',protectedAuthorityManifestSha256:'2'.repeat(64)});
  index.manifest.sourceTsv='C:/SYNTHETIC-PRIVATE/source.tsv';
  index.manifest.privateExtension={account:'SYNTHETIC-PRIVATE'};
  index.manifest.viewQuality.privateExtension={path:'SYNTHETIC-PRIVATE'};
  const authority={leaseId:lease,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),
    sourceSha256:await sha256Hex(new Uint8Array(Buffer.from(index.sourceTsv,'base64')))};
  const row=()=>sql.prepare('SELECT * FROM object_audit_candidates WHERE lease_id=?').get(lease);
  const reply=()=>({version:1,jobId:job,leaseId:lease,profileId:authority.profileId,policyId:authority.policyId,
    assignmentSha256:authority.assignmentSha256,submissionSha256:row().submission_sha256,
    candidateManifestSha256:'3'.repeat(64),state:'approved',decision:'approved',attempts:1,retryAt:0,
    receiptSha256:'4'.repeat(64),serverAuthorization:false,productionQualified:false,acceptedContributions:0,searchCreditsCreated:0});
  await stageObjectAudit(env,account,authority,index,now);
  let posts=0,gets=0;
  env.OBJECT_VERIFIER={fetch(request){if(request.method==='POST')posts++;else gets++;return Response.json(reply());}};
  await advanceObjectAudit(env,account,lease,now);
  const state=()=>JSON.stringify(Object.fromEntries(['accounts','leases','locations','lease_items','object_coverage',
    'object_audit_candidates','account_artifact_writes','published_index','ledger'].map(table=>[table,sql.prepare('SELECT * FROM '+table).all()])));
  const check=(time=now,timeout=20000)=>checkObjectSettlement(env,account,lease,time,timeout);
  return {sql,env,objects,row,index,reply,check,state,calls:()=>({posts,gets})};
}

test('fresh correlated receipt and exact stored features pass without writes, acceptance or credits',async t=>{
  const f=await setup(t),before=f.state(),bytes=[...f.objects].map(([k,v])=>[k,Buffer.from(v).toString('base64')]);
  const value=await f.check();assert.equal(value.records.length,2);assert.equal(value.receipt.state,'approved');
  assert.match(value.evidenceSha256,/^[a-f0-9]{64}$/);assert.equal(value.serverAuthorization,false);
  assert.equal(value.productionQualified,false);assert.equal(value.acceptedContributions,0);assert.equal(value.searchCreditsCreated,0);
  assert.equal(JSON.stringify(value.publicManifest).includes('SYNTHETIC-PRIVATE'),false);
  assert.equal(value.publicManifest.sourceTsv,'locations.tsv');
  assert.equal(value.objectIndex.manifest.privateExtension.account,'SYNTHETIC-PRIVATE');
  assert.equal(f.state(),before);assert.deepEqual(f.calls(),{posts:1,gets:1});
  assert.deepEqual([...f.objects].map(([k,v])=>[k,Buffer.from(v).toString('base64')]),bytes);
  assert.equal(objectCapabilities().objectContributions.ready,false);
});

test('final lookup forwards no user credentials, performs GET only and observes cancellation',async t=>{
  const f=await setup(t);let received;
  f.env.OBJECT_VERIFIER={fetch(request){received=request;
    assert.equal(request.url,`https://object-verifier.internal/object-audits/${job}`);assert.equal(request.method,'GET');
    assert.equal(request.body,null);assert.equal(request.headers.get('authorization'),null);assert.equal(request.headers.get('cookie'),null);
    return Response.json(f.reply());}};
  await f.check();assert.equal(received.signal.aborted,true);
});

test('busy candidates, changed upload ownership and lease membership bounds fail before native access',async t=>{
  for(const damage of [f=>f.sql.prepare('UPDATE object_audit_candidates SET claim_token=?,claim_until=100030').run('e'.repeat(32)),
    f=>{f.sql.exec('DROP TRIGGER artifact_write_intent_immutable');f.sql.exec("UPDATE account_artifact_writes SET sha256='wrong'");},
    f=>f.sql.exec('UPDATE object_audit_candidates SET native_attempts=0'),
    f=>f.sql.exec('UPDATE object_audit_candidates SET native_state=NULL'),
    f=>f.sql.exec('DELETE FROM account_artifact_writes'),
    f=>{for(let id=13;id<=16;id++)f.sql.exec(`INSERT INTO locations(id,asset_id,capture,lane,model) VALUES (${id},'extra-${id}','synthetic','object','synthetic'); INSERT INTO lease_items VALUES ('${lease}',${id})`);}
  ]){
    const f=await setup(t);damage(f);const before=f.state();
    await assert.rejects(f.check(),error=>['object_settlement_busy','object_settlement_evidence_unavailable'].includes(error.message));
    assert.equal(f.calls().gets,0);assert.equal(f.state(),before);
  }
});

test('coverage and lease expiry during inspection are checked using elapsed time',async t=>{
  for(const sql of ['UPDATE object_coverage SET validated_at=13601','UPDATE leases SET expires_at=100001']){
    const f=await setup(t);f.sql.exec(sql);const before=f.state();
    await assert.rejects(f.check(),{message:'object_settlement_evidence_unavailable'});assert.equal(f.state(),before);
  }
});

test('database stalls and malformed or hanging native response bodies share the finite deadline',async t=>{
  for(const mode of ['database','body-hang','body-limit','media','invalid-json']){
    const f=await setup(t),before=f.state();
    if(mode==='database')f.env.DB={prepare(){return {bind(){return {first:()=>new Promise(()=>{})};}};}};
    else f.env.OBJECT_VERIFIER={fetch(){
      if(mode==='body-hang')return new Response(new ReadableStream({pull:()=>new Promise(()=>{})}),{headers:{'content-type':'application/json'}});
      if(mode==='body-limit')return new Response(' '.repeat(65537),{headers:{'content-type':'application/json'}});
      if(mode==='media')return new Response(JSON.stringify(f.reply()),{headers:{'content-type':'text/plain'}});
      return new Response('{',{headers:{'content-type':'application/json'}});
    }};
    await assert.rejects(f.check(now,mode==='database'||mode==='body-hang'?10:20000),{message:'object_settlement_evidence_unavailable'});
    assert.equal(f.state(),before);
  }
});

test('cached approval cannot replace an unavailable, stale, wrong or overauthorizing native reply',async t=>{
  for(const damage of [()=>Response.json({error:'object_job_receipt_unavailable'},{status:503}),
    ()=>{throw Error('synthetic transport failure');},...[
      {jobId:'f'.repeat(32)},{leaseId:'f'.repeat(32)},{assignmentSha256:'f'.repeat(64)},
      {sourceSha256:'f'.repeat(64)},{submissionSha256:'f'.repeat(64)},{profileId:'f'.repeat(64)},
      {policyId:'different'},{candidateManifestSha256:'f'.repeat(64)},{receiptSha256:'f'.repeat(64)},
      {attempts:2},{state:'cancelled',decision:'pending'},{productionQualified:true},{acceptedContributions:1},
      {privatePath:'forbidden'},
    ].map(change=>f=>Response.json({...f.reply(),...change}))]) {
    const f=await setup(t),before=f.state();f.env.OBJECT_VERIFIER={fetch:()=>damage(f)};
    await assert.rejects(f.check(),{message:'object_settlement_evidence_unavailable',status:503});
    assert.equal(f.state(),before);assert.equal(f.row().native_state,'approved');
  }
});

test('ownership, cancellation, publication, expired coverage, changed pose/model and invalid setup refuse before native lookup',async t=>{
  for(const sql of ["UPDATE accounts SET deleted_at=100001,units=0", "UPDATE object_audit_candidates SET state='cancelled'",
    "UPDATE object_audit_candidates SET state='rejected'", "UPDATE leases SET state='expired'",'UPDATE leases SET expires_at=100000',
    "UPDATE locations SET camera_generation='gen3'", "UPDATE object_coverage SET validator='old'",'UPDATE object_coverage SET validated_at=1',
    'UPDATE object_coverage SET validated_at=100001',"UPDATE object_coverage SET evidence_sha256='invalid'",'DELETE FROM object_coverage',
    "UPDATE locations SET active_lease=NULL", "UPDATE locations SET model='old'",'UPDATE locations SET lat=lat+0.000001',
    'UPDATE locations SET heading=heading+0.01','UPDATE locations SET pitch=pitch+0.01','UPDATE locations SET zoom=zoom+0.01',
    "UPDATE locations SET country='changed'", "UPDATE locations SET asset_id='changed' WHERE id=11",'DELETE FROM lease_items WHERE location_id=11',
    "UPDATE object_dispatch_revision SET contract='future'",
    "INSERT INTO published_index(location_id,index_text,output_sha256,published_at) VALUES (11,'','synthetic',100000)"]){
    const f=await setup(t);f.sql.exec(sql);const before=f.state();
    await assert.rejects(f.check(),{message:'object_settlement_evidence_unavailable'});
    assert.equal(f.calls().gets,0);assert.equal(f.state(),before);
  }
});

test('owned R2 body, checksum, privacy fence and binary contents must agree with the saved submission',async t=>{
  for(const mode of ['missing','fence','size','checksum','stream-size','stream-hang','no-body','manifest','lane','source','quality-policy','quality-authority']) {
    const f=await setup(t),key=f.row().artifact_key,get=f.env.INDEX.get;
    if(mode==='missing')f.objects.delete(key);
    if(mode==='checksum')f.objects.set(key,encodeUtf8(' '.repeat(f.row().payload_bytes)));
    if(['manifest','lane','source','quality-policy','quality-authority'].includes(mode)) {
      const changed=structuredClone(f.index);
      if(mode==='manifest')changed.manifest.completed=false;
      if(mode==='quality-policy')changed.manifest.viewQuality.tunnelEvidencePolicy='none-darkness-kept-v1';
      if(mode==='quality-authority')delete changed.manifest.viewQuality.protectedAuthorityManifestSha256;
      if(mode==='lane')changed.files['semantic-pq128.bin']='';
      if(mode==='source')changed.sourceTsv=Buffer.from('changed').toString('base64');
      const raw=encodeUtf8(JSON.stringify(changed)),sha=await sha256Hex(raw),newKey=`object-quarantine/${lease}/${sha}.json`;
      // Explicit fixture corruption of the trusted saved identity; the native
      // reply still cannot bypass structural or source checks.
      f.sql.exec('DROP TRIGGER artifact_write_intent_immutable; DROP TRIGGER object_dispatch_immutable');
      f.sql.prepare('UPDATE object_audit_candidates SET submission_sha256=?,artifact_key=?,payload_bytes=?').run(sha,newKey,raw.length);
      f.sql.prepare('UPDATE account_artifact_writes SET artifact_key=?,sha256=?,bytes=?').run(newKey,sha,raw.length);
      f.objects.set(newKey,raw);
    }
    f.env.INDEX.get=async k=>{const obj=await get(k);if(!obj)return null;
      if(mode==='fence')obj.customMetadata={visionPrivacyFence:'1'};
      if(mode==='size')obj.size++;
      if(mode==='no-body')obj.body=null;
      if(mode==='stream-size')obj.body=new Response(new Uint8Array(obj.size+1)).body;
      if(mode==='stream-hang')obj.body=new ReadableStream({pull(){return new Promise(()=>{});}});
      return obj;};
    const before=f.state();await assert.rejects(f.check(now,mode==='stream-hang'?10:20000),{message:'object_settlement_evidence_unavailable'});
    assert.equal(f.calls().gets,0);assert.equal(f.state(),before);
  }
});

test('deletion, cancellation, changed receipt, pose or coverage during native lookup invalidate the inspection',async t=>{
  for(const change of ["UPDATE accounts SET deleted_at=100001,units=0","UPDATE object_audit_candidates SET state='cancelled'",
    "UPDATE object_audit_candidates SET receipt_sha256='"+'f'.repeat(64)+"'",'UPDATE locations SET heading=heading+0.01',
    'UPDATE object_coverage SET validated_at=99999',"UPDATE object_coverage SET evidence_sha256='"+'e'.repeat(64)+"'"]){
    const f=await setup(t);let after;
    f.env.OBJECT_VERIFIER={fetch(){const old=f.reply();f.sql.exec(change);after=f.state();return Response.json(old);}};
    await assert.rejects(f.check(),{message:'object_settlement_evidence_unavailable'});assert.equal(f.state(),after);
  }
});

test('one total deadline bounds R2/native reads and late replies are cancelled',async t=>{
  const f=await setup(t);let resolve,cancelled=false;
  f.env.OBJECT_VERIFIER={fetch:()=>new Promise(done=>{resolve=done;})};const before=f.state();
  await assert.rejects(f.check(now,20),{message:'object_settlement_evidence_unavailable'});
  resolve(new Response(new ReadableStream({cancel(){cancelled=true;}}),{headers:{'content-type':'application/json'}}));
  await new Promise(done=>setTimeout(done,5));assert.equal(cancelled,true);assert.equal(f.state(),before);
  f.env.INDEX.get=()=>new Promise(()=>{});await assert.rejects(f.check(now,5),{message:'object_settlement_evidence_unavailable'});
});

test('native body cleanup uses the remaining shared budget after a slow R2 read',async t=>{
  const f=await setup(t),get=f.env.INDEX.get;let cancelled=false;
  f.env.INDEX.get=async key=>{await new Promise(done=>setTimeout(done,80));return get(key);};
  f.env.OBJECT_VERIFIER={fetch:()=>new Response(new ReadableStream({
    pull:()=>new Promise(()=>{}),cancel(){cancelled=true;}}),{headers:{'content-type':'application/json'}})};
  await assert.rejects(f.check(now,130),{message:'object_settlement_evidence_unavailable'});
  await new Promise(done=>setTimeout(done,20));assert.equal(cancelled,true);
});

test('invalid caller identities and budgets fail before touching any resource',async()=>{
  for(const args of [[{},'x',lease,now,20],[{},account,'x',now,20],[{},account,lease,NaN,20],
    [{},account,lease,now,0],[{},account,lease,now,20001]]) {
    await assert.rejects(checkObjectSettlement(...args),{message:'invalid_object_settlement',status:400});
  }
});
