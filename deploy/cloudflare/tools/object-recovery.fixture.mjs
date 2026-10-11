// Actual workerd/D1/R2 recovery. Native acknowledgements explicitly synthetic.
import {stageObjectAudit} from '../src/objectAuditDispatch.js';
import {recoverObjectAudit} from '../src/objectAuditRecovery.js';
import {sha256Hex,encodeUtf8} from '../src/model.js';
import {deleteAccount,cleanupAccountArtifacts} from '../src/accountPrivacy.js';
const account='a'.repeat(32),lease='b'.repeat(32),job='d'.repeat(32),now=100000;
const source=encodeUtf8('synthetic source\n');
const authority={leaseId:lease,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64)};
const index={manifest:{synthetic:true},files:{'synthetic.bin':''},sourceTsv:btoa('synthetic source\n')};
const key=n=>n.toString(16).padStart(64,'0');
export default {async fetch(request,env){
  const path=new URL(request.url).pathname;
  const bound={...env,OBJECT_VERIFIER:{async fetch(request){
    const p=new URL(request.url).pathname;
    if(p===`/object-assignments/${lease}/erase`){
      await env.DB.prepare('UPDATE synthetic_retry_intents SET erased=1').run();
      return Response.json({version:1,leaseId:lease,policyId:authority.policyId,assignmentSha256:authority.assignmentSha256,
        state:'erased',productionQualified:false,serverAuthorization:false});
    }
    if(p!==`/object-audits/${job}/retry` || request.method!=='POST')throw Error('synthetic_wrong_route');
    const raw=await request.text(),value=JSON.parse(raw),fingerprint=await sha256Hex(encodeUtf8(raw));
    const previous=await env.DB.prepare('SELECT * FROM synthetic_retry_intents WHERE request_id=?').bind(value.requestId).first();
    if(previous && previous.fingerprint!==fingerprint)throw Error('synthetic_nonce_changed');
    await env.DB.prepare(`INSERT INTO synthetic_retry_intents VALUES (?,?,1,0)
      ON CONFLICT(request_id) DO UPDATE SET posts=posts+1`).bind(value.requestId,fingerprint).run();
    if(!previous && value.requestId===key(2))return Response.json({error:'synthetic_lost_retry_ack'},{status:503});
    const candidate=await env.DB.prepare('SELECT submission_sha256 FROM object_audit_candidates').first();
    const approved=value.requestId===key(3);
    return Response.json({version:1,jobId:job,leaseId:lease,profileId:authority.profileId,policyId:authority.policyId,
      assignmentSha256:authority.assignmentSha256,submissionSha256:candidate.submission_sha256,candidateManifestSha256:'3'.repeat(64),
      state:approved?'approved':'failed',decision:approved?'approved':'pending',attempts:approved?3:2,retryAt:approved?0:100090,
      receiptSha256:approved?'6'.repeat(64):null,productionQualified:false,serverAuthorization:false,
      acceptedContributions:0,searchCreditsCreated:0});
  }}};let value=null;
  if(path==='/stage')value=await stageObjectAudit(bound,account,{...authority,sourceSha256:await sha256Hex(source)},index,now);
  else if(path==='/pause'){
    await env.DB.prepare("UPDATE object_audit_candidates SET transport_failures=8,next_attempt=100900,last_error='object_audit_transport_unavailable'").run();
    value=await recoverObjectAudit(bound,account,lease,{action:'resume-transport',requestId:key(1)},now);
  }else if(path==='/retry'){
    await env.DB.prepare("UPDATE object_audit_candidates SET native_state='failed',native_attempts=1,job_id=?,candidate_manifest_sha256=?,receipt_sha256=?")
      .bind(job,'3'.repeat(64),'4'.repeat(64)).run();
    value=await recoverObjectAudit(bound,account,lease,{action:'retry-native',requestId:key(2)},now+60);
  }else if(path==='/repeat')value=await recoverObjectAudit(bound,account,lease,{action:'retry-native',requestId:key(2)},now+90);
  else if(path==='/next')value=await recoverObjectAudit(bound,account,lease,{action:'retry-native',requestId:key(3)},now+120);
  else if(path==='/delete')value=await deleteAccount(bound,account,{accountId:account,confirmation:'DELETE',idempotencyKey:key(4)},now+180);
  else if(path==='/cleanup')await cleanupAccountArtifacts(bound,account,64);
  else if(path==='/late'){
    try{await recoverObjectAudit(bound,account,lease,{action:'retry-native',requestId:key(2)},now+200);}
    catch(error){value={error:error.message,status:error.status};}
  }else if(path!=='/state')return new Response('not_found',{status:404});
  const candidate=await env.DB.prepare('SELECT * FROM object_audit_candidates').first();
  const artifact=candidate?await env.INDEX.get(candidate.artifact_key):null;
  return Response.json({value,candidate,history:(await env.DB.prepare('SELECT * FROM object_audit_recoveries ORDER BY created_at').all()).results,
    native:(await env.DB.prepare('SELECT * FROM synthetic_retry_intents ORDER BY request_id').all()).results,
    owner:await env.DB.prepare('SELECT units,deleted_at FROM accounts WHERE id=?').bind(account).first(),
    location:await env.DB.prepare('SELECT state,queue_state,active_lease FROM locations WHERE id=1').first(),
    publications:(await env.DB.prepare('SELECT COUNT(*) AS n FROM published_index').first()).n,
    earnedCredits:(await env.DB.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='verified_work'").first()).n,
    artifactFence:artifact?.customMetadata?.visionPrivacyFence==='1',nativeInferences:0,liveCalls:0});
}};
