import { bounded } from "../native-scene-bridge/worker.js";

const MAX_REQUEST = 6 * 1024 * 1024;
const MAX_RESPONSE = 64 * 1024;
const reply = (status, error) => Response.json({ error }, {
  status, headers: { "cache-control": "no-store" },
});

export async function handleVerification(request, env, fetcher = fetch) {
  const path = new URL(request.url).pathname;
  if (request.method !== "POST" || !["/qualify", "/audit"].includes(path)) return reply(404, "not_found");
  let endpoint, secret;
  try {
    secret = env.NATIVE_VERIFIER_SECRET;
    endpoint = new URL(env.NATIVE_VERIFIER_ORIGIN);
    if (typeof secret !== "string" || !/^[\x21-\x7e]{32,256}$/.test(secret)
        || endpoint.protocol !== "https:" || endpoint.username || endpoint.password
        || endpoint.pathname !== "/" || endpoint.search || endpoint.hash) throw Error("invalid host");
    endpoint.pathname = path;
  } catch { return reply(503, "scene_verifier_unavailable"); }
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
    return reply(400, "invalid_request");
  }
  const length = request.headers.get("content-length");
  if (length !== null && (!/^[0-9]+$/.test(length) || Number(length) > MAX_REQUEST)) return reply(413, "request_too_large");
  let body;
  try {
    body = await bounded(request.body, MAX_REQUEST);
    if (!body.byteLength || (length !== null && body.byteLength !== Number(length))) throw Error("invalid body");
  } catch { return reply(400, "invalid_request"); }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 55000);
  try {
    const response = await fetcher(endpoint.href, { method: "POST", redirect: "manual", signal: controller.signal,
      headers: { "content-type": "application/json", authorization: `Bearer ${secret}` }, body });
    if (![200, 422].includes(response.status)
        || response.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
      await response.body?.cancel();
      return reply(503, "scene_verifier_unavailable");
    }
    const size = response.headers.get("content-length");
    if (size !== null && (!/^[0-9]+$/.test(size) || Number(size) > MAX_RESPONSE)) throw Error("response limit");
    const bytes = await bounded(response.body, MAX_RESPONSE);
    if (!bytes.byteLength || (size !== null && bytes.byteLength !== Number(size))) throw Error("invalid response length");
    return new Response(bytes, { status: response.status,
      headers: { "content-type": "application/json", "cache-control": "no-store" } });
  } catch { return reply(503, "scene_verifier_unavailable"); }
  finally { clearTimeout(timer); }
}

export default { fetch(request, env) { return handleVerification(request, env); } };
