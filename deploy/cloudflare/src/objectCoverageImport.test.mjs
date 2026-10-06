import assert from 'node:assert/strict';
import test from 'node:test';
import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync,mkdirSync,readFileSync,writeFileSync,rmSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {coverageFixture,repin} from '../tools/object-coverage.fixture.mjs';
import {prepareCoverage,coveragePlan,saveCoveragePlan,tsv,digest} from '../tools/import-object-coverage.mjs';
import {prepareDatabase} from '../tools/initialize-schema.mjs';
import {sqliteD1} from '../tools/sqlite-d1.mjs';
import {objectCoverageComplete} from './objectCoverage.js';
import {objectCapabilities} from './objectAdmission.js';
const change=(fixture,edit)=>{const m=JSON.parse(fixture.manifest);edit(m,fixture);return repin(m,fixture);};
test('pinned current validator output preserves historical pose without publication, credits or admission',async()=>{
  const fixture=coverageFixture({rows:2,rejections:1,provenance:'private "operator" path'}),packet=prepareCoverage(fixture);
  assert.equal(packet.records.length,2);assert.equal(packet.records[0].capture,'2020-06');assert.equal(packet.records[0].heading,90.25);
  assert(!JSON.stringify(packet).includes('operator'));assert.equal(objectCapabilities().objectContributions.ready,false);
  const sql=new DatabaseSync(':memory:'),db=sqliteD1(sql);
  try {
    await prepareDatabase(db);const plan=coveragePlan(packet);
    const apply=()=>db.batch(plan.map(({sql,params})=>db.prepare(sql).bind(...params)));
    await apply();await apply();
    const rows=sql.prepare('SELECT * FROM locations ORDER BY id').all();assert.equal(rows.length,2);
    assert(rows.every(r=>r.state==='pending'&&r.contributor_id===null&&r.output_sha256===null));
    assert(await objectCoverageComplete(db,rows));
    for(const table of ['accounts','leases','published_index','ledger','searches'])assert.equal(sql.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n,0);
    // An exact retry may preserve genuinely advanced work, but cannot modify it.
    sql.exec("UPDATE locations SET state='leased',active_lease='saved',lease_until=123 WHERE id=1");
    await apply();assert.equal(sql.prepare('SELECT active_lease FROM locations WHERE id=1').get().active_lease,'saved');
  }finally{sql.close();}
});
for(const [name,edit] of [
  ['older timeline policy',m=>{m.validatorPolicy='strict-google-official-historical-v6-2026-09-12';}],
  ['future completion',m=>{m.completedAt=new Date(Date.now()+86400000).toISOString();}],
  ['stale completion',m=>{m.completedAt='2020-01-01T00:00:00Z';}],
  ['long stale cache',m=>{m.cacheMaxAgeDays=31;}],
  ['incomplete invariant',m=>{m.invariants.normalizedRowsAreStrictlyOfficial=false;}],
  ['wrong row count',m=>{m.counts.inputRows++;}],
  ['country mismatch',(m,f)=>{f.accepted=Buffer.from(f.accepted.toString().replace('USA','Italy'));}],
  ['historical ID replacement',(m,f)=>{f.accepted=Buffer.from(f.accepted.toString().replace('fixture00000000000000A','replaced0000000000000A'));}],
  ['pose replacement',(m,f)=>{f.accepted=Buffer.from(f.accepted.toString().replace('90.25','91.25'));}],
  ['unofficial label',(m,f)=>{f.accepted=Buffer.from(f.accepted.toString().replace('\tofficial\t','\tunofficial\t'));}],
  ['bad pano bits',(m,f)=>{f.input=Buffer.from(f.input.toString().replace('fixture00000000000000A','fixture00000000000000x'));f.accepted=Buffer.from(f.accepted.toString().replace('fixture00000000000000A','fixture00000000000000x'));}],
  ['unaccounted rejected row',(m,f)=>{f.denied=Buffer.from(f.denied.toString()+'extra\n');}]
])test('coverage refuses '+name,()=>assert.throws(()=>prepareCoverage(change(coverageFixture(),edit))));
test('receipt pins reject changed bytes before trusting labels',()=>{
  for(const name of ['manifest','input','countries','accepted','denied']) {
    const fixture=coverageFixture();fixture[name]=Buffer.concat([fixture[name],Buffer.from(' ')]);
    assert.throws(()=>prepareCoverage(fixture));
  }
});
test('camera labels other than exact Gen4 cannot enter Object work',()=>{
  for(const generation of ['gen1','gen2','gen3','trekker','badcam','unknown','Gen4'])assert.throws(()=>prepareCoverage(coverageFixture({generation})));
});
test('duplicate rows cannot inflate coverage and partial packets cannot omit rejections',()=>{
  const fixture=coverageFixture({rows:2});
  const edited=change(fixture,(m,f)=>{
    const lines=f.input.toString().trimEnd().split('\n');lines[2]=lines[1];f.input=Buffer.from(lines.join('\n')+'\n');
    const valid=f.accepted.toString().trimEnd().split('\n');valid[2]=valid[1];f.accepted=Buffer.from(valid.join('\n')+'\n');
  });assert.throws(()=>prepareCoverage(edited));
});
test('quoted TSV cannot hide new records or unclosed fields',()=>{
  assert.equal(tsv(Buffer.from('a\tb\n"one""quote"\t"two\nlines"\n')).rows[0].a,'one"quote');
  for(const input of ['a\ta\n1\t2\n','a\tb\n"one\t2\n','a\tb\n"one"suffix\t2\n','a\tb\n1\t2'])assert.throws(()=>tsv(Buffer.from(input)));
});
test('guarded batch refuses drift, active uncertified rows, changed receipts and late failure atomically',async()=>{
  const packet=prepareCoverage(coverageFixture({rows:2})),plan=coveragePlan(packet);
  for(const mutation of ['drift','active','receipt','late']) {
    const sql=new DatabaseSync(':memory:'),db=sqliteD1(sql);
    try {
      await prepareDatabase(db);
      if(mutation==='late') {
        await assert.rejects(db.batch([...plan.slice(0,-1),{sql:'INSERT INTO community_object_import_guard VALUES(0)',params:[]}]
          .map(({sql,params})=>db.prepare(sql).bind(...params))));
        assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM locations').get().n,0);
      }else {
        await db.batch(plan.map(({sql,params})=>db.prepare(sql).bind(...params)));
        if(mutation==='drift')sql.exec('UPDATE locations SET heading=180 WHERE id=1');
        if(mutation==='active')sql.exec("DELETE FROM object_coverage WHERE location_id=1;UPDATE locations SET state='leased' WHERE id=1");
        if(mutation==='receipt')sql.exec("UPDATE object_coverage SET evidence_sha256='changed' WHERE location_id=1");
        const before=JSON.stringify(sql.prepare('SELECT * FROM locations ORDER BY id').all());
        await assert.rejects(db.batch(plan.map(({sql,params})=>db.prepare(sql).bind(...params))));
        assert.equal(JSON.stringify(sql.prepare('SELECT * FROM locations ORDER BY id').all()),before);
      }
      assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name='community_object_import_guard'").get().n,0);
    }finally{sql.close();}
  }
});
test('private preparation excludes source paths, saves a complete batch and refuses existing or linked output',()=>{
  const root=mkdtempSync(join(tmpdir(),'coverage-')),validator=join(root,'validator'),fixture=coverageFixture();
  mkdirSync(validator);
  try {
    for(const [name,k] of [['manifest.json','manifest'],['normalized.tsv','accepted'],['rejected.tsv','denied']])writeFileSync(join(validator,name),fixture[k]);
    writeFileSync(join(root,'input.tsv'),fixture.input);writeFileSync(join(root,'countries.txt'),fixture.countries);
    const values={validator,input:join(root,'input.tsv'),countries:join(root,'countries.txt'),out:join(root,'saved'),
      'manifest-sha256':fixture.manifestSha256,'input-sha256':fixture.inputSha256,'countries-sha256':fixture.countriesSha256};
    assert.equal(saveCoveragePlan(values),1);
    const before=digest(readFileSync(join(values.out,'import-batch.private.json')));
    const report=JSON.parse(readFileSync(join(values.out,'report.private.json')));
    assert.equal(report.batchSha256,before);
    assert.throws(()=>saveCoveragePlan(values));assert.equal(digest(readFileSync(join(values.out,'import-batch.private.json'))),before);
    const link=join(root,'redirect');symlinkSync(validator,link,process.platform==='win32'?'junction':'dir');
    assert.throws(()=>saveCoveragePlan({...values,validator:link,out:join(root,'unsafe')}));
    assert.throws(()=>saveCoveragePlan({...values,out:join(link,'unsafe')}));
    const failed=join(root,'bad-input');assert.throws(()=>saveCoveragePlan({...values,out:failed,'manifest-sha256':'0'.repeat(64)}));
    assert.equal(JSON.parse(readFileSync(join(failed,'failure.private.json'))).status,'INCOMPLETE');
  }finally{rmSync(root,{recursive:true,force:true});}
});
