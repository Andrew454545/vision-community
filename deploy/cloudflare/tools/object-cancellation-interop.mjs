// Actual bridge/loopback Python saved jobs; inference explicitly synthetic.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectAuditCancellation} from './prepare-object-audit-cancellation.mjs';
import {sqliteD1} from './sqlite-d1.mjs';
import {stageObjectAudit,advanceObjectAudit} from '../src/objectAuditDispatch.js';
import {cancelObjectAudit,advanceObjectCancellation} from '../src/objectAuditCancellation.js';
import {handleObjectAuditJobs} from '../native-object-verifier-bridge/worker.js';
import {syntheticR2} from '../src/syntheticR2.mjs';
import {COVERAGE_VALIDATOR} from '../src/objectCoverage.js';
import {PRIVACY_FENCE} from '../src/artifactWrites.js';
const input=JSON.parse(readFileSync(process.argv[2],'utf8')),account='a'.repeat(32),lease=input.authority.leaseId,now=1000;
const sql=new DatabaseSync(':memory:'),objects=new Map(),r2=syntheticR2(objects);
let starts=0,erasures=0;const diagnostics=[];
const env={DB:sqliteD1(sql),INDEX:{...r2,async get(key){const value=await r2.get(key);
  return value?{...value,body:new Response(await value.arrayBuffer()).body}:null;}},OBJECT_VERIFIER:{fetch(request){
  return handleObjectAuditJobs(request,{NATIVE_OBJECT_VERIFIER_ORIGIN:'https://native.synthetic',NATIVE_OBJECT_VERIFIER_SECRET:input.secret},
    async(url,init)=>{
      const path=new URL(url).pathname,isStart=path==='/object-audits';
      if(isStart)starts++;if(path.endsWith('/erase'))erasures++;
      const response=await fetch(input.origin+path,init);diagnostics.push({path,status:response.status,reply:await response.clone().json()});
      if(isStart && response.status===202){await response.arrayBuffer();throw Error('synthetic lost start reply');}
      // Saved-job starts currently return HTTP 200; accept either success code
      // in this transport fault injector without changing the bridge contract.
      if(isStart && response.status===200){await response.arrayBuffer();throw Error('synthetic lost start reply');}
      return response;
    });
}}};
try{
  await prepareDatabase(env.DB);await prepareObjectAuditCancellation(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-session',10)").run(account);
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',9999)").run(lease,account);
  for(const item of input.items){
    sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (?,?,'synthetic','object','synthetic','leased',?,'gen4')")
      .run(item.locationId,item.panoId,lease);
    sql.prepare('INSERT INTO lease_items VALUES (?,?)').run(lease,item.locationId);
    sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,1000)').run(item.locationId,COVERAGE_VALIDATOR,'f'.repeat(64));
  }
  await stageObjectAudit(env,account,input.authority,input.objectIndex,now);
  const started=await advanceObjectAudit(env,account,lease,now);assert.equal(starts,1);assert.equal(started.freshAuditReply,false);
  const candidate=()=>sql.prepare('SELECT * FROM object_audit_candidates').get();
  assert.equal(candidate().job_id,null,'start reply was not lost');
  const cancelled=await cancelObjectAudit(env,account,lease,'7'.repeat(64),now+1);assert.equal(cancelled.cleanupPending,true);
  assert.equal(sql.prepare('SELECT prior_job_id FROM object_audit_cancellations').get().prior_job_id,null);
  let erased=false;
  for(let i=0;i<60;i++){
    const value=await advanceObjectCancellation(env,account,lease,now+2+i*900);
    assert.equal(value.accepted,0);assert.equal(value.unitsEarned,0);assert.equal(value.productionQualified,false);
    if(value.cleanupState==='erased'){erased=true;break;}
    await new Promise(resolve=>setTimeout(resolve,200));
  }
  assert.equal(erased,true,'running native assignment was not erased '+JSON.stringify(diagnostics));
  assert.equal(new TextDecoder().decode(objects.get(candidate().artifact_key)),PRIVACY_FENCE);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM locations WHERE active_lease IS NOT NULL').get().n,0);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM published_index').get().n,0);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
  const owner=sql.prepare('SELECT units,deleted_at FROM accounts WHERE id=?').get(account);assert.equal(owner.units,10);assert.equal(owner.deleted_at,null);
  assert.equal((await advanceObjectAudit(env,account,lease,100000)).cancelled,true);assert.equal(starts,1);
  const calls=erasures;assert.equal((await cancelObjectAudit(env,account,lease,'7'.repeat(64),100001)).cleanupState,'erased');
  await advanceObjectCancellation(env,account,lease,100002);assert.equal(erasures,calls);
  console.log(JSON.stringify({status:'NODE_PYTHON_OBJECT_CANCELLATION_INTEROP_PASSED',starts,erasures,
    lostStartReply:true,unknownHostedJobId:true,erased,accountActive:true,bankedUnits:10,
    syntheticInference:true,nativeInferences:0,earnedCredits:0,liveCalls:0}));
}finally{sql.close();}
