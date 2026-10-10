import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {STAGING_RESOURCE,CAPTURE_SQL,capturePublications,checkedProxyConfig,artifactBytes,uploadBundle} from './scene-refresh-source.mjs';
const sha=raw=>createHash('sha256').update(raw).digest('hex');
const config=()=>({account_id:STAGING_RESOURCE.accountId,workers_dev:false,preview_urls:false,
  d1_databases:[{binding:'DB',database_id:STAGING_RESOURCE.databaseId,remote:true}],
  r2_buckets:[{binding:'INDEX',bucket_name:STAGING_RESOURCE.bucket,remote:true}],
  services:[['NATIVE_OPERATOR','NativeSceneOperator'],['SEARCH_ENGINE','NativeSceneSearch']].map(([binding,entrypoint])=>
    ({binding,entrypoint,service:'vision-community-native-host-staging',remote:true}))});
test('collector uses one primary-first parameterized query without account secrets',async()=>{
  let calls=0;const db={withSession(mode){assert.equal(mode,'first-primary');return {prepare(sql){
    assert.equal(sql,CAPTURE_SQL);assert.doesNotMatch(sql,/token_hash|recovery_hash|paid_search|\bqueries\b|\bunits FROM accounts/i);
    return {bind(value){assert.deepEqual(JSON.parse(value),['staging.synthetic']);return {async first(){calls++;
      return {document:JSON.stringify({rows:[],candidates:[],qualifications:[],accounts:[],deletions:[],ledger:[]})};}};}};}};}};
  const value=await capturePublications(db,['staging.synthetic']);assert.equal(calls,1);
  assert.deepEqual(value.inventory,{version:1,resource:STAGING_RESOURCE,rows:[]});assert.deepEqual(value.control.deletions,[]);
});
test('invalid policy selection cannot reach a database',async()=>{
  for(const policies of [[],['production'],['staging.a','staging.a'],["staging.x'); DROP TABLE accounts;--"],Array(17).fill('staging.a')])
    await assert.rejects(capturePublications({},policies),/invalid_refresh_policies/);
});
test('private proxy cannot select an unconfirmed bucket, account, database or service',()=>{
  checkedProxyConfig(config());
  for(const mutate of [c=>c.r2_buckets[0].bucket_name='other',c=>c.account_id='other',
    c=>c.d1_databases[0].database_id='other',c=>c.services[0].service='other',
    c=>c.services[0].remote=false,c=>c.workers_dev=true,c=>c.r2_buckets.push(c.r2_buckets[0])]){
    const c=config();mutate(c);assert.throws(()=>checkedProxyConfig(c),/unconfirmed_refresh_resources/);
  }
});
test('artifacts accept only bounded full four-view records',async()=>{
  const bytes=new Uint8Array(3080);const bucket={get:async()=>({size:bytes.length,arrayBuffer:async()=>bytes.buffer})};
  assert.equal((await artifactBytes(bucket,'four-view-v4/'+'a'.repeat(32)+'.i8')).length,3080);
  await assert.rejects(artifactBytes(bucket,'native-host/private.zip'),/invalid_refresh_artifact_key/);
  await assert.rejects(artifactBytes({get:async()=>({size:3081})},'four-view-v4/'+'a'.repeat(32)+'.i8'),/refresh_artifact_unavailable/);
});
test('bundle upload is create-only, read back and idempotent',async()=>{
  let saved,puts=0;const bytes=new Uint8Array([1,2,3]),pin=sha(bytes);
  const descriptor={version:1,key:'native-host/bundles/'+pin+'.zip',sha256:pin,bytes:bytes.length};
  const bucket={get:async()=>saved&&({size:saved.length,arrayBuffer:async()=>saved.buffer}),put:async(key,raw,options)=>{
    assert.equal(key,descriptor.key);assert.equal(options.onlyIf.get('if-none-match'),'*');saved=raw;puts++;return {};}};
  assert.deepEqual(await uploadBundle(bucket,descriptor,bytes),{uploaded:true});
  assert.deepEqual(await uploadBundle(bucket,descriptor,bytes),{uploaded:false});assert.equal(puts,1);
  saved=new Uint8Array([4,5,6]);await assert.rejects(uploadBundle(bucket,descriptor,bytes),/refresh_bundle_conflict/);
  assert.equal(puts,1);
});
test('wrong pinned bundle bytes never reach storage',async()=>{
  await assert.rejects(uploadBundle({}, {version:1,key:'native-host/bundles/'+'a'.repeat(64)+'.zip',
    sha256:'a'.repeat(64),bytes:1},new Uint8Array([1])),/invalid_refresh_bundle/);
});
