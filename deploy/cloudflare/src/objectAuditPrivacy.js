import { assignmentErasureResult } from '../native-object-verifier-bridge/worker.js';
import { readVerifierJson } from './scenePipeline.js';

// This is an outbox identity, never an R2 object or a caller-chosen URL.
export const objectAuditCleanupKey = lease => `object-audit-jobs/${lease}`;
export const objectAuditCleanupLease = key => typeof key === 'string'
  ? /^object-audit-jobs\/([0-9a-f]{32})$/.exec(key)?.[1] ?? null : null;

export async function eraseObjectAssignment(env, lease, timeoutMs = 20000, expected = null) {
  if (typeof env.OBJECT_VERIFIER?.fetch !== 'function' || typeof lease !== 'string' || !/^[0-9a-f]{32}$/.test(lease)
      || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 20000) return false;
  if (expected !== null && (!expected || typeof expected !== 'object' || Array.isArray(expected)
      || Object.keys(expected).sort().join(',') !== 'assignmentSha256,policyId'
      || typeof expected.assignmentSha256 !== 'string' || !/^[0-9a-f]{64}$/.test(expected.assignmentSha256)
      || typeof expected.policyId !== 'string' || !/^[A-Za-z0-9_.-]{1,128}$/.test(expected.policyId))) return false;
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
    const checked = assignmentErasureResult(value, lease);
    return checked.state === 'erased' && (expected === null || Object.entries(expected).every(([key,wanted]) => checked[key] === wanted));
  } catch {
    // Transport/setup failures and pending erasure all retain the durable job.
    // Never retain native paths, candidate data, credentials or exception text.
    return false;
  } finally { clearTimeout(timer); abort.abort(); }
}
