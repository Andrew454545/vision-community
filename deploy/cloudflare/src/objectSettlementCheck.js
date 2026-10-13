// Private pre-publication integrity check. This does not qualify a computer,
// authorize publication, write a bundle, or create credit. Callers still need
// the approved qualification policy and an atomic guarded settlement.
import {ObjectDispatchError} from './objectAuditDispatch.js';
import {objectAuditResult,MAX_REQUEST} from '../native-object-verifier-bridge/worker.js';
import {readVerifierJson} from './scenePipeline.js';
import {validateObjectIndex,OBJECT_INDEX_MODEL} from './objectIndex.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {publicObjectManifest} from './objectPublicManifest.js';
import {base64ToBytes,sha256Hex,encodeUtf8} from './model.js';
const ID=/^[a-f0-9]{32}$/,HEX=/^[a-f0-9]{64}$/;
const fail=(code='object_settlement_evidence_unavailable',status=503)=>{throw new ObjectDispatchError(code,status);};

async function snapshot(env,account,lease,now,race,requireAudit) {
  const row=await race(()=>env.DB.prepare(`SELECT c.*,a.deleted_at,l.lane AS lease_lane,l.state AS lease_state,
    l.expires_at AS lease_expires,w.account_id AS artifact_owner,w.lease_id AS artifact_lease,
    w.sha256 AS artifact_sha256,w.bytes AS artifact_bytes
    FROM object_audit_candidates c JOIN accounts a ON a.id=c.account_id
    JOIN leases l ON l.id=c.lease_id AND l.account_id=c.account_id
    JOIN account_artifact_writes w ON w.artifact_key=c.artifact_key
    WHERE c.account_id=? AND c.lease_id=? AND EXISTS (SELECT 1 FROM object_dispatch_revision
      WHERE slot=1 AND contract='private-object-dispatch-v2-20261012')`).bind(account,lease).first());
  if(!row || row.deleted_at!==null || row.state!=='pending'
      || row.lease_lane!=='object' || row.lease_state!=='submitted' || row.lease_expires<=now
      || row.artifact_owner!==account || row.artifact_lease!==lease
      || row.artifact_key!==`object-quarantine/${lease}/${row.submission_sha256}.json`
      || row.artifact_sha256!==row.submission_sha256 || row.artifact_bytes!==row.payload_bytes
      || !Number.isSafeInteger(row.payload_bytes) || row.payload_bytes<1 || row.payload_bytes>MAX_REQUEST-1024
      || !Number.isSafeInteger(row.location_count) || row.location_count<1 || row.location_count>4
      || ![row.profile_id,row.assignment_sha256,row.source_sha256,row.submission_sha256]
        .every(v=>typeof v==='string'&&HEX.test(v))) fail();
  if(requireAudit && (row.native_state!=='approved' || typeof row.job_id!=='string' || !ID.test(row.job_id)
      || ![row.candidate_manifest_sha256,row.receipt_sha256].every(v=>typeof v==='string'&&HEX.test(v))
      || !Number.isSafeInteger(row.native_attempts) || row.native_attempts<1 || row.native_attempts>3)) fail();
  if(row.claim_token!==null || row.claim_until!==0) fail('object_settlement_busy',409);
  const rows=(await race(()=>env.DB.prepare(`SELECT l.*,c.validator,c.evidence_sha256,c.validated_at,
    p.location_id AS published_id FROM lease_items i JOIN locations l ON l.id=i.location_id
    LEFT JOIN object_coverage c ON c.location_id=l.id
    LEFT JOIN published_index p ON p.location_id=l.id WHERE i.lease_id=? ORDER BY l.id LIMIT 5`)
    .bind(lease).all())).results||[];
  if(rows.length!==row.location_count || rows.some(v=>v.lane!=='object' || v.model!==OBJECT_INDEX_MODEL || v.state!=='pending'
      || v.queue_state!=='quarantined' || v.active_lease!==lease || v.published_id!==null
      || v.camera_generation!=='gen4' || v.validator!==COVERAGE_VALIDATOR
      || typeof v.evidence_sha256!=='string' || !HEX.test(v.evidence_sha256)
      || !Number.isSafeInteger(v.validated_at) || v.validated_at>now || v.validated_at<=now-86400)) fail();
  return {row,rows};
}

async function storedPayload(env,row,race) {
  const object=await race(()=>env.INDEX.get(row.artifact_key));
  if(!object?.body || object.size!==row.payload_bytes || object.customMetadata?.visionPrivacyFence==='1') fail();
  const reader=object.body.getReader(),chunks=[];let size=0,raw;
  try {
    for(let i=0;i<65536;i++) {
      const next=await race(()=>reader.read());
      if(next.done) {
        raw=new Uint8Array(size);let offset=0;
        for(const chunk of chunks){raw.set(chunk,offset);offset+=chunk.length;}break;
      }
      if(!(next.value instanceof Uint8Array) || size+next.value.length>row.payload_bytes) fail();
      size+=next.value.length;chunks.push(next.value);
    }
  } finally {void reader.cancel().catch(()=>{});reader.releaseLock();}
  if(!raw || raw.length!==row.payload_bytes || await race(()=>sha256Hex(raw))!==row.submission_sha256) fail();
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
}

// Separate entry points prevent a request option from weakening native-audited
// settlement. Inspection supplies bytes/integrity only, never qualification,
// live protected-source authority, publication authority or an audit receipt.
export const inspectObjectUpload=(env,account,lease,now=Math.floor(Date.now()/1000),timeoutMs=20000)=>
  inspect(env,account,lease,now,timeoutMs,false);
export const checkObjectSettlement=(env,account,lease,now=Math.floor(Date.now()/1000),timeoutMs=20000)=>
  inspect(env,account,lease,now,timeoutMs,true);

async function inspect(env,account,lease,now,timeoutMs,requireAudit) {
  if(typeof account!=='string' || !ID.test(account) || typeof lease!=='string' || !ID.test(lease)
      || !Number.isSafeInteger(now) || now<0 || now>Number.MAX_SAFE_INTEGER-86400
      || !Number.isSafeInteger(timeoutMs) || timeoutMs<1 || timeoutMs>20000) fail('invalid_object_settlement',400);
  if((requireAudit && typeof env.OBJECT_VERIFIER?.fetch!=='function') || !env.INDEX || !env.DB) fail();
  const abort=new AbortController(),started=performance.now();let timer;
  const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{abort.abort();reject(Error('settlement_timeout'));},timeoutMs);});
  void deadline.catch(()=>{});
  const race=action=>Promise.race([Promise.resolve().then(action),deadline]);
  const currentTime=()=>now+Math.ceil((performance.now()-started)/1000);
  try {
    const before=await snapshot(env,account,lease,now,race,requireAudit),row=before.row;
    const index=await storedPayload(env,row,race);
    if(!index || Object.keys(index).sort().join(',')!=='files,manifest,sourceTsv'
        || !index.files || typeof index.files!=='object' || Array.isArray(index.files)
        || Object.keys(index.files).length>87) fail();
    const source=base64ToBytes(index.sourceTsv);
    if(await race(()=>sha256Hex(source))!==row.source_sha256) fail();
    const lines=new TextDecoder('utf-8',{fatal:true}).decode(source).split(/\r?\n/).filter(v=>v.trim());
    if(lines.length!==before.rows.length || lines.some((line,i)=>{
      const fields=line.split('\t'),v=before.rows[i];
      return fields.length!==12 || fields[7]!==v.asset_id || fields[8]!==v.country || fields[9]!=='gen4'
        || [v.lat,v.lon,v.heading,v.pitch,v.zoom].some((number,j)=>typeof number!=='number'
          || !Number.isFinite(number) || !fields[j+2].trim() || Number(fields[j+2])!==number);
    })) fail();
    const files=Object.fromEntries(Object.entries(index.files).map(([name,bytes])=>[name,base64ToBytes(bytes)]));
    const records=await race(()=>validateObjectIndex(index.manifest,files,source,before.rows.map(v=>({
      locationId:v.id,panoId:v.asset_id,lat:v.lat,lng:v.lon})),lease));
    const publicManifest=publicObjectManifest(index.manifest);
    let receipt;
    if(requireAudit) {
      // This is a fresh GET, never the cached approved D1 state or an upload's
      // replay acknowledgement. The host guards live inputs and saved receipts.
      const request=new Request(`https://object-verifier.internal/object-audits/${row.job_id}`,{signal:abort.signal});
      const transfer=Promise.resolve().then(()=>env.OBJECT_VERIFIER.fetch(request)).then(response=>{
        if(abort.signal.aborted){if(response.body)void response.body.cancel().catch(()=>{});throw Error('late_receipt');}
        return response;
      });
      const response=await Promise.race([transfer,deadline]);
      if(response.status!==200){if(response.body)void response.body.cancel().catch(()=>{});fail();}
      const responseBudget=Math.min(10000,Math.floor(timeoutMs-(performance.now()-started)));
      if(responseBudget<1){if(response.body)void response.body.cancel().catch(()=>{});fail();}
      receipt=objectAuditResult(await race(()=>readVerifierJson(response,responseBudget)),{
        jobId:row.job_id,leaseId:lease,profileId:row.profile_id,policyId:row.policy_id,
        assignmentSha256:row.assignment_sha256,submissionSha256:row.submission_sha256,
        candidateManifestSha256:row.candidate_manifest_sha256,state:'approved',decision:'approved',
        attempts:row.native_attempts,receiptSha256:row.receipt_sha256});
    }
    // Account deletion, cancellation, coverage/pose changes or another native
    // attempt during either asynchronous read invalidate this inspection.
    const after=await snapshot(env,account,lease,currentTime(),race,requireAudit);
    if(JSON.stringify(after)!==JSON.stringify(before) || performance.now()-started>=timeoutMs) fail();
    const evidenceSha256=await race(()=>sha256Hex(encodeUtf8(JSON.stringify(after))));
    if(performance.now()-started>=timeoutMs) fail();
    // Private in-memory bytes for the eventual guarded writer, never an HTTP
    // reply or portable approval. No R2/D1 mutation occurs in this function.
    return {leaseId:lease,records,objectIndex:index,publicManifest,source,files,...(requireAudit?{receipt}:{}),evidenceSha256,databaseSnapshot:after,
      verificationScope:requireAudit?'object-candidate-integrity-only':'object-upload-integrity-only',serverAuthorization:false,
      productionQualified:false,acceptedContributions:0,searchCreditsCreated:0};
  } catch(error) {
    if(error instanceof ObjectDispatchError) throw error;
    fail();
  } finally {clearTimeout(timer);abort.abort();}
}
