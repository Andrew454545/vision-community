// Finite actual workerd checks. Public synthetic fixture only; no cloud login/storage.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {resolve,dirname} from "node:path";
import {fileURLToPath,pathToFileURL} from "node:url";
import {crc8,crc16,crc32} from "../src/objectFeatures.js";
import {sha256Hex} from "../src/model.js";
const {Miniflare,convertV4MiniflareOptions} = await import(pathToFileURL(resolve(process.argv[2])).href);
const root = dirname(dirname(fileURLToPath(import.meta.url)));
const fixture = JSON.parse(readFileSync(new URL("../../../community/tests/fixtures/object-feature-content-v1.json",import.meta.url),"utf8"));
const paths = ["tools/object-feature.fixture.mjs","src/objectIndex.js","src/objectFeatures.js","src/objectAdmission.js","src/model.js"];
const options = {modules:paths.map(path => ({type:"ESModule",path:resolve(root,path)})),
  modulesRoot:root,compatibilityDate:"2026-09-19"};
const mf = new Miniflare(convertV4MiniflareOptions ? convertV4MiniflareOptions(options) : options);
let accepted = 0, rejected = 0;
try {
  for (const item of [{name:"baseline",valid:true},...fixture.cases]) {
    const document = structuredClone(fixture.baseline), manifest = document.manifest;
    const source = new Uint8Array(Buffer.from(item.sourceBase64 ?? document.sourceBase64,"base64"));
    const files = Object.fromEntries(Object.entries(document.filesBase64).map(([key,value])=>[key,new Uint8Array(Buffer.from(value,"base64"))]));
    for (const [key,value] of Object.entries(item.replacements ?? {})) files[key] = new Uint8Array(Buffer.from(value,"base64"));
    for (const write of item.writes ?? []) {
      const raw = files[write.file]; raw.set(Buffer.from(write.hex,"hex"),write.offset);
      const size = {crc8:32,crc16:144,crc32:8}[write.checksum];
      if (size) {
        const start = Math.floor(write.offset/size)*size, data = new DataView(raw.buffer);
        if (size===32) raw[start+31] = crc8(raw.subarray(start,start+31));
        else if (size===144) data.setUint16(start+142,crc16(raw.subarray(start,start+142)),true);
        else data.setUint32(start+4,crc32(raw.subarray(start,start+4)),true);
      }
    }
    const entries = ["offsets","metadata","globalIds","semantic","viewQuality"].map(key=>manifest[key]);
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
    const response = await mf.dispatchFetch("https://community.test",{
      method:"POST",headers:{"Content-Type":"application/json"},signal:AbortSignal.timeout(10_000),
      body:JSON.stringify({manifest,sourceBase64:Buffer.from(source).toString("base64"),
        filesBase64:Object.fromEntries(Object.entries(files).map(([key,value])=>[key,Buffer.from(value).toString("base64")])),
        items:fixture.items,leaseId:fixture.leaseId})});
    assert.equal(response.status,item.valid?200:422,item.name);
    const result = await response.json();
    if (item.valid) { assert.deepEqual(result,{valid:true,locations:2,ready:false},item.name); accepted++; }
    else { assert.deepEqual(result,{error:"verification_failed"},item.name); rejected++; }
  }
  console.log(JSON.stringify({scope:"synthetic-object-content-guards",cases:accepted+rejected,
    validFormatCases:accepted,rejectedFormatCases:rejected,objectAdmissionReady:false}));
} finally { await mf.dispose(); }
