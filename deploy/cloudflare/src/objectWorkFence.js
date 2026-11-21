// Optional assignment authority is never a request-controlled upload bypass.
import {OBJECT_WORK_CONTRACT} from './objectWorkSchema.js';
import {ObjectDispatchError} from './objectAuditDispatch.js';
export async function objectWorkFence(env,account,row,qualification,policySha256){
 if(!await env.DB.prepare("SELECT 1 FROM sqlite_master WHERE name GLOB 'object_work_*' LIMIT 1").first())return null;
 if((await env.DB.prepare('SELECT contract FROM object_work_revision WHERE slot=1').first())?.contract!==OBJECT_WORK_CONTRACT)
   throw new ObjectDispatchError('object_work_recovery_required',503);
 const work=await env.DB.prepare('SELECT * FROM object_work_requests WHERE lease_id=?').bind(row.lease_id).first();
 if(!work)return null; // Existing private operator-prepared path remains distinct.
 const pool=await env.DB.prepare('SELECT * FROM object_work_pool WHERE lease_id=?').bind(row.lease_id).first();
 if(!pool||work.account_id!==account||work.state!=='ready'||pool.state!=='claimed'||work.qualification_id!==qualification.id
   ||pool.profile_id!==row.profile_id||pool.policy_id!==row.policy_id||pool.eligibility_sha256!==policySha256
   ||pool.assignment_sha256!==row.assignment_sha256||pool.source_sha256!==row.source_sha256)
   throw new ObjectDispatchError('object_work_assignment_changed',409);
 return {work,pool};
}
export function objectWorkSqlFence(assignment){
 if(!assignment)return '';
 const key=k=>{if(!/^[a-z_][a-z_0-9]*$/.test(k))throw Error('invalid_object_work_snapshot');return k;};
 const all=v=>v.length===1?v[0]:`(${all(v.slice(0,Math.floor(v.length/2)))} AND ${all(v.slice(Math.floor(v.length/2)))})`;
 const matches=(values,alias,path)=>all(Object.keys(values).map(k=>`${alias}.${key(k)} IS json_extract(e.doc,'$.assignment.${path}.${k}')`));
 return ` AND EXISTS (SELECT 1 FROM object_work_requests wr JOIN object_work_pool wp ON wp.lease_id=wr.lease_id
   WHERE wr.lease_id=l.id AND wr.account_id=a.id AND wr.qualification_id=q.id AND wr.state='ready' AND wp.state='claimed'
     AND (${matches(assignment.work,'wr','work')}) AND (${matches(assignment.pool,'wp','pool')}))`;
}
