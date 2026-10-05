// Bound incoming JSON while streaming, even without an honest Content-Length.
// One growing buffer avoids an attacker allocating millions of chunk objects.
export const MAX_JSON_BODY_BYTES = 8 * 1024 * 1024;
const MAX_READS = 65536;
export class RequestBodyError extends Error {
  constructor(code, status) { super(code); this.status = status; }
}

function cancel(body) {
  // Cancellation can itself stall; observe rejection without awaiting it.
  try { void body?.cancel().catch(() => {}); } catch {}
}

export async function readRequestJson(request, timeoutMs = 60000) {
  const declared = request.headers.get('Content-Length');
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > MAX_JSON_BODY_BYTES)) {
    cancel(request.body);
    throw new RequestBodyError('request_too_large', 413);
  }
  if (!request.body) throw new RequestBodyError('invalid_json', 400);
  const reader = request.body.getReader();
  const end = Date.now() + timeoutMs;
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new RequestBodyError('request_timeout', 408)), timeoutMs);
  });
  let bytes = new Uint8Array(65536), length = 0, reads = 0;
  try {
    while (true) {
      if (++reads > MAX_READS || Date.now() >= end) throw new RequestBodyError('request_timeout', 408);
      const { done, value } = await Promise.race([reader.read(), deadline]);
      if (Date.now() >= end) throw new RequestBodyError('request_timeout', 408);
      if (done) break;
      if (!(value instanceof Uint8Array)) throw new RequestBodyError('invalid_json', 400);
      if (length + value.length > MAX_JSON_BODY_BYTES) throw new RequestBodyError('request_too_large', 413);
      if (length + value.length > bytes.length) {
        let size = bytes.length;
        while (size < length + value.length) size = Math.min(MAX_JSON_BODY_BYTES, size * 2);
        const grown = new Uint8Array(size);
        grown.set(bytes.subarray(0, length)); bytes = grown;
      }
      bytes.set(value, length); length += value.length;
    }
    if (declared !== null && Number(declared) !== length) throw new RequestBodyError('invalid_json', 400);
    let value;
    try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(0, length))); }
    catch { throw new RequestBodyError('invalid_json', 400); }
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new RequestBodyError('invalid_json', 400);
    return value;
  } catch (error) {
    cancel(reader);
    throw error instanceof RequestBodyError ? error : new RequestBodyError('invalid_json', 400);
  } finally {
    clearTimeout(timer);
    try { reader.releaseLock(); } catch {}
  }
}
