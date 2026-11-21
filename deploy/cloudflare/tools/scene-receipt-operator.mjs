// Offline operator packet/response validation. No network, deployment or writes.
// Actual D1 reads require their own explicit operational scope.
import {canonicalRecoveryTarget,recoverSceneReceipt} from './scene-receipt-recovery.mjs';
import {SCHEMA_READ,SCHEMA_REVISION,SCHEMA_CONTRACT} from '../src/schemaRevision.js';
import {encodeUtf8,sha256Hex} from '../src/model.js';

export async function prepareOperatorReadback(target,recoveryCode) {
  canonicalRecoveryTarget(target);
  let captured;
  const env={DB:{prepare(sql){
    if(sql===SCHEMA_READ)return {async first(){
      // Capture only: this fixture value cannot authorize a real response.
      return {revision:SCHEMA_REVISION,contract:SCHEMA_CONTRACT};
    }};
    if(captured||!/^SELECT\b/.test(sql)||sql.includes(';'))throw Error('operator_query_changed');
    captured={sql,params:[]};
    return {bind(...params){captured.params=params;return this;},async first(){return null;}};
  }}};
  try {await recoverSceneReceipt(env,target,recoveryCode);throw Error('operator_capture_unexpected_success');}
  catch(error){if(error.message!=='unauthorized'||!captured)throw error;}
  if(!captured||!captured.params.length)throw Error('operator_query_missing');
  // The schema revision and receipt row are read in the same SELECT snapshot.
  // RecoverSceneReceipt still validates the actual returned schema and all
  // account/deletion/lease/publication/original-award fences afterward.
  return {sql:`SELECT receipt.*, revision.revision AS observed_schema_revision,
    revision.contract AS observed_schema_contract
    FROM (${captured.sql}) receipt CROSS JOIN (${SCHEMA_READ}) revision`,params:captured.params};
}

export function operatorSqlFile(query) {
  let next=0;
  const sql=query.sql.replaceAll('?',()=>{
    const value=query.params[next++];
    if(typeof value!=='string')throw Error('operator_parameter_invalid');
    return "'"+value.replaceAll("'","''")+"'";
  });
  if(next!==query.params.length)throw Error('operator_parameter_count');
  return sql+';\n';
}

export async function validateOperatorReadback(target,recoveryCode,response) {
  if(!Array.isArray(response)||response.length!==1||response[0].success!==true)
    throw Error('operator_response_invalid');
  const {meta,results}=response[0];
  if(!Number.isSafeInteger(meta?.rows_read)||meta.rows_read<0||meta.rows_read>200
    ||meta.rows_written!==0||meta.total_attempts!==1)throw Error('operator_usage_invalid');
  if(!Array.isArray(results)||results.length!==1)throw Error('operator_receipt_missing');
  const row=results[0],expected=await prepareOperatorReadback(target,recoveryCode);
  const env={DB:{prepare(sql){
    if(sql===SCHEMA_READ)return {async first(){return {
      revision:row.observed_schema_revision,contract:row.observed_schema_contract};}};
    // Verify the offline replay executes exactly the captured receipt query.
    if(!expected.sql.includes(`FROM (${sql}) receipt CROSS JOIN`))throw Error('operator_query_changed');
    return {bind(...params){
      if(JSON.stringify(params)!==JSON.stringify(expected.params))throw Error('operator_parameters_changed');
      return this;
    },async first(){return row;}};
  }}};
  const reply=await recoverSceneReceipt(env,target,recoveryCode);
  return {reply,observedUsage:{read:meta.rows_read,written:0}};
}

export async function validateOperatorPair(target,recoveryCode,responses) {
  if(!Array.isArray(responses)||responses.length!==2)throw Error('operator_pair_required');
  const first=await validateOperatorReadback(target,recoveryCode,responses[0]);
  const second=await validateOperatorReadback(target,recoveryCode,responses[1]);
  if(first.observedUsage.read+second.observedUsage.read>200)throw Error('operator_usage_limit');
  if(JSON.stringify(first.reply)!==JSON.stringify(second.reply))throw Error('operator_receipt_changed');
  return {status:'OPERATOR_EXISTING_SCENE_RECEIPT_RECONCILED',readOnly:true,
    targetSha256:await sha256Hex(encodeUtf8(canonicalRecoveryTarget(target))),
    reply:first.reply,observedUsage:{read:first.observedUsage.read+second.observedUsage.read,written:0},
    gatewayAuthenticationVerified:false,r2ArtifactRead:false,qualificationRenewed:false,
    newAssignment:false,nativeInference:false,productionQualified:false};
}
