// Operator-only source function. Never called by a public route; no provider transport.
import {sha256Hex,encodeUtf8} from '../src/model.js';
import {OBJECT_WORK_CONTRACT} from '../src/objectWorkSchema.js';
import {qualifiedObjectEligibilityPolicy} from '../src/qualifiedObjectEligibility.js';
const hex=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v),id=v=>typeof v==='string'&&/^[a-f0-9]{32}$/.test(v);
const require=v=>{if(!v)throw Error('invalid_prepared_object_pool');};
export async function importObjectWorkPool(env,raw,pin,now=Math.floor(Date.now()/1000)) {
 require(typeof raw==='string'&&encodeUtf8(raw).length<=1024*1024&&hex(pin)&&await sha256Hex(encodeUtf8(raw))===pin);
 require((await env.DB.prepare('SELECT contract FROM object_work_revision WHERE slot=1').first())?.contract===OBJECT_WORK_CONTRACT);
 const p=await qualifiedObjectEligibilityPolicy(env,now),doc=JSON.parse(raw);
 require(doc.version===1&&doc.scope==='operator-prepared-qualified-object-pool-v1'
   &&doc.eligibilityPolicySha256===env.OBJECT_ELIGIBILITY_POLICY_SHA256
   &&JSON.stringify(doc.resource)===JSON.stringify(p.resource)&&Array.isArray(doc.entries)&&doc.entries.length>=1&&doc.entries.length<=64);
 const seen=new Set(),statements=[];
 for(const v of doc.entries){
   require(id(v.leaseId)&&!seen.has(v.leaseId)&&hex(v.profileId)&&hex(v.assignmentSha256)&&hex(v.sourceSha256)
     &&typeof v.sourceTsv==='string'&&encodeUtf8(v.sourceTsv).length<=8192&&v.sourceTsv.endsWith('\n')
     &&await sha256Hex(encodeUtf8(v.sourceTsv))===v.sourceSha256&&Array.isArray(v.records)&&v.records.length>=1&&v.records.length<=4
     &&Number.isSafeInteger(v.validUntil)&&v.validUntil>now&&v.validUntil<=now+3600&&v.validUntil<=p.validUntil);
   seen.add(v.leaseId);
   const lines=v.sourceTsv.trimEnd().split('\n');require(lines.length===v.records.length);
   v.records.forEach((r,i)=>{const f=lines[i].split('\t');require(Number.isSafeInteger(r.locationId)&&r.locationId>0
     &&(i===0||r.locationId>v.records[i-1].locationId)&&typeof r.panoId==='string'&&typeof r.country==='string'
     &&r.cameraGeneration==='gen4'&&hex(r.coverageEvidenceSha256)&&f.length===12&&Number(f[1])===r.locationId
     &&f[7]===r.panoId&&f[8]===r.country&&f[9]==='gen4'
     &&[r.lat,r.lng,r.heading,r.pitch,r.zoom].every((n,j)=>typeof n==='number'&&Number.isFinite(n)&&Number(f[j+2])===n));});
   const rows=JSON.stringify(v.records);require(encodeUtf8(rows).length<=16384);
   const old=await env.DB.prepare('SELECT * FROM object_work_pool WHERE lease_id=?').bind(v.leaseId).first();
   if(old){require(old.profile_id===v.profileId&&old.policy_id===p.policyId&&old.eligibility_sha256===doc.eligibilityPolicySha256
     &&old.assignment_sha256===v.assignmentSha256&&old.source_sha256===v.sourceSha256&&old.source_tsv===v.sourceTsv
     &&old.records_json===rows&&old.valid_until===v.validUntil);continue;}
   require(!await env.DB.prepare('SELECT 1 FROM leases WHERE id=?').bind(v.leaseId).first());
   statements.push(env.DB.prepare(`INSERT INTO object_work_pool VALUES (?,?,?,?,?,?,?,?,?,?,'available')`).bind(v.leaseId,v.profileId,p.policyId,
     doc.eligibilityPolicySha256,v.assignmentSha256,v.sourceSha256,v.sourceTsv,rows,now,v.validUntil));
 }
 if(statements.length){
   await env.DB.prepare("UPDATE object_work_pool SET state='retired' WHERE state='available' AND valid_until<=?").bind(now).run();
   await env.DB.batch(statements);
 }
 return {imported:statements.length,eligibilityGranted:false,qualificationGranted:false,accepted:0,unitsEarned:0};
}
