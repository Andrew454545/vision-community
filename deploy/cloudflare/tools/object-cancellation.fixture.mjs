// Actual workerd/local D1/R2; native replies deliberately synthetic.
import {stageObjectAudit,advanceObjectAudit} from '../src/objectAuditDispatch.js';
import {cancelObjectAudit,advanceObjectCancellation} from '../src/objectAuditCancellation.js';
import {sha256Hex,encodeUtf8} from '../src/model.js';
const account='a'.repeat(32),lease='b'.repeat(32),now=100000;
const authority={leaseId:lease,profileId:'1'.repeat(64),policyId:'staging.synthetic',assignmentSha256:'2'.repeat(64)};
const index={manifest:{synthetic:true},files:{'synthetic.bin':''},sourceTsv:btoa('synthetic source\n')};
export default {async fetch(request,env){
  const path=new URL(request.url).pathname;
  const bound={...env,OBJECT_VERIFIER:{async fetch(request){
    const route=new URL(request.url).pathname;
    if(route==='/object-audits'){
      await env.DB.prepare('UPDATE synthetic_native SET starts=starts+1').run();
      return Response.json({error:'synthetic_start_reply_lost'},{status:503});
    }
    if(route!==`/object-assignments/${lease}/erase`)throw Error('synthetic_wrong_route');
    await env.DB.prepare('UPDATE synthetic_native SET erasures=erasures+1').run();
    const native=await env.DB.prepare('SELECT * FROM synthetic_native').first();
    return Response.json({version:1,leaseId:lease,policyId:authority.policyId,assignmentSha256:authority.assignmentSha256,
      state:native.finish?'erased':'erasing',serverAuthorization:false,productionQualified:false});
  }}};
  let value=null;
  if(path==='/stage')value=await stageObjectAudit(bound,account,{...authority,sourceSha256:await sha256Hex(encodeUtf8('synthetic source\n'))},index,now);
  else if(path==='/start')value=await advanceObjectAudit(bound,account,lease,now);
  else if(path==='/cancel')value=await cancelObjectAudit(bound,account,lease,'7'.repeat(64),now+1);
  else if(path==='/reassigned'){
    const next='e'.repeat(32),other='c'.repeat(32),prefix='object-index-v4/'+next+'/';
    await env.INDEX.put(prefix+'manifest.json','synthetic other-owner bundle');
    await env.DB.batch([
      env.DB.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-other',7)").bind(other),
      env.DB.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','submitted',101000)").bind(next,other),
      env.DB.prepare('INSERT INTO lease_items VALUES (?,1)').bind(next),
      env.DB.prepare("UPDATE locations SET state='published',queue_state='published' WHERE id=1"),
      env.DB.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (1,'synthetic',?,100001,?)").bind('f'.repeat(64),prefix),
    ]);
  }
  else if(path==='/partial')value=await advanceObjectCancellation(bound,account,lease,now+2);
  else if(path==='/finish'){
    await env.DB.prepare('UPDATE synthetic_native SET finish=1').run();
    value=await advanceObjectCancellation(bound,account,lease,now+32);
  }else if(path==='/replay')value=await cancelObjectAudit(bound,account,lease,'7'.repeat(64),now+90);
  else if(path==='/late')value=await advanceObjectAudit(bound,account,lease,now+91);
  else if(path!=='/state')return new Response('not_found',{status:404});
  const candidate=await env.DB.prepare('SELECT * FROM object_audit_candidates').first();
  const artifact=candidate?await env.INDEX.get(candidate.artifact_key):null;
  const otherArtifact=await env.INDEX.get('object-index-v4/'+'e'.repeat(32)+'/manifest.json');
  return Response.json({value,candidate,cancellation:await env.DB.prepare('SELECT * FROM object_audit_cancellations').first(),
    native:await env.DB.prepare('SELECT * FROM synthetic_native').first(),
    owner:await env.DB.prepare('SELECT units,deleted_at FROM accounts WHERE id=?').bind(account).first(),
    location:await env.DB.prepare('SELECT state,queue_state,active_lease FROM locations WHERE id=1').first(),
    lease:await env.DB.prepare('SELECT state FROM leases WHERE id=?').bind(lease).first(),
    publications:(await env.DB.prepare('SELECT COUNT(*) AS n FROM published_index').first()).n,
    ledgerEntries:(await env.DB.prepare('SELECT COUNT(*) AS n FROM ledger').first()).n,
    artifactFence:artifact?.customMetadata?.visionPrivacyFence==='1',otherBundlePreserved:otherArtifact ? await otherArtifact.text()==='synthetic other-owner bundle' : false,
    nativeInferences:0,liveCalls:0});
}};
