// Private operator-only readback. No normal deployment selects this entrypoint.
// Unlike an audit request, this cannot advance pending work or grant credit.
import {RECOVERY_PEPPER,sha256Hex,encodeUtf8,equalHex} from '../src/model.js';
import {requireSchema} from '../src/schemaRevision.js';
import {readRequestJson} from '../src/requestBody.js';
import {candidateResult} from '../src/scenePipeline.js';
import {meterSceneBindings,FINITE_HEADERS} from './finite-scene-gateway.mjs';

export const RECOVERY_LIMITS=Object.freeze({read:200,written:0,puts:0,bytes:0});
const hex=(value,n)=>typeof value==='string'&&new RegExp(`^[0-9a-f]{${n}}$`).test(value);
const fail=(code,status)=>Object.assign(Error(code),{status});

export function canonicalRecoveryTarget(target) {
  if(!target||Object.keys(target).sort().join(',')!=='accountId,leaseId,payloadSha256,policyId,records'
    ||!hex(target.accountId,32)||!hex(target.leaseId,32)||!hex(target.payloadSha256,64)
    ||typeof target.policyId!=='string'||!/^qualified-device-v1\|staging\.[A-Za-z0-9._-]+$/.test(target.policyId)
    ||target.policyId.length>220||!Array.isArray(target.records)||target.records.length<1||target.records.length>2
    ||new Set(target.records.map(r=>r?.locationId)).size!==target.records.length
    ||target.records.some(r=>!r||Object.keys(r).sort().join(',')!=='locationId,outputSha256'
      ||!Number.isSafeInteger(r.locationId)||r.locationId<1||!hex(r.outputSha256,64)))
    throw fail('invalid_recovery_target',400);
  // Exactly Python's sort_keys=True compact JSON for this ASCII target.
  return JSON.stringify({accountId:target.accountId,leaseId:target.leaseId,payloadSha256:target.payloadSha256,
    policyId:target.policyId,records:target.records.map(r=>({locationId:r.locationId,outputSha256:r.outputSha256}))});
}

export async function recoverSceneReceipt(env,target,code) {
  if(typeof code!=='string'||code.length<16||code.length>80)throw fail('unauthorized',401);
  await requireSchema(env);
  const recoveryHash=await sha256Hex(encodeUtf8(`${RECOVERY_PEPPER}\n${code}`));
  // One statement observes account/deletion, acceptance, award and publications
  // consistently. All lookups use primary/unique keys or this lease's items.
  // It reads no corpus statistics, R2 objects, model or qualification service.
  const row=await env.DB.prepare(`SELECT a.units,c.lease_id,c.account_id,c.policy_id,c.state,
      c.records_json,c.submission_sha256,l.account_id AS lease_account,l.lane,l.state AS lease_state,
      d.account_id AS ledger_account,d.units AS award,d.reason,d.reference,
      (SELECT COUNT(*) FROM lease_items WHERE lease_id=?) AS item_count,
      -- Keep the tiny expected-ID list outermost. An ordinary JOIN let SQLite
      -- scan published history despite equality lookups in a scaled fixture.
      (SELECT COUNT(*) FROM json_each(?) r
        CROSS JOIN lease_items i ON i.lease_id=? AND i.location_id=json_extract(r.value,'$.locationId')
        CROSS JOIN locations p ON p.id=i.location_id
        CROSS JOIN published_index x ON x.location_id=p.id
        WHERE p.lane='scene' AND p.state='published' AND p.contributor_id=a.id
          AND p.output_sha256=json_extract(r.value,'$.outputSha256')
          AND x.output_sha256=p.output_sha256 AND x.four_view_sha256=p.output_sha256
          AND x.four_view_key=?) AS publication_count
    FROM accounts a LEFT JOIN scene_candidates c ON c.lease_id=? AND c.account_id=a.id
    LEFT JOIN leases l ON l.id=c.lease_id
    LEFT JOIN ledger d ON d.reference=?
    WHERE a.id=? AND a.recovery_hash=? AND a.deleted_at IS NULL`)
    .bind(target.leaseId,JSON.stringify(target.records),target.leaseId,`four-view-v4/${target.leaseId}.i8`,
      target.leaseId,`lease:${target.leaseId}`,target.accountId,recoveryHash).first();
  if(!row)throw fail('unauthorized',401);
  let records;try{if(row.records_json?.length>8192)throw Error();records=JSON.parse(row.records_json);}catch{}
  const n=target.records.length;
  if(row.state!=='published'||row.lease_id!==target.leaseId||row.account_id!==target.accountId
    ||row.policy_id!==target.policyId||row.lease_account!==target.accountId||row.lane!=='scene'
    ||row.lease_state!=='submitted'||row.ledger_account!==target.accountId
    ||row.award!==n||row.reason!=='qualified_device_work'||row.reference!==`lease:${target.leaseId}`
    ||row.item_count!==n||row.publication_count!==n||!hex(row.submission_sha256,64)
    ||!Number.isSafeInteger(row.units)||row.units<0||!Array.isArray(records)||records.length!==n
    ||records.some((r,i)=>r.locationId!==target.records[i].locationId||r.outputSha256!==target.records[i].outputSha256))
    throw fail('scene_receipt_conflict',409);
  return {receiptContractVersion:1,readOnly:true,submissionId:target.leaseId,
    targetSha256:await sha256Hex(encodeUtf8(canonicalRecoveryTarget(target))),
    submissionSha256:row.submission_sha256,admissionMode:'qualified-device-v1',
    accepted:n,originalAwardUnits:row.award,currentUnits:row.units,ledgerEntries:1,
    unitsEarned:0,publicationDigestsMatched:true,auditReplay:candidateResult(row),
    r2ArtifactRead:false,qualificationRenewed:false};
}

export default {async fetch(request,env) {
  const headers={'cache-control':'no-store','x-content-type-options':'nosniff','referrer-policy':'no-referrer'};
  const reply=(data,status)=>Response.json(data,{status,headers});
  let metered;
  try {
    const now=Date.now(),until=Number(env.SCENE_RECOVERY_UNTIL),url=new URL(request.url);
    if(env.DEPLOYMENT_ENVIRONMENT!=='staging'||env.INDEX_BUCKET_NAME!=='vision-community-staging'
      ||env.DELETION_ARCHIVE_DB_ID!=='17043cb7-5dab-4a6f-84ca-19ae1c14cc05'
      ||env.SCENE_RECOVERY_ACCOUNT!=='272760294910ef0b246980278aeb36e2'
      ||!hex(env.SCENE_RECOVERY_TOKEN_SHA256,64)||!hex(env.SCENE_RECOVERY_TARGET_SHA256,64)
      ||!Number.isSafeInteger(until)||until<=now||until>now+20*60000||!env.DB
      ||env.RESTORE_MAINTENANCE!==undefined&&env.RESTORE_MAINTENANCE!=='0')
      throw fail('scene_recovery_unavailable',503);
    const token=request.headers.get('x-vision-finite-cohort')||'';
    if(!hex(token,64)||!equalHex(await sha256Hex(encodeUtf8(token)),env.SCENE_RECOVERY_TOKEN_SHA256))
      throw fail('unauthorized',403);
    if(request.method!=='POST'||url.pathname!=='/api/scene-receipt-recovery'||url.search
      ||request.headers.get('origin')!==url.origin)throw fail('not_found',404);
    const body=await readRequestJson(request,10000,2048);
    if(Object.keys(body).sort().join(',')!=='recoveryCode,target')throw fail('invalid_recovery_target',400);
    const digest=await sha256Hex(encodeUtf8(canonicalRecoveryTarget(body.target)));
    if(!equalHex(digest,env.SCENE_RECOVERY_TARGET_SHA256))throw fail('scene_recovery_target_changed',409);
    const remaining={};
    for(const [key,max]of Object.entries(RECOVERY_LIMITS)){
      const value=request.headers.get('x-vision-trial-remaining-'+key)||'';
      if(!/^(?:0|[1-9][0-9]{0,2})$/.test(value)||Number(value)>max)throw fail('finite_scene_budget_required',400);
      remaining[key]=Number(value);
    }
    metered=meterSceneBindings({...env,INDEX:{}},remaining);
    // Expose only SELECT to the readback helper. Even a later accidental write
    // cannot rotate credentials, expire jobs, publish or settle a balance here.
    const underlying=metered.env.DB;
    metered.env.DB={prepare(sql){if(!/^\s*SELECT\b/i.test(sql))throw fail('read_only_recovery',503);return underlying.prepare(sql);}};
    const data=await recoverSceneReceipt(metered.env,body.target,body.recoveryCode);
    if(metered.usage.read>remaining.read||metered.usage.written||metered.usage.puts||metered.usage.bytes)
      throw fail('finite_scene_usage_limit',503);
    return finish(data,200);
  }catch(error){return finish({error:['unauthorized','not_found','invalid_recovery_target',
    'scene_recovery_target_changed','scene_receipt_conflict','finite_scene_budget_required',
    'schema_update_required','finite_scene_usage_limit'].includes(error.message)?error.message:'scene_recovery_unavailable'},
    Number.isInteger(error.status)?error.status:503);
  }finally{if(request.body&&!request.body.locked)void request.body.cancel().catch(()=>{});}
  function finish(data,status){
    if(metered){headers['x-vision-trial-usage-complete']=metered.usage.complete?'1':'0';
      for(const [key,name]of Object.entries(FINITE_HEADERS))headers[name]=String(metered.usage[key]);}
    return reply(data,status);
  }
}};
