// Private prepared-lease integrity. No fake native candidate or audit approval.
import {validateObjectIndex,OBJECT_INDEX_MODEL} from './objectIndex.js';
import {publicObjectManifest} from './objectPublicManifest.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {base64ToBytes,encodeUtf8,sha256Hex} from './model.js';
import {ObjectDispatchError} from './objectAuditDispatch.js';
const fail=()=>{throw new ObjectDispatchError('qualified_object_preparation_changed',409);};
export async function inspectPreparedObjectUpload(env,account,authority,index,createdAt,now,race) {
  const lease=authority.leaseId;
  const held=await race(()=>env.DB.prepare(`SELECT l.*,a.deleted_at FROM leases l JOIN accounts a ON a.id=l.account_id
    WHERE l.id=? AND l.account_id=? AND l.lane='object' AND l.state='active' AND a.deleted_at IS NULL AND l.expires_at>?`)
    .bind(lease,account,now).first());
  if(!held)fail();
  const rows=(await race(()=>env.DB.prepare(`SELECT x.*,v.validator,v.evidence_sha256,v.validated_at,p.location_id AS published_id
    FROM lease_items i JOIN locations x ON x.id=i.location_id LEFT JOIN object_coverage v ON v.location_id=x.id
    LEFT JOIN published_index p ON p.location_id=x.id WHERE i.lease_id=? ORDER BY x.id LIMIT 5`).bind(lease).all())).results||[];
  if(!rows.length||rows.length>4||rows.some(r=>r.lane!=='object'||r.model!==OBJECT_INDEX_MODEL||r.state!=='leased'
    ||r.active_lease!==lease||r.published_id!==null||r.camera_generation!=='gen4'||r.validator!==COVERAGE_VALIDATOR
    ||typeof r.evidence_sha256!=='string'||!/^[a-f0-9]{64}$/.test(r.evidence_sha256)
    ||!Number.isSafeInteger(r.validated_at)||r.validated_at>now||r.validated_at<=now-86400))fail();
  if(!index||Object.keys(index).sort().join(',')!=='files,manifest,sourceTsv'||!index.files||typeof index.files!=='object'
    ||Array.isArray(index.files)||Object.keys(index.files).length>87)fail();
  const payload=encodeUtf8(JSON.stringify(index));
  if(!payload.length||payload.length>4193280)fail();
  const source=base64ToBytes(index.sourceTsv);
  if(await race(()=>sha256Hex(source))!==authority.sourceSha256)fail();
  const lines=new TextDecoder('utf-8',{fatal:true}).decode(source).split(/\r?\n/).filter(v=>v.trim());
  if(lines.length!==rows.length||lines.some((line,i)=>{const f=line.split('\t'),r=rows[i];
    return f.length!==12||f[7]!==r.asset_id||f[8]!==r.country||f[9]!=='gen4'
      ||[r.lat,r.lon,r.heading,r.pitch,r.zoom].some((v,j)=>typeof v!=='number'||!Number.isFinite(v)||!f[j+2].trim()||Number(f[j+2])!==v);
  }))fail();
  const files=Object.fromEntries(Object.entries(index.files).map(([name,value])=>[name,base64ToBytes(value)]));
  const records=await race(()=>validateObjectIndex(index.manifest,files,source,rows.map(r=>({locationId:r.id,panoId:r.asset_id,lat:r.lat,lng:r.lon})),lease));
  const submission=await race(()=>sha256Hex(payload));
  return {records,source,files,objectIndex:index,publicManifest:publicObjectManifest(index.manifest),payload,
    databaseSnapshot:{row:{lease_id:lease,account_id:account,profile_id:authority.profileId,policy_id:authority.policyId,
      assignment_sha256:authority.assignmentSha256,source_sha256:authority.sourceSha256,submission_sha256:submission,
      artifact_key:`object-quarantine/${lease}/${submission}.json`,payload_bytes:payload.length,location_count:rows.length,created_at:createdAt,
      lease_lane:held.lane,lease_state:held.state,lease_expires:held.expires_at,lease_generation:held.generation,deleted_at:null},rows},
    verificationScope:'qualified-object-prepared-upload-integrity-only',serverAuthorization:false,productionQualified:false,
    acceptedContributions:0,searchCreditsCreated:0};
}
