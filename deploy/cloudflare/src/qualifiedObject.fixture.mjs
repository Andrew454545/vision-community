// Test-only synthetic identity/coverage/protection. No authentic inference.
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {prepareObjectAuditDispatch} from '../tools/prepare-object-audit-dispatch.mjs';
import {prepareObjectQualification} from '../tools/prepare-object-qualification.mjs';
import {prepareQualifiedObject,bindQualifiedObjectPolicy} from '../tools/prepare-qualified-object.mjs';
import {qualifyObjectDevice} from './objectQualification.js';
import {policy as samplePolicy,evidence} from '../tools/fixtures/object-qualification-proof.mjs';
import {syntheticR2} from './syntheticR2.mjs';
import {sha256Hex,encodeUtf8} from './model.js';
import {OBJECT_INDEX_MODEL} from './objectIndex.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {stageQualifiedObjectUpload,settleQualifiedObjectUpload} from './qualifiedObjectPublication.js';

export const ACCOUNT='b'.repeat(32),SCENE_ACCOUNT='a'.repeat(32);
const d=JSON.parse(readFileSync(new URL('../../../community/tests/fixtures/object-feature-content-v1.json',import.meta.url),'utf8'));
export const LEASE=d.leaseId;
export async function qualifiedFixture(t,{file=':memory:',install=true}={}) {
  const sql=new DatabaseSync(file);if(t)t.after(()=>sql.close());const now=Math.floor(Date.now()/1000);
  const objects=new Map(),r2=syntheticR2(objects);
  const env={DB:sqliteD1(sql),DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',INDEX:{...r2,
    async get(key){const obj=await r2.get(key);return obj?{...obj,body:new Response(await obj.arrayBuffer()).body}:null;}}};
  await prepareDatabase(env.DB);await prepareObjectAuditDispatch(env.DB);await prepareObjectQualification(env.DB);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-object-owner',0)").run(ACCOUNT);
  sql.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-scene-owner',0)").run(SCENE_ACCOUNT);
  sql.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at,generation) VALUES (?,?,'object','active',?,1)").run(LEASE,ACCOUNT,now+10000);
  for(const item of d.items){
    sql.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation,lat,lon,heading,pitch,zoom,country,generation)
      VALUES (?,?,'synthetic','object',?,'leased',?,'gen4',?,?,?,?,?,?,1)`).run(item.locationId,item.panoId,OBJECT_INDEX_MODEL,
        LEASE,item.lat,item.lng,item.heading,item.pitch,item.zoom,item.country);
    sql.prepare('INSERT INTO lease_items VALUES (?,?)').run(LEASE,item.locationId);
    sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,?)').run(item.locationId,COVERAGE_VALIDATOR,'d'.repeat(64),now);
    sql.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,output_sha256,contributor_id,camera_generation,lat,lon,heading,pitch,zoom,country)
      VALUES (?,?,'synthetic','scene','synthetic-scene-input','published',?,?,'gen4',?,?,?,?,?,?)`).run(item.locationId+100,
        item.panoId,'e'.repeat(64),SCENE_ACCOUNT,item.lat,item.lng,item.heading,item.pitch,item.zoom,item.country);
    sql.prepare(`INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_sha256,four_view_key)
      VALUES (?,'',?,?,?,?)`).run(item.locationId+100,'e'.repeat(64),now,'e'.repeat(64),'four-view-v4/synthetic.i8');
  }
  const index={manifest:structuredClone(d.baseline.manifest),sourceTsv:d.baseline.sourceBase64,files:structuredClone(d.baseline.filesBase64)};
  Object.assign(index.manifest.viewQuality,{policy:'vision-per-view-quality-v1',implementationIdentity:'1'.repeat(64),viewCount:6,
    blurAreaFractionExclusive:.5,tileGrid:8,tunnelVisionProbabilityInclusive:.85,tunnelEvidencePolicy:'none-darkness-never-rejects-v1',
    protectedAuthorityManifestSha256:'2'.repeat(64)});
  index.manifest.sourceTsv='C:/SYNTHETIC-PRIVATE/original.tsv';
  const authority={leaseId:LEASE,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64),
    sourceSha256:await sha256Hex(new Uint8Array(Buffer.from(index.sourceTsv,'base64')))};
  const qPolicy=samplePolicy();qPolicy.profiles={[authority.profileId]:'d'.repeat(64)};
  env.OBJECT_QUALIFICATION_MODE='saved-sample-v1';env.OBJECT_QUALIFICATION_POLICY=JSON.stringify(qPolicy);
  env.OBJECT_QUALIFIER={fetch:async request=>{const body=await request.json(),value=evidence(body,qPolicy,true,now);
    value.report.profileId=authority.profileId;value.artifacts.detectorProfileId=authority.profileId;value.artifacts.indexProfileId=authority.profileId;
    return Response.json(value);}};
  const qualification=await qualifyObjectDevice(env,ACCOUNT,{requestId:'9'.repeat(32),profileId:authority.profileId,artifactSetSha256:'8'.repeat(64)},now);
  const policy={version:1,scope:'qualified-object-eligibility-v1',policyId:authority.policyId,
    qualificationPolicySha256:qPolicy.policySha256,protectedPolicySha256:'6'.repeat(64),qualityImplementationIdentity:'1'.repeat(64),
    protectedAuthoritySha256:'2'.repeat(64),protectedOriginHandoffSha256:'7'.repeat(64),sceneInputModel:'synthetic-scene-input',
    resource:qPolicy.resource,validFrom:now-10,validUntil:now+7200};
  env.OBJECT_ELIGIBILITY_POLICY=JSON.stringify(policy);env.OBJECT_ELIGIBILITY_POLICY_SHA256=await sha256Hex(encodeUtf8(env.OBJECT_ELIGIBILITY_POLICY));
  env.OBJECT_QUALIFIED_UPLOAD_MODE='qualified-device-v1';
  if(install){await prepareQualifiedObject(env.DB);await bindQualifiedObjectPolicy(env.DB,env.OBJECT_ELIGIBILITY_POLICY_SHA256,
    sql.prepare('SELECT authority_sha256 FROM object_qualification_requests WHERE id=?').get(qualification.qualificationId).authority_sha256);}
  let protectionCalls=0;
  const records=d.items.map(i=>({locationId:i.locationId,coverageEvidenceSha256:'d'.repeat(64)}));
  const proof=request=>({...request,scope:'trusted-live-object-protection-v1',protectedPolicySha256:policy.protectedPolicySha256,
    qualityImplementationIdentity:policy.qualityImplementationIdentity,protectedAuthoritySha256:policy.protectedAuthoritySha256,
    protectedOriginHandoffSha256:policy.protectedOriginHandoffSha256,resource:policy.resource,records,
    protectedEligible:true,verifiedOnOriginalSourceMachine:true,sceneMembershipVerified:false,coverageVerified:false,qualificationVerified:false,
    serverAuthorization:false,productionQualified:false,acceptedContributions:0,searchCreditsCreated:0,issuedAt:now,expiresAt:now+30});
  env.OBJECT_ELIGIBILITY={fetch:async request=>{protectionCalls++;return Response.json(proof(await request.json()));}};
  env.OBJECT_VERIFIER={fetch(){throw Error('synthetic forbidden native audit');}};
  const counts=()=>({candidates:sql.prepare('SELECT COUNT(*) n FROM qualified_object_candidates').get().n,
    acceptances:sql.prepare('SELECT COUNT(*) n FROM qualified_object_acceptances').get().n,
    publications:sql.prepare("SELECT COUNT(*) n FROM published_index p JOIN locations l ON l.id=p.location_id WHERE l.lane='object'").get().n,
    awards:sql.prepare("SELECT COUNT(*) n FROM ledger WHERE reason='qualified_device_work'").get().n,
    units:sql.prepare('SELECT units FROM accounts WHERE id=?').get(ACCOUNT).units});
  return {env,sql,index,authority,qualification,policy,now,objects,proof,counts,protectionCalls:()=>protectionCalls,
    stage:(at=now,timeout=20000)=>stageQualifiedObjectUpload(env,ACCOUNT,authority,index,at,timeout),
    settle:(at=now,timeout=20000)=>settleQualifiedObjectUpload(env,ACCOUNT,LEASE,at,timeout)};
}
