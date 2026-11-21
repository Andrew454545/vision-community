// Separate qualified-device admission. No native approval is minted or consumed.
import {QUALIFIED_OBJECT_CONTRACT} from './qualifiedObjectSchema.js';
import {inspectQualifiedPreparedUpload,inspectQualifiedObjectCandidateEligibility,qualifiedObjectEligibilityPolicy} from './qualifiedObjectEligibility.js';
import {qualifiedObjectGuard,QUALIFIED_OBJECT_JOINS} from './qualifiedObjectGuard.js';
import {writeObjectArtifact} from './artifactWrites.js';
import {ObjectDispatchError} from './objectAuditDispatch.js';
import {encodeUtf8,sha256Hex,randomHex,UNITS} from './model.js';
const ID=/^[a-f0-9]{32}$/,HEX=/^[a-f0-9]{64}$/;
const fail=(code='qualified_object_unavailable',status=503)=>{throw new ObjectDispatchError(code,status);};
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===[...keys].sort().join(',');
function identity(account,lease,now,timeout){
  if(typeof account!=='string'||!ID.test(account)||typeof lease!=='string'||!ID.test(lease)
    ||!Number.isSafeInteger(now)||now<0||now>Number.MAX_SAFE_INTEGER-86400||!Number.isSafeInteger(timeout)||timeout<1||timeout>20000)
    fail('invalid_qualified_object_request',400);
}
async function ready(env) {
  if((await env.DB.prepare('SELECT contract FROM qualified_object_revision WHERE slot=1').first())?.contract!==QUALIFIED_OBJECT_CONTRACT)
    fail('qualified_object_setup_required');
}
async function active(env,account) {
  if(!await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first())fail('account_not_active',401);
}
const rowFor=(env,account,lease)=>env.DB.prepare('SELECT * FROM qualified_object_candidates WHERE account_id=? AND lease_id=?').bind(account,lease).first();

export async function savedQualifiedObjectAcceptance(env,account,lease) {
  await active(env,account);
  const row=await env.DB.prepare('SELECT * FROM qualified_object_acceptances WHERE account_id=? AND lease_id=?').bind(account,lease).first();
  if(!row)return null;
  const proof=await env.DB.prepare(`SELECT (SELECT units FROM ledger WHERE account_id=? AND reference=? AND reason='qualified_device_work') AS units,
    (SELECT COUNT(*) FROM lease_items i JOIN locations x ON x.id=i.location_id JOIN published_index p ON p.location_id=x.id
      WHERE i.lease_id=? AND x.state='published' AND x.contributor_id=? AND p.object_index_key=?) AS n,
    (SELECT state FROM qualified_object_candidates WHERE lease_id=?) AS state`).bind(account,`lease:${lease}`,lease,account,
      `object-index-v4/${lease}/`,lease).first();
  if(proof?.units!==row.units||proof.n!==row.location_count||proof.state!=='published')fail('qualified_object_reconciliation_required');
  return {submissionId:lease,accepted:row.location_count,unitsEarned:0,replayed:true,pendingAudit:false,
    admissionMode:'qualified-device-v1',verification:'qualified-profile-and-upload-integrity',independentlyRecomputed:false};
}

function bounded(now,timeout) {
  const start=performance.now();let timer;
  const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('qualified_object_timeout')),timeout);});
  void deadline.catch(()=>{});
  return {race:action=>Promise.race([Promise.resolve().then(action),deadline]),at:()=>now+Math.ceil((performance.now()-start)/1000),
    budget:()=>{const n=Math.floor(timeout-(performance.now()-start));if(n<1)fail();return n;},close:()=>clearTimeout(timer)};
}
async function checkedPolicy(env,checked,at) {
  const p=await qualifiedObjectEligibilityPolicy(env,at);
  if(checked.eligibilityPolicySha256!==env.OBJECT_ELIGIBILITY_POLICY_SHA256||p.policyId!==checked.databaseSnapshot.row.policy_id)fail();
  return p;
}

export async function stageQualifiedObjectUpload(env,account,authority,index,now=Math.floor(Date.now()/1000),timeout=20000) {
  const lease=authority?.leaseId;identity(account,lease,now,timeout);
  if(!exact(authority,['leaseId','profileId','policyId','assignmentSha256','sourceSha256'])
    ||!['profileId','assignmentSha256','sourceSha256'].every(k=>typeof authority[k]==='string'&&HEX.test(authority[k]))
    ||typeof authority.policyId!=='string'||!/^[A-Za-z0-9_.-]{1,128}$/.test(authority.policyId))fail('invalid_qualified_object_authority',400);
  const b=bounded(now,timeout);
  try {
    await b.race(()=>ready(env));await b.race(()=>active(env,account));
    const payload=encodeUtf8(JSON.stringify(index));if(payload.length>4193280)fail('invalid_qualified_object_upload',400);
    const submission=await b.race(()=>sha256Hex(payload)),old=await b.race(()=>rowFor(env,account,lease));
    if(old){
      if(old.profile_id!==authority.profileId||old.policy_id!==authority.policyId||old.assignment_sha256!==authority.assignmentSha256
        ||old.source_sha256!==authority.sourceSha256||old.submission_sha256!==submission)fail('qualified_object_submission_conflict',409);
      if(old.state==='published')return await b.race(()=>savedQualifiedObjectAcceptance(env,account,lease));
      if(old.state!=='pending')fail('qualified_object_cancelled',409);
      return {submissionId:lease,accepted:0,unitsEarned:0,pending:true,replayed:true,admissionMode:'qualified-device-v1'};
    }
    const initial=await inspectQualifiedPreparedUpload(env,account,authority,index,now,now,b.budget());
    const r=initial.databaseSnapshot.row;
    await b.race(()=>writeObjectArtifact(env,account,lease,r.artifact_key,payload,b.at()));
    const checked=await inspectQualifiedPreparedUpload(env,account,authority,index,now,b.at(),b.budget());
    if(checked.eligibilitySha256!==initial.eligibilitySha256)fail('qualified_object_changed',409);
    const p=await b.race(()=>checkedPolicy(env,checked,b.at())),at=b.at();
    const cte=`WITH e AS (SELECT json(?) AS doc,max(?,unixepoch()) AS at,? AS policy)`;
    const guard=qualifiedObjectGuard(checked.eligibilitySnapshot,true);
    const statements=[env.DB.prepare(`${cte} INSERT INTO qualified_object_candidates
      SELECT l.id,a.id,q.id,e.policy,?,?,?,?,?,?,?,?,?,'pending'
      FROM e JOIN leases l ON l.id=? JOIN accounts a ON a.id=l.account_id ${QUALIFIED_OBJECT_JOINS}
      WHERE a.id=? AND (${guard}) AND ?>e.at AND ?>e.at
        AND NOT EXISTS (SELECT 1 FROM ledger WHERE reference=?)
        AND EXISTS (SELECT 1 FROM account_artifact_writes w WHERE w.artifact_key=? AND w.account_id=a.id AND w.lease_id=l.id
          AND w.sha256=? AND w.bytes=?) ON CONFLICT(lease_id) DO NOTHING`).bind(
        JSON.stringify(checked.eligibilitySnapshot),at,checked.eligibilityPolicySha256,r.profile_id,r.policy_id,r.assignment_sha256,
        r.source_sha256,r.submission_sha256,r.artifact_key,r.payload_bytes,r.location_count,now,lease,account,
        checked.protection.expiresAt,p.validUntil,`lease:${lease}`,r.artifact_key,r.submission_sha256,r.payload_bytes),
      env.DB.prepare(`UPDATE locations SET state='pending',queue_state='quarantined',lease_until=NULL WHERE active_lease=?
        AND EXISTS (SELECT 1 FROM qualified_object_candidates WHERE lease_id=? AND state='pending')`).bind(lease,lease),
      env.DB.prepare(`UPDATE leases SET state='submitted' WHERE id=? AND EXISTS
        (SELECT 1 FROM qualified_object_candidates WHERE lease_id=? AND state='pending')`).bind(lease,lease)];
    await b.race(()=>env.DB.batch(statements));
    const saved=await b.race(()=>rowFor(env,account,lease));
    if(!saved||saved.submission_sha256!==submission||saved.qualification_id!==checked.qualificationId)fail('qualified_object_changed',409);
    return {submissionId:lease,accepted:0,unitsEarned:0,pending:true,replayed:false,admissionMode:'qualified-device-v1'};
  }catch(error){if(error instanceof ObjectDispatchError)throw error;fail();}finally{b.close();}
}

export async function settleQualifiedObjectUpload(env,account,lease,now=Math.floor(Date.now()/1000),timeout=20000) {
  identity(account,lease,now,timeout);const b=bounded(now,timeout);
  try {
    await b.race(()=>ready(env));const saved=await b.race(()=>savedQualifiedObjectAcceptance(env,account,lease));if(saved)return saved;
    const initial=await inspectQualifiedObjectCandidateEligibility(env,account,lease,now,b.budget());
    const r=initial.databaseSnapshot.row,prefix=`object-index-v4/${lease}/`,artifacts=[];
    for(const [name,bytes] of [['manifest.json',encodeUtf8(JSON.stringify(initial.publicManifest))],['locations.tsv',initial.source],
      ...Object.entries(initial.files).sort(([a],[c])=>a.localeCompare(c))]){
      const key=prefix+name,sha256=await b.race(()=>writeObjectArtifact(env,account,lease,key,bytes,b.at()));
      artifacts.push({key,sha256,bytes:bytes.length});
    }
    const checked=await inspectQualifiedObjectCandidateEligibility(env,account,lease,b.at(),b.budget());
    if(checked.eligibilitySha256!==initial.eligibilitySha256)fail('qualified_object_changed',409);
    const p=await b.race(()=>checkedPolicy(env,checked,b.at())),at=b.at(),token=randomHex(16),units=r.location_count*UNITS.object;
    if(r.eligibility_policy_sha256!==checked.eligibilityPolicySha256)fail();
    const files=JSON.stringify(artifacts),artifactsSha=await b.race(()=>sha256Hex(encodeUtf8(files)));
    const protectionSha=await b.race(()=>sha256Hex(encodeUtf8(JSON.stringify(checked.protection))));
    const guard=qualifiedObjectGuard(checked.eligibilitySnapshot);
    const insert=env.DB.prepare(`WITH e AS (SELECT json(?) AS doc,max(?,unixepoch()) AS at,? AS policy),files AS (SELECT value FROM json_each(?))
      INSERT INTO qualified_object_acceptances SELECT c.lease_id,c.account_id,?,?,?,e.at,q.id,q.authority_sha256,e.policy,?,?,?,?,?,
        c.assignment_sha256,c.source_sha256,c.submission_sha256,?,?,?
      FROM e JOIN qualified_object_candidates c ON c.lease_id=? JOIN accounts a ON a.id=c.account_id
      JOIN leases l ON l.id=c.lease_id AND l.account_id=c.account_id JOIN account_artifact_writes w ON w.artifact_key=c.artifact_key
      ${QUALIFIED_OBJECT_JOINS} WHERE a.id=? AND c.state='pending' AND (${guard}) AND ?>e.at AND ?>e.at
        AND NOT EXISTS (SELECT 1 FROM ledger WHERE reference=?)
        AND (SELECT COUNT(*) FROM files JOIN account_artifact_writes f ON f.artifact_key=json_extract(files.value,'$.key')
          WHERE f.account_id=a.id AND f.lease_id=l.id AND f.sha256=json_extract(files.value,'$.sha256')
            AND f.bytes=json_extract(files.value,'$.bytes'))=? ON CONFLICT(lease_id) DO NOTHING`).bind(
      JSON.stringify(checked.eligibilitySnapshot),at,checked.eligibilityPolicySha256,files,token,r.location_count,units,
      p.qualificationPolicySha256,p.protectedPolicySha256,p.qualityImplementationIdentity,p.protectedAuthoritySha256,p.protectedOriginHandoffSha256,
      checked.eligibilitySha256,protectionSha,artifactsSha,lease,account,checked.protection.expiresAt,p.validUntil,`lease:${lease}`,artifacts.length);
    const own=`EXISTS (SELECT 1 FROM qualified_object_acceptances WHERE lease_id=? AND account_id=? AND operation_token=?)`;
    const statements=[insert,
      env.DB.prepare(`INSERT INTO ledger(account_id,units,reason,reference) SELECT ?,?,'qualified_device_work',? WHERE ${own}`)
        .bind(account,units,`lease:${lease}`,lease,account,token),
      env.DB.prepare(`UPDATE accounts SET units=units+? WHERE id=? AND deleted_at IS NULL AND ${own}`).bind(units,account,lease,account,token)];
    for(const record of checked.records){
      statements.push(env.DB.prepare(`UPDATE locations SET state='published',queue_state='published',active_lease=NULL,lease_until=NULL,
        output_sha256=?,contributor_id=? WHERE id=? AND ${own}`).bind(record.outputSha256,account,record.locationId,lease,account,token));
      statements.push(env.DB.prepare(`INSERT INTO published_index(location_id,index_text,output_sha256,published_at,embedding,object_index_sha256,object_index_key)
        SELECT ?,'',?,?,NULL,?,? WHERE ${own}`).bind(record.locationId,record.outputSha256,at,r.source_sha256,prefix,lease,account,token));
    }
    statements.push(env.DB.prepare(`UPDATE qualified_object_candidates SET state='published' WHERE lease_id=? AND ${own}`).bind(lease,lease,account,token));
    const result=await b.race(()=>env.DB.batch(statements)),ack=await b.race(()=>savedQualifiedObjectAcceptance(env,account,lease));
    if(!ack)fail('qualified_object_changed',409);
    return {...ack,unitsEarned:result[0].meta.changes===1?units:0,replayed:result[0].meta.changes!==1};
  }catch(error){if(error instanceof ObjectDispatchError)throw error;fail();}finally{b.close();}
}
