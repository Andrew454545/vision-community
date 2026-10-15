import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareOperatorReadback,operatorSqlFile,validateOperatorReadback,validateOperatorPair} from './scene-receipt-operator.mjs';
const target={accountId:'a'.repeat(32),leaseId:'b'.repeat(32),payloadSha256:'c'.repeat(64),
  policyId:'qualified-device-v1|staging.synthetic',records:[{locationId:81,outputSha256:'d'.repeat(64)}]};
const code='synthetic-recovery-code';
const good={units:3,lease_id:target.leaseId,account_id:target.accountId,policy_id:target.policyId,state:'published',
  records_json:JSON.stringify(target.records),submission_sha256:'f'.repeat(64),lease_account:target.accountId,lane:'scene',
  lease_state:'submitted',ledger_account:target.accountId,award:1,reason:'qualified_device_work',reference:'lease:'+target.leaseId,
  item_count:1,publication_count:1,observed_schema_revision:1,observed_schema_contract:'vision-community-d1-v1-20261004'};
const response=(patch={},meta={})=>[{success:true,results:[{...good,...patch}],
  meta:{rows_read:15,rows_written:0,total_attempts:1,...meta}}];

test('operator packet binds authentication and reads schema/receipt in one SELECT without network',async()=>{
  const query=await prepareOperatorReadback(target,code),sql=operatorSqlFile(query);
  assert.match(sql,/^SELECT receipt/);assert.match(sql,/CROSS JOIN \(SELECT revision,contract/);
  assert.match(sql,/a\.recovery_hash=/);assert.match(sql,/a\.deleted_at IS NULL/);
  assert.match(sql,/CROSS JOIN published_index/);assert.match(sql,/lease:/);
  assert.ok(!sql.includes(code));assert.ok(!sql.includes('?'));
  await assert.rejects(prepareOperatorReadback(target,'short'),/unauthorized/);
});
test('actual schema, publication, lease and original unique award gates are reused',async()=>{
  const valid=await validateOperatorReadback(target,code,response());
  assert.equal(valid.reply.accepted,1);assert.equal(valid.reply.unitsEarned,0);
  for(const patch of [{observed_schema_revision:0},{observed_schema_contract:'other'},
    {state:'pending'},{publication_count:0},{award:2},{ledger_account:'f'.repeat(32)},{reason:'verified_work'}])
    await assert.rejects(validateOperatorReadback(target,code,response(patch)));
  await assert.rejects(validateOperatorReadback(target,code,[{...response()[0],results:[]}]),/missing/);
});
test('usage, automatic attempts, changed balances and incomplete pairs fail closed',async()=>{
  for(const meta of [{rows_read:201},{rows_read:undefined},{rows_written:1},{total_attempts:2}])
    await assert.rejects(validateOperatorReadback(target,code,response({},meta)),/usage/);
  await assert.rejects(validateOperatorPair(target,code,[response()]),/pair/);
  await assert.rejects(validateOperatorPair(target,code,[response(),response({units:4})]),/changed/);
  await assert.rejects(validateOperatorPair(target,code,[response({},{rows_read:101}),response({},{rows_read:101})]),/usage_limit/);
  const result=await validateOperatorPair(target,code,[response(),response()]);
  assert.equal(result.reply.originalAwardUnits,1);assert.equal(result.reply.unitsEarned,0);
  assert.equal(result.observedUsage.read,30);assert.equal(result.gatewayAuthenticationVerified,false);
});
