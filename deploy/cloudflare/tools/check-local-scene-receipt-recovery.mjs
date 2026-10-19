// Actual local workerd/D1; every account/feature/publication is synthetic.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve,dirname,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {prepareDatabase} from './initialize-schema.mjs';
import {canonicalRecoveryTarget,recoverSceneReceipt} from './scene-receipt-recovery.mjs';
import {RECOVERY_PEPPER} from '../src/model.js';
import {deleteAccount} from '../src/accountPrivacy.js';
const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(process.argv[2])).href);
const hash=v=>createHash('sha256').update(v).digest('hex');
const account='a'.repeat(32),lease='b'.repeat(32),code='synthetic-code-123456',token='e'.repeat(64);
const target={accountId:account,leaseId:lease,payloadSha256:'c'.repeat(64),policyId:'qualified-device-v1|staging.synthetic',
  records:[{locationId:81,outputSha256:'d'.repeat(64)},{locationId:82,outputSha256:'f'.repeat(64)}]};
const path=resolve(process.argv[3]);
const options={modules:true,scriptPath:path,modulesRoot:dirname(path),compatibilityDate:'2026-09-19',
  compatibilityFlags:['nodejs_compat'],resourcePersistencePath:mkdtempSync(join(tmpdir(),'scene-receipt-')),
  d1Databases:['DB'],bindings:{DEPLOYMENT_ENVIRONMENT:'staging',INDEX_BUCKET_NAME:'vision-community-staging',
    DELETION_ARCHIVE_DB_ID:'17043cb7-5dab-4a6f-84ca-19ae1c14cc05',SCENE_RECOVERY_ACCOUNT:'272760294910ef0b246980278aeb36e2',
    SCENE_RECOVERY_UNTIL:String(Date.now()+600000),SCENE_RECOVERY_TOKEN_SHA256:hash(token),
    SCENE_RECOVERY_TARGET_SHA256:hash(canonicalRecoveryTarget(target))}};
const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
let checks=0;const attempts=[];
async function call(body={target,recoveryCode:code},route='/api/scene-receipt-recovery',credential=token){
  const res=await mf.dispatchFetch('https://fixture.test'+route,{method:'POST',body:JSON.stringify(body),headers:{
    origin:'https://fixture.test','content-type':'application/json','x-vision-finite-cohort':credential,
    'x-vision-trial-remaining-read':'200','x-vision-trial-remaining-written':'0',
    'x-vision-trial-remaining-puts':'0','x-vision-trial-remaining-bytes':'0'}});
  const usage={};
  if(res.headers.get('x-vision-trial-usage-complete')==='1')for(const [key,name]of
    Object.entries({read:'rows-read',written:'rows-written',puts:'r2-puts',bytes:'r2-bytes'})){
    usage[key]=Number(res.headers.get('x-vision-trial-'+name));assert.ok(Number.isSafeInteger(usage[key]));
  }
  attempts.push({path:route,status:res.status,usage});return res;
}
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
  await db.prepare(`INSERT INTO scene_candidates VALUES(?,?,?,?,?,?,?,0,'published')`)
    .bind(lease,account,'synthetic-qualification',target.policyId,'3'.repeat(64),'fixture-quarantine',JSON.stringify(target.records)).run();
  await db.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES(?,2,'qualified_device_work',?)")
    .bind(account,'lease:'+lease).run();
  await db.prepare(`WITH RECURSIVE n(x) AS(VALUES(1000) UNION ALL SELECT x+1 FROM n WHERE x<2023)
    INSERT INTO locations(id,asset_id,capture,lane,model,state) SELECT x,'old-'||x,'fixture','scene','fixture','published' FROM n`).run();
  assert.equal((await recoverSceneReceipt({DB:db},target,code)).originalAwardUnits,2);checks++;
  assert.equal((await call(undefined,undefined,'f'.repeat(64))).status,403);checks++;
  assert.equal((await call(undefined,'/api/submissions')).status,404);checks++;
  assert.equal((await call({target:{...target,leaseId:'f'.repeat(32)},recoveryCode:code})).status,409);checks++;
  assert.equal((await call({target,recoveryCode:'wrong-code-123456'})).status,401);checks++;
  const first=await call();assert.equal(first.status,200,JSON.stringify({attempt:attempts.at(-1),reply:await first.clone().json()}));const original=await first.json();
  assert.equal(original.accepted,2);assert.equal(original.originalAwardUnits,2);assert.equal(original.currentUnits,102);checks++;
  assert.equal(original.unitsEarned,0);assert.equal(original.auditReplay.replayed,true);assert.equal(original.qualificationRenewed,false);checks++;
  const second=await call();assert.equal(second.status,200);assert.deepEqual(await second.json(),original);checks++;
  for(const attempt of attempts.filter(a=>a.status===200)){
    assert.ok(attempt.usage.read<100);assert.equal(attempt.usage.written,0);assert.equal(attempt.usage.puts,0);checks++;
  }
  const savedToken=(await db.prepare('SELECT token_hash FROM accounts WHERE id=?').bind(account).first()).token_hash;
  assert.equal(savedToken,hash('synthetic-session'));checks++;
  assert.equal((await db.prepare('SELECT COUNT(*) n FROM ledger').first()).n,1);checks++;
  await assert.rejects(db.prepare("INSERT INTO ledger(account_id,units,reason,reference) VALUES(?,2,'qualified_device_work',?)")
    .bind(account,'lease:'+lease).run());checks++;
  await db.prepare('UPDATE published_index SET output_sha256=? WHERE location_id=81').bind('4'.repeat(64)).run();
  assert.equal((await call()).status,409);checks++;
  await db.prepare('UPDATE published_index SET output_sha256=? WHERE location_id=81').bind(target.records[0].outputSha256).run();
  await db.prepare('UPDATE ledger SET units=1 WHERE reference=?').bind('lease:'+lease).run();
  assert.equal((await call()).status,409);checks++;
  await db.prepare('UPDATE ledger SET units=2 WHERE reference=?').bind('lease:'+lease).run();
  const deleted=await deleteAccount({DB:db},account,{accountId:account,confirmation:'DELETE',idempotencyKey:'9'.repeat(64)});
  assert.equal(deleted.deleted,true);checks++;
  assert.equal((await call()).status,401);checks++;
  assert.equal((await db.prepare('SELECT units FROM accounts WHERE id=?').bind(account).first()).units,0);checks++;
  // Account deletion preserves accepted pool work and its historical award;
  // recovery must not resurrect the account or its forfeited banked balance.
  assert.equal((await db.prepare('SELECT COUNT(*) n FROM published_index').first()).n,2);checks++;
  console.log(JSON.stringify({status:'LOCAL_SCENE_RECEIPT_RECOVERY_PASS',checks,attempts,
    syntheticPublishedBackgroundRows:1024,actualLocalWorkerdD1:true,r2BindingAbsent:true,
    authorityAndOutputsSynthetic:true,cloudAccess:false,nativeInference:false,productionQualified:false}));
}finally{await mf.dispose();}
