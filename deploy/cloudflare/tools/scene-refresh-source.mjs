// Private operator collector. Never select credentials, recovery hashes or queries.
import { createHash } from 'node:crypto';

export const STAGING_RESOURCE = Object.freeze({accountId:'272760294910ef0b246980278aeb36e2',
  databaseId:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',bucket:'vision-community-staging'});
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const object = fields => 'json_object('+Object.entries(fields).map(([key,column])=>`'${key}',${column}`).join(',')+')';
const columns = names => Object.fromEntries(names.map(name=>[name,name]));
const inventory = {id:'l.id',asset_id:'l.asset_id',capture:'l.capture',lane:'l.lane',model:'l.model',state:'l.state',
  contributor_id:'l.contributor_id',lat:'l.lat',lon:'l.lon',heading:'l.heading',pitch:'l.pitch',zoom:'l.zoom',
  country:'l.country',camera_generation:'l.camera_generation',location_output_sha256:'l.output_sha256',
  output_sha256:'i.output_sha256',four_view_sha256:'i.four_view_sha256',four_view_key:'i.four_view_key'};
const candidateColumns=columns(['lease_id','account_id','qualification_id','policy_id','submission_sha256',
  'artifact_key','records_json','created_at','state']);
export const CAPTURE_SQL = `WITH admitted AS (SELECT * FROM scene_candidates
  WHERE state='published' AND policy_id IN (SELECT value FROM json_each(?)))
  SELECT json_object(
    'rows',(SELECT json_group_array(${object(inventory)}) FROM locations l
      JOIN published_index i ON i.location_id=l.id JOIN lease_items z ON z.location_id=l.id
      JOIN admitted c ON c.lease_id=z.lease_id
      WHERE l.lane='scene' AND l.state='published' ORDER BY l.id),
    'candidates',(SELECT json_group_array(${object(candidateColumns)}) FROM admitted ORDER BY lease_id),
    'qualifications',(SELECT json_group_array(${object(columns(['id','account_id','profile_id','policy_id','created_at','expires_at']))})
      FROM scene_qualifications WHERE id IN (SELECT qualification_id FROM admitted) ORDER BY id),
    'accounts',(SELECT json_group_array(${object(columns(['id','deleted_at']))}) FROM accounts
      WHERE id IN (SELECT account_id FROM admitted) ORDER BY id),
    'deletions',(SELECT json_group_array(${object(columns(['account_id','deleted_at']))}) FROM account_deletion_receipts
      WHERE account_id IN (SELECT account_id FROM admitted) ORDER BY account_id),
    'ledger',(SELECT json_group_array(${object(columns(['reference','account_id','units','reason']))}) FROM ledger
      WHERE reference IN (SELECT 'lease:'||lease_id FROM admitted) ORDER BY reference)) AS document`;

export async function capturePublications(db, policies) {
  if (!Array.isArray(policies) || !policies.length || policies.length>16
      || policies.some(p=>typeof p!=='string'||!/^staging\.[A-Za-z0-9_.-]{1,180}$/.test(p))
      || new Set(policies).size!==policies.length) throw Error('invalid_refresh_policies');
  // One query in a primary-first session is the export's consistency boundary.
  const row=await db.withSession('first-primary').prepare(CAPTURE_SQL).bind(JSON.stringify(policies)).first();
  if (!row || typeof row.document!=='string' || Buffer.byteLength(row.document)>64*1024*1024)
    throw Error('refresh_export_unavailable');
  const {rows,...control}=JSON.parse(row.document);
  if (!Array.isArray(rows) || rows.length>100000) throw Error('refresh_export_unavailable');
  return {inventory:{version:1,resource:STAGING_RESOURCE,rows},control:{version:1,resource:STAGING_RESOURCE,...control}};
}

export function checkedProxyConfig(config) {
  if (config.account_id!==STAGING_RESOURCE.accountId || config.workers_dev!==false || config.preview_urls!==false
      || config.d1_databases?.length!==1 || config.r2_buckets?.length!==1 || config.services?.length!==2
      || config.d1_databases[0].binding!=='DB' || config.d1_databases[0].database_id!==STAGING_RESOURCE.databaseId
      || config.d1_databases[0].remote!==true || config.r2_buckets[0].binding!=='INDEX'
      || config.r2_buckets[0].bucket_name!==STAGING_RESOURCE.bucket || config.r2_buckets[0].remote!==true
      || ![['NATIVE_OPERATOR','NativeSceneOperator'],['SEARCH_ENGINE','NativeSceneSearch']].every(([binding,entrypoint])=>
        config.services.some(s=>s.binding===binding&&s.entrypoint===entrypoint&&s.remote===true
          &&s.service==='vision-community-native-host-staging')))
    throw Error('unconfirmed_refresh_resources');
}

export async function artifactBytes(bucket,key) {
  if (!/^four-view-v4\/[0-9a-f]{32}\.i8$/.test(key)) throw Error('invalid_refresh_artifact_key');
  const object=await bucket.get(key);
  if (!object || !Number.isSafeInteger(object.size) || object.size<3080 || object.size>3080000
      || object.size%3080) throw Error('refresh_artifact_unavailable');
  const bytes=new Uint8Array(await object.arrayBuffer());
  if(bytes.byteLength!==object.size)throw Error('refresh_artifact_unavailable');
  return bytes;
}

export async function uploadBundle(bucket,descriptor,bytes) {
  if (descriptor?.version!==1 || !/^[0-9a-f]{64}$/.test(descriptor.sha256||'')
      || descriptor.key!=='native-host/bundles/'+descriptor.sha256+'.zip'
      || descriptor.bytes!==bytes.byteLength || bytes.byteLength<1 || bytes.byteLength>384*1024*1024
      || hash(bytes)!==descriptor.sha256) throw Error('invalid_refresh_bundle');
  const matches=async existing=>existing && existing.size===bytes.byteLength
    && hash(new Uint8Array(await existing.arrayBuffer()))===descriptor.sha256;
  let existing=await bucket.get(descriptor.key);
  if (existing) {if(!await matches(existing))throw Error('refresh_bundle_conflict');return {uploaded:false};}
  const written=await bucket.put(descriptor.key,bytes,{onlyIf:new Headers({'if-none-match':'*'}),
    httpMetadata:{contentType:'application/zip',cacheControl:'no-store'}});
  existing=await bucket.get(descriptor.key);
  if (!await matches(existing))throw Error('refresh_bundle_readback_failed');
  return {uploaded:!!written};
}
