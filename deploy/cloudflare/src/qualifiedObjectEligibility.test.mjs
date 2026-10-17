// Real local SQLite/quarantine bytes. All qualification/protection is synthetic.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {ownerFixture,ACCOUNT,LEASE} from './ownerObjectAudit.fixture.mjs';
import {prepareObjectQualification} from '../tools/prepare-object-qualification.mjs';
import {qualifyObjectDevice,revokeObjectQualification} from './objectQualification.js';
import {policy as samplePolicy,evidence} from '../tools/fixtures/object-qualification-proof.mjs';
import {inspectQualifiedObjectUpload,qualifiedObjectEligibilityPolicy} from './qualifiedObjectEligibility.js';
import {sha256Hex,encodeUtf8} from './model.js';
import {objectCapabilities} from './objectAdmission.js';

const sceneAccount='a'.repeat(32);
async function setup(t,manifestChange=null) {
  let overrides={};
  if(manifestChange){
    const d=JSON.parse(readFileSync(new URL('../../../community/tests/fixtures/object-feature-content-v1.json',import.meta.url),'utf8'));
    const index={manifest:d.baseline.manifest,sourceTsv:d.baseline.sourceBase64,files:d.baseline.filesBase64};
    Object.assign(index.manifest.viewQuality,{policy:'vision-per-view-quality-v1',implementationIdentity:'1'.repeat(64),viewCount:6,
      blurAreaFractionExclusive:.5,tileGrid:8,tunnelVisionProbabilityInclusive:.85,tunnelEvidencePolicy:'none-darkness-never-rejects-v1',
      protectedAuthorityManifestSha256:'2'.repeat(64)});
    manifestChange(index.manifest);overrides={index};
  }
  const f=await ownerFixture(t,overrides),p=samplePolicy(),profile=f.authority.profileId;
  p.profiles={[profile]:'d'.repeat(64)};
  f.env.OBJECT_QUALIFICATION_MODE='saved-sample-v1';f.env.OBJECT_QUALIFICATION_POLICY=JSON.stringify(p);
  await prepareObjectQualification(f.env.DB);
  f.env.OBJECT_QUALIFIER={fetch:async request=>{
    const body=await request.json(),value=evidence(body,p,true,f.now);
    value.report.profileId=profile;value.artifacts.detectorProfileId=profile;value.artifacts.indexProfileId=profile;
    return Response.json(value);
  }};
  const qualified=await qualifyObjectDevice(f.env,ACCOUNT,{requestId:'9'.repeat(32),profileId:profile,artifactSetSha256:'8'.repeat(64)},f.now);
  const policy={version:1,scope:'qualified-object-eligibility-v1',policyId:f.authority.policyId,
    qualificationPolicySha256:p.policySha256,protectedPolicySha256:'6'.repeat(64),qualityImplementationIdentity:'1'.repeat(64),
    protectedAuthoritySha256:'2'.repeat(64),protectedOriginHandoffSha256:'7'.repeat(64),sceneInputModel:'synthetic-scene-input',
    resource:f.resource,validFrom:f.now-10,validUntil:f.now+7200};
  const setPolicy=async()=>{
    f.env.OBJECT_ELIGIBILITY_POLICY=JSON.stringify(policy);
    f.env.OBJECT_ELIGIBILITY_POLICY_SHA256=await sha256Hex(encodeUtf8(f.env.OBJECT_ELIGIBILITY_POLICY));
  };
  await setPolicy();f.env.OBJECT_QUALIFIED_UPLOAD_MODE='qualified-device-v1';
  f.sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-scene-owner',0)").run(sceneAccount);
  for(const row of f.sql.prepare('SELECT * FROM locations ORDER BY id').all()){
    f.sql.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,output_sha256,contributor_id,
      camera_generation,lat,lon,heading,pitch,zoom,country) VALUES (?,?,?,'scene',?,'published',?,?,'gen4',?,?,?,?,?,?)`)
      .run(row.id+100,row.asset_id,row.capture,policy.sceneInputModel,'e'.repeat(64),sceneAccount,
        row.lat,row.lon,row.heading,row.pitch,row.zoom,row.country);
    f.sql.prepare(`INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_sha256,four_view_key)
      VALUES (?,'',?,?,?,?)`).run(row.id+100,'e'.repeat(64),f.now,'e'.repeat(64),'four-view-v4/synthetic.i8');
  }
  let calls=0,lastRequest;
  const proof=request=>({
    ...request,scope:'trusted-live-object-protection-v1',
    ...Object.fromEntries(['protectedPolicySha256','qualityImplementationIdentity','protectedAuthoritySha256',
      'protectedOriginHandoffSha256','resource'].map(k=>[k,policy[k]])),
    records:f.sql.prepare('SELECT location_id AS locationId,evidence_sha256 AS coverageEvidenceSha256 FROM object_coverage ORDER BY location_id').all(),
    protectedEligible:true,verifiedOnOriginalSourceMachine:true,
    sceneMembershipVerified:false,coverageVerified:false,qualificationVerified:false,serverAuthorization:false,productionQualified:false,
    acceptedContributions:0,searchCreditsCreated:0,issuedAt:f.now,expiresAt:f.now+30,
  });
  f.env.OBJECT_ELIGIBILITY={fetch:async request=>{
    calls++;assert.equal(request.url,'https://object-eligibility.internal/object-eligibility/evidence');
    lastRequest=await request.json();return Response.json(proof(lastRequest));
  }};
  f.env.OBJECT_VERIFIER={fetch:()=>assert.fail('no native audit allowed for qualified inspection')};
  const state=()=>JSON.stringify(Object.fromEntries(['accounts','leases','locations','object_coverage','lease_items',
    'object_audit_candidates','object_qualification_requests','object_qualification_controls','published_index','ledger','account_artifact_writes']
    .map(name=>[name,f.sql.prepare(`SELECT * FROM ${name}`).all()])));
  return {...f,policy,setPolicy,qualification:qualified,proof,calls:()=>calls,request:()=>lastRequest,state,
    inspect:(at=f.now,timeout=20000)=>inspectQualifiedObjectUpload(f.env,ACCOUNT,LEASE,at,timeout)};
}

test('complete profile plus current contributed Scene, Gen4 and protection connects read-only eligibility',async t=>{
  const f=await setup(t),before=f.state(),objects=[...f.objects];
  const result=await f.inspect();
  assert.equal(result.eligibilityVerified,true);assert.equal(result.qualificationId,f.qualification.qualificationId);
  assert.equal(result.verificationScope,'qualified-object-upload-eligibility-only');
  assert.equal(result.admissionMode,'qualified-device-v1');assert.equal(result.routineUploadsIndependentlyRecomputed,false);
  assert.equal(result.protection.sceneMembershipVerified,false);assert.equal(result.sceneMembership.length,2);
  assert.equal(result.serverAuthorization,false);assert.equal(result.acceptedContributions,0);assert.equal(result.searchCreditsCreated,0);
  assert.equal(f.state(),before);assert.deepEqual([...f.objects],objects);assert.equal(f.calls(),1);
  assert.equal(f.row().native_state,null);assert.equal(objectCapabilities().objectContributions.ready,false);
  assert.equal(JSON.stringify(result.protection).includes('FICTIONAL-PRIVATE'),false);
});

test('missing mode, policy hash, scope, resource, runtime context and protected authority fail closed',async t=>{
  const f=await setup(t);
  for(const changes of [{OBJECT_QUALIFIED_UPLOAD_MODE:undefined},{OBJECT_ELIGIBILITY_POLICY_SHA256:'0'.repeat(64)},
    {OBJECT_ELIGIBILITY_POLICY:'{}'},{OBJECT_ELIGIBILITY:undefined}]){
    await assert.rejects(inspectQualifiedObjectUpload({...f.env,...changes},ACCOUNT,LEASE,f.now));
  }
  for(const changes of [{scope:'object-batch-parity-v1'},{version:true},{resource:{...f.resource,bucket:'unrelated-resource'}},
    {qualificationPolicySha256:'0'.repeat(64)},{sceneInputModel:'bad/path'},{validUntil:f.now},
    {validUntil:f.now+31*86400},{protectedPolicySha256:'short'},{qualityImplementationIdentity:'short'}]){
    const p={...f.policy,...changes},raw=JSON.stringify(p);
    await assert.rejects(qualifiedObjectEligibilityPolicy({...f.env,OBJECT_ELIGIBILITY_POLICY:raw,
      OBJECT_ELIGIBILITY_POLICY_SHA256:await sha256Hex(encodeUtf8(raw))},f.now));
  }
  assert.equal(f.calls(),0);
});

test('unqualified revoked expired and changed profile never reach private protection',async t=>{
  for(const change of ['revoked','expired','changed-profile','changed-qualification-policy']){
    const f=await setup(t);
    if(change==='revoked')await revokeObjectQualification(f.env,ACCOUNT,{operationId:'7'.repeat(32),profileId:f.authority.profileId},f.now);
    if(change==='changed-profile'){
      const p=JSON.parse(f.env.OBJECT_QUALIFICATION_POLICY);p.profiles={['0'.repeat(64)]:'d'.repeat(64)};
      f.env.OBJECT_QUALIFICATION_POLICY=JSON.stringify(p);
    }
    if(change==='changed-qualification-policy'){
      const p=JSON.parse(f.env.OBJECT_QUALIFICATION_POLICY);p.validUntil++;f.env.OBJECT_QUALIFICATION_POLICY=JSON.stringify(p);
    }
    await assert.rejects(f.inspect(change==='expired'?f.now+3601:f.now));assert.equal(f.calls(),0);
  }
});

test('Scene membership must be published, contributed, active and exact in the approved input model',async t=>{
  for(const change of ["DELETE FROM published_index WHERE location_id=111","UPDATE locations SET state='pending' WHERE id=111",
    "UPDATE locations SET contributor_id=NULL WHERE id=111","UPDATE accounts SET deleted_at=1 WHERE id='"+sceneAccount+"'",
    "UPDATE locations SET asset_id='other' WHERE id=111","UPDATE locations SET capture='other' WHERE id=111",
    'UPDATE locations SET lat=lat+0.000001 WHERE id=111',"UPDATE locations SET country='other' WHERE id=111",
    "UPDATE locations SET camera_generation='gen3' WHERE id=111","UPDATE locations SET model='old' WHERE id=111",
    "UPDATE published_index SET four_view_sha256='"+'0'.repeat(64)+"' WHERE location_id=111",
    "UPDATE published_index SET four_view_key='object-index-v4/other/' WHERE location_id=111"]){
    const f=await setup(t);f.sql.exec(change);await assert.rejects(f.inspect());assert.equal(f.calls(),0);
  }
});

test('current official Gen4 and quality integrity remain mandatory before qualification-based inspection',async t=>{
  for(const change of ["UPDATE locations SET camera_generation='gen3' WHERE lane='object'",
    "UPDATE object_coverage SET validator='old'",'UPDATE object_coverage SET validated_at=1',
    'UPDATE object_coverage SET validated_at=validated_at+100','DELETE FROM object_coverage',
    "UPDATE leases SET state='expired'","UPDATE locations SET active_lease=NULL WHERE lane='object'"]){
    const f=await setup(t);f.sql.exec(change);await assert.rejects(f.inspect());assert.equal(f.calls(),0);
  }
  const f=await setup(t);f.policy.qualityImplementationIdentity='0'.repeat(64);await f.setPolicy();
  await assert.rejects(f.inspect());assert.equal(f.calls(),0);
});

test('incomplete inference and fetch work cannot pass the qualified eligibility gate',async t=>{
  for(const field of ['fetchErrors','inferenceErrors','permanentlyInvalidLocations']){
    const f=await setup(t,manifest=>{manifest[field]=1;});
    const before=f.state();await assert.rejects(f.inspect());assert.equal(f.calls(),0);assert.equal(f.state(),before);
  }
});

test('protection reply must bind every authority and must not self-assert qualification or Scene/coverage approval',async t=>{
  const f=await setup(t);
  for(const changes of [{accountId:'0'.repeat(32)},{leaseId:'0'.repeat(32)},{qualificationId:'0'.repeat(32)},
    {profileId:'0'.repeat(64)},{challenge:'0'.repeat(32)},{snapshotSha256:'0'.repeat(64)},
    {assignmentSha256:'0'.repeat(64)},{sourceSha256:'0'.repeat(64)},{policySha256:'0'.repeat(64)},
    {protectedPolicySha256:'0'.repeat(64)},{protectedAuthoritySha256:'0'.repeat(64)},{protectedOriginHandoffSha256:'0'.repeat(64)},
    {resource:{...f.resource,bucket:'unrelated-resource'}},{protectedEligible:false},{verifiedOnOriginalSourceMachine:false},
    {sceneMembershipVerified:true},{coverageVerified:true},{qualificationVerified:true},{serverAuthorization:true},
    {productionQualified:true},{acceptedContributions:1},{searchCreditsCreated:1},{expiresAt:f.now},
    {issuedAt:f.now-21},{expiresAt:f.now+31},{privatePath:'secret'},{records:[]}]){
    f.env.OBJECT_ELIGIBILITY={fetch:async request=>Response.json({...f.proof(await request.json()),...changes})};
    const before=f.state();await assert.rejects(f.inspect());assert.equal(f.state(),before);
  }
});

test('coverage records in the independent assignment must match the current trusted import exactly',async t=>{
  const f=await setup(t);
  for(const change of ['wrong-location','wrong-coverage','duplicate','different-order']){
    f.env.OBJECT_ELIGIBILITY={fetch:async request=>{
      const v=f.proof(await request.json());
      if(change==='wrong-location')v.records[0].locationId=999;
      if(change==='wrong-coverage')v.records[0].coverageEvidenceSha256='0'.repeat(64);
      if(change==='duplicate')v.records[1]=v.records[0];
      if(change==='different-order')v.records.reverse();
      return Response.json(v);
    }};await assert.rejects(f.inspect());
  }
});

test('revocation deletion coverage Scene and policy changes during protection invalidate the captured authority',async t=>{
  for(const change of ['revocation','deletion','scene-deletion','scene-digest','coverage','pose','mode','policy']){
    const f=await setup(t);
    f.env.OBJECT_ELIGIBILITY={fetch:async request=>{
      const value=f.proof(await request.json());
      if(change==='revocation')await revokeObjectQualification(f.env,ACCOUNT,{operationId:'7'.repeat(32),profileId:f.authority.profileId},f.now);
      if(change==='deletion')f.sql.prepare('UPDATE accounts SET deleted_at=?,units=0 WHERE id=?').run(f.now,ACCOUNT);
      if(change==='scene-deletion')f.sql.prepare('UPDATE accounts SET deleted_at=?,units=0 WHERE id=?').run(f.now,sceneAccount);
      if(change==='scene-digest')f.sql.exec("UPDATE published_index SET output_sha256='"+'0'.repeat(64)+"' WHERE location_id=111");
      if(change==='coverage')f.sql.exec('UPDATE object_coverage SET validated_at=validated_at-1');
      if(change==='pose')f.sql.exec("UPDATE locations SET heading=heading+1 WHERE lane='object'");
      if(change==='mode')f.env.OBJECT_QUALIFIED_UPLOAD_MODE=undefined;
      if(change==='policy')f.env.OBJECT_ELIGIBILITY_POLICY+=' ';
      return Response.json(value);
    }};
    await assert.rejects(f.inspect());assert.equal(f.sql.prepare("SELECT COUNT(*) n FROM ledger WHERE units>0").get().n,0);
  }
});

test('deadline bounds slow files, hung headers/body and discards late evidence',async t=>{
  for(const mode of ['headers','body','stored','late']){
    const f=await setup(t);let resolve,cancelled=false;
    if(mode==='headers')f.env.OBJECT_ELIGIBILITY={fetch:()=>new Promise(()=>{})};
    if(mode==='body')f.env.OBJECT_ELIGIBILITY={fetch:()=>new Response(new ReadableStream({pull:()=>new Promise(()=>{})}),
      {headers:{'content-type':'application/json'}})};
    if(mode==='stored')f.env.INDEX.get=()=>new Promise(()=>{});
    if(mode==='late')f.env.OBJECT_ELIGIBILITY={fetch:()=>new Promise(done=>{resolve=done;})};
    const before=f.state(),at=Date.now();
    await assert.rejects(f.inspect(f.now,mode==='late'?50:20));assert(Date.now()-at<1000);
    if(mode==='late'){
      assert(resolve);resolve(new Response(new ReadableStream({cancel(){cancelled=true;}}),{headers:{'content-type':'application/json'}}));
      await new Promise(done=>setTimeout(done,5));assert.equal(cancelled,true);
    }
    assert.equal(f.state(),before);
  }
});

test('malformed oversized and failed protection is an outage without a qualification rejection',async t=>{
  const f=await setup(t);
  for(const response of [new Response('private path'),new Response(new Uint8Array(65537),{headers:{'content-type':'application/json'}}),
    Response.json({error:'private path'},{status:503}),Response.json({})]){
    f.env.OBJECT_ELIGIBILITY={fetch:()=>response};const before=f.state();
    await assert.rejects(f.inspect(),error=>!error.message.includes('private path'));assert.equal(f.state(),before);
  }
});

test('invalid caller identity and budgets cannot touch storage or services',async()=>{
  for(const args of [[{},'bad',LEASE,0,20],[{},ACCOUNT,'bad',0,20],[{},ACCOUNT,LEASE,NaN,20],
    [{},ACCOUNT,LEASE,0,0],[{},ACCOUNT,LEASE,0,20001]]){
    await assert.rejects(inspectQualifiedObjectUpload(...args),{message:'invalid_object_eligibility',status:400});
  }
});
