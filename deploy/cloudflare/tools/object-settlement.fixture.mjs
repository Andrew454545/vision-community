// Local workerd only: valid synthetic binary records, no native inference.
import {checkObjectSettlement} from '../src/objectSettlementCheck.js';
import {stageObjectAudit,advanceObjectAudit} from '../src/objectAuditDispatch.js';
import {sha256Hex,encodeUtf8,base64ToBytes} from '../src/model.js';
import {OBJECT_INDEX_MODEL} from '../src/objectIndex.js';
import {COVERAGE_VALIDATOR} from '../src/objectCoverage.js';
import {objectCapabilities} from '../src/objectAdmission.js';
const account='b'.repeat(32),lease='a'.repeat(32),job='c'.repeat(32),now=100000;
export default {async fetch(request,env){
  const mode=new URL(request.url).pathname.slice(1);
  const provider={async fetch(r){
    await env.DB.prepare('UPDATE synthetic_settlement SET gets=gets+?').bind(r.method==='GET'?1:0).run();
    if(mode==='unavailable')return Response.json({error:'object_job_receipt_unavailable'},{status:503});
    const c=await env.DB.prepare('SELECT * FROM object_audit_candidates WHERE lease_id=?').bind(lease).first();
    const receipt={version:1,jobId:job,leaseId:lease,profileId:c.profile_id,policyId:c.policy_id,
      assignmentSha256:c.assignment_sha256,submissionSha256:c.submission_sha256,
      candidateManifestSha256:'3'.repeat(64),state:'approved',decision:'approved',attempts:1,retryAt:0,
      receiptSha256:mode==='wrong-pin'?'f'.repeat(64):'4'.repeat(64),productionQualified:false,
      serverAuthorization:false,acceptedContributions:0,searchCreditsCreated:0};
    if(mode==='coverage-late')await env.DB.prepare('UPDATE object_coverage SET validated_at=99999').run();
    if(mode==='delete-late')await env.DB.prepare('UPDATE accounts SET deleted_at=100001,units=0').run();
    return Response.json(receipt);
  }};
  const bound={...env,OBJECT_VERIFIER:provider};let value;
  if(mode==='seed'){
    const doc=await request.json(),index={manifest:doc.baseline.manifest,sourceTsv:doc.baseline.sourceBase64,files:doc.baseline.filesBase64};
    Object.assign(index.manifest.viewQuality,{policy:'vision-per-view-quality-v1',implementationIdentity:'1'.repeat(64),viewCount:6,
    blurAreaFractionExclusive:0.5,tileGrid:8,tunnelVisionProbabilityInclusive:0.85,
    tunnelEvidencePolicy:'none-darkness-never-rejects-v1',protectedAuthorityManifestSha256:'2'.repeat(64)});
    index.manifest.sourceTsv='C:/SYNTHETIC-PRIVATE/source.tsv';
    index.manifest.privateExtension={account:'SYNTHETIC-PRIVATE'};
    index.manifest.viewQuality.privateExtension={path:'SYNTHETIC-PRIVATE'};
    await env.DB.batch([
      env.DB.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic',0)").bind(account),
      env.DB.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',101000)").bind(lease,account),
      env.DB.prepare('CREATE TABLE synthetic_settlement(payload TEXT,gets INTEGER)'),
      env.DB.prepare('INSERT INTO synthetic_settlement VALUES (?,0)').bind(JSON.stringify(index)),
    ]);
    for(const item of doc.items)await env.DB.batch([
      env.DB.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation,
        lat,lon,heading,pitch,zoom,country) VALUES (?,?,'synthetic','object',?,'leased',?,'gen4',?,?,?,?,?,?)`)
        .bind(item.locationId,item.panoId,OBJECT_INDEX_MODEL,lease,item.lat,item.lng,item.heading,item.pitch,item.zoom,item.country),
      env.DB.prepare('INSERT INTO lease_items VALUES (?,?)').bind(lease,item.locationId),
      env.DB.prepare('INSERT INTO object_coverage VALUES (?,?,?,100000)').bind(item.locationId,COVERAGE_VALIDATOR,'d'.repeat(64)),
    ]);
    await stageObjectAudit(bound,account,{leaseId:lease,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),
      sourceSha256:await sha256Hex(base64ToBytes(index.sourceTsv))},index,now);
    value=await advanceObjectAudit(bound,account,lease,now);
  }else{
    if(mode==='restore'){
      const c=await env.DB.prepare('SELECT artifact_key FROM object_audit_candidates').first();
      const original=await env.DB.prepare('SELECT payload FROM synthetic_settlement').first();
      await env.INDEX.put(c.artifact_key,encodeUtf8(original.payload));
      await env.DB.prepare('UPDATE object_coverage SET validated_at=100000').run();
    }
    if(mode==='tamper'||mode==='fence'){
      const c=await env.DB.prepare('SELECT artifact_key,payload_bytes FROM object_audit_candidates').first();
      await env.INDEX.put(c.artifact_key,encodeUtf8(' '.repeat(c.payload_bytes)),mode==='fence'?{customMetadata:{visionPrivacyFence:'1'}}:{});
    }
    try{
      const check=await checkObjectSettlement(bound,account,lease,now);
      value={status:'CHECKED_NOT_AUTHORIZED',records:check.records.length,evidenceSha256:check.evidenceSha256,
        accepted:check.acceptedContributions,credits:check.searchCreditsCreated,serverAuthorization:check.serverAuthorization,
        publicMetadataOnly:!JSON.stringify(check.publicManifest).includes('SYNTHETIC-PRIVATE'),
        publicSource:check.publicManifest.sourceTsv,privateCandidatePreserved:check.objectIndex.manifest.privateExtension.account==='SYNTHETIC-PRIVATE'};
    }catch(error){value={error:error.message,status:error.status};}
  }
  return Response.json({value,gets:(await env.DB.prepare('SELECT gets FROM synthetic_settlement').first()).gets,
    owner:await env.DB.prepare('SELECT units,deleted_at FROM accounts WHERE id=?').bind(account).first(),
    publications:(await env.DB.prepare('SELECT count(*) AS n FROM published_index').first()).n,
    ledger:(await env.DB.prepare('SELECT count(*) AS n FROM ledger').first()).n,
    objectAdmissionReady:objectCapabilities().objectContributions.ready,nativeInferences:0,liveCalls:0});
}};
