// Private service binding -> authenticated native host. No storage or settlement.
export const MAX_REQUEST = 8 * 1024 * 1024 + 64 * 1024;
export const MAX_RESPONSE = 4 * 1024 * 1024;

const reply = (status, error) => Response.json({ error }, {
  status, headers: { "Cache-Control": "no-store" },
});

async function bounded(stream, maximum) {
  if (!stream) throw Error("missing body");
  const reader = stream.getReader(), chunks = [];
  let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximum) throw Error("body limit");
      chunks.push(value);
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return bytes;
}

function upstream(env) {
  const secret = env.NATIVE_ENGINE_SECRET;
  if (typeof secret !== "string" || !/^[\x20-\x7e]{32,256}$/.test(secret)) throw Error("missing secret");
  if (typeof env.NATIVE_ENGINE_URL !== "string") throw Error("missing host");
  const url = new URL(env.NATIVE_ENGINE_URL);
  if (url.protocol !== "https:" || !url.hostname || url.username || url.password
      || url.pathname !== "/search" || url.search || url.hash) throw Error("invalid host");
  return { url, secret };
}

export async function handleSearch(request, env, fetcher = fetch) {
  if (request.method !== "POST" || new URL(request.url).pathname !== "/search") return reply(404, "not_found");
  let target;
  try { target = upstream(env); } catch { return reply(503, "search_unavailable"); }
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
    return reply(400, "invalid_request");
  }
  const length = request.headers.get("content-length");
  if (length !== null && (!/^[0-9]+$/.test(length) || Number(length) > MAX_REQUEST)) {
    return reply(413, "request_too_large");
  }
  let body;
  try {
    body = await bounded(request.body, MAX_REQUEST);
    if (!body.byteLength || (length !== null && body.byteLength !== Number(length))) throw Error("invalid length");
  } catch { return reply(400, "invalid_request"); }
  const controller = new AbortController();
  // The native process has a 110-second bound; the gateway has 120 seconds.
  // Keep the timer through response-body consumption, not only receipt of headers.
  const timer = setTimeout(() => controller.abort(), 115000);
  try {
    const response = await fetcher(target.url.href, {
      method: "POST", redirect: "manual", signal: controller.signal,
      // Fetch computes Content-Length from these fixed bytes. Do not copy or
      // manually supply a framing header across the hosting/Fetch boundary.
      headers: { "content-type": "application/json", authorization: `Bearer ${target.secret}` },
      body,
    });
    if (response.status !== 200 || response.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
      await response.body?.cancel();
      return reply(503, "search_unavailable");
    }
    const size = response.headers.get("content-length");
    if (size !== null && (!/^[0-9]+$/.test(size) || Number(size) > MAX_RESPONSE)) {
      await response.body?.cancel();
      return reply(503, "search_unavailable");
    }
    const bytes = await bounded(response.body, MAX_RESPONSE);
    if (!bytes.byteLength || (size !== null && bytes.byteLength !== Number(size))) throw Error("invalid response length");
    return new Response(bytes, { status: 200,
      headers: { "content-type": "application/json", "cache-control": "no-store" } });
  } catch { return reply(503, "search_unavailable"); }
  finally { clearTimeout(timer); }
}

export default { fetch(request, env) { return handleSearch(request, env); } };
