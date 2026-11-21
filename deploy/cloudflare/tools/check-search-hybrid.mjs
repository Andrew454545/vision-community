// Offline operator/recovery preflight. Use a closed private database copy.
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {HYBRID_SCHEMA,HYBRID_CONTRACT_SQL,HYBRID_CONTRACT} from '../src/searchHybridSchema.js';
import {inspectCloudBudget} from '../src/searchHybrid.js';
import {checkSearchQueue} from './check-search-queue.mjs';
const HEX=/^[0-9a-f]{64}$/,ID=/^[0-9a-f]{32}$/;
const integer=(v,min,max)=>Number.isSafeInteger(v)&&v>=min&&v<=max;
const invalid=()=>{throw Error('search_hybrid_preflight_failed');};
export function checkSearchHybrid(sql,now=Math.floor(Date.now()/1000)) {
  if(!integer(now,0,8640000000000))invalid();
  checkSearchQueue(sql);
  const expected=new DatabaseSync(':memory:');
  try{
    expected.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));
    expected.exec(readFileSync(new URL('../search-queue.sql',import.meta.url),'utf8'));
    for(const definition of [...HYBRID_SCHEMA,HYBRID_CONTRACT_SQL])expected.exec(definition);
    const objects=db=>db.prepare(`SELECT type,name,tbl_name,sql FROM sqlite_master
      WHERE name LIKE 'search_hybrid_%' OR name LIKE 'search_cloud_%' ORDER BY name`).all()
      .map(row=>({...row,sql:row.sql?.replace(/\s+/g,' ').trim()}));
    if(JSON.stringify(objects(sql))!==JSON.stringify(objects(expected)))invalid();
    const revision=sql.prepare('SELECT * FROM search_hybrid_revision').all();
    if(revision.length!==1||revision[0].slot!==1||revision[0].contract!==HYBRID_CONTRACT)invalid();
    const budgetRows=sql.prepare('SELECT * FROM search_cloud_budget').all();
    if(budgetRows.length!==1||budgetRows[0].slot!==1)invalid();
    const budget=inspectCloudBudget(budgetRows[0],now),rows=sql.prepare('SELECT * FROM search_hybrid_claims').all();
    if(rows.length>512)invalid();
    let rollingCents=0,monthlyCents=0;
    const month=value=>{const d=new Date(value*1000);return d.getUTCFullYear()*12+d.getUTCMonth();};
    for(const row of rows){
      const job=sql.prepare('SELECT * FROM search_jobs WHERE id=?').get(row.job_id);
      if(!job||!ID.test(row.job_id)||!HEX.test(row.claim_token)||!['cloud','local'].includes(row.executor)
          ||!integer(row.claimed_at,0,now)||(job.state==='claimed'&&job.claim_token!==row.claim_token))invalid();
      if(row.cloud_token===null){
        if(row.executor!=='local'||['cloud_deadline','cloud_reserved_cents','cloud_reserved_at','stopped_at','shutdown_sha256'].some(k=>row[k]!==null))invalid();
      }else{
        if(!budget.initialized||!HEX.test(row.cloud_token)||!integer(row.cloud_reserved_cents,1,300)
            ||!integer(row.cloud_reserved_at,0,row.claimed_at)||!integer(row.cloud_deadline,row.cloud_reserved_at+1,row.cloud_reserved_at+240)
            ||(row.executor==='local'&&row.stopped_at===null)
            ||(row.stopped_at===null)!==(row.shutdown_sha256===null)
            ||(row.stopped_at!==null&&(!integer(row.stopped_at,row.cloud_reserved_at,now)||!HEX.test(row.shutdown_sha256)))
            ||(row.executor==='cloud'&&(row.claim_token!==row.cloud_token||(job.state==='claimed'&&job.claim_until>row.cloud_deadline))))invalid();
        if(row.cloud_reserved_at>now-31*86400)rollingCents+=row.cloud_reserved_cents;
        if(month(row.cloud_reserved_at)===month(now))monthlyCents+=row.cloud_reserved_cents;
      }
    }
    if(sql.prepare(`SELECT 1 FROM search_jobs j LEFT JOIN search_hybrid_claims h ON h.job_id=j.id
      WHERE j.state='claimed' AND (h.job_id IS NULL OR h.claim_token!=j.claim_token) LIMIT 1`).get())invalid();
    if(rollingCents>(budget.rollingReservedCents||0)||monthlyCents>(budget.monthlyReservedCents||0))invalid();
    return {passed:true,contract:HYBRID_CONTRACT,claims:rows.length,...budget,offline:true,liveReady:false};
  }finally{expected.close();}
}
