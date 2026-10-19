// Finite local workerd/D1/R2 recovery. All inputs and native acknowledgements
// are explicitly synthetic; this fixture does not qualify or admit Objects.
import {writeObjectArtifact,PRIVACY_FENCE} from '../src/artifactWrites.js';
import {deleteAccount,cleanupAccountArtifacts} from '../src/accountPrivacy.js';
import {sha256Hex,encodeUtf8} from '../src/model.js';
import {objectCapabilities} from '../src/objectAdmission.js';
const account='a'.repeat(32),lease='d'.repeat(32),publishedLease='e'.repeat(32);
const pendingPrefix=`object-index-v4/${lease}/`,publishedPrefix=`object-index-v4/${publishedLease}/`;
const bytes=encodeUtf8('synthetic private Object bytes\n');
const deletion={accountId:account,confirmation:'DELETE',idempotencyKey:'c'.repeat(64)};
const provider={async fetch(request) {
  const id=/\/object-assignments\/([0-9a-f]{32})\/erase$/.exec(new URL(request.url).pathname)?.[1];
  if(!id) return Response.json({error:'synthetic_path_mismatch'},{status:500});
  return Response.json({version:1,leaseId:id,policyId:'staging.synthetic',assignmentSha256:'f'.repeat(64),
    state:'erased',serverAuthorization:false,productionQualified:false});
}};
export default {async fetch(request,env) {
  const path=new URL(request.url).pathname;
  const quarantine=`object-quarantine/${lease}/${await sha256Hex(bytes)}.json`;
  const pending=[quarantine,pendingPrefix+'locations.tsv',pendingPrefix+'semantic.bin'];
  const kept=[publishedPrefix+'manifest.json',publishedPrefix+'locations.tsv',publishedPrefix+'semantic.bin'];
  let refused=false;
  if(path==='/stage') {
    for(const key of pending) await writeObjectArtifact(env,account,lease,key,key.endsWith('.bin')?new Uint8Array():bytes,100);
    for(const key of kept) await writeObjectArtifact(env,account,publishedLease,key,key.endsWith('.bin')?new Uint8Array():bytes,100);
  } else if(path==='/delete') await deleteAccount(env,account,deletion,1234);
  else if(path==='/cleanup') await cleanupAccountArtifacts({...env,OBJECT_VERIFIER:provider},account,64);
  else if(path==='/late') {
    try {await writeObjectArtifact(env,account,lease,pending[1],bytes,200);}
    catch(error) {refused=error.message.includes('account_not_active');}
  } else if(path!=='/state') return new Response('not_found',{status:404});
  const objects=[];
  for(const key of [...pending,...kept]) {
    const object=await env.INDEX.get(key);
    objects.push(object ? {size:object.size,fence:object.customMetadata?.visionPrivacyFence==='1',
      sha256:await sha256Hex(new Uint8Array(await object.arrayBuffer()))} : null);
  }
  return Response.json({objects,refused,privateSha256:await sha256Hex(bytes),emptySha256:await sha256Hex(new Uint8Array()),
    fenceSha256:await sha256Hex(encodeUtf8(PRIVACY_FENCE)),
    intents:(await env.DB.prepare('SELECT count(*) AS n FROM account_artifact_writes').first()).n,
    cleanup:(await env.DB.prepare('SELECT artifact_key,state FROM account_cleanup ORDER BY artifact_key').all()).results,
    owner:await env.DB.prepare('SELECT units,deleted_at,recovery_hash FROM accounts WHERE id=?').bind(account).first(),
    publications:(await env.DB.prepare('SELECT count(*) AS n FROM published_index').first()).n,
    deletionDebits:(await env.DB.prepare("SELECT count(*) AS n FROM ledger WHERE reason='account_deleted'").first()).n,
    objectAdmissionReady:objectCapabilities().objectContributions.ready,nativeInferences:0,earnedCredits:0});
}};
