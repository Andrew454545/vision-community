// Optional private cleanup outbox. A durable native acknowledgement transfers
// cleanup ownership; it neither approves output nor changes publication/credit.
import {objectRetirementProof,OBJECT_SETTLEMENT_CONTRACT} from './objectSettlement.js';
import {objectAuditResult} from '../native-object-verifier-bridge/worker.js';
import {readVerifierJson} from './scenePipeline.js';
import {sha256Hex,encodeUtf8} from './model.js';
export const OBJECT_RETENTION_CONTRACT='private-object-retention-v1-20261012';
export const OBJECT_RETENTION_SCHEMA=[
  `CREATE TABLE IF NOT EXISTS object_retention_revision (slot INTEGER PRIMARY KEY CHECK(slot=1),contract TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS object_audit_retirements (
    lease_id TEXT PRIMARY KEY REFERENCES object_acceptances(lease_id),request_sha256 TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','delivered','privacy')),
    failures INTEGER NOT NULL DEFAULT 0 CHECK(failures BETWEEN 0 AND 16),
    next_attempt INTEGER NOT NULL DEFAULT 0,delivered_at INTEGER)`,
  `CREATE TRIGGER IF NOT EXISTS object_retirement_immutable BEFORE UPDATE ON object_audit_retirements
    WHEN NEW.lease_id IS NOT OLD.lease_id OR NEW.request_sha256 IS NOT OLD.request_sha256
      OR (OLD.state!='pending' AND NEW.state!=OLD.state)
    BEGIN SELECT RAISE(ABORT,'object_retirement_immutable'); END`,
];
const normalized=sql=>sql.replace(/IF NOT EXISTS/ig,'').replace(/[\s;]/g,'').toLowerCase();
const quote=v=>"'"+v.replaceAll("'","''")+"'";
const stored="lower(replace(replace(replace(replace(replace(replace(replace(sql,'IF NOT EXISTS',''),'if not exists',''),' ',''),char(10),''),char(13),''),char(9),''),';',''))";
const checks=OBJECT_RETENTION_SCHEMA.map(sql=>{
  const [,kind,name]=sql.match(/^CREATE (TABLE|TRIGGER) IF NOT EXISTS (\w+)/);
  return `EXISTS (SELECT 1 FROM sqlite_master WHERE type=${quote(kind.toLowerCase())} AND name=${quote(name)}
    AND ${stored}=${quote(normalized(sql))})`;
}).join(' AND ');
export const OBJECT_RETENTION_CONTRACT_SQL=`INSERT INTO object_retention_revision
  SELECT 1,CASE WHEN (${checks}) AND EXISTS (SELECT 1 FROM object_settlement_revision
    WHERE slot=1 AND contract='${OBJECT_SETTLEMENT_CONTRACT}') THEN '${OBJECT_RETENTION_CONTRACT}' ELSE NULL END
  ON CONFLICT(slot) DO UPDATE SET contract=CASE WHEN contract=excluded.contract THEN contract ELSE NULL END`;

export async function retireAcceptedObjectAudits(env,{account=null,lease=null,limit=2,
  now=Math.floor(Date.now()/1000),timeoutMs=5000}={}) {
  const result={delivered:0,pending:0,setupRequired:false};
  if(!env.OBJECT_VERIFIER || !env.DB)return result;
  if(!Number.isSafeInteger(limit) || limit<1 || limit>2 || !Number.isSafeInteger(now) || now<0
      || now>Number.MAX_SAFE_INTEGER-3600 || !Number.isSafeInteger(timeoutMs) || timeoutMs<1 || timeoutMs>5000
      || (account===null)!==(lease===null) || account!==null && ![account,lease].every(v=>typeof v==='string' && /^[a-f0-9]{32}$/.test(v))) {
    throw Error('invalid_object_retirement');
  }
  const abort=new AbortController(),started=performance.now();let timer;
  const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{abort.abort();reject(Error('retirement_timeout'));},timeoutMs);});
  void deadline.catch(()=>{});
  const race=fn=>Promise.race([Promise.resolve().then(fn),deadline]);
  try {
    let revision;
    try {revision=await race(()=>env.DB.prepare('SELECT contract FROM object_retention_revision WHERE slot=1').first());}
    catch {result.setupRequired=true;return result;}
    if(revision?.contract!==OBJECT_RETENTION_CONTRACT){result.setupRequired=true;return result;}
    const filter=account===null?'':' AND a.account_id=? AND a.lease_id=?',args=account===null?[]:[account,lease];
    // Seed a bounded number from the immutable journal. This also recovers a
    // crash after acceptance but before the request-path cleanup callback.
    const unqueued=await race(()=>env.DB.prepare(`SELECT a.account_id,a.lease_id FROM object_acceptances a
      JOIN accounts u ON u.id=a.account_id LEFT JOIN object_audit_retirements r ON r.lease_id=a.lease_id
      WHERE r.lease_id IS NULL AND u.deleted_at IS NULL${filter} ORDER BY a.accepted_at,a.lease_id LIMIT ?`).bind(...args,limit).all());
    for(const row of unqueued.results) {
      const proof=await race(()=>objectRetirementProof(env,row.account_id,row.lease_id));
      if(!proof)continue;
      const hash=await race(()=>sha256Hex(encodeUtf8(JSON.stringify(proof))));
      await race(()=>env.DB.prepare(`INSERT INTO object_audit_retirements(lease_id,request_sha256,state)
        SELECT ? ,?,'pending' WHERE EXISTS (SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL)
        ON CONFLICT(lease_id) DO NOTHING`).bind(row.lease_id,hash,row.account_id).run());
    }
    // Deleted accounts use the stronger existing privacy erasure path instead.
    await race(()=>env.DB.prepare(`UPDATE object_audit_retirements SET state='privacy',next_attempt=0
      WHERE state='pending' AND lease_id IN (SELECT a.lease_id FROM object_acceptances a JOIN accounts u ON u.id=a.account_id
        WHERE u.deleted_at IS NOT NULL${filter})`).bind(...args).run());
    const due=await race(()=>env.DB.prepare(`SELECT r.*,a.account_id FROM object_audit_retirements r
      JOIN object_acceptances a ON a.lease_id=r.lease_id WHERE r.state='pending' AND r.next_attempt<=?${filter}
      ORDER BY r.next_attempt,a.accepted_at,r.lease_id LIMIT ?`).bind(now,...args,limit).all());
    for(const row of due.results) {
      // Reserve the retry/backoff before contacting the host. A hard timeout or
      // concurrent callback cannot create a hot loop or undo a delivered intent.
      const claimed=await race(()=>env.DB.prepare(`UPDATE object_audit_retirements
        SET failures=min(failures+1,16),next_attempt=? WHERE lease_id=? AND state='pending'
          AND next_attempt=? AND failures=?`).bind(now+Math.min(3600,60*2**row.failures),row.lease_id,
            row.next_attempt,row.failures).run());
      if(claimed.meta?.changes!==1)continue;
      try {
        const proof=await race(()=>objectRetirementProof(env,row.account_id,row.lease_id));
        if(!proof || await race(()=>sha256Hex(encodeUtf8(JSON.stringify(proof))))!==row.request_sha256)throw Error('retirement_changed');
        const transfer=Promise.resolve().then(()=>env.OBJECT_VERIFIER.fetch(new Request(
          `https://object-verifier.internal/object-audits/${proof.jobId}/retire`,{method:'POST',
            headers:{'content-type':'application/json'},body:JSON.stringify(proof.body),signal:abort.signal}))).then(response=>{
              if(abort.signal.aborted){if(response.body)void response.body.cancel().catch(()=>{});throw Error('late_retirement');}
              return response;
            });
        const response=await race(()=>transfer);
        if(response.status!==200){if(response.body)void response.body.cancel().catch(()=>{});throw Error('retirement_unavailable');}
        const remaining=Math.floor(timeoutMs-(performance.now()-started));if(remaining<1)throw Error('retirement_timeout');
        const expected={jobId:proof.jobId,...Object.fromEntries(['leaseId','assignmentSha256','submissionSha256',
          'candidateManifestSha256','attempts'].map(k=>[k,proof.body[k]]))};
        const checked=objectAuditResult(await race(()=>readVerifierJson(response,remaining)),expected);
        if(!['retiring','retired','erasing','erased'].includes(checked.state)
            || ['retiring','retired'].includes(checked.state) && checked.receiptSha256!==proof.body.receiptSha256)throw Error('retirement_unconfirmed');
        await race(()=>env.DB.prepare(`UPDATE object_audit_retirements SET state=?,next_attempt=0,delivered_at=?
          WHERE lease_id=? AND request_sha256=? AND state='pending'`).bind(
            ['erasing','erased'].includes(checked.state)?'privacy':'delivered',now,row.lease_id,row.request_sha256).run());
        result.delivered++;
      } catch {
        result.pending++;
      }
    }
  } catch {result.pending++;} // Cleanup cannot roll back accepted work or credit.
  finally {clearTimeout(timer);abort.abort();}
  return result;
}
