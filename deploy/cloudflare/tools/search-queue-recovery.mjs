// Offline, read-only queue/accounting identity. No expiry, repair or inference.
import {createHash} from 'node:crypto';
import {checkSearchQueue} from './check-search-queue.mjs';

export class QueueRecoveryError extends Error {}
const need=(v,code='invalid_queued_accounting_state')=>{if(!v)throw new QueueRecoveryError(code);};
const hex=(v,n=64)=>typeof v==='string' && new RegExp(`^[0-9a-f]{${n}}$`).test(v);
const integer=(v,low=0,high=Number.MAX_SAFE_INTEGER)=>Number.isSafeInteger(v) && v>=low && v<=high;
const sha=v=>createHash('sha256').update(v).digest('hex');
const object=v=>v && typeof v==='object' && !Array.isArray(v);

export function collectSearchQueue(sql) {
  const present=sql.prepare("SELECT 1 FROM sqlite_master WHERE name LIKE 'search_jobs%' OR name='search_queue_revision' LIMIT 1").get();
  if(!present)return {installed:false,jobs:new Map(),reservedUnits:0,active:0};
  try {checkSearchQueue(sql);} catch {throw new QueueRecoveryError('queued_accounting_schema_invalid');}
  const jobs=new Map(), holds=new Map(); let active=0,reservedUnits=0;
  for(const row of sql.prepare('SELECT * FROM search_jobs ORDER BY id').iterate()) {
    need(hex(row.id,32) && typeof row.account_id==='string'
      && typeof row.idempotency_key==='string' && row.idempotency_key.length>=8 && row.idempotency_key.length<=100
      && typeof row.query_digest==='string' && /^sha256:[0-9a-f]{64}$/.test(row.query_digest)
      && ['scene','object'].includes(row.lane) && integer(row.cost_units,1)
      && integer(row.created_at) && integer(row.expires_at) && row.expires_at-row.created_at===3600
      && integer(row.attempts,0,3));
    const account=sql.prepare('SELECT units,deleted_at FROM accounts WHERE id=?').get(row.account_id);
    need(account && account.deleted_at===null && integer(account.units));
    need(typeof row.binding_json==='string' && Buffer.byteLength(row.binding_json)<=2048);
    let pin;try{pin=JSON.parse(row.binding_json);}catch{need(false);}
    need(object(pin) && Object.keys(pin).sort().join(',')==='contractVersion,policyId,runtimeSha256,snapshotSha256'
      && pin.contractVersion===2 && typeof pin.policyId==='string' && pin.policyId.length>=1 && pin.policyId.length<=200
      && hex(pin.runtimeSha256) && hex(pin.snapshotSha256));
    const running=['queued','claimed'].includes(row.state);
    if(running) {
      need(typeof row.query_json==='string' && Buffer.byteLength(row.query_json)<=65536
        && sha(row.query_json)===row.query_digest.slice(7) && row.completion_nonce===null && row.error_code===null);
      let query;try{query=JSON.parse(row.query_json);}catch{need(false);}
      need(object(query) && query.lane===row.lane);
      const previous=holds.get(row.account_id)||{count:0,units:0};
      const next={count:previous.count+1,units:previous.units+row.cost_units};
      need(next.count<=3 && integer(next.units) && next.units<=account.units);
      holds.set(row.account_id,next);active++;reservedUnits+=row.cost_units;
    } else need(row.query_json===null && row.claim_token===null && row.claim_until===null);
    if(row.state==='claimed')need(hex(row.claim_token) && integer(row.claim_until,row.created_at+1,row.expires_at) && row.attempts>=1);
    else if(row.state==='queued')need(row.claim_token===null && row.claim_until===null && row.attempts===0);
    const saved=sql.prepare('SELECT id,query,result_json FROM searches WHERE account_id=? AND idempotency_key=?')
      .get(row.account_id,row.idempotency_key);
    const debit=sql.prepare("SELECT account_id,units FROM ledger WHERE reason='search' AND reference=?").all('search:'+row.id);
    if(row.state==='settled') {
      need(row.attempts>=1 && hex(row.completion_nonce) && row.error_code===null && saved
        && saved.id===row.id && saved.query===row.query_digest && typeof saved.result_json==='string'
        && debit.length===1 && debit[0].account_id===row.account_id && debit[0].units===-row.cost_units);
      let result;try{result=JSON.parse(saved.result_json);}catch{need(false);}
      need(object(result) && result.searchId===row.id && result.costUnits===row.cost_units);
    } else {
      need(row.completion_nonce===null && !saved && !debit.length);
      need(row.error_code===({failed:'search_failed',cancelled:'search_cancelled',expired:'search_expired'}[row.state]??null));
    }
    jobs.set(row.id,row);
  }
  need(active<=128 && integer(reservedUnits));
  return {installed:true,jobs,reservedUnits,active};
}

export function queueHistory(backup,current) {
  need(!backup.installed || current.installed,'current_search_queue_missing');
  const immutable=['id','account_id','idempotency_key','query_digest','lane','binding_json','cost_units','created_at','expires_at'];
  for(const [id,old] of backup.jobs) {
    const next=current.jobs.get(id);
    // Terminal rows can have been pruned. Current authority is a separately
    // pinned full database; exact recovery must match it, not the older holds.
    if(!next)continue;
    need(immutable.every(k=>old[k]===next[k])
      && (old.query_json===null || next.query_json===null || old.query_json===next.query_json)
      && next.attempts>=old.attempts
      && (['queued','claimed'].includes(old.state) || old.state===next.state),'backup_search_job_identity_changed');
  }
}
