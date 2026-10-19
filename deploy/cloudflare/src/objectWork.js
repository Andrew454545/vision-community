// Inactive internal allocator for operator-prepared work. No public router import.
import {OBJECT_WORK_CONTRACT} from './objectWorkSchema.js';
import {qualifiedObjectEligibilityPolicy,sceneMembers,validateObjectProtectionEvidence} from './qualifiedObjectEligibility.js';
import {activeObjectQualification} from './objectQualification.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {OBJECT_INDEX_MODEL} from './objectIndex.js';
import {ObjectDispatchError} from './objectAuditDispatch.js';
import {sha256Hex,encodeUtf8,randomHex} from './model.js';
import {readVerifierJson} from './scenePipeline.js';
const id=v=>typeof v==='string'&&/^[a-f0-9]{32}$/.test(v),hex=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const fail=(code='qualified_object_work_unavailable',status=503)=>{throw new ObjectDispatchError(code,status);};
const key=k=>{if(!/^[a-z_][a-z_0-9]*$/.test(k))fail();return k;};
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
// D1 caps expression depth at 100. Preserve every equality using a balanced tree.
const all=items=>items.length===1?items[0]:`(${all(items.slice(0,Math.floor(items.length/2)))} AND ${all(items.slice(Math.floor(items.length/2)))})`;
async function setup(env,account,now){
 if((await env.DB.prepare('SELECT contract FROM object_work_revision WHERE slot=1').first())?.contract!==OBJECT_WORK_CONTRACT)fail();
 if(!await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first())fail('account_not_active',401);
 const p=await qualifiedObjectEligibilityPolicy(env,now);
 if(typeof env.OBJECT_ELIGIBILITY?.fetch!=='function')fail();return p;
}
const requestFor=(env,account,request)=>env.DB.prepare('SELECT * FROM object_work_requests WHERE account_id=? AND request_key=?').bind(account,request).first();
const poolFor=(env,lease)=>env.DB.prepare('SELECT * FROM object_work_pool WHERE lease_id=?').bind(lease).first();
async function snapshot(env,account,pool,now,request=null){
 const p=await setup(env,account,now),qualification=await activeObjectQualification(env,account,pool.profile_id,now,request?.qualification_id??null);
 if(!qualification)fail('object_device_qualification_required',403);
 if(pool.policy_id!==p.policyId||pool.eligibility_sha256!==env.OBJECT_ELIGIBILITY_POLICY_SHA256||pool.valid_until<=now)fail('object_work_expired',409);
 const wanted=JSON.parse(pool.records_json),rows=(await env.DB.prepare(`SELECT x.*,v.validator,v.evidence_sha256,v.validated_at,ip.location_id AS published_id
   FROM locations x JOIN object_coverage v ON v.location_id=x.id LEFT JOIN published_index ip ON ip.location_id=x.id
   WHERE x.id IN (SELECT json_extract(value,'$.locationId') FROM json_each(?)) ORDER BY x.id`).bind(pool.records_json).all()).results;
 if(rows.length!==wanted.length||!rows.length||rows.length>4||rows.some((r,i)=>{
   const v=wanted[i];return r.id!==v.locationId||r.asset_id!==v.panoId||r.country!==v.country||r.camera_generation!=='gen4'
     ||r.lane!=='object'||r.model!==OBJECT_INDEX_MODEL||r.published_id!==null||r.validator!==COVERAGE_VALIDATOR
     ||r.evidence_sha256!==v.coverageEvidenceSha256||!hex(r.evidence_sha256)||r.validated_at>now||r.validated_at<=now-86400
     ||[r.lat,r.lon,r.heading,r.pitch,r.zoom].some((n,j)=>n!==[v.lat,v.lng,v.heading,v.pitch,v.zoom][j])
     ||r.state!==(request?'leased':'pending')||r.queue_state!=='pending'||r.active_lease!==(request?pool.lease_id:null);
 }))fail('object_work_inputs_changed',409);
 const scenes=await sceneMembers({...env,sceneModel:p.sceneInputModel},rows,fn=>fn());
 const lease=request?await env.DB.prepare('SELECT * FROM leases WHERE id=? AND account_id=?').bind(pool.lease_id,account).first():null;
 if(request&&(!lease||request.state==='cancelled'||lease.state!=='active'||lease.expires_at<=now||lease.expires_at!==request.expires_at
   ||(await env.DB.prepare('SELECT COUNT(*) n FROM lease_items WHERE lease_id=?').bind(pool.lease_id).first()).n!==rows.length))fail('object_work_expired',409);
 return {pool,qualification,rows,scenes,request,lease,policySha256:env.OBJECT_ELIGIBILITY_POLICY_SHA256};
}
function guard(s){
 const q=all(Object.keys(s.qualification).map(k=>`q.${key(k)} IS json_extract(e.doc,'$.qualification.${k}')`));
 const extra={validator:'v.validator',evidence_sha256:'v.evidence_sha256',validated_at:'v.validated_at',published_id:'ip.location_id'};
 const row=all(Object.keys(s.rows[0]).map(k=>`${extra[k]||'x.'+key(k)} IS json_extract(j.value,'$.${k}')`));
 const sx={deleted_at:'sa.deleted_at',four_view_sha256:'sp.four_view_sha256',four_view_key:'sp.four_view_key',published_sha256:'sp.output_sha256'};
 const scene=all(Object.keys(s.scenes[0].scene).map(k=>`${sx[k]||'ss.'+key(k)} IS json_extract(j.value,'$.scene.${k}')`));
 const pool=all(Object.keys(s.pool).map(k=>`p.${key(k)} IS json_extract(e.doc,'$.pool.${k}')`));
 return `(${q}) AND (${pool}) AND q.state='qualified' AND q.epoch=k.epoch AND q.expires_at>e.at
   AND ctl.slot=1 AND ctl.eligibility_sha256=e.policy AND ctl.qualification_authority_sha256=q.authority_sha256
   AND p.eligibility_sha256=e.policy AND p.valid_until>e.at AND a.deleted_at IS NULL AND a.id=q.account_id
   AND (SELECT COUNT(*) FROM json_each(e.doc,'$.rows') j JOIN locations x ON x.id=json_extract(j.value,'$.id')
     JOIN object_coverage v ON v.location_id=x.id LEFT JOIN published_index ip ON ip.location_id=x.id
     WHERE (${row}) AND v.validated_at<=e.at AND v.validated_at>e.at-86400)=json_array_length(e.doc,'$.rows')
   AND (SELECT COUNT(*) FROM json_each(e.doc,'$.scenes') j JOIN locations ss ON ss.id=json_extract(j.value,'$.scene.id')
     JOIN published_index sp ON sp.location_id=ss.id JOIN accounts sa ON sa.id=ss.contributor_id
     WHERE (${scene}) AND sa.deleted_at IS NULL)=json_array_length(e.doc,'$.scenes')`;
}
const joins=`JOIN object_qualification_requests q ON q.id=json_extract(e.doc,'$.qualification.id') JOIN accounts a ON a.id=q.account_id
 JOIN object_qualification_controls k ON k.account_id=q.account_id AND k.authority_sha256=q.authority_sha256 AND k.profile_id=q.profile_id
 JOIN qualified_object_policy ctl ON ctl.slot=1`;
const cte=`WITH e AS (SELECT json(?) AS doc,max(?,unixepoch()) AS at,? AS policy)`;
function reply(s){return {leaseId:s.pool.lease_id,expiresAt:s.request.expires_at,pace:s.request.pace,resumed:true,
 resourceBudget:'qualified-runtime',admissionMode:'qualified-device-v1',independentlyRecomputed:false,
 authority:{leaseId:s.pool.lease_id,profileId:s.pool.profile_id,policyId:s.pool.policy_id,
   assignmentSha256:s.pool.assignment_sha256,sourceSha256:s.pool.source_sha256},
 sourceTsv:s.pool.source_tsv,items:s.rows.map(r=>({locationId:r.id,assetId:r.asset_id,panoId:r.asset_id,capture:r.capture,
   lane:r.lane,model:r.model,generation:r.generation,lat:r.lat,lng:r.lon,heading:r.heading,pitch:r.pitch,zoom:r.zoom,
   country:r.country,cameraGeneration:'gen4',persistImagery:false,viewStrategy:'vision-pano-v1'})),accepted:0,unitsEarned:0};}

export async function requestQualifiedObjectWork(env,account,body,now=Math.floor(Date.now()/1000),timeout=20000){
 if(!id(account)||!body||Object.keys(body).sort().join(',')!=='count,pace,profileId,requestKey'||!id(body.requestKey)||!hex(body.profileId)
   ||!Number.isSafeInteger(body.count)||body.count<1||body.count>4||!['slow','medium','max'].includes(body.pace)
   ||!Number.isSafeInteger(now)||now<0||!Number.isSafeInteger(timeout)||timeout<1||timeout>20000)fail('invalid_object_work_request',400);
 const start=performance.now(),abort=new AbortController();let timer;
 const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{abort.abort();reject(Error());},timeout);});void deadline.catch(()=>{});
 const race=fn=>Promise.race([Promise.resolve().then(fn),deadline]),at=()=>now+Math.ceil((performance.now()-start)/1000);
 try{
   const policy=await race(()=>setup(env,account,now));
   await race(()=>env.DB.prepare("UPDATE leases SET state='expired' WHERE lane='object' AND state='active' AND expires_at<=?").bind(now).run());
   await race(()=>env.DB.prepare("UPDATE object_work_pool SET state='retired' WHERE state='available' AND valid_until<=?").bind(now).run());
   let request=await race(()=>requestFor(env,account,body.requestKey)),pool;
   if(request){
     pool=await race(()=>poolFor(env,request.lease_id));
     if(!pool||pool.profile_id!==body.profileId||request.requested_count!==body.count||request.pace!==body.pace)fail('object_work_request_conflict',409);
   }else{
     const choices=(await race(()=>env.DB.prepare(`SELECT * FROM object_work_pool WHERE profile_id=? AND state='available'
       AND valid_until>? AND json_array_length(records_json)<=? ORDER BY lease_id LIMIT 8`).bind(body.profileId,now,body.count).all())).results;
     let selected;
     for(const choice of choices){try{selected=await race(()=>snapshot(env,account,choice,at()));break;}
       catch(e){if(e instanceof ObjectDispatchError&&e.message==='object_work_inputs_changed')continue;throw e;}}
     if(!selected)fail('no_available_work',409);pool=selected.pool;
     const expires=Math.min(pool.valid_until,selected.qualification.expires_at,policy.validUntil,now+3600),g=guard(selected);
     const args=[JSON.stringify(selected),at(),selected.policySha256];
     const own=`EXISTS (SELECT 1 FROM object_work_requests WHERE account_id=? AND request_key=? AND lease_id=?)`;
     const statements=[env.DB.prepare(`${cte} INSERT INTO leases SELECT p.lease_id,a.id,'object',?,'active',1,?,NULL
       FROM e JOIN object_work_pool p ON p.lease_id=? ${joins} WHERE a.id=? AND (${g}) AND p.state='available' AND ?>e.at
       AND NOT EXISTS (SELECT 1 FROM leases WHERE account_id=a.id AND lane='object' AND state='active' AND expires_at>e.at)
       AND (SELECT COUNT(*) FROM object_work_requests r JOIN leases l ON l.id=r.lease_id WHERE l.state='active' AND r.state!='cancelled')
         +(SELECT COUNT(*) FROM qualified_object_candidates WHERE state='pending')<8`).bind(...args,expires,body.pace,pool.lease_id,account,expires),
       env.DB.prepare(`INSERT INTO object_work_requests SELECT ?,?,l.id,?,?,?,?,?,'preparing',NULL FROM leases l
         JOIN object_work_pool p ON p.lease_id=l.id WHERE l.id=? AND l.account_id=? AND l.state='active' AND p.state='available'`)
         .bind(account,body.requestKey,selected.qualification.id,now,expires,body.count,body.pace,pool.lease_id,account),
       env.DB.prepare(`INSERT INTO lease_items SELECT ?,json_extract(value,'$.id') FROM json_each(?) WHERE ${own}`)
         .bind(pool.lease_id,JSON.stringify(selected.rows),account,body.requestKey,pool.lease_id),
       env.DB.prepare(`UPDATE locations SET state='leased',active_lease=?,lease_until=?,generation=coalesce(generation,0)+1
         WHERE id IN (SELECT location_id FROM lease_items WHERE lease_id=?) AND ${own}`).bind(pool.lease_id,expires,pool.lease_id,account,body.requestKey,pool.lease_id),
       env.DB.prepare(`UPDATE object_work_pool SET state='claimed' WHERE lease_id=? AND ${own}`).bind(pool.lease_id,account,body.requestKey,pool.lease_id)];
     try{await race(()=>env.DB.batch(statements));}catch(error){
       request=await race(()=>requestFor(env,account,body.requestKey));if(!request)throw error;
     }
     request=await race(()=>requestFor(env,account,body.requestKey));if(!request)fail('object_work_conflict',409);
     pool=await race(()=>poolFor(env,request.lease_id));
   }
   if(request.state==='cancelled')fail('object_work_expired',409);
   const lease=await race(()=>env.DB.prepare('SELECT state FROM leases WHERE id=?').bind(pool.lease_id).first());
   if(lease?.state==='submitted')return {leaseId:pool.lease_id,alreadySubmitted:true,accepted:0,unitsEarned:0};
   const before=await race(()=>snapshot(env,account,pool,at(),request));
   if(request.state==='ready')return reply(before);
   const snapshotSha256=await race(()=>sha256Hex(encodeUtf8(JSON.stringify(before))));
   const challenge={version:1,accountId:account,leaseId:pool.lease_id,profileId:pool.profile_id,qualificationId:request.qualification_id,
     challenge:randomHex(16),assignmentSha256:pool.assignment_sha256,sourceSha256:pool.source_sha256,snapshotSha256,
     policyId:policy.policyId,policySha256:before.policySha256,qualificationPolicySha256:policy.qualificationPolicySha256};
   const pending=Promise.resolve().then(()=>env.OBJECT_ELIGIBILITY.fetch(new Request('https://object-eligibility.internal/object-eligibility/evidence',
     {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(challenge),signal:abort.signal}))).then(r=>{
       if(abort.signal.aborted){if(r.body)void r.body.cancel().catch(()=>{});throw Error();}return r;});
   const response=await race(()=>pending);if(response.status!==200){if(response.body)void response.body.cancel().catch(()=>{});fail();}
   const proof=validateObjectProtectionEvidence(await race(()=>readVerifierJson(response,Math.min(10000,Math.max(1,Math.floor(timeout-(performance.now()-start)))))),challenge,policy,before.rows,at());
   const after=await race(async()=>snapshot(env,account,await poolFor(env,pool.lease_id),at(),await requestFor(env,account,body.requestKey)));
   if(!same(before,after)||!same(policy,await race(()=>qualifiedObjectEligibilityPolicy(env,at()))))fail('object_work_changed',409);
   const proofSha=await race(()=>sha256Hex(encodeUtf8(JSON.stringify(proof))));
   await race(()=>env.DB.prepare(`${cte} UPDATE object_work_requests SET state='ready',proof_sha256=? WHERE account_id=? AND request_key=?
     AND state='preparing' AND EXISTS (SELECT 1 FROM e JOIN object_work_pool p ON p.lease_id=object_work_requests.lease_id ${joins}
       JOIN leases l ON l.id=p.lease_id AND l.account_id=a.id WHERE a.id=object_work_requests.account_id AND (${guard(after)})
       AND l.state='active' AND l.expires_at>e.at AND l.expires_at=object_work_requests.expires_at
       AND l.generation=json_extract(e.doc,'$.lease.generation') AND ?>e.at
       AND (SELECT COUNT(*) FROM lease_items WHERE lease_id=l.id)=json_array_length(e.doc,'$.rows'))`)
     .bind(JSON.stringify(after),at(),after.policySha256,proofSha,account,body.requestKey,proof.expiresAt).run());
   const saved=await race(()=>requestFor(env,account,body.requestKey));if(saved?.state!=='ready')fail('object_work_changed',409);
   return reply({...after,request:saved});
 }catch(e){if(e instanceof ObjectDispatchError)throw e;fail();}finally{clearTimeout(timer);abort.abort();}
}

export async function cancelQualifiedObjectWork(env,account,requestKey,now=Math.floor(Date.now()/1000)){
 if(!id(account)||!id(requestKey)||!Number.isSafeInteger(now)||now<0)fail('invalid_object_work_request',400);
 if((await env.DB.prepare('SELECT contract FROM object_work_revision WHERE slot=1').first())?.contract!==OBJECT_WORK_CONTRACT)fail();
 if(!await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first())fail('account_not_active',401);
 const r=await requestFor(env,account,requestKey);if(!r)fail('object_work_not_found',404);
 const l=await env.DB.prepare('SELECT state FROM leases WHERE id=?').bind(r.lease_id).first();
 if(l?.state==='submitted')return {alreadySubmitted:true,cancelled:false,leaseId:r.lease_id};
 await env.DB.prepare("UPDATE leases SET state='expired' WHERE id=? AND account_id=? AND state='active'").bind(r.lease_id,account).run();
 return {cancelled:true,leaseId:r.lease_id};
}
