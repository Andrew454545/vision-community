// Actual local workerd persistence, synthetic native decisions/coverage only.
import seed from './object-settlement.fixture.mjs';
import {settleObjectAudit} from '../src/objectSettlement.js';
import {advanceObjectContribution} from '../src/objectAuditFlow.js';
import {deleteAccount} from '../src/accountPrivacy.js';
import {objectCapabilities} from '../src/objectAdmission.js';
const account='b'.repeat(32),lease='a'.repeat(32),job='c'.repeat(32);
const pins={policySha256:'5'.repeat(64),runtimeProfileSha256:'6'.repeat(64),qualityImplementationIdentity:'1'.repeat(64),
  protectedAuthoritySha256:'2'.repeat(64),protectedOriginHandoffSha256:'7'.repeat(64)};
const resource={accountId:'272760294910ef0b246980278aeb36e2',databaseId:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',bucket:'vision-community-staging'};
export default {async fetch(request,env){
  const mode=new URL(request.url).pathname.slice(1);
  const now=Math.floor(Date.now()/1000);
  if(mode==='seed') {
    await seed.fetch(request,env);
    await env.DB.prepare('UPDATE leases SET expires_at=?').bind(now+1000).run();
    await env.DB.prepare('UPDATE object_coverage SET validated_at=?').bind(now).run();
    await env.DB.prepare('CREATE TABLE synthetic_acceptance_calls (calls INTEGER,full INTEGER)').run();
    await env.DB.prepare('INSERT INTO synthetic_acceptance_calls VALUES (0,0)').run();
  }
  const provider={async fetch(r){
    const full=r.url.endsWith('/settlement-evidence');
    await env.DB.prepare('UPDATE synthetic_acceptance_calls SET calls=calls+1,full=full+?').bind(full?1:0).run();
    const c=await env.DB.prepare('SELECT * FROM object_audit_candidates WHERE lease_id=?').bind(lease).first();
    const audit={version:1,jobId:job,leaseId:lease,profileId:c.profile_id,policyId:c.policy_id,
      assignmentSha256:c.assignment_sha256,submissionSha256:c.submission_sha256,candidateManifestSha256:'3'.repeat(64),
      state:'approved',decision:'approved',attempts:1,retryAt:0,receiptSha256:'4'.repeat(64),
      serverAuthorization:false,productionQualified:false,acceptedContributions:0,searchCreditsCreated:0};
    if(!full)return Response.json(audit);
    if(mode==='pose-late')await env.DB.prepare('UPDATE locations SET heading=heading+1').run();
    return Response.json({audit,...pins,...(mode==='wrong-policy'?{policySha256:'9'.repeat(64)}:{}),
      resource,qualificationScope:'batch-only',issuedAt:now,expiresAt:now+30});
  }};
  const bound={...env,OBJECT_VERIFIER:provider,INDEX_BUCKET_NAME:resource.bucket,
    OBJECT_SETTLEMENT_POLICY:JSON.stringify({version:1,scope:'object-batch-parity-v1',policyId:'staging.synthetic',
      profiles:['1'.repeat(64)],...pins,resource})};
  if(mode==='partial')bound.INDEX={get:(...args)=>env.INDEX.get(...args),put:(key,...args)=>{
    if(key.endsWith('/locations.tsv'))throw Error('synthetic interrupted upload');return env.INDEX.put(key,...args);}};
  if(mode==='lost-commit')bound.DB={prepare:(...args)=>env.DB.prepare(...args),async batch(statements){
    await env.DB.batch(statements);throw Error('synthetic lost database response');}};
  let value;
  try {
    if(mode==='seed')value={seeded:true};
    else if(mode==='delete'){value=await deleteAccount(bound,account,{accountId:account,idempotencyKey:'8'.repeat(64),confirmation:'DELETE'},now+1);}
    else if(mode==='advance')value=await advanceObjectContribution(bound,account,lease,now);
    else value=await settleObjectAudit(bound,account,lease,now);
  }catch(error){value={error:error.message,status:error.status};}
  const manifest=await env.INDEX.get(`object-index-v4/${lease}/manifest.json`);
  return Response.json({value,publications:(await env.DB.prepare('SELECT count(*) AS n FROM published_index').first()).n,
    ledger:(await env.DB.prepare("SELECT count(*) AS n FROM ledger WHERE reason='verified_work'").first()).n,
    acceptances:(await env.DB.prepare('SELECT count(*) AS n FROM object_acceptances').first()).n,
    owner:await env.DB.prepare('SELECT units,deleted_at FROM accounts WHERE id=?').bind(account).first(),
    calls:await env.DB.prepare('SELECT * FROM synthetic_acceptance_calls').first(),
    sanitized:manifest?!((await manifest.text()).includes('SYNTHETIC-PRIVATE')):null,
    objectAdmissionReady:objectCapabilities().objectContributions.ready,nativeInferences:0,liveCalls:0});
}};
