import assert from "node:assert/strict";
import test from "node:test";
import bridge, { handleVerification } from "./worker.js";

const env = { NATIVE_VERIFIER_ORIGIN: "https://trusted-native.example.test",
  NATIVE_VERIFIER_SECRET: "synthetic-only-private-transport-credential" };
const body = '{"records":[{"lat":1e-7,"assetId":"雪"}],"submissionSha256":"synthetic"}';
const request = (path="/audit", options={}) => new Request("https://scene-verifier.internal"+path,
  { method:"POST",headers:{"content-type":"application/json"},body,...options });

test("both native verification routes preserve exact metadata fingerprints and operator auth", async () => {
  for (const path of ["/qualify", "/audit"]) {
    const result = await handleVerification(request(path, {headers:{"content-type":"application/json",cookie:"private",authorization:"Bearer client"}}),env,
      async (url, init) => {
        assert.equal(url, env.NATIVE_VERIFIER_ORIGIN+path);
        assert.equal(new TextDecoder().decode(init.body),body);
        assert.equal(init.headers.authorization, `Bearer ${env.NATIVE_VERIFIER_SECRET}`);
        assert.equal(init.headers.cookie,undefined);
        assert.equal(init.headers["content-length"],undefined);
        assert.equal(init.redirect,"manual");
        return Response.json({decision:"approved"},{headers:{"set-cookie":"private"}});
      });
    assert.equal(result.status,200);
    assert.equal(result.headers.get("set-cookie"),null);
  }
});

test("native PC rejection remains distinct from unavailable hosting", async () => {
  const rejected = await handleVerification(request("/qualify"),env,
    () => Response.json({error:"scene_device_not_qualified"},{status:422}));
  assert.equal(rejected.status,422);
  assert.deepEqual(await rejected.json(),{error:"scene_device_not_qualified"});
  const unavailable = await handleVerification(request(),env,() => new Response("private diagnostics",{status:503}));
  assert.equal(unavailable.status,503);
  assert.deepEqual(await unavailable.json(),{error:"scene_verifier_unavailable"});
});

test("missing configuration, wrong routes and untrusted URLs never forward", async () => {
  for (const changes of [{NATIVE_VERIFIER_SECRET:"short"},{NATIVE_VERIFIER_ORIGIN:"http://host"},
    {NATIVE_VERIFIER_ORIGIN:"https://host/audit"},{NATIVE_VERIFIER_ORIGIN:"https://user:credential@host"},
    {NATIVE_VERIFIER_ORIGIN:"https://host/?query=x"}]) {
    assert.equal((await handleVerification(request(),{...env,...changes},() => assert.fail("forwarded"))).status,503);
  }
  assert.equal((await handleVerification(request("/search"),env,() => assert.fail("forwarded"))).status,404);
});

test("framing and streamed request bounds prevent native work", async () => {
  for (const value of [request("/audit",{body:new Uint8Array(6*1024*1024+1)}),
    request("/audit",{headers:{"content-type":"application/json","content-length":"1"}})]) {
    assert.equal((await handleVerification(value,env,() => assert.fail("forwarded"))).status,400);
  }
});

test("redirects, invalid media, oversized responses and native exceptions stay private", async () => {
  for (const fetcher of [() => new Response("private",{status:302,headers:{location:"https://other-host"}}),
    () => new Response("private",{headers:{"content-type":"text/plain"}}),
    () => new Response(new Uint8Array(65537),{headers:{"content-type":"application/json"}}),
    () => {throw Error("private secret and paths");}]) {
    const result = await handleVerification(request(),env,fetcher);
    assert.equal(result.status,503);
    assert.deepEqual(await result.json(),{error:"scene_verifier_unavailable"});
  }
});

test("Worker execution context does not replace the native fetch function", async t => {
  t.mock.method(globalThis,"fetch",() => Response.json({approved:false},{status:422}));
  assert.equal((await bridge.fetch(request("/qualify"),env,{waitUntil(){}})).status,422);
});
