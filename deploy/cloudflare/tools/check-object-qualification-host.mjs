// Real finite loopback HTTP -> dedicated bridge -> actual SQLite registry.
// All artifacts/identities/permits are synthetic; no cloud/model execution.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {DatabaseSync} from 'node:sqlite';
import {sqliteD1} from './sqlite-d1.mjs';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectQualification} from './prepare-object-qualification.mjs';
import {qualifyObjectDevice,revokeObjectQualification,objectQualificationStatus} from '../src/objectQualification.js';
import {handleObjectQualification} from '../object-qualification-bridge/worker.js';

if(!process.argv[2])throw Error('private_python_path_required');
const child=spawn(process.argv[2],['-m','community.tests.serve_object_qualification_host'],{
  cwd:new URL('../../../',import.meta.url),windowsHide:true,stdio:['pipe','pipe','pipe'],
  env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'},
});
let timer,stderr='',sql,receipt;
child.stderr.on('data',chunk=>{stderr=(stderr+chunk).slice(-16384);});
child.stdin.on('error',()=>{});
try {
  const ready=await new Promise((resolve,reject)=>{
    let data='';
    timer=setTimeout(()=>reject(Error('synthetic_private_host_ready_timeout')),60000);
    child.on('error',reject);child.on('exit',code=>reject(Error('synthetic_private_host_exit_'+code)));
    child.stdout.on('data',chunk=>{
      data+=chunk;if(data.length>16384)return reject(Error('synthetic_private_host_ready_limit'));
      if(data.includes('\n')){clearTimeout(timer);try{resolve(JSON.parse(data.split('\n')[0]));}catch(e){reject(e);}}
    });
  });
  assert.equal(ready.scope,'synthetic-owned-sample-host-no-inference');
  assert(Number.isInteger(ready.port)&&ready.port>0&&ready.port<65536);
  const p=ready.policy,account=ready.request.accountId;
  const privateEnv={OBJECT_SAMPLE_QUALIFIER_ORIGIN:'https://synthetic-owned-host.test',
    OBJECT_SAMPLE_QUALIFIER_SECRET:'synthetic-private-sample-secret-0000000000'};
  sql=new DatabaseSync(':memory:');let calls=0;
  const env={DB:sqliteD1(sql),DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:p.resource.bucket,
    OBJECT_QUALIFICATION_MODE:'saved-sample-v1',OBJECT_QUALIFICATION_POLICY:JSON.stringify(p),
    OBJECT_QUALIFIER:{async fetch(request){
      calls++;
      return handleObjectQualification(request,privateEnv,(url,init)=>{
        assert.equal(url,'https://synthetic-owned-host.test/object-qualifications/evidence');
        // Test-only substitution: the production bridge still requires HTTPS;
        // the fixture is reachable solely on this process's loopback adapter.
        return fetch(`http://127.0.0.1:${ready.port}/object-qualifications/evidence`,init);
      });
    }}};
  await prepareDatabase(env.DB);await prepareObjectQualification(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-private-token',0)").run(account);
  const body={requestId:ready.request.requestId,profileId:ready.request.profileId,artifactSetSha256:ready.request.artifactSetSha256};
  const result=await qualifyObjectDevice(env,account,body);
  assert.equal(result.qualified,true);assert.equal(result.independentlyRecomputedRoutineUploads,false);
  const at=Math.floor(Date.now()/1000);
  assert.equal((await objectQualificationStatus(env,account,body.profileId,at)).qualified,true);
  const replay=await qualifyObjectDevice(env,account,body,at);
  assert.equal(replay.replayed,true);assert.equal(replay.expiresAt,result.expiresAt);assert.equal(calls,1);
  await revokeObjectQualification(env,account,{operationId:'7'.repeat(32),profileId:body.profileId},at);
  assert.equal((await objectQualificationStatus(env,account,body.profileId,at)).qualified,false);
  assert.equal((await qualifyObjectDevice(env,account,body,at)).qualified,false);assert.equal(calls,1);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM ledger').get().n,0);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM published_index').get().n,0);
  receipt={status:'SYNTHETIC_OWNED_HOST_BRIDGE_REGISTRY_PASSED',checks:1,locations:100,views:600,
    actualLoopbackHTTP:true,actualFullNumericalComparator:true,actualSQLiteRegistry:true,
    lostReplyReplayWithoutAnotherComparison:true,revocationPreventsRegrant:true,
    nativeInference:false,realQualifiedAccounts:0,acceptedContributions:0,creditsCreated:0,providerCalls:0};
}catch(error){
  if(stderr)process.stderr.write(stderr);throw error;
}finally{
  clearTimeout(timer);if(sql)sql.close();
  child.stdin.end();
  let stop;
  try{
    if(child.exitCode===null&&child.signalCode===null)await Promise.race([
      once(child,'exit'),new Promise((_,reject)=>{stop=setTimeout(()=>reject(Error('synthetic_private_host_stop_timeout')),5000);}),
    ]);
    if(receipt)assert.equal(child.exitCode,0,'owned synthetic host must close normally before success');
  }finally{clearTimeout(stop);if(child.exitCode===null&&child.signalCode===null)child.kill();}
}
console.log(JSON.stringify({...receipt,ownedPrivateHostStopped:true}));
