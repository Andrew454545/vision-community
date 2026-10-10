import { assignmentErasureResult } from '../native-object-verifier-bridge/worker.js';
import { readVerifierJson } from './scenePipeline.js';

// This is an outbox identity, never an R2 object or a caller-chosen URL.
export const objectAuditCleanupKey = lease => `object-audit-jobs/${lease}`;
export const objectAuditCleanupLease = key => typeof key === 'string'
  ? /^object-audit-jobs\/([0-9a-f]{32})$/.exec(key)?.[1] ?? null : null;

export async function eraseObjectAssignment(env, lease, timeoutMs = 20000) {
  if (typeof env.OBJECT_VERIFIER?.fetch !== 'function' || !/^[0-9a-f]{32}$/.test(lease)
      || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 20000) return false;
  const abort = new AbortController();
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => { abort.abort(); reject(Error('object_erasure_timeout')); }, timeoutMs);
  });
  void deadline.catch(() => {});
  try {
    const transfer = Promise.resolve().then(() => env.OBJECT_VERIFIER.fetch(new Request(
      `https://object-verifier.internal/object-assignments/${lease}/erase`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}', signal: abort.signal,
      }))).then(response => {
      if (abort.signal.aborted) {
        if (response.body) void response.body.cancel().catch(() => {});
        throw Error('object_erasure_timeout');
      }
      return response;
    });
    const response = await Promise.race([transfer, deadline]);
    if (response.status !== 200) {
      if (response.body) void response.body.cancel().catch(() => {});
      return false;
    }
    const value = await Promise.race([readVerifierJson(response, Math.min(timeoutMs, 10000)), deadline]);
    return assignmentErasureResult(value, lease).state === 'erased';
  } catch {
    // Transport/setup failures and pending erasure all retain the durable job.
    // Never retain native paths, candidate data, credentials or exception text.
    return false;
  } finally { clearTimeout(timer); abort.abort(); }
}
