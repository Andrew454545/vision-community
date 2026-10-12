// Finite local workerd/D1/R2 prototype checks, never real admission or earnings.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {prepareDatabase} from './initialize-schema.mjs';
import {sha256Hex,encodeUtf8} from '../src/model.js';
import {validateObjectIndex,OBJECT_INDEX_MODEL} from '../src/objectIndex.js';
import {publicObjectManifest} from '../src/objectPublicManifest.js';
import {COVERAGE_VALIDATOR} from '../src/objectCoverage.js';
const [mfPath,bundle,persistence,phase]=process.argv.slice(2),script=fileURLToPath(import.meta.url);
if(!phase){
  let cases=0;
  for(const stage of ['seed','recover']){
    const child=spawnSync(process.execPath,[script,mfPath,bundle,persistence,stage],{
      env:process.env,windowsHide:true,timeout:90000,encoding:'utf8'});
    assert.equal(child.status,0,child.stderr||child.stdout);cases+=JSON.parse(child.stdout.trim()).cases;
  }
  console.log(JSON.stringify({status:'ACTUAL_WORKERD_OBJECT_PUBLICATION_PRIVACY_PASSED',cases,separateProcesses:2,
    syntheticInference:true,syntheticCreditedUnits:20,publicAdmission:false,realAcceptedContributions:0,realEarnedCredits:0,liveCalls:0}));
}else{
  const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(mfPath)).href);
  const options={modules:[{type:'ESModule',path:resolve(bundle)}],modulesRoot:dirname(resolve(bundle)),
    compatibilityDate:'2026-09-19',compatibilityFlags:['nodejs_compat'],
    d1Databases:{DB:'00000000-0000-4000-8000-000000000334'},r2Buckets:['INDEX'],
    bindings:{OBJECT_PROTOTYPE_TEST_ONLY:'1'},
    ...(convertV4MiniflareOptions?{resourcePersistencePath:resolve(persistence)}:{d1Persist:resolve(persistence,'d1'),r2Persist:resolve(persistence,'r2')})};
  const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);let cases=0;
  try{
    const db=await mf.getD1Database('DB'),bucket=await mf.getR2Bucket('INDEX');
    const fixture=JSON.parse(readFileSync(new URL('../../../community/tests/fixtures/object-feature-content-v1.json',import.meta.url),'utf8'));
    const account='b'.repeat(32),lease=fixture.leaseId,token='synthetic-local-publication',marker='SYNTHETIC-PRIVATE-ACCOUNT-AND-PATH';
    const index={manifest:structuredClone(fixture.baseline.manifest),files:fixture.baseline.filesBase64,sourceTsv:fixture.baseline.sourceBase64};
    Object.assign(index.manifest.viewQuality,{policy:'vision-per-view-quality-v1',implementationIdentity:'1'.repeat(64),viewCount:6,
      blurAreaFractionExclusive:0.5,tileGrid:8,tunnelVisionProbabilityInclusive:0.85,
      tunnelEvidencePolicy:'none-darkness-never-rejects-v1',protectedAuthorityManifestSha256:'2'.repeat(64)});
    index.manifest.sourceTsv='C:/'+marker+'/source.tsv';index.manifest.private={secret:marker};
    index.manifest.contractVersions.private={secret:marker};
    for(const key of ['offsets','metadata','globalIds','semantic','viewQuality'])index.manifest[key].private={secret:marker};
    for(const entry of [...index.manifest.classes,...index.manifest.hotConcepts])entry.private={secret:marker};
    const source=new Uint8Array(Buffer.from(index.sourceTsv,'base64'));
    const files=Object.fromEntries(Object.entries(index.files).map(([k,v])=>[k,new Uint8Array(Buffer.from(v,'base64'))]));
    const records=await validateObjectIndex(index.manifest,files,source,fixture.items,lease);
    const body={leaseId:lease,outputs:records.map(row=>({...row,model:OBJECT_INDEX_MODEL})),objectIndex:index};
    const call=(payload=body,origin='https://community.test')=>mf.dispatchFetch(origin+'/api/submissions',{
      method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+token},
      body:JSON.stringify(payload),signal:AbortSignal.timeout(15000)});
    const state=async()=>({owner:await db.prepare('SELECT units,deleted_at FROM accounts WHERE id=?').bind(account).first(),
      publications:(await db.prepare('SELECT COUNT(*) AS n FROM published_index').first()).n,
      credits:(await db.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='verified_work'").first()).n,
      intents:(await db.prepare('SELECT COUNT(*) AS n FROM account_artifact_writes').first()).n,
      objects:(await bucket.list()).objects.length});
    if(phase==='seed'){
      await prepareDatabase(db);
      await db.prepare('INSERT INTO accounts(id,token_hash,units) VALUES (?,?,0)').bind(account,await sha256Hex(encodeUtf8(token))).run();
      await db.prepare("INSERT INTO leases(id,account_id,lane,state,expires_at) VALUES (?,?,'object','active',?)")
        .bind(lease,account,Math.floor(Date.now()/1000)+3600).run();
      for(const item of fixture.items)await db.batch([
        db.prepare(`INSERT INTO locations(id,asset_id,capture,lane,model,state,active_lease,camera_generation,lat,lon)
          VALUES (?,?,'synthetic','object','synthetic','leased',?,'gen4',?,?)`)
          .bind(item.locationId,item.panoId,lease,item.lat,item.lng),
        db.prepare('INSERT INTO lease_items VALUES (?,?)').bind(lease,item.locationId),
        db.prepare('INSERT INTO object_coverage VALUES (?,?,?,1)').bind(item.locationId,COVERAGE_VALIDATOR,'d'.repeat(64)),
      ]);
      const before=await state();
      const gated=await call(body,'https://vision-community-staging.visioncommunity.workers.dev');
      assert.equal(gated.status,503);assert.deepEqual(await gated.json(),{error:'object_verification_unavailable'});
      assert.deepEqual(await state(),before);cases++;
      for(const change of [{policy:'old'},{protectedAuthorityManifestSha256:null},
        {tunnelEvidencePolicy:'none-darkness-kept-v1'},{keptViews:{private:marker}}]){
        const damaged=structuredClone(body);Object.assign(damaged.objectIndex.manifest.viewQuality,change);
        const response=await call(damaged);assert.equal(response.status,422);assert.deepEqual(await response.json(),{error:'verification_failed'});
        assert.deepEqual(await state(),before);cases++;
      }
      const response=await call();assert.equal(response.status,200,await response.clone().text());
      assert.deepEqual(await response.json(),{accepted:2,unitsEarned:20,replayed:false,segments:[]});cases++;
    }else{
      const before=await state(),response=await call();assert.equal(response.status,200);
      const reply=await response.json();assert.equal(reply.accepted,2);assert.equal(reply.unitsEarned,0);assert.equal(reply.replayed,true);
      assert.deepEqual(await state(),before);cases++;
    }
    const prefix=`object-index-v4/${lease}/`,raw=new Uint8Array(await (await bucket.get(prefix+'manifest.json')).arrayBuffer());
    const projected=JSON.parse(new TextDecoder().decode(raw));
    assert.equal(new TextDecoder().decode(raw).includes(marker),false);assert.deepEqual(projected,publicObjectManifest(index.manifest));
    const intent=await db.prepare('SELECT sha256,bytes FROM account_artifact_writes WHERE artifact_key=?').bind(prefix+'manifest.json').first();
    assert.deepEqual(intent,{sha256:await sha256Hex(raw),bytes:raw.length});
    assert.deepEqual(new Uint8Array(await (await bucket.get(prefix+'locations.tsv')).arrayBuffer()),source);
    for(const [name,bytes] of Object.entries(files))assert.deepEqual(new Uint8Array(await (await bucket.get(prefix+name)).arrayBuffer()),bytes);
    assert.deepEqual(await validateObjectIndex(projected,files,source,fixture.items,lease),records);
    const final=await state();assert.equal(final.publications,2);assert.equal(final.credits,1);assert.equal(final.owner.units,20);
    assert.equal(final.intents,Object.keys(files).length+2);assert.equal(final.objects,final.intents);cases++;
    const status=await mf.dispatchFetch('https://community.test/api/capabilities',{signal:AbortSignal.timeout(15000)});
    assert.equal(status.status,200);assert.equal((await status.json()).objectContributions.ready,false);cases++;
    console.log(JSON.stringify({phase,cases}));
  }finally{await mf.dispose();}
}
