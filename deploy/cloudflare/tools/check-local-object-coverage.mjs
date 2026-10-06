// Finite synthetic actual workerd/D1 transactions. No live coverage or cloud API.
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {prepareDatabase} from './initialize-schema.mjs';
import {coverageFixture} from './object-coverage.fixture.mjs';
import {prepareCoverage,coveragePlan} from './import-object-coverage.mjs';
import {objectCoverageComplete} from '../src/objectCoverage.js';
const {Miniflare,convertV4MiniflareOptions}=await import(pathToFileURL(resolve(process.argv[2])).href);
const options={modules:true,script:'export default {fetch(){return new Response("offline synthetic coverage");}};',
  compatibilityDate:'2026-09-19',compatibilityFlags:['nodejs_compat'],d1Databases:['DB']};
const mf=new Miniflare(convertV4MiniflareOptions?convertV4MiniflareOptions(options):options);
try {
  const db=await mf.getD1Database('DB');await prepareDatabase(db);
  const packet=prepareCoverage(coverageFixture({rows:3})),plan=coveragePlan(packet);
  const execute=items=>db.batch(items.map(({sql,params})=>db.prepare(sql).bind(...params)));
  const count=async table=>(await db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).first()).n;
  const noGuard=async()=>assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name='community_object_import_guard'").first()).n,0);
  await assert.rejects(execute([...plan.slice(0,-1),{sql:'INSERT INTO community_object_import_guard VALUES(0)',params:[]} ]));
  assert.equal(await count('locations'),0);assert.equal(await count('object_coverage'),0);await noGuard();
  await execute(plan);await execute(plan);
  const rows=(await db.prepare('SELECT * FROM locations ORDER BY id').all()).results;
  assert.equal(rows.length,3);assert.equal(await objectCoverageComplete(db,rows),true);
  await db.prepare("UPDATE object_coverage SET validator='official-gen4-historical-v1' WHERE location_id=2").run();
  assert.equal(await objectCoverageComplete(db,rows),false);
  await assert.rejects(execute(plan));await noGuard();
  await db.prepare("UPDATE object_coverage SET validator='official-gen4-historical-v2-exact-pano' WHERE location_id=2").run();
  assert(rows.every(row=>row.state==='pending'&&row.contributor_id===null&&row.output_sha256===null));
  await noGuard();
  await db.prepare("UPDATE locations SET state='leased',active_lease='saved',lease_until=123 WHERE id=1").run();
  await execute(plan);assert.equal((await db.prepare('SELECT active_lease FROM locations WHERE id=1').first()).active_lease,'saved');
  await db.prepare('UPDATE locations SET lat=11 WHERE id=2').run();
  await assert.rejects(execute(plan));await noGuard();
  assert.equal((await db.prepare('SELECT lat FROM locations WHERE id=2').first()).lat,11);
  await db.prepare('UPDATE locations SET lat=10.25 WHERE id=2').run();
  await db.prepare('DELETE FROM object_coverage WHERE location_id=1').run();
  await assert.rejects(execute(plan));await noGuard();assert.equal(await count('object_coverage'),2);
  for(const table of ['accounts','leases','published_index','ledger','searches'])assert.equal(await count(table),0);
  console.log(JSON.stringify({status:'SYNTHETIC_OBJECT_COVERAGE_D1_PASSED',records:3,replay:true,lateRollback:true,
    changedPoseRefused:true,uncertifiedActiveRefused:true,creditsChanged:false,liveCoverage:false,cloudResourcesAccessed:false}));
}finally{await mf.dispose();}
