// Local-only prototype transport regression. Synthetic bytes/coverage are not
// native qualification, and the real hosted Object gate must stay closed.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import worker from './worker.js';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {syntheticR2} from './syntheticR2.mjs';
import {sha256Hex,encodeUtf8} from './model.js';
import {validateObjectIndex,OBJECT_INDEX_MODEL} from './objectIndex.js';
import {publicObjectManifest} from './objectPublicManifest.js';
import {COVERAGE_VALIDATOR} from './objectCoverage.js';
import {deleteAccount,cleanupAccountArtifacts} from './accountPrivacy.js';
import {PRIVACY_FENCE} from './artifactWrites.js';
const fixtureDoc=JSON.parse(readFileSync(new URL('../../../community/tests/fixtures/object-feature-content-v1.json',import.meta.url),'utf8'));
const account='a'.repeat(32),token='synthetic-local-object-session';
async function setup(t) {
  const sql=new DatabaseSync(':memory:');t.after(()=>sql.close());
  const objects=new Map(),env={DB:sqliteD1(sql),INDEX:syntheticR2(objects),OBJECT_PROTOTYPE_TEST_ONLY:'1'};
  await prepareDatabase(env.DB);
  sql.prepare('INSERT INTO accounts(id,token_hash,units) VALUES (?,?,10)').run(account,await sha256Hex(encodeUtf8(token)));
  sql.prepare("INSERT INTO leases(id,account_id,lane,expires_at,state) VALUES (?,?,'object',?,'active')")
    .run(fixtureDoc.leaseId,account,Math.floor(Date.now()/1000)+3600);
  for(const item of fixtureDoc.items) {
    sql.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,lat,lon,camera_generation)
      VALUES (?,?,'synthetic','object','synthetic','leased',?,?,?,'gen4')`)
      .run(item.locationId,item.panoId,fixtureDoc.leaseId,item.lat,item.lng);
    sql.prepare('INSERT INTO lease_items VALUES (?,?)').run(fixtureDoc.leaseId,item.locationId);
    sql.prepare('INSERT INTO object_coverage VALUES (?,?,?,1)').run(item.locationId,COVERAGE_VALIDATOR,'f'.repeat(64));
  }
  const doc=structuredClone(fixtureDoc.baseline);
  Object.assign(doc.manifest.viewQuality,{policy:'vision-per-view-quality-v1',implementationIdentity:'1'.repeat(64),viewCount:6,
    blurAreaFractionExclusive:0.5,tileGrid:8,tunnelVisionProbabilityInclusive:0.85,
    tunnelEvidencePolicy:'none-darkness-never-rejects-v1',protectedAuthorityManifestSha256:'2'.repeat(64)});
  const files=Object.fromEntries(Object.entries(doc.filesBase64)
    .map(([key,value])=>[key,new Uint8Array(Buffer.from(value,'base64'))]));
  const rows=await validateObjectIndex(doc.manifest,files,new Uint8Array(Buffer.from(doc.sourceBase64,'base64')),fixtureDoc.items,fixtureDoc.leaseId);
  const body={leaseId:fixtureDoc.leaseId,outputs:rows.map(row=>({...row,model:OBJECT_INDEX_MODEL})),
    objectIndex:{manifest:doc.manifest,files:doc.filesBase64,sourceTsv:doc.sourceBase64}};
  const call=(url='https://community.test/api/submissions')=>worker.fetch(new Request(url,{
    method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+token},body:JSON.stringify(body)}),env);
  return {sql,env,objects,call,body};
}
test('actual local prototype route journals all Object files and replay credits nothing again',async t=>{
  const {sql,objects,call,body}=await setup(t);
  const privateText='SYNTHETIC-PRIVATE-ACCOUNT-AND-PATH';
  body.objectIndex.manifest.sourceTsv='C:/'+privateText+'/source.tsv';
  body.objectIndex.manifest.private={secret:privateText};
  body.objectIndex.manifest.contractVersions.private={secret:privateText};
  for(const key of ['offsets','metadata','globalIds','semantic','viewQuality'])body.objectIndex.manifest[key].private={secret:privateText};
  for(const entry of [...body.objectIndex.manifest.classes,...body.objectIndex.manifest.hotConcepts])entry.private={secret:privateText};
  const first=await call();assert.equal(first.status,200,await first.clone().text());
  const result=await first.json();assert.equal(result.accepted,2);assert.equal(result.unitsEarned,20);
  const raw=objects.get(`object-index-v4/${body.leaseId}/manifest.json`),manifest=JSON.parse(new TextDecoder().decode(raw));
  assert.equal(manifest.sourceTsv,'locations.tsv');assert.equal(new TextDecoder().decode(raw).includes(privateText),false);
  assert.equal(manifest.sourceSha256,body.objectIndex.manifest.sourceSha256);
  assert.deepEqual(manifest.viewQuality,publicObjectManifest(body.objectIndex.manifest).viewQuality);
  assert.equal(objects.size,Object.keys(body.objectIndex.files).length+2);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM account_artifact_writes').get().n,objects.size);
  assert.equal(sql.prepare("SELECT count(*) AS n FROM ledger WHERE reason='verified_work'").get().n,1);
  const replay=await call();assert.equal(replay.status,200);assert.equal((await replay.json()).unitsEarned,0);
  assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,30);
});
test('account deletion during actual Object route upload prevents publication and credit',async t=>{
  const {sql,env,objects,call}=await setup(t),put=env.INDEX.put;
  let first=true;
  env.INDEX.put=async(...args)=>{
    const result=await put(...args);
    if(first){first=false;await deleteAccount(env,account,
      {accountId:account,confirmation:'DELETE',idempotencyKey:'c'.repeat(64)},1234);
      await cleanupAccountArtifacts(env,account,64);}
    return result;
  };
  const response=await call();assert.equal(response.status,401);
  assert.deepEqual(await response.json(),{error:'unauthorized'});
  assert.equal(sql.prepare('SELECT count(*) AS n FROM published_index').get().n,0);
  assert.equal(sql.prepare("SELECT count(*) AS n FROM ledger WHERE reason='verified_work'").get().n,0);
  assert.equal(sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,0);
  assert.equal(objects.size,1);
  assert.equal(new TextDecoder().decode([...objects.values()][0]),PRIVACY_FENCE);
});
test('the same synthetic route fixture cannot open the hosted Object gate',async t=>{
  const {sql,objects,call}=await setup(t);
  const response=await call('https://vision-community-staging.visioncommunity.workers.dev/api/submissions');
  assert.equal(response.status,503);assert.deepEqual(await response.json(),{error:'object_verification_unavailable'});
  assert.equal(objects.size,0);assert.equal(sql.prepare('SELECT count(*) AS n FROM account_artifact_writes').get().n,0);
});

test('incomplete or retired quality metadata cannot create publication, artifact intents or credits',async t=>{
  for(const change of [{policy:'old'},{protectedAuthorityManifestSha256:null},{tunnelEvidencePolicy:'none-darkness-kept-v1'},
    {keptViews:{private:'SYNTHETIC-PRIVATE'}}]){
    const f=await setup(t);Object.assign(f.body.objectIndex.manifest.viewQuality,change);
    const response=await f.call();assert.equal(response.status,422);assert.deepEqual(await response.json(),{error:'verification_failed'});
    assert.equal(f.objects.size,0);assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM account_artifact_writes').get().n,0);
    assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM published_index').get().n,0);
    assert.equal(f.sql.prepare('SELECT COUNT(*) AS n FROM ledger').get().n,0);
    assert.equal(f.sql.prepare('SELECT units FROM accounts WHERE id=?').get(account).units,10);
  }
});
