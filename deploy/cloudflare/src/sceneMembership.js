// Optional, separately operator-pinned Scene membership. No schema, account
// write, provider call, model or root supplied by a contributor/owner packet.
import {encodeUtf8, sha256Hex} from './model.js';
import {SearchError} from './searchLedger.js';

export const MAX_SEALED_SCENE_HITS = 64;
const HEX = /^[0-9a-f]{64}$/;
const KEYS = 'environment,lane,locations,policyId,resource,rootSha256,runtimeSha256,scope,snapshotSha256,version';
const POSE_KEYS = 'cameraGeneration,capture,country,heading,lat,lng,panoId,pitch,zoom';
const RESOURCES = {
  production: {accountId:'272760294910ef0b246980278aeb36e2',
    databaseId:'ed4705fa-1190-41fa-86a0-02d755db1b2a',bucket:'vision-community'},
  staging: {accountId:'272760294910ef0b246980278aeb36e2',
    databaseId:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',bucket:'vision-community-staging'},
};
const keys = value => value && typeof value === 'object' && !Array.isArray(value)
  ? Object.keys(value).sort().join(',') : '';
const refuse = () => { throw new SearchError('search_unavailable'); };

export function sceneMembershipBinding(env, identity) {
  if (env.SEARCH_SCENE_MEMBERSHIP === undefined) return null;
  try {
    if (typeof env.SEARCH_SCENE_MEMBERSHIP !== 'string'
        || encodeUtf8(env.SEARCH_SCENE_MEMBERSHIP).length > 4096) refuse();
    const value = JSON.parse(env.SEARCH_SCENE_MEMBERSHIP), resource = RESOURCES[value?.environment];
    if (keys(value) !== KEYS || value.version !== 1 || value.scope !== 'operator-sealed-scene-membership-v1'
        || value.lane !== 'scene' || !['staging','production'].includes(value.environment) || !resource || env.DEPLOYMENT_ENVIRONMENT !== value.environment
        || env.INDEX_BUCKET_NAME !== resource.bucket || keys(value.resource) !== 'accountId,bucket,databaseId'
        || Object.keys(resource).some(k => value.resource[k] !== resource[k])
        || typeof value.policyId !== 'string' || !/^[A-Za-z0-9_.-]{1,128}$/.test(value.policyId)
        || value.policyId.startsWith('staging.') && value.environment !== 'staging'
        || ['runtimeSha256','snapshotSha256','rootSha256'].some(k => typeof value[k] !== 'string' || !HEX.test(value[k]))
        || !Number.isSafeInteger(value.locations) || value.locations < 1 || value.locations > 100000
        || identity && ['policyId','runtimeSha256','snapshotSha256'].some(k => value[k] !== identity[k])) refuse();
    return value;
  } catch { refuse(); }
}

function bytes(hex) { return Uint8Array.from(hex.match(/../g), part => parseInt(part,16)); }
function join(...parts) {
  const result = new Uint8Array(parts.reduce((size, part) => size + part.length, 0));
  let offset = 0;
  for (const part of parts) { result.set(part, offset); offset += part.length; }
  return result;
}
function memberValue(raw, hit) {
  if (typeof raw !== 'string' || encodeUtf8(raw).length > 8192) refuse();
  let value;
  try { value = JSON.parse(raw); } catch { refuse(); }
  if (keys(value) !== 'locationId,outputSha256,pose,sourceIndex'
      || !Number.isSafeInteger(value.sourceIndex) || value.sourceIndex < 0 || value.sourceIndex !== hit.sourceIndex
      || !Number.isSafeInteger(value.locationId) || value.locationId < 1 || value.locationId !== hit.locationId
      || typeof value.outputSha256 !== 'string' || !HEX.test(value.outputSha256) || value.outputSha256 !== hit.outputSha256
      || keys(value.pose) !== POSE_KEYS) refuse();
  const p = value.pose;
  for (const [key,low,high] of [['lat',-90,90],['lng',-180,180],['heading',0,360],['pitch',-90,90],['zoom',0,5]])
    if (!Number.isFinite(p[key]) || p[key] < low || p[key] > high) refuse();
  for (const [key,minimum,maximum] of [['panoId',1,1000],['capture',1,1000],['country',0,100],['cameraGeneration',0,64]])
    if (typeof p[key] !== 'string' || p[key].length < minimum || p[key].length > maximum || /[\x00-\x1f\x7f]/.test(p[key])) refuse();
  return value;
}

export async function sealedSceneRows(env, query, result, snapshotSha256) {
  if (query.lane !== 'scene') return null; // Objects retain exact official-Gen4 D1 authority.
  const binding = sceneMembershipBinding(env, {policyId:env.SEARCH_POLICY_ID,
    runtimeSha256:env.SEARCH_RUNTIME_SHA256,snapshotSha256});
  if (!binding) return null;
  if (!Number.isSafeInteger(query.resultCount) || query.resultCount < 1 || query.resultCount > MAX_SEALED_SCENE_HITS
      || result.processedLocations !== binding.locations || !Array.isArray(result.membership)
      || result.membership.length !== result.hits.length || result.hits.length > MAX_SEALED_SCENE_HITS
      || result.hits.some(hit => !keys(hit))) refuse();
  const context = encodeUtf8(JSON.stringify(['vision-contributed-scene-member-v1',binding.environment,'scene',
    binding.policyId,binding.runtimeSha256,binding.snapshotSha256,binding.locations]));
  const rows = [];
  for (let i=0;i<result.hits.length;i++) {
    const proof = result.membership[i], hit = result.hits[i];
    if (keys(proof) !== 'memberJson,siblings' || !Array.isArray(proof.siblings)
        || proof.siblings.length > 17 || proof.siblings.some(node => typeof node !== 'string' || !HEX.test(node))) refuse();
    const member = memberValue(proof.memberJson, hit);
    if (member.sourceIndex >= binding.locations) refuse();
    let node = await sha256Hex(join(new Uint8Array([0]),context,encodeUtf8('\n'+proof.memberJson)));
    let index=member.sourceIndex, width=binding.locations, level=0;
    while (width > 1) {
      const sibling=proof.siblings[level++];
      if (sibling === undefined || (index % 2 === 0 && index+1 >= width && sibling !== node)) refuse();
      node = await sha256Hex(join(new Uint8Array([1]),bytes(index%2?sibling:node),bytes(index%2?node:sibling)));
      index=Math.floor(index/2); width=Math.ceil(width/2);
    }
    if (level !== proof.siblings.length || node !== binding.rootSha256) refuse();
    const p=member.pose;
    rows.push({id:member.locationId,output_sha256:member.outputSha256,asset_id:p.panoId,
      lat:p.lat,lon:p.lng,heading:p.heading,pitch:p.pitch,zoom:p.zoom,country:p.country,camera_generation:p.cameraGeneration});
  }
  return rows;
}
