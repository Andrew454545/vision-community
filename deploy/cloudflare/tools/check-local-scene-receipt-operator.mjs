// One focused actual local workerd/D1 test of the new single-SELECT packet.
// Synthetic accounts, authority, features and provider-attempt metadata only.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {prepareDatabase} from './initialize-schema.mjs';
import {prepareOperatorReadback,operatorSqlFile,validateOperatorReadback,validateOperatorPair} from './scene-receipt-operator.mjs';
import {RECOVERY_PEPPER} from '../src/model.js';
import {deleteAccount} from '../src/accountPrivacy.js';
const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(process.argv[2])).href);
const hash=v=>createHash('sha256').update(v).digest('hex');
const account='a'.repeat(32),lease='b'.repeat(32),code='synthetic-code-123456';
const target={accountId:account,leaseId:lease,payloadSha256:'c'.repeat(64),policyId:'qualified-device-v1|staging.synthetic',
  records:[{locationId:81,outputSha256:'d'.repeat(64)},{locationId:82,outputSha256:'f'.repeat(64)}]};
const options={modules:true,script:'export default {fetch(){return new Response("local");}}',
  compatibilityDate:'2026-09-19',resourcePersistencePath:mkdtempSync(join(tmpdir(),'receipt-operator-')),d1Databases:['DB']};
const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
let checks=0;const usage=[];
try{
  const db=await mf.getD1Database('DB');await prepareDatabase(db);
  await db.prepare('INSERT INTO accounts(id,token_hash,recovery_hash,units) VALUES(?,?,?,102)')
    .bind(account,hash('synthetic-session'),hash(RECOVERY_PEPPER+'\n'+code)).run();
  await db.prepare('INSERT INTO scene_qualifications VALUES(?,?,?,?,?,?,?)')
    .bind('synthetic-qualification',account,'1'.repeat(64),'staging.synthetic','2'.repeat(64),1,0).run();
  await db.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES(?,?,'scene',1,'submitted')").bind(lease,account).run();
  for(const record of target.records){
    await db.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,contributor_id,output_sha256)
      VALUES(?,'fixture-'||?,'fixture','scene','fixture','published',?,?)`).bind(record.locationId,record.locationId,account,record.outputSha256).run();
    await db.prepare('INSERT INTO lease_items VALUES(?,?)').bind(lease,record.locationId).run();
    await db.prepare(`INSERT INTO published_index(location_id,index_text,output_sha256,published_at,four_view_sha256,four_view_key)
      VALUES(?,'',?,0,?,?)`).bind(record.locationId,record.outputSha256,record.outputSha256,`four-view-v4/${lease}.i8`).run();
  }
  await db.prepare("INSERT INTO scene_candidates VALUES(?,?,?,?,?,?,?,0,'published')")
    .bind(lease,account,'synthetic-qualification',target.policyId,'3'.repeat(64),'fixture-quarantine',JSON.stringify(target.records)).run();
  await db.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES(?,2,'qualified_device_work',?)").bind(account,'lease:'+lease).run();
  await db.prepare(`WITH RECURSIVE n(x) AS(VALUES(1000) UNION ALL SELECT x+1 FROM n WHERE x<2023)
    INSERT INTO locations(id,asset_id,capture,lane,model,state) SELECT x,'old-'||x,'fixture','scene','fixture','published' FROM n`).run();
  const query=await prepareOperatorReadback(target,code);
  async function read(q=query){
    const result=await db.prepare(operatorSqlFile(q)).all();
    usage.push({read:result.meta.rows_read,written:result.meta.rows_written});
    // Local D1 lacks the remote API's total_attempts; exactly one local all()
    // call supplies this synthetic provider field, not hosted retry evidence.
    return [{...result,meta:{...result.meta,total_attempts:1}}];
  }
  const first=await read(),second=await read();
  const pair=await validateOperatorPair(target,code,[first,second]);
  assert.equal(pair.reply.originalAwardUnits,2);assert.equal(pair.reply.unitsEarned,0);checks++;
  assert.ok(pair.observedUsage.read<100);assert.equal(pair.observedUsage.written,0);checks++;
  assert.equal((await db.prepare('SELECT COUNT(*) n FROM ledger').first()).n,1);checks++;
  const wrong=await prepareOperatorReadback(target,'wrong-code-123456');
  await assert.rejects(validateOperatorReadback(target,code,await read(wrong)),/missing/);checks++;
  await db.prepare('UPDATE community_schema_revision SET revision=2 WHERE slot=1').run();
  await assert.rejects(validateOperatorReadback(target,code,await read()),/schema_update_required/);checks++;
  await db.prepare('UPDATE community_schema_revision SET revision=1 WHERE slot=1').run();
  await db.prepare('UPDATE published_index SET output_sha256=? WHERE location_id=81').bind('4'.repeat(64)).run();
  await assert.rejects(validateOperatorReadback(target,code,await read()),/scene_receipt_conflict/);checks++;
  await db.prepare('UPDATE published_index SET output_sha256=? WHERE location_id=81').bind(target.records[0].outputSha256).run();
  await deleteAccount({DB:db},account,{accountId:account,confirmation:'DELETE',idempotencyKey:'9'.repeat(64)});
  await assert.rejects(validateOperatorReadback(target,code,await read()),/missing/);checks++;
  assert.equal((await db.prepare('SELECT units FROM accounts WHERE id=?').bind(account).first()).units,0);checks++;
  console.log(JSON.stringify({status:'LOCAL_RECEIPT_OPERATOR_PASS',checks,usage,
    firstPairRowsRead:pair.observedUsage.read,syntheticPublishedBackgroundRows:1024,
    actualLocalWorkerdD1:true,providerAttemptFieldSynthetic:true,r2BindingAbsent:true,
    authorityAndOutputsSynthetic:true,cloudAccess:false,nativeInference:false,productionQualified:false}));
}finally{await mf.dispose();}
