import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "node:http";
import bridge, { handleSearch, MAX_REQUEST, MAX_RESPONSE } from "./worker.js";

const env = { NATIVE_ENGINE_URL: "https://trusted-native.example.test/search",
  NATIVE_ENGINE_SECRET: "synthetic-test-secret-not-a-real-credential" };
const body = '{"query":{"prompt":"雪の道","excluded":[{"lat":1e-7,"lng":2}]},"requestSha256":"synthetic"}';
const request = (options = {}) => new Request("https://engine.internal/search", {
  method: "POST", headers: { "content-type": "application/json" }, body, ...options,
});

test("Worker entry point accepts an execution context without treating it as fetch", async t => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ contractVersion: 2, hits: [] }));
  const result = await bridge.fetch(request(), env, { waitUntil() {} });
  assert.equal(result.status, 200);
});

test("private bridge preserves exact query bytes and uses only operator host/secret", async () => {
  let calls = 0;
  const result = await handleSearch(request({ headers: { "content-type": "application/json",
    authorization: "Bearer client-value-must-not-be-forwarded", cookie: "private-cookie" } }), env,
  async (url, init) => {
    calls++;
    assert.equal(url, env.NATIVE_ENGINE_URL);
    assert.equal(init.redirect, "manual");
    assert.equal(new TextDecoder().decode(init.body), body);
    assert.equal(init.headers.authorization, `Bearer ${env.NATIVE_ENGINE_SECRET}`);
    assert.equal(init.headers.cookie, undefined);
    assert.equal(init.headers["content-length"], undefined);
    return Response.json({ contractVersion: 2, hits: [] }, { headers: { "set-cookie": "private-native-cookie", "x-private": "hidden" } });
  });
  assert.equal(calls, 1);
  assert.equal(result.status, 200);
  assert.equal(result.headers.get("cache-control"), "no-store");
  assert.equal(result.headers.get("set-cookie"), null);
  assert.equal(result.headers.get("x-private"), null);
  assert.deepEqual(await result.json(), { contractVersion: 2, hits: [] });
});

test("actual native-host HTTP hop computes byte length and preserves Unicode JSON", async t => {
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const bytes = Buffer.concat(chunks);
    assert.equal(req.headers["content-length"], String(Buffer.byteLength(body)));
    assert.equal(req.headers["transfer-encoding"], undefined);
    assert.equal(bytes.toString("utf8"), body);
    assert.equal(req.headers.authorization, `Bearer ${env.NATIVE_ENGINE_SECRET}`);
    res.writeHead(200, { "content-type": "application/json" });
    res.end('{"contractVersion":2,"hits":[]}');
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const response = await handleSearch(request(), env, (_, init) =>
    fetch(`http://127.0.0.1:${server.address().port}/search`, init));
  assert.equal(response.status, 200);
});

test("missing or unsafe operator configuration never sends a request", async () => {
  for (const change of [{ NATIVE_ENGINE_SECRET: "short" }, { NATIVE_ENGINE_SECRET: "x".repeat(257) },
    { NATIVE_ENGINE_URL: "http://host/search" }, { NATIVE_ENGINE_URL: "https://user:secret@host/search" },
    { NATIVE_ENGINE_URL: "https://host/search?query=x" }, { NATIVE_ENGINE_URL: "https://host/other" },
    { NATIVE_ENGINE_URL: "https://host/search#private" }, { NATIVE_ENGINE_URL: "not a url" }]) {
    assert.equal((await handleSearch(request(), { ...env, ...change }, () => assert.fail("unexpected forwarding"))).status, 503);
  }
});

test("wrong route, media type and declared oversized body fail before forwarding", async () => {
  for (const req of [new Request("https://engine.internal/other", { method: "POST", body }),
    new Request("https://engine.internal/search"), request({ headers: { "content-type": "text/plain" } }),
    request({ headers: { "content-type": "application/json", "content-length": String(MAX_REQUEST + 1) } })]) {
    assert.notEqual((await handleSearch(req, env, () => assert.fail("unexpected forwarding"))).status, 200);
  }
});

test("actual request streaming limit and inconsistent lengths fail without forwarding", async () => {
  for (const req of [request({ body: new Uint8Array(MAX_REQUEST + 1) }),
    request({ headers: { "content-type": "application/json", "content-length": "1" } }), request({ body: "" })]) {
    assert.equal((await handleSearch(req, env, () => assert.fail("unexpected forwarding"))).status, 400);
  }
});

test("redirects and upstream failures expose no private body and are not followed", async () => {
  for (const status of [302, 401, 500]) {
    const result = await handleSearch(request(), env, async (_, init) => {
      assert.equal(init.redirect, "manual");
      return new Response("private host path and diagnostics", { status, headers: { location: "https://other-host/" } });
    });
    assert.equal(result.status, 503);
    assert.deepEqual(await result.json(), { error: "search_unavailable" });
  }
});

test("oversized, empty, non-JSON and inconsistent upstream bodies fail closed", async () => {
  for (const make of [() => new Response(new Uint8Array(MAX_RESPONSE + 1), { headers: { "content-type": "application/json" } }),
    () => new Response("{}", { headers: { "content-type": "application/json", "content-length": String(MAX_RESPONSE + 1) } }),
    () => new Response("{}", { headers: { "content-type": "text/plain" } }),
    () => new Response("", { headers: { "content-type": "application/json" } }),
    () => new Response("{}", { headers: { "content-type": "application/json", "content-length": "1" } })]) {
    assert.equal((await handleSearch(request(), env, make)).status, 503);
  }
});

test("upstream network errors expose only a fixed unavailable response", async () => {
  const result = await handleSearch(request(), env, () => { throw Error("private host and secret must not escape"); });
  assert.equal(result.status, 503);
  assert.deepEqual(await result.json(), { error: "search_unavailable" });
});
