// Trusted coordinator only. Every batch is independently compared; this does
// not grant a reusable device qualification or open public Object admission.
import {checkObjectSettlement} from './objectSettlementCheck.js';
import {ObjectDispatchError} from './objectAuditDispatch.js';
import {objectSettlementEvidence} from '../native-object-verifier-bridge/worker.js';
import {writeObjectArtifact} from './artifactWrites.js';
import {readVerifierJson} from './scenePipeline.js';
import {sha256Hex,encodeUtf8,randomHex,UNITS} from './model.js';
const ID=/^[a-f0-9]{32}$/,HEX=/^[a-f0-9]{64}$/;
const CONTRACT='private-object-settlement-v1-20261012';
const fail=(code='object_settlement_unavailable',status=503)=>{throw new ObjectDispatchError(code,status);};
export const OBJECT_SETTLEMENT_SCHEMA=[
  `CREATE TABLE IF NOT EXISTS object_settlement_revision (slot INTEGER PRIMARY KEY CHECK(slot=1),contract TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS object_acceptances (
    lease_id TEXT PRIMARY KEY REFERENCES object_audit_candidates(lease_id),account_id TEXT NOT NULL REFERENCES accounts(id),
    operation_token TEXT NOT NULL UNIQUE,location_count INTEGER NOT NULL CHECK(location_count BETWEEN 1 AND 4),
    units INTEGER NOT NULL CHECK(units=location_count*10),accepted_at INTEGER NOT NULL,
    profile_id TEXT NOT NULL,policy_id TEXT NOT NULL,policy_sha256 TEXT NOT NULL,runtime_sha256 TEXT NOT NULL,
    quality_sha256 TEXT NOT NULL,protected_sha256 TEXT NOT NULL,origin_sha256 TEXT NOT NULL,
    assignment_sha256 TEXT NOT NULL,source_sha256 TEXT NOT NULL,submission_sha256 TEXT NOT NULL,
    candidate_sha256 TEXT NOT NULL,job_id TEXT NOT NULL,attempt INTEGER NOT NULL,receipt_sha256 TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,artifacts_sha256 TEXT NOT NULL)`,
  `CREATE TRIGGER IF NOT EXISTS object_acceptance_immutable BEFORE UPDATE ON object_acceptances
    BEGIN SELECT RAISE(ABORT,'object_acceptance_immutable'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_acceptance_retained BEFORE DELETE ON object_acceptances
    BEGIN SELECT RAISE(ABORT,'object_acceptance_retained'); END`,
  `CREATE TRIGGER IF NOT EXISTS object_acceptance_active BEFORE INSERT ON object_acceptances
    WHEN NOT EXISTS (SELECT 1 FROM accounts a JOIN leases l ON l.account_id=a.id
      JOIN object_audit_candidates c ON c.lease_id=l.id AND c.account_id=a.id
      WHERE a.id=NEW.account_id AND a.deleted_at IS NULL AND l.id=NEW.lease_id AND l.state='submitted'
      AND c.state='pending' AND c.native_state='approved' AND c.claim_token IS NULL AND c.claim_until=0
      AND c.receipt_sha256=NEW.receipt_sha256 AND c.native_attempts=NEW.attempt)
    BEGIN SELECT RAISE(ABORT,'object_acceptance_authority_lost'); END`,
];
const normalized=sql=>sql.replace(/IF NOT EXISTS/ig,'').replace(/[\s;]/g,'').toLowerCase();
const quote=v=>"'"+v.replaceAll("'","''")+"'";
const stored="lower(replace(replace(replace(replace(replace(replace(replace(sql,'IF NOT EXISTS',''),'if not exists',''),' ',''),char(10),''),char(13),''),char(9),''),';',''))";
const checks=OBJECT_SETTLEMENT_SCHEMA.map(sql=>{
  const [,kind,name]=sql.match(/^CREATE (TABLE|TRIGGER) IF NOT EXISTS (\w+)/);
  return `EXISTS (SELECT 1 FROM sqlite_master WHERE type=${quote(kind.toLowerCase())} AND name=${quote(name)}
    AND ${stored}=${quote(normalized(sql))})`;
}).join(' AND ');
export const OBJECT_SETTLEMENT_CONTRACT_SQL=`INSERT INTO object_settlement_revision
  SELECT 1,CASE WHEN (${checks}) AND EXISTS (SELECT 1 FROM object_dispatch_revision
    WHERE slot=1 AND contract='private-object-dispatch-v1-20261011') THEN '${CONTRACT}' ELSE NULL END
  ON CONFLICT(slot) DO UPDATE SET contract=CASE WHEN contract=excluded.contract THEN contract ELSE NULL END`;

function policy(env) {
  let p;try {p=JSON.parse(env.OBJECT_SETTLEMENT_POLICY);}catch{fail('object_settlement_policy_required');}
  const keys=['version','scope','policyId','policySha256','runtimeProfileSha256','qualityImplementationIdentity',
    'protectedAuthoritySha256','protectedOriginHandoffSha256','profiles','resource'];
  const resources=[{accountId:'272760294910ef0b246980278aeb36e2',databaseId:'ed4705fa-1190-41fa-86a0-02d755db1b2a',bucket:'vision-community'},
    {accountId:'272760294910ef0b246980278aeb36e2',databaseId:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',bucket:'vision-community-staging'}];
  if(!p || Object.keys(p).sort().join(',')!==keys.sort().join(',') || p.version!==1 || p.scope!=='object-batch-parity-v1'
      || typeof p.policyId!=='string' || !/^[A-Za-z0-9_.-]{1,128}$/.test(p.policyId)
      || !keys.filter(k=>k.endsWith('Sha256') || k==='qualityImplementationIdentity').every(k=>typeof p[k]==='string' && HEX.test(p[k]))
      || !Array.isArray(p.profiles) || p.profiles.length<1 || p.profiles.length>16
      || new Set(p.profiles).size!==p.profiles.length || !p.profiles.every(v=>typeof v==='string' && HEX.test(v))
      || !p.resource || Object.keys(p.resource).sort().join(',')!=='accountId,bucket,databaseId'
      || !resources.some(r=>Object.keys(r).every(k=>r[k]===p.resource[k]))
      || env.INDEX_BUCKET_NAME!==p.resource.bucket
      || p.policyId.startsWith('staging.') && p.resource.bucket!=='vision-community-staging') fail('object_settlement_policy_required');
  return p;
}

async function saved(env,account,lease) {
  const active=await env.DB.prepare('SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first();
  if(!active) fail('account_not_active',401);
  const row=await env.DB.prepare('SELECT * FROM object_acceptances WHERE lease_id=? AND account_id=?').bind(lease,account).first();
  if(!row)return null;
  const proof=await env.DB.prepare(`SELECT (SELECT units FROM ledger WHERE reference=? AND account_id=? AND reason='verified_work') AS units,
    (SELECT COUNT(*) FROM lease_items i JOIN locations l ON l.id=i.location_id JOIN published_index p ON p.location_id=l.id
      WHERE i.lease_id=? AND l.state='published' AND l.contributor_id=? AND p.object_index_key=?) AS n`).bind(
    `lease:${lease}`,account,lease,account,`object-index-v4/${lease}/`).first();
  if(proof?.units!==row.units || proof.n!==row.location_count)fail('object_settlement_reconciliation_required');
  return {submissionId:lease,accepted:row.location_count,unitsEarned:0,replayed:true,pendingAudit:false,
    auditState:'published',qualificationScope:'batch-only'};
}

// SQL identifiers come only from a selected database row, never request JSON.
// The final transaction compares every captured value, not a checksum-as-lock.
function exactSnapshot(snapshot) {
  const extra={deleted_at:'a.deleted_at',lease_lane:'l.lane',lease_state:'l.state',lease_expires:'l.expires_at',
    artifact_owner:'w.account_id',artifact_lease:'w.lease_id',artifact_sha256:'w.sha256',artifact_bytes:'w.bytes'};
  const field=(key,prefix)=>{if(!/^[a-z_][a-z_0-9]*$/.test(key))fail();return `${prefix}.${key}`;};
  const candidate=Object.keys(snapshot.row).map(k=>`${extra[k]||field(k,'c')} IS json_extract(e.document,'$.row.${k}')`).join(' AND ');
  const joined={validator:'v.validator',evidence_sha256:'v.evidence_sha256',validated_at:'v.validated_at',published_id:'p.location_id'};
  const locations=Object.keys(snapshot.rows[0]).map(k=>`${joined[k]||field(k,'x')} IS json_extract(j.value,'$.${k}')`).join(' AND ');
  return {candidate,locations};
}

export async function settleObjectAudit(env,account,lease,now=Math.floor(Date.now()/1000),timeoutMs=20000) {
  if(typeof account!=='string' || !ID.test(account) || typeof lease!=='string' || !ID.test(lease)
      || !Number.isSafeInteger(now) || now<0 || now>Number.MAX_SAFE_INTEGER-86400
      || !Number.isSafeInteger(timeoutMs) || timeoutMs<1 || timeoutMs>20000) fail('invalid_object_settlement',400);
  const started=performance.now(),abort=new AbortController();let timer;
  const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{abort.abort();reject(Error('settlement_timeout'));},timeoutMs);});
  void deadline.catch(()=>{});
  const race=action=>Promise.race([Promise.resolve().then(action),deadline]);
  const current=()=>now+Math.ceil((performance.now()-started)/1000);
  const budget=()=>{const n=Math.floor(timeoutMs-(performance.now()-started));if(n<1)fail();return n;};
  try {
    try {if((await race(()=>env.DB.prepare('SELECT contract FROM object_settlement_revision WHERE slot=1').first()))?.contract!==CONTRACT)throw Error();}
    catch{fail('object_settlement_setup_required');}
    const prior=await race(()=>saved(env,account,lease));if(prior)return prior;
    const configured=policy(env);
    const initial=await checkObjectSettlement(env,account,lease,now,budget());
    const row=initial.databaseSnapshot.row,quality=initial.publicManifest.viewQuality;
    if(row.policy_id!==configured.policyId || !configured.profiles.includes(row.profile_id)
        || quality.implementationIdentity!==configured.qualityImplementationIdentity
        || quality.protectedAuthorityManifestSha256!==configured.protectedAuthoritySha256)fail('object_settlement_policy_mismatch');
    const prefix=`object-index-v4/${lease}/`,artifacts=[];
    for(const [name,bytes] of [['manifest.json',encodeUtf8(JSON.stringify(initial.publicManifest))],
        ['locations.tsv',initial.source],...Object.entries(initial.files).sort(([a],[b])=>a.localeCompare(b))]) {
      const key=prefix+name,sha256=await race(()=>writeObjectArtifact(env,account,lease,key,bytes,current()));
      artifacts.push({key,sha256,bytes:bytes.length});
    }
    const checked=await checkObjectSettlement(env,account,lease,current(),budget());
    if(checked.evidenceSha256!==initial.evidenceSha256)fail('object_settlement_changed',409);
    const transfer=Promise.resolve().then(()=>env.OBJECT_VERIFIER.fetch(new Request(
      `https://object-verifier.internal/object-audits/${row.job_id}/settlement-evidence`,{
        method:'POST',headers:{'content-type':'application/json'},body:'{}',signal:abort.signal}))).then(response=>{
          if(abort.signal.aborted){if(response.body)void response.body.cancel().catch(()=>{});throw Error('late_settlement_evidence');}
          return response;
        });
    const response=await race(()=>transfer);
    if(response.status!==200){if(response.body)void response.body.cancel().catch(()=>{});fail();}
    const full=objectSettlementEvidence(await race(()=>readVerifierJson(response,Math.min(10000,budget()))),checked.receipt,current());
    if(['policySha256','runtimeProfileSha256','qualityImplementationIdentity','protectedAuthoritySha256',
        'protectedOriginHandoffSha256'].some(k=>full[k]!==configured[k])
        || Object.keys(configured.resource).some(k=>full.resource[k]!==configured.resource[k]))fail('object_settlement_policy_mismatch');
    if(performance.now()-started>=timeoutMs || full.expiresAt<=current())fail();
    const at=current(),token=randomHex(16),units=checked.records.length*UNITS.object;
    const snapshot=JSON.stringify(checked.databaseSnapshot),files=JSON.stringify(artifacts),match=exactSnapshot(checked.databaseSnapshot);
    const artifactsSha=await race(()=>sha256Hex(encodeUtf8(files)));
    const insert=env.DB.prepare(`WITH e AS (SELECT json(?) AS document),files AS (SELECT value FROM json_each(?))
      INSERT INTO object_acceptances
      SELECT c.lease_id,c.account_id,?,?,?, ?,c.profile_id,c.policy_id,?,?,?,?,?,c.assignment_sha256,c.source_sha256,
        c.submission_sha256,c.candidate_manifest_sha256,c.job_id,c.native_attempts,c.receipt_sha256,?,?
      FROM object_audit_candidates c JOIN accounts a ON a.id=c.account_id
      JOIN leases l ON l.id=c.lease_id AND l.account_id=c.account_id
      JOIN account_artifact_writes w ON w.artifact_key=c.artifact_key CROSS JOIN e
      WHERE c.account_id=? AND c.lease_id=? AND (${match.candidate}) AND a.deleted_at IS NULL
        AND l.expires_at>max(?,unixepoch()) AND ?>max(?,unixepoch()) AND NOT EXISTS (SELECT 1 FROM ledger WHERE reference=?)
        AND (SELECT COUNT(*) FROM lease_items WHERE lease_id=c.lease_id)=c.location_count
        AND (SELECT COUNT(*) FROM lease_items i JOIN locations x ON x.id=i.location_id
          JOIN object_coverage v ON v.location_id=x.id LEFT JOIN published_index p ON p.location_id=x.id
          JOIN json_each(e.document,'$.rows') j ON x.id=json_extract(j.value,'$.id')
          WHERE i.lease_id=c.lease_id AND (${match.locations}) AND v.validated_at<=max(?,unixepoch())
            AND v.validated_at>max(?,unixepoch()-86400))=c.location_count
        AND (SELECT COUNT(*) FROM files JOIN account_artifact_writes f ON f.artifact_key=json_extract(files.value,'$.key')
          WHERE f.account_id=c.account_id AND f.lease_id=c.lease_id AND f.sha256=json_extract(files.value,'$.sha256')
            AND f.bytes=json_extract(files.value,'$.bytes'))=?
      ON CONFLICT(lease_id) DO NOTHING`).bind(snapshot,files,token,checked.records.length,units,at,
        full.policySha256,full.runtimeProfileSha256,full.qualityImplementationIdentity,full.protectedAuthoritySha256,
        full.protectedOriginHandoffSha256,checked.evidenceSha256,artifactsSha,account,lease,at,full.expiresAt,at,`lease:${lease}`,at,at-86400,artifacts.length);
    const own=`EXISTS (SELECT 1 FROM object_acceptances WHERE lease_id=? AND account_id=? AND operation_token=?)`;
    const statements=[insert,
      env.DB.prepare(`INSERT INTO ledger(account_id,units,reason,reference) SELECT ?,?,'verified_work',? WHERE ${own}`)
        .bind(account,units,`lease:${lease}`,lease,account,token),
      env.DB.prepare(`UPDATE accounts SET units=units+? WHERE id=? AND deleted_at IS NULL AND ${own}`).bind(units,account,lease,account,token)];
    for(const record of checked.records) {
      statements.push(env.DB.prepare(`UPDATE locations SET state='published',queue_state='published',active_lease=NULL,
        lease_until=NULL,output_sha256=?,contributor_id=? WHERE id=? AND ${own}`)
        .bind(record.outputSha256,account,record.locationId,lease,account,token));
      statements.push(env.DB.prepare(`INSERT INTO published_index(location_id,index_text,output_sha256,published_at,embedding,
        object_index_sha256,object_index_key) SELECT ?,'',?,?,NULL,?,? WHERE ${own}`)
        .bind(record.locationId,record.outputSha256,at,row.source_sha256,prefix,lease,account,token));
    }
    // A lost database reply is safe: the immutable acceptance plus unique lease
    // ledger reference is the durable acknowledgement on the next invocation.
    const result=await race(()=>env.DB.batch(statements));
    const receipt=await race(()=>saved(env,account,lease));
    if(!receipt)fail('object_settlement_changed',409);
    return {...receipt,unitsEarned:result[0].meta?.changes===1?units:0,replayed:result[0].meta?.changes!==1};
  } catch(error) {if(error instanceof ObjectDispatchError)throw error;fail();}
  finally {clearTimeout(timer);abort.abort();}
}
