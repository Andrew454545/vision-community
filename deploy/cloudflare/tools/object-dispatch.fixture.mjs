// Actual local D1/R2 recovery, explicitly synthetic native acknowledgements.
import {stageObjectAudit,advanceObjectAudit} from '../src/objectAuditDispatch.js';
import {sha256Hex,encodeUtf8} from '../src/model.js';
import {deleteAccount,cleanupAccountArtifacts} from '../src/accountPrivacy.js';
import {objectCapabilities} from '../src/objectAdmission.js';
const account='a'.repeat(32),lease='b'.repeat(32),job='d'.repeat(32),now=100000;
const source=encodeUtf8('synthetic source\n');
const objectIndex={manifest:{synthetic:true},files:{'synthetic.bin':''},sourceTsv:btoa('synthetic source\n')};
const authority={leaseId:lease,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),sourceSha256:null};
export default {async fetch(request,env) {
  const path=new URL(request.url).pathname;
  const provider={async fetch(r) {
    const nativePath=new URL(r.url).pathname;
    if(nativePath===`/object-assignments/${lease}/erase`) {
      await env.DB.prepare('UPDATE synthetic_native_jobs SET erased=1').run();
      return Response.json({version:1,leaseId:lease,policyId:authority.policyId,assignmentSha256:authority.assignmentSha256,
        state:'erased',productionQualified:false,serverAuthorization:false});
    }
    if(r.method==='POST') {
      const body=await r.text(),fingerprint=await sha256Hex(encodeUtf8(body));
      const old=await env.DB.prepare('SELECT fingerprint FROM synthetic_native_jobs').first();
      if(old && old.fingerprint!==fingerprint) return Response.json({error:'synthetic_conflict'},{status:409});
      await env.DB.prepare(`INSERT INTO synthetic_native_jobs(id,fingerprint,posts,gets,erased) VALUES (?,?,1,0,0)
        ON CONFLICT(id) DO UPDATE SET posts=posts+1`).bind(job,fingerprint).run();
      if(!old) return Response.json({error:'synthetic_lost_ack'},{status:503});
    } else {
      if(nativePath!==`/object-audits/${job}`) throw Error('synthetic_path_mismatch');
      await env.DB.prepare('UPDATE synthetic_native_jobs SET gets=gets+1').run();
    }
    const candidate=await env.DB.prepare('SELECT submission_sha256 FROM object_audit_candidates WHERE lease_id=?').bind(lease).first();
    return Response.json({version:1,jobId:job,leaseId:lease,profileId:authority.profileId,policyId:authority.policyId,
      assignmentSha256:authority.assignmentSha256,submissionSha256:candidate.submission_sha256,candidateManifestSha256:'3'.repeat(64),
      state:'approved',decision:'approved',attempts:1,retryAt:0,receiptSha256:'6'.repeat(64),
      productionQualified:false,serverAuthorization:false,acceptedContributions:0,searchCreditsCreated:0});
  }};
  const bound={...env,OBJECT_VERIFIER:provider};let value=null;
  if(path==='/stage') value=await stageObjectAudit(bound,account,{...authority,sourceSha256:await sha256Hex(source)},objectIndex,now);
  else if(path==='/start') value=await advanceObjectAudit(bound,account,lease,now);
  else if(path==='/recover') value=await advanceObjectAudit(bound,account,lease,now+30);
  else if(path==='/observe') value=await advanceObjectAudit(bound,account,lease,now+60);
  else if(path==='/delete') value=await deleteAccount(bound,account,{accountId:account,confirmation:'DELETE',idempotencyKey:'4'.repeat(64)},now+61);
  else if(path==='/cleanup') await cleanupAccountArtifacts(bound,account,64);
  else if(path==='/late') {
    try {await advanceObjectAudit(bound,account,lease,now+120);}
    catch(error){value={error:error.message,status:error.status};}
  } else if(path!=='/state') return new Response('not_found',{status:404});
  const candidate=await env.DB.prepare('SELECT * FROM object_audit_candidates WHERE lease_id=?').bind(lease).first();
  const artifact=candidate?await env.INDEX.get(candidate.artifact_key):null;
  return Response.json({value,candidate,native:await env.DB.prepare('SELECT * FROM synthetic_native_jobs').first(),
    owner:await env.DB.prepare('SELECT units,deleted_at FROM accounts WHERE id=?').bind(account).first(),
    location:await env.DB.prepare('SELECT state,queue_state,active_lease FROM locations WHERE id=1').first(),
    publications:(await env.DB.prepare('SELECT count(*) AS n FROM published_index').first()).n,
    earnedCredits:(await env.DB.prepare("SELECT count(*) AS n FROM ledger WHERE reason='verified_work'").first()).n,
    artifactFence:artifact?.customMetadata?.visionPrivacyFence==='1',objectAdmissionReady:objectCapabilities().objectContributions.ready,
    nativeInferences:0,liveCalls:0});
}};
