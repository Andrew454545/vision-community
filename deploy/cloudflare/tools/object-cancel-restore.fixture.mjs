// Actual local workerd/D1/R2, synthetic identities only; no native binding.
import {fenceRestoredObjectArtifact} from '../src/objectCancellationRestore.js';
import {writeObjectArtifact,PRIVACY_FENCE} from '../src/artifactWrites.js';
const account='a'.repeat(32),other='c'.repeat(32),lease='b'.repeat(32);
export default {async fetch(request,env){
  const url=new URL(request.url),early=url.pathname.startsWith('/early/'),path=url.pathname.replace(/^\/early/,'');
  const bound={DB:early?env.EARLY:env.DB,INDEX:early?env.EARLY_INDEX:env.INDEX},db=bound.DB;
  const row=await db.prepare('SELECT * FROM object_cancellation_tombstones WHERE lease_id=?').bind(lease).first();
  let value=null;
  if(path==='/fence')value=await fenceRestoredObjectArtifact(bound,lease,row.artifact_key);
  else if(path==='/unowned'){
    try{await fenceRestoredObjectArtifact(bound,lease,'object-index-v4/'+lease+'/unowned.bin');throw Error('unexpected success');}
    catch(error){if(error.message!=='object_cancel_ownership_unconfirmed')throw error;value={unownedRefused:true};}
  }else if(path==='/late'){
    if(early)await db.prepare("INSERT INTO accounts(id,token_hash,units) VALUES (?,'synthetic-future',0) ON CONFLICT(id) DO NOTHING").bind(account).run();
    const statements=[
      db.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',9999) ON CONFLICT(id) DO UPDATE SET state='active'").bind(lease,account),
      db.prepare("INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease) VALUES (99,'synthetic-late','fixture','object','synthetic','leased',?)").bind(lease),
      db.prepare("INSERT INTO account_artifact_writes VALUES (?,?,?,?,1,1003)").bind('object-index-v4/'+lease+'/manifest.json',account,lease,'f'.repeat(64)),
      db.prepare("INSERT INTO published_index(location_id,index_text,output_sha256,published_at,object_index_key) VALUES (99,'synthetic','fixture',1003,?)").bind('object-index-v4/'+lease+'/'),
      db.prepare('INSERT INTO lease_items VALUES (?,99)').bind(lease),
    ];
    if(!early)statements.push(db.prepare("UPDATE object_audit_candidates SET receipt_sha256='late' WHERE lease_id=?").bind(lease));
    let blocked=0;
    for(const statement of statements){
      try{await statement.run();throw Error('unexpected success');}
      catch(error){if(!/object_assignment_cancelled/.test(error.message))throw error;blocked++;}
    }
    let puts=0;
    try{
      const payload=new TextEncoder().encode(JSON.stringify({manifest:{synthetic:true},files:{'synthetic.bin':''},sourceTsv:btoa('synthetic source\n')}));
      await writeObjectArtifact({...bound,INDEX:{put(){puts++;throw Error('unexpected write');}}},account,lease,row.artifact_key,payload,1003);
      throw Error('unexpected success');
    }catch(error){if(!/lease_lost/.test(error.message))throw error;}
    if(puts)throw Error('unexpected R2 write');
    value={blockedLateStatements:blocked,lateR2Writes:puts};
  }else if(path!=='/state')return new Response('not_found',{status:404});
  const object=await bound.INDEX.get(row.artifact_key),otherObject=await bound.INDEX.get('object-index-v4/'+other+'/manifest.json');
  return Response.json({early,value,tombstone:row,owner:await db.prepare('SELECT units,deleted_at FROM accounts WHERE id=?').bind(account).first(),
    candidate:await db.prepare('SELECT state,receipt_sha256,native_attempts,last_error FROM object_audit_candidates WHERE lease_id=?').bind(lease).first(),
    lease:await db.prepare('SELECT state FROM leases WHERE id=?').bind(lease).first(),
    ledgerEntries:(await db.prepare('SELECT count(*) AS n FROM ledger').first()).n,
    publications:(await db.prepare('SELECT count(*) AS n FROM published_index').first()).n,
    artifactFenced:object?.customMetadata?.visionPrivacyFence==='1' && await object.text()===PRIVACY_FENCE,
    otherBundlePreserved:otherObject?await otherObject.text()==='synthetic retained bundle':false,nativeInferences:0,liveCalls:0});
}};
