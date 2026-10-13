// Reusable account/profile authority from a private saved full-sample comparison.
// This never executes a model or treats a contributor's pass flag as authority.
import {sha256Hex,encodeUtf8,randomHex} from './model.js';
import {readVerifierJson} from './scenePipeline.js';
import {OBJECT_QUALIFICATION_CONTRACT} from './objectQualificationSchema.js';

const ID=/^[0-9a-f]{32}$/,HEX=/^[0-9a-f]{64}$/;
const resources={staging:{accountId:'272760294910ef0b246980278aeb36e2',databaseId:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',bucket:'vision-community-staging'},
  production:{accountId:'272760294910ef0b246980278aeb36e2',databaseId:'ed4705fa-1190-41fa-86a0-02d755db1b2a',bucket:'vision-community'}};
const exact=(v,keys)=>v && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join(',')===[...keys].sort().join(',');
const hex=v=>typeof v==='string'&&HEX.test(v);
const id=v=>typeof v==='string'&&ID.test(v);
const integer=(v,a,b)=>Number.isSafeInteger(v)&&v>=a&&v<=b;
export class ObjectQualificationError extends Error {constructor(code,status=503){super(code);this.status=status;}}
const fail=(code='object_qualification_unavailable',status=503)=>{throw new ObjectQualificationError(code,status);};

export function objectQualificationPolicy(env) {
  if(env.OBJECT_QUALIFICATION_MODE!=='saved-sample-v1')fail('object_verification_unavailable');
  let p;try{p=JSON.parse(env.OBJECT_QUALIFICATION_POLICY);}catch{fail('object_qualification_policy_required');}
  const keys=['version','scope','policyId','policySha256','scorePolicySha256','fixtureSha256','referenceBundleSha256',
    'frozenViewsManifestSha256','sourceSha256','locations','profiles','resource','validFrom','validUntil'];
  if(!exact(p,keys)||p.version!==1||p.scope!=='saved-full-object-sample-qualification-v1'
    ||typeof p.policyId!=='string'||!/^[A-Za-z0-9_.-]{1,128}$/.test(p.policyId)
    ||!keys.filter(k=>k.endsWith('Sha256')).every(k=>hex(p[k]))
    ||!integer(p.locations,100,112)||!integer(p.validFrom,0,Number.MAX_SAFE_INTEGER-30*86400)
    ||!integer(p.validUntil,p.validFrom+1,p.validFrom+30*86400)
    ||!exact(p.resource,['accountId','databaseId','bucket'])
    ||!resources[env.DEPLOYMENT_ENVIRONMENT]||Object.keys(p.resource).some(k=>p.resource[k]!==resources[env.DEPLOYMENT_ENVIRONMENT][k])
    ||env.INDEX_BUCKET_NAME!==p.resource.bucket||p.policyId.startsWith('staging.')&&env.DEPLOYMENT_ENVIRONMENT!=='staging'
    ||!p.profiles||typeof p.profiles!=='object'||Array.isArray(p.profiles)||Object.keys(p.profiles).length<1
    ||Object.keys(p.profiles).length>16||!Object.entries(p.profiles).every(([profile,settings])=>hex(profile)&&hex(settings)))
    fail('object_qualification_policy_required');
  return p;
}
export function objectQualificationConfigured(env) {
  try{objectQualificationPolicy(env);return true;}catch{return false;}
}
const canonical=v=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;
async function setup(env,account,now) {
  const p=objectQualificationPolicy(env);
  if(!id(account)||!integer(now,0,Number.MAX_SAFE_INTEGER-30*86400))fail('invalid_object_qualification_request',400);
  if(now<p.validFrom||now>=p.validUntil)fail('object_qualification_policy_expired');
  try{if((await env.DB.prepare('SELECT contract FROM object_qualification_revision WHERE slot=1').first())?.contract!==OBJECT_QUALIFICATION_CONTRACT)throw Error();}
  catch{fail('object_qualification_setup_required');}
  if(!await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first())fail('account_not_active',401);
  return {...p,authoritySha256:await sha256Hex(encodeUtf8(JSON.stringify(canonical(p))))};
}
function status(row,p,profile) {
  return row?{qualified:true,qualificationId:row.id,profileId:profile,policyId:p.policyId,policySha256:p.policySha256,
    expiresAt:row.expires_at,admissionMode:'qualified-device-v1',verification:'trusted-reference-sample-comparison',
    independentlyRecomputedRoutineUploads:false}
    :{qualified:false,profileId:profile,policyId:p.policyId,policySha256:p.policySha256};
}
export async function activeObjectQualification(env,account,profile,now=Math.floor(Date.now()/1000),qualificationId=null) {
  const p=await setup(env,account,now);
  if(!hex(profile)||!(profile in p.profiles)||qualificationId!==null&&!id(qualificationId))fail('object_device_qualification_required',403);
  const row=await env.DB.prepare(`SELECT r.* FROM object_qualification_requests r JOIN object_qualification_controls c
    ON c.account_id=r.account_id AND c.authority_sha256=r.authority_sha256 AND c.profile_id=r.profile_id
    JOIN accounts a ON a.id=r.account_id WHERE a.deleted_at IS NULL AND r.account_id=? AND r.authority_sha256=?
    AND r.profile_id=? AND r.state='qualified' AND r.epoch=c.epoch AND r.expires_at>?
    AND (? IS NULL OR r.id=?) ORDER BY r.completed_at DESC,r.id DESC LIMIT 1`).bind(account,p.authoritySha256,profile,now,qualificationId,qualificationId).first();
  return row;
}
export async function objectQualificationStatus(env,account,profile,now=Math.floor(Date.now()/1000)) {
  const row=await activeObjectQualification(env,account,profile,now);
  return status(row,objectQualificationPolicy(env),profile);
}
function proof(value,row,p,now) {
  const keys=['version','scope','accountId','requestId','challenge','artifactSetSha256','artifacts','report','issuedAt','expiresAt'];
  if(!exact(value,keys)||value.version!==1||value.scope!=='trusted-saved-object-sample-evidence-v1'
    ||value.accountId!==row.account_id||value.requestId!==row.id||value.challenge!==row.challenge
    ||value.artifactSetSha256!==row.artifact_sha256||!integer(value.issuedAt,row.created_at,now+2)
    ||!integer(value.expiresAt,value.issuedAt+1,value.issuedAt+30)||value.expiresAt<=now)fail();
  const a=value.artifacts,r=value.report;
  if(!exact(a,['detectorProfileId','indexProfileId','detectorSettingsSha256','indexSettingsSha256','executionReceiptSha256'])
    ||a.detectorProfileId!==row.profile_id||a.indexProfileId!==row.profile_id
    ||a.detectorSettingsSha256!==p.profiles[row.profile_id]||a.indexSettingsSha256!==p.profiles[row.profile_id]
    ||!hex(a.executionReceiptSha256)||!r||r.version!==1||r.qualificationScope!=='fixed-input-object-score-and-index-parity-only'
    ||r.policyId!==p.policyId||r.policySha256!==p.policySha256||r.scorePolicySha256!==p.scorePolicySha256
    ||r.fixtureSha256!==p.fixtureSha256||r.referenceBundleSha256!==p.referenceBundleSha256
    ||r.frozenViewsManifestSha256!==p.frozenViewsManifestSha256||r.profileId!==row.profile_id
    ||!hex(r.scoreSubmissionSha256)||!hex(r.candidateManifestSha256)||r.locations!==p.locations||r.views!==p.locations*6
    ||r.qualified!==false||r.serverAuthorization!==false||r.productionQualified!==false
    ||r.currentEligibilityVerified!==false||r.inferenceProvenanceVerified!==false||r.identicalInputBindingVerified!==true
    ||r.acceptedContributions!==0||r.searchCreditsCreated!==0
    ||!['sampleCompatible','scoreCompatible','indexCompatible'].every(k=>typeof r[k]==='boolean')
    ||r.sampleCompatible!==(r.scoreCompatible&&r.indexCompatible)
    ||!integer(r.issuedAt,row.created_at,value.issuedAt)||!integer(r.expiresAt,now+1,p.validUntil)
    ||r.expiresAt>r.issuedAt+30*86400)fail();
  const i=r.indexComparison,d=r.detectorComparison;
  if(!i||i.version!==1||i.scope!=='offline-object-index-comparison'||i.status!=='COMPLETE'||i.locations!==p.locations
    ||i.sourceSha256!==p.sourceSha256||i.candidateManifestSha256!==r.candidateManifestSha256||!hex(i.referenceManifestSha256)
    ||i.declaredFrozenViews?.reference!==p.frozenViewsManifestSha256||i.declaredFrozenViews?.candidate!==p.frozenViewsManifestSha256
    ||i.qualified!==false||i.referenceProvenanceVerified!==false||i.identicalPixelsVerified!==false
    ||i.nativeSearchParityVerified!==false||i.serverAuthorization!==false
    ||!i.lanes||!Array.isArray(i.lanes.classes)||i.lanes.classes.length!==80
    ||!Array.isArray(i.lanes.hotConcepts)||i.lanes.hotConcepts.length!==2
    ||i.semantic?.recordsCompared!==p.locations*16||!d||!integer(d.numericValuesCompared,1,Number.MAX_SAFE_INTEGER)
    ||!integer(d.structuralDifferences,0,Number.MAX_SAFE_INTEGER))fail();
  const finite=(v,max=Number.MAX_VALUE)=>typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=max;
  const limits={maximumScoreDifference:.001,maximumConfidenceDifference:.001,maximumHeadingDegrees:.05,
    maximumPitchDegrees:.05,maximumZoomDifference:.001,maximumAreaDifference:.001};
  const lanes=[...i.lanes.classes,...i.lanes.hotConcepts];
  // Invalid negative evidence is an outage, not grounds to revoke a device.
  if(!finite(d.maximumScoreDifference,2)||!finite(d.maximumBoxDifference,1)
    ||!integer(i.viewQualityDifferences,0,p.locations)||!integer(i.semantic.differentCodeBytes,0,p.locations*16*128)
    ||!integer(i.semantic.differentFaces,0,p.locations*16)||!finite(i.semantic.maximumBoxDifference,1)
    ||!finite(i.semantic.maximumLogitShiftDifference)||!finite(i.semantic.maximumLogitScaleDifference)
    ||!i.nativeCounters||!['reference','candidate'].every(k=>exact(i.nativeCounters[k],['fetchErrors','inferenceErrors','permanentlyInvalidLocations'])
      &&Object.values(i.nativeCounters[k]).every(v=>integer(v,0,Number.MAX_SAFE_INTEGER)))
    ||lanes.some(l=>!l||!['missingRecords','extraRecords','discreteDifferences'].every(k=>integer(l[k],0,Number.MAX_SAFE_INTEGER))
      ||Object.keys(limits).some(k=>!finite(l[k]))))fail();
  if(r.scoreCompatible&&(d.structuralDifferences||!finite(d.maximumScoreDifference,.001)||!finite(d.maximumBoxDifference,2/65535)))fail();
  if(r.indexCompatible) {
    if(i.viewQualityDifferences!==0||i.semantic.differentCodeBytes!==0||i.semantic.differentFaces!==0
      ||!finite(i.semantic.maximumBoxDifference,2/65535)||!finite(i.semantic.maximumLogitShiftDifference,.01)
      ||!finite(i.semantic.maximumLogitScaleDifference,.01)
      ||!['reference','candidate'].every(k=>Object.values(i.nativeCounters[k]).every(v=>v===0)))fail();
    if(lanes.some(l=>l.missingRecords!==0||l.extraRecords!==0||l.discreteDifferences!==0
      ||Object.entries(limits).some(([k,max])=>!finite(l[k],max))))fail();
  }
  // The binding is the trusted numerical comparator. Preserve its full report
  // (including incompatible results); never convert detector-only evidence or
  // an uploader-supplied Boolean into an account qualification.
  return r;
}

export async function qualifyObjectDevice(env,account,body,now=Math.floor(Date.now()/1000),timeoutMs=70000) {
  const p=await setup(env,account,now),policyConfig=env.OBJECT_QUALIFICATION_POLICY;
  if(!exact(body,['requestId','profileId','artifactSetSha256'])||!id(body.requestId)||!hex(body.profileId)
    ||!(body.profileId in p.profiles)||!hex(body.artifactSetSha256)||!integer(timeoutMs,1,70000))fail('invalid_object_qualification_request',400);
  const started=performance.now(),current=()=>now+Math.floor((performance.now()-started)/1000);
  const find=()=>env.DB.prepare('SELECT * FROM object_qualification_requests WHERE id=?').bind(body.requestId).first();
  let row=await find();
  if(row&&(row.account_id!==account||row.authority_sha256!==p.authoritySha256||row.profile_id!==body.profileId||row.artifact_sha256!==body.artifactSetSha256))
    fail('object_qualification_request_conflict',409);
  if(row?.state==='qualified')return {...status(await activeObjectQualification(env,account,body.profileId,current(),row.id),p,body.profileId),replayed:true};
  if(row?.state==='incompatible')return {qualified:false,profileId:body.profileId,requestId:row.id,reason:'object_sample_incompatible',replayed:true};
  if(row&&(row.state==='cancelled'||row.deadline_at<=current()))fail('object_qualification_request_expired',409);
  if(typeof env.OBJECT_QUALIFIER?.fetch!=='function')fail('object_qualification_verifier_required');
  if(!row) {
    await env.DB.batch([
      env.DB.prepare(`INSERT OR IGNORE INTO object_qualification_controls(account_id,authority_sha256,profile_id) VALUES (?,?,?)`).bind(account,p.authoritySha256,body.profileId),
      env.DB.prepare(`INSERT OR IGNORE INTO object_qualification_requests(id,account_id,authority_sha256,profile_id,artifact_sha256,challenge,epoch,created_at,deadline_at)
        SELECT ?,?,?,?,?,?,epoch,?,? FROM object_qualification_controls WHERE account_id=? AND authority_sha256=? AND profile_id=?`)
        .bind(body.requestId,account,p.authoritySha256,body.profileId,body.artifactSetSha256,randomHex(16),now,now+600,account,p.authoritySha256,body.profileId),
    ]);
    row=await find();
    if(!row||row.account_id!==account||row.authority_sha256!==p.authoritySha256||row.profile_id!==body.profileId||row.artifact_sha256!==body.artifactSetSha256)
      fail('object_qualification_request_conflict',409);
  }
  const token=randomHex(16),at=current();
  const claim=await env.DB.prepare(`UPDATE object_qualification_requests SET claim_token=?,claim_until=? WHERE id=? AND state='pending'
    AND claim_until<=? AND deadline_at>? AND EXISTS (SELECT 1 FROM object_qualification_controls c JOIN accounts a ON a.id=c.account_id
      WHERE c.account_id=object_qualification_requests.account_id AND c.authority_sha256=object_qualification_requests.authority_sha256
      AND c.profile_id=object_qualification_requests.profile_id AND c.epoch=object_qualification_requests.epoch AND a.deleted_at IS NULL)`)
    .bind(token,Math.min(at+90,row.deadline_at),row.id,at,at).run();
  if(claim.meta.changes!==1)fail('object_qualification_request_waiting',409);
  let timer;const abort=new AbortController();
  const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{abort.abort();reject(Error('object_qualification_timeout'));},timeoutMs);});
  void deadline.catch(()=>{});
  try {
    const transfer=Promise.resolve().then(()=>env.OBJECT_QUALIFIER.fetch(new Request('https://object-qualifier.internal/object-qualifications/evidence',{
      method:'POST',headers:{'content-type':'application/json'},signal:abort.signal,
      body:JSON.stringify({version:1,accountId:account,requestId:row.id,challenge:row.challenge,profileId:row.profile_id,
        artifactSetSha256:row.artifact_sha256,policyId:p.policyId,policySha256:p.policySha256})}))).then(response=>{
          if(abort.signal.aborted){if(response.body)void response.body.cancel().catch(()=>{});throw Error('late_object_qualification');}return response;
        });
    const response=await Promise.race([transfer,deadline]);
    if(response.status!==200){if(response.body)void response.body.cancel().catch(()=>{});fail();}
    const value=await Promise.race([readVerifierJson(response,Math.min(timeoutMs,10000)),deadline]);
    const report=proof(value,row,p,current());
    // Keep hashes and bounded scalar summaries here. The trusted producer must
    // retain its original artifacts/report; arbitrary report metadata or paths
    // must not enter the coordination database or a contributor response.
    const receipt={version:1,scope:'saved-object-qualification-registry-receipt-v1',accountId:account,requestId:row.id,
      authoritySha256:p.authoritySha256,artifactSetSha256:row.artifact_sha256,artifacts:value.artifacts,
      policyId:p.policyId,policySha256:p.policySha256,scorePolicySha256:p.scorePolicySha256,profileId:row.profile_id,
      fixtureSha256:p.fixtureSha256,referenceBundleSha256:p.referenceBundleSha256,
      scoreSubmissionSha256:report.scoreSubmissionSha256,candidateManifestSha256:report.candidateManifestSha256,
      comparisonResponseSha256:await sha256Hex(encodeUtf8(JSON.stringify(value))),
      sampleCompatible:report.sampleCompatible,scoreCompatible:report.scoreCompatible,indexCompatible:report.indexCompatible,
      locations:report.locations,views:report.views,issuedAt:report.issuedAt,expiresAt:report.expiresAt};
    const json=JSON.stringify(receipt),sha=await sha256Hex(encodeUtf8(json));
    if(performance.now()-started>=timeoutMs||env.OBJECT_QUALIFICATION_MODE!=='saved-sample-v1'
      ||env.OBJECT_QUALIFICATION_POLICY!==policyConfig||current()>=p.validUntil||current()>=value.expiresAt)fail();
    const completed=current(),state=report.sampleCompatible?'qualified':'incompatible';
    await env.DB.batch([
      env.DB.prepare(`UPDATE object_qualification_requests SET state=?,completed_at=?,expires_at=?,proof_sha256=?,proof_json=?,claim_token=NULL,claim_until=0
        WHERE id=? AND state='pending' AND claim_token=? AND claim_until>? AND deadline_at>?`)
        .bind(state,completed,report.expiresAt,sha,json,row.id,token,completed,completed),
      env.DB.prepare(`UPDATE object_qualification_controls SET epoch=epoch+1 WHERE account_id=? AND authority_sha256=? AND profile_id=?
        AND EXISTS (SELECT 1 FROM object_qualification_requests r WHERE r.id=? AND r.state='incompatible' AND r.proof_sha256=?
          AND r.epoch=object_qualification_controls.epoch)`)
        .bind(account,p.authoritySha256,body.profileId,row.id,sha),
    ]);
    const saved=await find();
    if(saved?.state!==state||saved.proof_sha256!==sha)fail('object_qualification_authority_lost',409);
    if(state==='incompatible')return {qualified:false,profileId:body.profileId,requestId:row.id,reason:'object_sample_incompatible',replayed:false};
    const active=await activeObjectQualification(env,account,body.profileId,current(),row.id);
    if(!active)fail('object_qualification_authority_lost',409);
    return {...status(active,p,body.profileId),replayed:false};
  } catch(error) {
    if(error instanceof ObjectQualificationError)throw error;
    fail();
  } finally {
    clearTimeout(timer);
    await env.DB.prepare(`UPDATE object_qualification_requests SET claim_token=NULL,claim_until=0 WHERE id=? AND state='pending' AND claim_token=?`).bind(row.id,token).run();
  }
}

export async function revokeObjectQualification(env,account,body,now=Math.floor(Date.now()/1000)) {
  const p=await setup(env,account,now);
  if(!exact(body,['operationId','profileId'])||!id(body.operationId)||!hex(body.profileId))fail('invalid_object_qualification_request',400);
  const get=()=>env.DB.prepare('SELECT * FROM object_qualification_revocations WHERE id=?').bind(body.operationId).first();
  const prior=await get();
  if(prior&&(prior.account_id!==account||prior.authority_sha256!==p.authoritySha256||prior.profile_id!==body.profileId))fail('object_qualification_request_conflict',409);
  if(!prior)await env.DB.batch([
    env.DB.prepare(`INSERT OR IGNORE INTO object_qualification_revocations SELECT ?,account_id,authority_sha256,profile_id,epoch,?
      FROM object_qualification_controls WHERE account_id=? AND authority_sha256=? AND profile_id=?`).bind(body.operationId,now,account,p.authoritySha256,body.profileId),
    env.DB.prepare(`UPDATE object_qualification_controls SET epoch=epoch+1 WHERE account_id=? AND authority_sha256=? AND profile_id=?
      AND EXISTS (SELECT 1 FROM object_qualification_revocations r WHERE r.id=? AND r.epoch=object_qualification_controls.epoch)`)
      .bind(account,p.authoritySha256,body.profileId,body.operationId),
  ]);
  const saved=await get();
  if(!saved||saved.account_id!==account||saved.authority_sha256!==p.authoritySha256||saved.profile_id!==body.profileId)fail('object_qualification_request_conflict',409);
  return {qualified:false,profileId:body.profileId,operationId:body.operationId,replayed:!!prior};
}
