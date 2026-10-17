// Finite Windows Node -> actual Python/SQLite/HTTP audit service. The Python
// test supplies a synthetic native runner, never production imagery/inference.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectAuditDispatch} from './prepare-object-audit-dispatch.mjs';
import {sqliteD1} from './sqlite-d1.mjs';
import {stageObjectAudit,advanceObjectAudit} from '../src/objectAuditDispatch.js';
import {handleObjectAuditJobs} from '../native-object-verifier-bridge/worker.js';
import {syntheticR2} from '../src/syntheticR2.mjs';
import {sha256Hex,encodeUtf8} from '../src/model.js';
import {deleteAccount,cleanupAccountArtifacts} from '../src/accountPrivacy.js';
import {COVERAGE_VALIDATOR} from '../src/objectCoverage.js';
const input=JSON.parse(readFileSync(process.argv[2],'utf8')),account='a'.repeat(32),lease=input.authority.leaseId,now=1000;
const sql=new DatabaseSync(':memory:'),objects=new Map(),r2=syntheticR2(objects);
let lost=true,starts=0,statuses=0;const diagnostics=[];
const env={DB:sqliteD1(sql),INDEX:{...r2,async get(key){const value=await r2.get(key);
  return value?{...value,body:new Response(await value.arrayBuffer()).body}:null;}},OBJECT_VERIFIER:{fetch(request){
  return handleObjectAuditJobs(request,{NATIVE_OBJECT_VERIFIER_ORIGIN:'https://native.synthetic',
    NATIVE_OBJECT_VERIFIER_SECRET:input.secret},async(url,init)=>{
      const path=new URL(url).pathname;
      if(path==='/object-audits')starts++;else if(init.method==='GET')statuses++;
      const response=await fetch(input.origin+path,init);diagnostics.push({path,status:response.status,reply:await response.clone().json()});
      if(path==='/object-audits' && lost){lost=false;await response.arrayBuffer();throw Error('synthetic lost acknowledgement');}
      return response;
    });
}}};
try {
  await prepareDatabase(env.DB);await prepareObjectAuditDispatch(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-session',10)").run(account);
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',9999)").run(lease,account);
  for(const item of input.items) {
    sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (?,?,'synthetic','object','synthetic','leased',?,'gen4')")
      .run(item.locationId,item.panoId,lease);
    sql.prepare('INSERT INTO lease_items VALUES (?,?)').run(lease,item.locationId);
    sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,1000)').run(item.locationId,COVERAGE_VALIDATOR,'f'.repeat(64));
  }
  await stageObjectAudit(env,account,input.authority,input.objectIndex,now);
  const lostResult=await advanceObjectAudit(env,account,lease,now);assert.equal(lostResult.freshAuditReply,false);
  assert.equal(sql.prepare('SELECT job_id FROM object_audit_candidates').get().job_id,null);
  // Native runner is tiny but asynchronous. Use a finite 12-second protocol
  // check rather than interpreting acknowledgement as completed inference.
  let approved;
  for(let i=1;i<=60;i++) {
    const value=await advanceObjectAudit(env,account,lease,now+i*30);
    assert.equal(value.accepted,0);assert.equal(value.unitsEarned,0);assert.equal(value.productionQualified,false);
    if(value.auditState==='approved' && value.freshAuditReply){approved=value;break;}
    await new Promise(resolve=>setTimeout(resolve,200));
  }
  assert.ok(approved,'synthetic native audit did not complete within finite limit '+JSON.stringify(diagnostics));
  const pin=sql.prepare('SELECT job_id,candidate_manifest_sha256,receipt_sha256 FROM object_audit_candidates').get();
  assert.equal(pin.candidate_manifest_sha256,input.nativeManifestSha256);assert.match(pin.receipt_sha256,/^[0-9a-f]{64}$/);
  const next=sql.prepare('SELECT next_attempt FROM object_audit_candidates').get().next_attempt;
  const observed=await advanceObjectAudit(env,account,lease,next);assert.equal(observed.freshAuditReply,true);
  assert.deepEqual(sql.prepare('SELECT job_id,candidate_manifest_sha256,receipt_sha256 FROM object_audit_candidates').get(),pin);
  assert.equal(starts,2);assert.ok(statuses>=1);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM published_index').get().n,0);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
  const stored=objects.values().next().value;
  assert.equal(await sha256Hex(stored),await sha256Hex(encodeUtf8(JSON.stringify(input.objectIndex))));
  await deleteAccount(env,account,{accountId:account,confirmation:'DELETE',idempotencyKey:'4'.repeat(64)},2000);
  let erased=false;
  for(let i=0;i<20;i++) {
    await cleanupAccountArtifacts(env,account,64);
    const state=sql.prepare("SELECT state FROM account_cleanup WHERE artifact_key=?").get('object-audit-jobs/'+lease);
    if(state?.state==='erased'){erased=true;break;}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.equal(erased,true);assert.equal(sql.prepare('SELECT state FROM object_audit_candidates').get().state,'cancelled');
  await assert.rejects(advanceObjectAudit(env,account,lease,2001),{message:'account_not_active'});
  console.log(JSON.stringify({status:'NODE_PYTHON_OBJECT_DISPATCH_INTEROP_PASSED',starts,statuses,
    nativeManifestMatches:true,erased:true,syntheticInference:true,nativeInferences:0,earnedCredits:0}));
} finally {sql.close();}
