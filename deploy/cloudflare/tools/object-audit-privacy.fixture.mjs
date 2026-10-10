// Offline integration only. The native provider is explicitly synthetic.
import {deleteAccount,cleanupAccountArtifacts} from '../src/accountPrivacy.js';
import {handleObjectAuditJobs} from '../native-object-verifier-bridge/worker.js';
import {objectCapabilities} from '../src/objectAdmission.js';
const account='a'.repeat(32),lease='1'.repeat(32);
const native={NATIVE_OBJECT_VERIFIER_ORIGIN:'https://synthetic-native.invalid',
  NATIVE_OBJECT_VERIFIER_SECRET:'synthetic-object-erasure-transport-secret'};
export default {async fetch(request,env) {
  const path=new URL(request.url).pathname;
  let calls=0;
  const provider={async fetch(request) {
    return handleObjectAuditJobs(request,native,async (url,init)=>{
      calls++;
      if(url!==`${native.NATIVE_OBJECT_VERIFIER_ORIGIN}/object-assignments/${lease}/erase`
          || init.headers.authorization!=='Bearer '+native.NATIVE_OBJECT_VERIFIER_SECRET
          || init.headers.cookie || new TextDecoder().decode(init.body)!=='{}') throw Error('synthetic_transport_mismatch');
      if(path==='/cleanup/outage') return Response.json({error:'object_job_capacity_reached'},{status:503});
      return Response.json({version:1,leaseId:path==='/cleanup/wrong-id'?'f'.repeat(32):lease,
        policyId:'staging.synthetic',assignmentSha256:'b'.repeat(64),
        state:path==='/cleanup/erasing'?'erasing':'erased',serverAuthorization:false,productionQualified:false});
    });
  }};
  if(path==='/delete') {
    await deleteAccount({...env,OBJECT_VERIFIER:provider},account,
      {accountId:account,confirmation:'DELETE',idempotencyKey:'c'.repeat(64)},1234);
  } else if(path.startsWith('/cleanup/')) {
    await cleanupAccountArtifacts({...env,...(path==='/cleanup/missing'?{}:{OBJECT_VERIFIER:provider})},account);
  } else return new Response('offline fixture route missing',{status:404});
  const owner=await env.DB.prepare('SELECT units,deleted_at,recovery_hash FROM accounts WHERE id=?').bind(account).first();
  const cleanup=await env.DB.prepare('SELECT state FROM account_cleanup WHERE artifact_key=?').bind(`object-audit-jobs/${lease}`).first();
  const ledger=await env.DB.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='account_deleted'").first();
  const other=await env.DB.prepare('SELECT units,deleted_at FROM accounts WHERE id=?').bind('d'.repeat(32)).first();
  return Response.json({calls,owner,cleanup,deletedLedgerRows:ledger.n,other,
    objectAdmissionReady:objectCapabilities().objectContributions.ready,nativeInferences:0});
}};
