import test from 'node:test';
import assert from 'node:assert/strict';
import gateway,{canonicalRecoveryTarget,recoverSceneReceipt} from './scene-receipt-recovery.mjs';
import {sha256Hex,encodeUtf8} from '../src/model.js';
const target={accountId:'a'.repeat(32),leaseId:'b'.repeat(32),payloadSha256:'c'.repeat(64),
  policyId:'qualified-device-v1|staging.synthetic',records:[{locationId:81,outputSha256:'d'.repeat(64)}]};
const hash=v=>sha256Hex(encodeUtf8(v));
async function configuration(){return {DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',
  DELETION_ARCHIVE_DB_ID:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',SCENE_RECOVERY_ACCOUNT:'272760294910ef0b246980278aeb36e2',
  SCENE_RECOVERY_UNTIL:String(Date.now()+600000),SCENE_RECOVERY_TOKEN_SHA256:await hash('e'.repeat(64)),
  SCENE_RECOVERY_TARGET_SHA256:await hash(canonicalRecoveryTarget(target)),DB:{prepare(){throw Error('no database');}}};}
function request(body={target,recoveryCode:'fixture-recovery-code'},patch={}){return new Request('https://fixture.test/api/scene-receipt-recovery',{
  method:'POST',headers:{origin:'https://fixture.test','x-vision-finite-cohort':'e'.repeat(64),
    'x-vision-trial-remaining-read':'200','x-vision-trial-remaining-written':'0','x-vision-trial-remaining-puts':'0',
    'x-vision-trial-remaining-bytes':'0',...patch},body:JSON.stringify(body)});}
test('only a pinned ASCII, bounded, unique target is canonical',()=>{
  assert.equal(canonicalRecoveryTarget(target),JSON.stringify(target));
  for(const patch of [{records:[]},{records:[...target.records,...target.records]}, {policyId:'audited-v1'},
    {extra:true},{records:[{...target.records[0],extra:true}]},{policyId:'qualified-device-v1|staging.é'}])
    assert.throws(()=>canonicalRecoveryTarget({...target,...patch}),/invalid_recovery_target/);
});
test('expired, changed-resource, maintenance and uncredentialed entrypoints never reach SQL',async()=>{
  const env=await configuration();
  for(const patch of [{DEPLOYMENT_ENVIRONMENT:'production'},{INDEX_BUCKET_NAME:'vision-community'},
    {SCENE_RECOVERY_ACCOUNT:'other'},{SCENE_RECOVERY_UNTIL:'1'},{SCENE_RECOVERY_UNTIL:String(Date.now()+3600000)},
    {RESTORE_MAINTENANCE:'1'}])assert.equal((await gateway.fetch(request(),{...env,...patch})).status,503);
  assert.equal((await gateway.fetch(request(undefined,{'x-vision-finite-cohort':'f'.repeat(64)}),env)).status,403);
  for(const route of ['/api/leases','/api/submissions','/api/scene-audits','/api/searches','/api/recovery']){
    const req=request();assert.equal((await gateway.fetch(new Request('https://fixture.test'+route,req),env)).status,404);
  }
});
test('changed target, budgets and origin fail before SQL',async()=>{
  const env=await configuration();
  assert.equal((await gateway.fetch(request({target:{...target,accountId:'f'.repeat(32)},recoveryCode:'fixture-code-12345'}),env)).status,409);
  for(const patch of [{'x-vision-trial-remaining-written':'1'},{'x-vision-trial-remaining-read':'201'}, {origin:'https://other.test'}])
    assert.ok((await gateway.fetch(request(undefined,patch),env)).status>=400);
});
test('published receipt requires exact current publication, original award and active account; expired qualification is irrelevant',async()=>{
  const good={units:1,lease_id:target.leaseId,account_id:target.accountId,policy_id:target.policyId,state:'published',
    records_json:JSON.stringify(target.records),submission_sha256:'f'.repeat(64),lease_account:target.accountId,lane:'scene',
    lease_state:'submitted',ledger_account:target.accountId,award:1,reason:'qualified_device_work',reference:'lease:'+target.leaseId,
    item_count:1,publication_count:1};
  function env(row){let reads=0;return {DB:{prepare(sql){assert.match(sql,/^SELECT/);return {bind(){return this;},async first(){
    reads++;return reads===1?{revision:1,contract:'vision-community-d1-v1-20261004'}:row;}};}}};}
  const reply=await recoverSceneReceipt(env(good),target,'fixture-recovery-code');
  assert.equal(reply.originalAwardUnits,1);assert.equal(reply.unitsEarned,0);assert.equal(reply.auditReplay.replayed,true);
  for(const patch of [{state:'pending'},{publication_count:0},{award:2},{ledger_account:'f'.repeat(32)},
    {reason:'verified_work'},{policy_id:'another'},{records_json:'[]'},{item_count:2}])
    await assert.rejects(recoverSceneReceipt(env({...good,...patch}),target,'fixture-recovery-code'),/scene_receipt_conflict/);
  await assert.rejects(recoverSceneReceipt(env(null),target,'fixture-recovery-code'),/unauthorized/);
});
