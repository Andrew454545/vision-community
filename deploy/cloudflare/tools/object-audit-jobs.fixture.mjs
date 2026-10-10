import {handleObjectAuditJobs} from '../native-object-verifier-bridge/worker.js';
import {objectCapabilities} from '../src/objectAdmission.js';
const env = {NATIVE_OBJECT_VERIFIER_ORIGIN:'https://synthetic-native.invalid',
  NATIVE_OBJECT_VERIFIER_SECRET:'synthetic-private-object-transport-credential'};
const body = {version:1,leaseId:'a'.repeat(32),profileId:'b'.repeat(64),policyId:'staging.synthetic',
  assignmentSha256:'c'.repeat(64),submissionSha256:'d'.repeat(64),objectIndex:{synthetic:true}};
const receipt = {version:1,jobId:'e'.repeat(32),leaseId:body.leaseId,profileId:body.profileId,policyId:body.policyId,
  assignmentSha256:body.assignmentSha256,submissionSha256:body.submissionSha256,candidateManifestSha256:'f'.repeat(64),
  state:'queued',decision:'pending',attempts:0,retryAt:0,receiptSha256:null,serverAuthorization:false,
  productionQualified:false,acceptedContributions:0,searchCreditsCreated:0};
export default {async fetch(request) {
  const mode = new URL(request.url).pathname.slice(1);
  const start = mode === 'start';
  const control = mode === 'cancel' || mode === 'retry';
  const path = '/object-audits' + (start ? '' : '/'+receipt.jobId+(control ? '/'+mode : ''));
  const upstream = new Request('https://object-verifier.internal'+path,{
    method:start || control ? 'POST' : 'GET',
    headers:{'content-type':'application/json',authorization:'Bearer caller',cookie:'private-cookie'},
    ...(start || control ? {body:JSON.stringify(start ? body : {})} : {})});
  let calls = 0;
  const response = await handleObjectAuditJobs(upstream,env,async (url,init) => {
    calls++;
    if (url !== env.NATIVE_OBJECT_VERIFIER_ORIGIN+path || init.headers.cookie
        || init.headers.authorization !== 'Bearer '+env.NATIVE_OBJECT_VERIFIER_SECRET
        || init.redirect !== 'manual') throw Error('transport_contract_failed');
    if (mode === 'deadline') return new Promise(()=>{});
    if (mode === 'conflict') return Response.json({error:'object_job_conflict'},{status:409});
    if (mode === 'unapproved') return Response.json({...receipt,productionQualified:true});
    if (mode === 'wrong-id') return Response.json({...receipt,jobId:'1'.repeat(32)});
    if (mode === 'complete') return Response.json({...receipt,state:'approved',decision:'approved',attempts:1,receiptSha256:'1'.repeat(64)});
    return Response.json(mode === 'cancel' ? {...receipt,state:'cancelled'} : receipt);
  },mode === 'deadline' ? 5 : 20000);
  return Response.json({responseStatus:response.status,result:await response.json(),calls,
    objectAdmissionReady:objectCapabilities().objectContributions.ready,nativeInferences:0});
}};
