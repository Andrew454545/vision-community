import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {publicObjectManifest} from './objectPublicManifest.js';
import {validateObjectIndex} from './objectIndex.js';
import {objectCapabilities} from './objectAdmission.js';
const fixture=JSON.parse(readFileSync(new URL('../../../community/tests/fixtures/object-feature-content-v1.json',import.meta.url),'utf8'));
function input() {
  const manifest=structuredClone(fixture.baseline.manifest);
  Object.assign(manifest.viewQuality,{policy:'vision-per-view-quality-v1',implementationIdentity:'1'.repeat(64),
    viewCount:6,blurAreaFractionExclusive:0.5,tileGrid:8,tunnelVisionProbabilityInclusive:0.85,
    tunnelEvidencePolicy:'none-darkness-never-rejects-v1',protectedAuthorityManifestSha256:'2'.repeat(64)});
  return manifest;
}
test('public projection removes private extensions at every level and preserves immutable feature identity',async()=>{
  const manifest=input(),privateText='SYNTHETIC-PRIVATE-PATH-AND-ACCOUNT';
  manifest.sourceTsv='C:/'+privateText+'/source.tsv';manifest.operator={secret:privateText};
  manifest.contractVersions.private=privateText;
  for(const key of ['offsets','metadata','globalIds','semantic','viewQuality'])manifest[key].private=privateText;
  for(const entry of [...manifest.classes,...manifest.hotConcepts])entry.private={secret:privateText};
  const before=JSON.stringify(manifest),projected=publicObjectManifest(manifest);
  assert.equal(JSON.stringify(manifest),before);assert.equal(projected.sourceTsv,'locations.tsv');
  assert.equal(JSON.stringify(projected).includes(privateText),false);
  const source=new Uint8Array(Buffer.from(fixture.baseline.sourceBase64,'base64'));
  const files=Object.fromEntries(Object.entries(fixture.baseline.filesBase64).map(([k,v])=>[k,new Uint8Array(Buffer.from(v,'base64'))]));
  assert.deepEqual(await validateObjectIndex(projected,files,source,fixture.items,fixture.leaseId),
    await validateObjectIndex(manifest,files,source,fixture.items,fixture.leaseId));
  assert.deepEqual(publicObjectManifest(projected),projected);
  assert.equal(projected.viewQuality.protectedAuthorityManifestSha256,'2'.repeat(64));
  assert.equal(objectCapabilities().objectContributions.ready,false);
});
test('diagnostic markers cannot be sanitized into contribution metadata',()=>{
  for(const value of [null,'','f'.repeat(64)])assert.throws(()=>publicObjectManifest({...input(),frozenViewsManifestSha256:value}),/verification_failed/);
});
test('malformed retained fields and counter values fail instead of leaking nested metadata',()=>{
  for(const change of [m=>m.version={secret:'private'},m=>m.offsets.sha256={secret:'private'},
    m=>m.contractVersions.manifest={secret:'private'},m=>m.classes[0].name=['private'],
    m=>m.semantic.codec={secret:'private'},m=>m.viewQuality.policy=['private'],
    m=>m.countries=['country\nprivate'],m=>m.countries=['x'.repeat(101)],m=>m.countries=[{}],
    m=>m.classes=new Array(101).fill({}),m=>m.hotConcepts=[null],m=>m.metadata=null,
    m=>m.fetchErrors=true,m=>m.inferenceErrors=-1,m=>m.fetchErrors=0.5,m=>m.version=NaN]){
    const m=input();change(m);assert.throws(()=>publicObjectManifest(m),/verification_failed/);
  }
});
test('complete current per-view quality semantics and protected authority identity are required when quality exists',()=>{
  for(const change of [{policy:'old'},{implementationIdentity:''},{protectedAuthorityManifestSha256:null},
    {viewCount:5},{blurAreaFractionExclusive:0.51},{tileGrid:2},{tunnelVisionProbabilityInclusive:0.8},
    {tunnelEvidencePolicy:'none-darkness-kept-v1'},{darkTunnelRejectedViews:1,keptViews:11},
    {keptViews:13},{fullyRejectedLocations:3},{keptViews:true},{tunnelEvidenceQualifiedViews:1},
    {tunnelEvidenceManifestSha256:'3'.repeat(64)},{permanentlyInvalidLocations:1},
    {invalidLocationPolicy:'old'},{tunnelEvidenceVisualScoreRecords:0.5}]){
    const m=input();Object.assign(m.viewQuality,change);assert.throws(()=>publicObjectManifest(m),/verification_failed/);
  }
});
test('sealed tunnel policy retains independent evidence pins without granting authority',()=>{
  const m=input();Object.assign(m.viewQuality,{tunnelEvidencePolicy:'sealed-external-map-plus-tunnel-vision-exact-pano-coordinate-v1',
    tunnelEvidenceManifestSha256:'3'.repeat(64),tunnelEvidenceQualifiedViews:1,tunnelEvidenceMapMatchRecords:1,
    tunnelEvidenceVisualScoreRecords:1,darkTunnelRejectedViews:1,keptViews:11});
  assert.deepEqual(publicObjectManifest(m).viewQuality,m.viewQuality);
  for(const key of ['tunnelEvidenceManifestSha256','tunnelEvidenceMapMatchRecords','tunnelEvidenceVisualScoreRecords']){
    const changed=structuredClone(m);delete changed.viewQuality[key];assert.throws(()=>publicObjectManifest(changed),/verification_failed/);
  }
  m.viewQuality.tunnelEvidenceQualifiedViews=0;assert.throws(()=>publicObjectManifest(m),/verification_failed/);
});
test('optional legacy quality and Unicode country names match the offline format',()=>{
  for(const quality of [null,{}]){const m=input();m.viewQuality=quality;assert.equal(Object.hasOwn(publicObjectManifest(m),'viewQuality'),false);}
  const m=input();m.countries=['\u{1f30d}'.repeat(100)];assert.equal(publicObjectManifest(m).countries[0],m.countries[0]);
});
