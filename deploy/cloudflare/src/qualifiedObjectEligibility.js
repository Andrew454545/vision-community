// Optional read-only eligibility, not publication, credit or public admission.
import {inspectObjectUpload} from './objectSettlementCheck.js';
import {activeObjectQualification,objectQualificationPolicy} from './objectQualification.js';
import {readVerifierJson} from './scenePipeline.js';
import {sha256Hex,encodeUtf8,randomHex} from './model.js';
import {ObjectDispatchError} from './objectAuditDispatch.js';
const ID=/^[0-9a-f]{32}$/,HEX=/^[0-9a-f]{64}$/;
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===[...keys].sort().join(',');
const integer=(v,a,b)=>Number.isSafeInteger(v)&&v>=a&&v<=b;
const hex=v=>typeof v==='string'&&HEX.test(v);
const fail=(code='object_eligibility_unavailable',status=503)=>{throw new ObjectDispatchError(code,status);};

export async function qualifiedObjectEligibilityPolicy(env,now=Math.floor(Date.now()/1000)) {
  if(env.OBJECT_QUALIFIED_UPLOAD_MODE!=='qualified-device-v1')fail('object_verification_unavailable');
  const raw=env.OBJECT_ELIGIBILITY_POLICY,pin=env.OBJECT_ELIGIBILITY_POLICY_SHA256;
  if(typeof raw!=='string'||encodeUtf8(raw).length>4096||!hex(pin)||await sha256Hex(encodeUtf8(raw))!==pin)fail();
  let p;try{p=JSON.parse(raw);}catch{fail();}
  const fields=['version','scope','policyId','qualificationPolicySha256','protectedPolicySha256',
    'qualityImplementationIdentity','protectedAuthoritySha256','protectedOriginHandoffSha256',
    'sceneInputModel','resource','validFrom','validUntil'];
  const q=objectQualificationPolicy(env);
  if(!exact(p,fields)||p.version!==1||p.scope!=='qualified-object-eligibility-v1'
    ||typeof p.policyId!=='string'||!/^[A-Za-z0-9_.-]{1,128}$/.test(p.policyId)
    ||p.policyId.startsWith('staging.')&&env.DEPLOYMENT_ENVIRONMENT!=='staging'
    ||!fields.filter(k=>k.endsWith('Sha256')||k==='qualityImplementationIdentity').every(k=>hex(p[k]))
    ||p.qualificationPolicySha256!==q.policySha256||!exact(p.resource,['accountId','databaseId','bucket'])
    ||Object.keys(q.resource).some(k=>p.resource[k]!==q.resource[k])
    ||typeof p.sceneInputModel!=='string'||!/^[A-Za-z0-9_.:-]{1,128}$/.test(p.sceneInputModel)
    ||!integer(p.validFrom,0,Number.MAX_SAFE_INTEGER-30*86400)||!integer(p.validUntil,p.validFrom+1,p.validFrom+30*86400)
    ||!integer(now,p.validFrom,p.validUntil-1))fail();
  return p;
}

async function sceneMembers(env,rows,race) {
  const members=[];
  for(const row of rows) {
    const matches=(await race(()=>env.DB.prepare(`SELECT s.id,s.asset_id,s.capture,s.model,s.lat,s.lon,s.country,s.camera_generation,
      s.state,s.contributor_id,s.output_sha256,a.deleted_at,p.four_view_sha256,p.four_view_key,p.output_sha256 AS published_sha256
      FROM locations s JOIN published_index p ON p.location_id=s.id JOIN accounts a ON a.id=s.contributor_id
      WHERE s.lane='scene' AND s.asset_id=? AND s.capture=? AND s.lat=? AND s.lon=? AND s.country=?
        AND s.camera_generation='gen4' AND s.state='published' AND a.deleted_at IS NULL AND s.model=?
      ORDER BY s.id LIMIT 2`).bind(row.asset_id,row.capture,row.lat,row.lon,row.country,env.sceneModel).all())).results||[];
    if(matches.length!==1)fail('object_scene_membership_required',409);
    const scene=matches[0];
    if(!hex(scene.output_sha256)||scene.published_sha256!==scene.output_sha256||scene.four_view_sha256!==scene.output_sha256
      ||typeof scene.four_view_key!=='string'||!scene.four_view_key.startsWith('four-view-v4/')||!scene.four_view_key.endsWith('.i8'))fail();
    members.push({objectLocationId:row.id,scene});
  }
  return members;
}

export function validateObjectProtectionEvidence(value,request,p,rows,now) {
  const fields=[...Object.keys(request),'scope','protectedPolicySha256','qualityImplementationIdentity',
    'protectedAuthoritySha256','protectedOriginHandoffSha256','resource','records','protectedEligible','verifiedOnOriginalSourceMachine',
    'sceneMembershipVerified','coverageVerified','qualificationVerified','serverAuthorization','productionQualified',
    'acceptedContributions','searchCreditsCreated','issuedAt','expiresAt'];
  if(!exact(value,fields)||value.scope!=='trusted-live-object-protection-v1'
    ||Object.keys(request).some(k=>value[k]!==request[k])
    ||['protectedPolicySha256','qualityImplementationIdentity','protectedAuthoritySha256','protectedOriginHandoffSha256'].some(k=>value[k]!==p[k])
    ||!exact(value.resource,['accountId','databaseId','bucket'])||Object.keys(p.resource).some(k=>value.resource[k]!==p.resource[k])
    ||value.protectedEligible!==true||value.verifiedOnOriginalSourceMachine!==true
    ||['sceneMembershipVerified','coverageVerified','qualificationVerified','serverAuthorization','productionQualified'].some(k=>value[k]!==false)
    ||value.acceptedContributions!==0||value.searchCreditsCreated!==0
    ||!integer(value.issuedAt,now-20,now+2)||!integer(value.expiresAt,now+1,Math.min(value.issuedAt+30,p.validUntil))
    ||!Array.isArray(value.records)||value.records.length!==rows.length
    ||value.records.some((r,i)=>!exact(r,['locationId','coverageEvidenceSha256'])||r.locationId!==rows[i].id
      ||r.coverageEvidenceSha256!==rows[i].evidence_sha256))fail();
  return value;
}

export async function inspectQualifiedObjectUpload(env,account,lease,now=Math.floor(Date.now()/1000),timeoutMs=20000) {
  if(typeof account!=='string'||!ID.test(account)||typeof lease!=='string'||!ID.test(lease)
    ||!integer(now,0,Number.MAX_SAFE_INTEGER-86400)||!integer(timeoutMs,1,20000))fail('invalid_object_eligibility',400);
  const started=performance.now(),abort=new AbortController();let timer;
  const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{abort.abort();reject(Error());},timeoutMs);});
  void deadline.catch(()=>{});
  const race=action=>Promise.race([Promise.resolve().then(action),deadline]);
  const at=()=>now+Math.ceil((performance.now()-started)/1000);
  const budget=()=>{const left=Math.floor(timeoutMs-(performance.now()-started));if(left<1)fail();return left;};
  try {
    const p=await race(()=>qualifiedObjectEligibilityPolicy(env,now));
    const policyRaw=env.OBJECT_ELIGIBILITY_POLICY,policyPin=env.OBJECT_ELIGIBILITY_POLICY_SHA256,qualificationRaw=env.OBJECT_QUALIFICATION_POLICY;
    if(typeof env.OBJECT_ELIGIBILITY?.fetch!=='function')fail();
    const before=await inspectObjectUpload(env,account,lease,now,budget()),row=before.databaseSnapshot.row;
    if(['fetchErrors','inferenceErrors','permanentlyInvalidLocations'].some(k=>(before.publicManifest[k]??0)!==0)
      ||row.policy_id!==p.policyId||before.publicManifest.viewQuality.implementationIdentity!==p.qualityImplementationIdentity
      ||before.publicManifest.viewQuality.protectedAuthorityManifestSha256!==p.protectedAuthoritySha256)fail();
    const qualification=await race(()=>activeObjectQualification(env,account,row.profile_id,at()));
    if(!qualification)fail('object_device_qualification_required',403);
    const scenes=await sceneMembers({...env,sceneModel:p.sceneInputModel},before.databaseSnapshot.rows,race);
    const snapshot={integrity:before.databaseSnapshot,qualification,scenes};
    const snapshotSha256=await race(()=>sha256Hex(encodeUtf8(JSON.stringify(snapshot))));
    const request={version:1,accountId:account,leaseId:lease,profileId:row.profile_id,qualificationId:qualification.id,
      challenge:randomHex(16),assignmentSha256:row.assignment_sha256,sourceSha256:row.source_sha256,snapshotSha256,
      policyId:p.policyId,policySha256:policyPin,qualificationPolicySha256:p.qualificationPolicySha256};
    const transfer=Promise.resolve().then(()=>env.OBJECT_ELIGIBILITY.fetch(new Request('https://object-eligibility.internal/object-eligibility/evidence',{
      method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(request),signal:abort.signal}))).then(response=>{
        if(abort.signal.aborted){if(response.body)void response.body.cancel().catch(()=>{});throw Error();}return response;
      });
    const response=await race(()=>transfer);
    if(response.status!==200){if(response.body)void response.body.cancel().catch(()=>{});fail();}
    const protection=validateObjectProtectionEvidence(await race(()=>readVerifierJson(response,Math.min(10000,budget()))),request,p,before.databaseSnapshot.rows,at());
    const after=await inspectObjectUpload(env,account,lease,at(),budget());
    const currentQualification=await race(()=>activeObjectQualification(env,account,row.profile_id,at(),qualification.id));
    const currentScenes=await sceneMembers({...env,sceneModel:p.sceneInputModel},after.databaseSnapshot.rows,race);
    const current={integrity:after.databaseSnapshot,qualification:currentQualification,scenes:currentScenes};
    if(JSON.stringify(current)!==JSON.stringify(snapshot)||env.OBJECT_ELIGIBILITY_POLICY!==policyRaw
      ||env.OBJECT_ELIGIBILITY_POLICY_SHA256!==policyPin||env.OBJECT_QUALIFICATION_POLICY!==qualificationRaw
      ||JSON.stringify(await race(()=>qualifiedObjectEligibilityPolicy(env,at())))!==JSON.stringify(p)
      ||protection.expiresAt<=at()||performance.now()-started>=timeoutMs)fail('object_eligibility_changed',409);
    return {...after,qualificationId:qualification.id,qualification,protection,sceneMembership:scenes,
      eligibilitySnapshot:current,eligibilitySha256:snapshotSha256,eligibilityPolicySha256:policyPin,
      admissionMode:'qualified-device-v1',verificationScope:'qualified-object-upload-eligibility-only',
      routineUploadsIndependentlyRecomputed:false,eligibilityVerified:true,serverAuthorization:false,
      productionQualified:false,acceptedContributions:0,searchCreditsCreated:0};
  } catch(error){if(error instanceof ObjectDispatchError)throw error;fail();}
  finally{clearTimeout(timer);abort.abort();}
}
