// Actual Python comparator -> saved adapter -> authenticated registry contract.
// Input is a locally generated synthetic fixture, not authentic inference.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {sqliteD1} from './sqlite-d1.mjs';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareObjectQualification} from './prepare-object-qualification.mjs';
import {qualifyObjectDevice,objectQualificationStatus} from '../src/objectQualification.js';
const packet=JSON.parse(readFileSync(process.argv[2],'utf8'));
assert.equal(packet.scope,'synthetic-private-adapter-fixture-no-inference');
const sql=new DatabaseSync(':memory:');
try {
  const p=packet.policy,account=packet.request.accountId;
  const env={DB:sqliteD1(sql),DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:p.resource.bucket,
    OBJECT_QUALIFICATION_MODE:'saved-sample-v1',OBJECT_QUALIFICATION_POLICY:JSON.stringify(p),
    OBJECT_QUALIFIER:{async fetch(request){
      const actual=await request.json();
      assert.equal(actual.accountId,account);assert.equal(actual.profileId,packet.request.profileId);
      assert.equal(actual.artifactSetSha256,packet.request.artifactSetSha256);
      // The stored Python comparison took real time. Advance the consumer's
      // observed wall time by waiting that same bounded interval, then issue a
      // fresh challenge envelope as the private host would on a readback.
      const seconds=Math.max(0,packet.proof.issuedAt-packet.now);
      assert(seconds<=60);await new Promise(resolve=>setTimeout(resolve,seconds*1000));
      return Response.json({...packet.proof,requestId:actual.requestId,challenge:actual.challenge});
    }}};
  await prepareDatabase(env.DB);await prepareObjectQualification(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-private-token',0)").run(account);
  const body={requestId:packet.request.requestId,profileId:packet.request.profileId,artifactSetSha256:packet.request.artifactSetSha256};
  const result=await qualifyObjectDevice(env,account,body,packet.now);
  assert.equal(result.qualified,true);assert.equal(result.independentlyRecomputedRoutineUploads,false);
  assert.equal(packet.proof.report.qualified,false);
  assert.equal((await objectQualificationStatus(env,account,body.profileId,packet.proof.issuedAt)).qualified,true);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM ledger').get().n,0);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM published_index').get().n,0);
  console.log(JSON.stringify({status:'SYNTHETIC_PYTHON_REGISTRY_ADAPTER_PASSED',checks:1,locations:packet.proof.report.locations,
    numericalSampleCompatible:packet.proof.report.sampleCompatible,nativeInference:false,realQualifiedAccounts:0,
    acceptedContributions:0,creditsCreated:0,providerCalls:0}));
}finally{sql.close();}
