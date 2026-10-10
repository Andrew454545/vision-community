// Local workerd fixture only: no bindings, accounts, native inference or uploads.
import {validateObjectIndex} from "../src/objectIndex.js";
import {objectCapabilities} from "../src/objectAdmission.js";
export default {async fetch(request) {
  try {
    if (request.headers.get("Content-Length") && Number(request.headers.get("Content-Length")) > 512*1024)
      return Response.json({error:"verification_failed"},{status:422});
    const raw = await request.arrayBuffer();
    if (raw.byteLength > 512*1024) return Response.json({error:"verification_failed"},{status:422});
    const body = JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(raw));
    const bytes = value => Uint8Array.from(atob(value),letter => letter.charCodeAt(0));
    const files = Object.fromEntries(Object.entries(body.filesBase64).map(([key,value]) => [key,bytes(value)]));
    const result = await validateObjectIndex(body.manifest,files,bytes(body.sourceBase64),body.items,body.leaseId);
    return Response.json({valid:true,locations:result.length,ready:objectCapabilities().objectContributions.ready});
  } catch { return Response.json({error:"verification_failed"},{status:422}); }
}};
