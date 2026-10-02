// Actual workerd service-binding/RPC boundaries; no model execution or admission.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(process.argv[2])));
const script = await readFile(resolve(process.argv[3]), "utf8");
const secret = "synthetic-operator-" + "x".repeat(48);
const options = { workers: [{ name: "private-native-host", modules: true, script,
  compatibilityDate: "2026-10-02", compatibilityFlags: ["nodejs_compat"],
  durableObjects: { NATIVE_HOST: { className: "NativeHostProbe", useSQLite: true } },
  bindings: { PROBE_SECRET: secret },
}, { name: "binding-test", modules: true,
  compatibilityDate: "2026-10-02", compatibilityFlags: ["nodejs_compat"],
  serviceBindings: { ENGINE: { name: "private-native-host", entrypoint: "NativeSceneSearch" },
    VERIFIER: { name: "private-native-host", entrypoint: "NativeSceneVerification" },
    OPERATOR: "private-native-host", PRIVATE_OPERATOR: { name: "private-native-host", entrypoint: "NativeSceneOperator" } },
  script: `export default {fetch(request, env) {
    const url=new URL(request.url); const binding=url.pathname.startsWith('/engine/')?'ENGINE':url.pathname.startsWith('/verifier/')?'VERIFIER':url.pathname.startsWith('/private/')?'PRIVATE_OPERATOR':'OPERATOR';
    if(binding!=='OPERATOR') url.pathname=url.pathname.slice(binding==='ENGINE'?7:binding==='PRIVATE_OPERATOR'?8:9);
    return env[binding].fetch(new Request(url, request));
  }};`,
}] };
// dispatchFetch targets the first Worker; the actual native host is reached
// through the test gateway's three service bindings, including named entrypoints.
options.workers.reverse();
const instance = new Miniflare(convertV4MiniflareOptions(options));
let count = 0;
try {
  for (const [path, init, status, error] of [
    ["/health", {}, 401, "unauthorized"],
    ["/health", { headers: { authorization: "Bearer incorrect" } }, 401, "unauthorized"],
    ["/health", { headers: { authorization: "Bearer " + secret } }, 503, "native_host_unavailable"],
    ["/search", { method: "POST" }, 404, "not_found"],
    ["/audit", { method: "POST" }, 404, "not_found"],
    ["/qualify", { method: "POST" }, 404, "not_found"],
    ["/operator/model-check", { method: "POST" }, 401, "unauthorized"],
    ["/operator/model-check", { method: "POST", headers: { authorization: "Bearer " + secret } }, 503, "model_check_egress_disabled"],
    ["/private/health", {}, 503, "native_host_unavailable"],
    ["/private/operator/model-check", { method: "POST" }, 503, "model_check_egress_disabled"],
    ["/operator/launch-check", { method: "POST" }, 401, "unauthorized"],
    ["/operator/launch-check", { method: "POST", headers: { authorization: "Bearer " + secret } }, 503, "native_host_unavailable"],
    ["/private/operator/launch-check", { method: "POST" }, 503, "native_host_unavailable"],
    ["/private/search", { method: "POST" }, 404, "not_found"],
    ["/private/audit", { method: "POST" }, 404, "not_found"],
    ["/operator/bundle", { method: "POST", headers: { authorization: "Bearer " + secret, "content-type": "application/json" }, body: "{}" }, 400, "invalid_operator_descriptor"],
    ["/engine/search", { method: "POST", headers: { "content-type": "application/json" }, body: '{"query":{"x":1e-7}}' }, 503, "native_service_unavailable"],
    ["/engine/audit", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }, 404, "not_found"],
    ["/verifier/audit", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }, 503, "native_service_unavailable"],
    ["/verifier/qualify", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }, 503, "native_service_unavailable"],
    ["/verifier/search", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }, 404, "not_found"],
    ["/engine/search", { method: "POST", body: "{}" }, 400, "invalid_request"],
  ]) {
    const response = await instance.dispatchFetch("https://binding.invalid" + path, init);
    assert.equal(response.status, status, path);
    assert.deepEqual(await response.json(), { error }, path);
    assert.equal(response.headers.get("cache-control"), "no-store", path);
    count++;
  }
  const response = await instance.dispatchFetch("https://binding.invalid/operator/status", { headers: { authorization: "Bearer " + secret } });
  assert.equal(response.status, 200);
  const status = await response.json();
  assert.equal(status.activeBundle, null);
  assert.equal(status.productionQualified, false);
  count++;
  const privateResponse = await instance.dispatchFetch("https://binding.invalid/private/operator/status");
  assert.equal(privateResponse.status, 200);
  assert.deepEqual(await privateResponse.json(), status);
  count++;
  console.log(JSON.stringify({ status: "ACTUAL_WORKERD_PRIVATE_NATIVE_HOST_GATES_PASSED", checks: count,
    modelInference: false, productionQualified: false }));
} finally { await instance.dispose(); }
