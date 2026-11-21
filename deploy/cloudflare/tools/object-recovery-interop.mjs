// Actual Node/bridge -> loopback Python saved jobs; native inference synthetic.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectAuditRecovery} from './prepare-object-audit-recovery.mjs';
import {sqliteD1} from './sqlite-d1.mjs';
import {stageObjectAudit,advanceObjectAudit} from '../src/objectAuditDispatch.js';
import {recoverObjectAudit} from '../src/objectAuditRecovery.js';
import {handleObjectAuditJobs} from '../native-object-verifier-bridge/worker.js';
import {syntheticR2} from '../src/syntheticR2.mjs';
import {COVERAGE_VALIDATOR} from '../src/objectCoverage.js';
import {deleteAccount,cleanupAccountArtifacts} from '../src/accountPrivacy.js';
const input=JSON.parse(readFileSync(process.argv[2],'utf8')),account='a'.repeat(32),lease=input.authority.leaseId,now=1000;
const sql=new DatabaseSync(':memory:'),r2=syntheticR2(new Map());
let retryPosts=0,lost=true;const diagnostics=[];
const env={DB:sqliteD1(sql),INDEX:{...r2,async get(key){const value=await r2.get(key);
  return value?{...value,body:new Response(await value.arrayBuffer()).body}:null;}},OBJECT_VERIFIER:{fetch(request){
  return handleObjectAuditJobs(request,{NATIVE_OBJECT_VERIFIER_ORIGIN:'https://native.synthetic',NATIVE_OBJECT_VERIFIER_SECRET:input.secret},
    async(url,init)=>{
      const path=new URL(url).pathname,isRetry=path.endsWith('/retry');if(isRetry)retryPosts++;
      const response=await fetch(input.origin+path,init);diagnostics.push({path,status:response.status,reply:await response.clone().json()});
      if(isRetry && lost && response.status===200){lost=false;await response.arrayBuffer();throw Error('synthetic lost retry ack');}
      return response;
    });
}}};
try{
  await prepareDatabase(env.DB);await prepareObjectAuditRecovery(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-session',10)").run(account);
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',9999)").run(lease,account);
  for(const item of input.items){
    sql.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation) VALUES (?,?,'synthetic','object','synthetic','leased',?,'gen4')")
      .run(item.locationId,item.panoId,lease);
    sql.prepare('INSERT INTO lease_items VALUES (?,?)').run(lease,item.locationId);
    sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,1000)').run(item.locationId,COVERAGE_VALIDATOR,'f'.repeat(64));
  }
  await stageObjectAudit(env,account,input.authority,input.objectIndex,now);
  let failed;
  for(let i=0;i<60;i++){
    const value=await advanceObjectAudit(env,account,lease,now+i*30);
    if(value.auditState==='failed'){failed=value;break;}
    await new Promise(resolve=>setTimeout(resolve,200));
  }
  assert.ok(failed,'synthetic first failure not observed '+JSON.stringify(diagnostics));
  assert.equal(sql.prepare('SELECT native_attempts FROM object_audit_candidates').get().native_attempts,1);
  const request={action:'retry-native',requestId:'7'.repeat(64)};
  const first=await recoverObjectAudit(env,account,lease,request,3000);assert.equal(first.recoveryState,'pending');
  assert.equal(retryPosts,1);assert.equal(sql.prepare('SELECT expected_attempts FROM object_audit_recoveries').get().expected_attempts,1);
  const second=await recoverObjectAudit(env,account,lease,request,3030);assert.equal(second.recoveryState,'applied');assert.equal(retryPosts,2);
  let approved;
  for(let i=0;i<60;i++){
    const value=await advanceObjectAudit(env,account,lease,3060+i*30);
    assert.equal(value.accepted,0);assert.equal(value.unitsEarned,0);assert.equal(value.productionQualified,false);
    if(value.auditState==='approved' && value.freshAuditReply){approved=value;break;}
    await new Promise(resolve=>setTimeout(resolve,200));
  }
  assert.ok(approved,'synthetic retry not approved '+JSON.stringify(diagnostics));
  assert.equal(sql.prepare('SELECT native_attempts FROM object_audit_candidates').get().native_attempts,2);
  assert.equal((await recoverObjectAudit(env,account,lease,request,5000)).freshAuditReply,false);assert.equal(retryPosts,2);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM published_index').get().n,0);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM ledger').get().n,0);
  await deleteAccount(env,account,{accountId:account,confirmation:'DELETE',idempotencyKey:'8'.repeat(64)},6000);
  let erased=false;
  for(let i=0;i<20;i++){
    await cleanupAccountArtifacts(env,account,64);
    if(sql.prepare('SELECT state FROM account_cleanup WHERE artifact_key=?').get('object-audit-jobs/'+lease)?.state==='erased'){erased=true;break;}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.equal(erased,true);
  console.log(JSON.stringify({status:'NODE_PYTHON_OBJECT_RECOVERY_INTEROP_PASSED',retryPosts,nativeAttempts:2,
    originalFailedAttemptObserved:true,erased,syntheticInference:true,nativeInferences:0,earnedCredits:0}));
}finally{sql.close();}
