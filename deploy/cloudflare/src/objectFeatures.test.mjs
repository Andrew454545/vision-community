import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {crc8, crc16, crc32, validateFeatureContents} from "./objectFeatures.js";
import {validateObjectIndex} from "./objectIndex.js";
import {sha256Hex} from "./model.js";
import {objectCapabilities} from "./objectAdmission.js";

const document = JSON.parse(readFileSync(new URL("../../../community/tests/fixtures/object-feature-content-v1.json",import.meta.url),"utf8"));
async function mutate(item) {
  const baseline = structuredClone(document.baseline), manifest = baseline.manifest;
  const source = new Uint8Array(Buffer.from(item.sourceBase64 ?? baseline.sourceBase64,"base64"));
  const files = Object.fromEntries(Object.entries(baseline.filesBase64).map(([key,value]) =>
    [key,new Uint8Array(Buffer.from(value,"base64"))]));
  for (const [key,value] of Object.entries(item.replacements ?? {})) files[key] = new Uint8Array(Buffer.from(value,"base64"));
  for (const write of item.writes ?? []) {
    const raw = files[write.file], offset = write.offset;
    raw.set(Buffer.from(write.hex,"hex"),offset);
    const size = {crc8:32,crc16:144,crc32:8}[write.checksum];
    if (size) {
      const start = Math.floor(offset / size) * size, view = new DataView(raw.buffer);
      if (write.checksum === "crc8") raw[start+31] = crc8(raw.subarray(start,start+31));
      else if (write.checksum === "crc16") view.setUint16(start+142,crc16(raw.subarray(start,start+142)),true);
      else view.setUint32(start+4,crc32(raw.subarray(start,start+4)),true);
    }
  }
  const entries = ["offsets","metadata","globalIds","semantic","viewQuality"].map(key => manifest[key]);
  entries.push(...manifest.classes,...manifest.hotConcepts);
  for (const entry of entries) {
    const raw = files[entry.file];
    Object.assign(entry,{bytes:raw.length,records:Math.floor(raw.length/(entry.recordBytes ?? 32)),sha256:await sha256Hex(raw)});
  }
  Object.assign(manifest,{sourceBytes:source.length,sourceSha256:await sha256Hex(source)});
  for (const change of item.changes ?? []) {
    let target = manifest;
    for (const key of change.path.slice(0,-1)) target = target[key];
    target[change.path.at(-1)] = change.value;
  }
  return {manifest,files,source};
}

test("known native checksum vectors",() => {
  const raw = new TextEncoder().encode("123456789");
  assert.equal(crc8(raw),0xf4); assert.equal(crc16(raw),0x29b1); assert.equal(crc32(raw),0xcbf43926);
});

test("frozen replay is refused as a contribution even with a null marker", async () => {
  for (const value of [null, "a".repeat(64), ""]) {
    const {manifest, files, source} = await mutate({});
    manifest.frozenViewsManifestSha256 = value;
    await assert.rejects(validateObjectIndex(manifest, files, source, document.items, document.leaseId), /verification_failed/);
  }
});
test("baseline covers all lanes and UTF-8 row pointers without granting admission",async () => {
  const {manifest,files,source} = await mutate({});
  assert.deepEqual(validateFeatureContents(manifest,files,source),
    {locations:2,commonAndHotRecords:3,semanticRecords:32,qualityRecords:2});
  assert.equal((await validateObjectIndex(manifest,files,source,document.items,document.leaseId)).length,2);
  assert.equal(objectCapabilities().objectContributions.ready,false);
});
test("transport byte and source bounds precede record processing",async () => {
  const {manifest,files,source} = await mutate({});
  files["too-large.bin"] = new Uint8Array(32_000_001);
  assert.throws(() => validateFeatureContents(manifest,files,source),/verification_failed/);
  assert.throws(() => validateFeatureContents(manifest,{},new Uint8Array(1024*1024+1)),/verification_failed/);
});
for (const item of document.cases) test(item.name,async () => {
  const {manifest,files,source} = await mutate(item);
  if (item.valid) {
    assert.equal((await validateObjectIndex(manifest,files,source,document.items,document.leaseId)).length,2);
    assert.equal(objectCapabilities().objectContributions.ready,false);
  } else await assert.rejects(validateObjectIndex(manifest,files,source,document.items,document.leaseId),/verification_failed/);
});
