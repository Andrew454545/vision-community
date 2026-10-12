// Private binding -> authenticated saved Object jobs. No inference in fetch(),
// qualification, publication, spending, or new public route/admission flag.
export const MAX_REQUEST = 4 * 1024 * 1024;
export const MAX_RESPONSE = 65536;
const ID = /^[0-9a-f]{32}$/;
const HEX = /^[0-9a-f]{64}$/;
const STATES = new Set(['staging', 'queued', 'running', 'approved', 'rejected', 'failed', 'cancelled', 'erasing', 'erased']);
const ERRORS = new Map([
  ['invalid_object_job', 400], ['invalid_object_job_file', 400],
  ['unknown_object_assignment', 403], ['unknown_object_job', 404],
  ['object_job_identity_mismatch', 409], ['object_job_conflict', 409], ['object_job_control_conflict', 409], ['object_job_source_mismatch', 409],
  ['object_assignment_revoked', 409],
  ['object_job_candidate_incomplete', 409], ['object_job_retry_limited', 429],
  ['object_job_capacity_reached', 503], ['object_job_disk_budget', 503], ['object_job_queue_full', 503],
]);
export const objectAuditQueueFull = value => !!value && typeof value==='object' && !Array.isArray(value)
  && Object.keys(value).join(',')==='error' && value.error==='object_job_queue_full';
const reply = (status, error) => Response.json({error}, {status, headers:{'cache-control':'no-store'}});

async function bounded(stream, maximum, deadline) {
  if (!stream) throw Error('missing_body');
  const reader = stream.getReader(), chunks = [];
  let length = 0;
  try {
    // Bound empty/tiny chunks too; a stream cannot starve the wall-clock timer.
    for (let i = 0; i < 65536; i++) {
      const {done, value} = await Promise.race([reader.read(), deadline]);
      if (done) {
        const bytes = new Uint8Array(length);
        let offset = 0;
        for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
        return bytes;
      }
      if (!(value instanceof Uint8Array) || length + value.byteLength > maximum) throw Error('body_limit');
      length += value.byteLength;
      chunks.push(value);
    }
    throw Error('chunk_limit');
  } finally {
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

function framed(headers, maximum) {
  if (headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json') throw Error('invalid_media');
  const length = headers.get('content-length');
  if (length !== null && (!/^[0-9]+$/.test(length) || Number(length) < 1 || Number(length) > maximum)) throw Error('invalid_length');
  return length === null ? null : Number(length);
}

export function objectAuditResult(value, expected) {
  const fields = ['version','jobId','leaseId','profileId','policyId','assignmentSha256','submissionSha256',
    'candidateManifestSha256','state','decision','attempts','retryAt','receiptSha256','serverAuthorization',
    'productionQualified','acceptedContributions','searchCreditsCreated'];
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || Object.keys(value).sort().join(',') !== [...fields].sort().join(',')
      || value.version !== 1 || typeof value.jobId !== 'string' || !ID.test(value.jobId)
      || typeof value.leaseId !== 'string' || !ID.test(value.leaseId)
      || ![value.profileId,value.assignmentSha256,value.submissionSha256,value.candidateManifestSha256].every(v => typeof v === 'string' && HEX.test(v))
      || typeof value.policyId !== 'string' || !/^[A-Za-z0-9_.-]{1,128}$/.test(value.policyId)
      || !STATES.has(value.state) || value.decision !== (['approved','rejected'].includes(value.state) ? value.state : 'pending')
      || !Number.isSafeInteger(value.attempts) || value.attempts < 0 || value.attempts > 3
      || !Number.isSafeInteger(value.retryAt) || value.retryAt < 0
      || !(value.receiptSha256 === null || typeof value.receiptSha256 === 'string' && HEX.test(value.receiptSha256))
      || ['approved','rejected'].includes(value.state) && (value.attempts < 1 || value.receiptSha256 === null)
      || ['erasing','erased'].includes(value.state) && (value.receiptSha256 !== null || value.retryAt !== 0)
      || value.serverAuthorization !== false || value.productionQualified !== false
      || value.acceptedContributions !== 0 || value.searchCreditsCreated !== 0
      || Object.entries(expected).some(([key, wanted]) => value[key] !== wanted)) throw Error('invalid_job_response');
  return value;
}

export function assignmentErasureResult(value, leaseId) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || Object.keys(value).sort().join(',') !== 'assignmentSha256,leaseId,policyId,productionQualified,serverAuthorization,state,version'
      || value.version !== 1 || value.leaseId !== leaseId || !ID.test(value.leaseId)
      || typeof value.assignmentSha256 !== 'string' || !HEX.test(value.assignmentSha256)
      || typeof value.policyId !== 'string' || !/^[A-Za-z0-9_.-]{1,128}$/.test(value.policyId)
      || !['erasing','erased'].includes(value.state) || value.serverAuthorization !== false
      || value.productionQualified !== false) throw Error('invalid_assignment_erasure');
  return value;
}

export function objectSettlementEvidence(value, expected, now = Math.floor(Date.now()/1000)) {
  const keys = ['audit','policySha256','runtimeProfileSha256','qualityImplementationIdentity',
    'protectedAuthoritySha256','protectedOriginHandoffSha256','resource','qualificationScope','issuedAt','expiresAt'];
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || Object.keys(value).sort().join(',') !== keys.sort().join(',')
      || !keys.filter(k=>k.endsWith('Sha256') || k==='qualityImplementationIdentity')
        .every(k=>typeof value[k]==='string' && HEX.test(value[k]))
      || value.qualificationScope!=='batch-only' || !Number.isSafeInteger(value.issuedAt) || value.issuedAt<0
      || !Number.isSafeInteger(value.expiresAt) || value.expiresAt!==value.issuedAt+30
      || value.issuedAt>now || value.expiresAt<=now
      || !value.resource || Object.keys(value.resource).sort().join(',')!=='accountId,bucket,databaseId'
      || typeof value.resource.accountId!=='string' || !ID.test(value.resource.accountId)
      || typeof value.resource.databaseId!=='string' || !/^[a-f0-9-]{36}$/.test(value.resource.databaseId)
      || !['vision-community','vision-community-staging'].includes(value.resource.bucket)) throw Error('invalid_settlement_response');
  objectAuditResult(value.audit,{...expected,state:'approved',decision:'approved'});
  return value;
}

export async function handleObjectAuditJobs(request, env, fetcher = fetch, timeoutMs = 20000) {
  const url = new URL(request.url), path = url.pathname;
  const route = /^\/object-audits\/([0-9a-f]{32})(?:\/(cancel|retry|erase|settlement-evidence))?$/.exec(path);
  const erasure = /^\/object-assignments\/([0-9a-f]{32})\/erase$/.exec(path);
  if (url.search || !(request.method === 'POST' && (path === '/object-audits' || route?.[2] || erasure)
      || request.method === 'GET' && route && !route[2])) return reply(404, 'not_found');
  let target, secret;
  try {
    target = new URL(env.NATIVE_OBJECT_VERIFIER_ORIGIN);
    secret = env.NATIVE_OBJECT_VERIFIER_SECRET;
    if (target.protocol !== 'https:' || target.username || target.password || target.pathname !== '/' || target.search || target.hash
        || typeof secret !== 'string' || !/^[\x21-\x7e]{32,256}$/.test(secret)
        || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 20000) throw Error('invalid_configuration');
    target.pathname = path;
  } catch { return reply(503, 'object_verifier_unavailable'); }
  const abort = new AbortController();
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => { abort.abort(); reject(Error('job_transport_timeout')); }, timeoutMs);
  });
  // A rejection while between bounded reads is still always handled.
  void deadline.catch(() => {});
  try {
    let body;
    const expected = route ? {jobId:route[1]} : {};
    if (request.method === 'POST') {
      try {
        const maximum = route || erasure ? 1024 : MAX_REQUEST, length = framed(request.headers, maximum);
        body = await bounded(request.body, maximum, deadline);
        if (!body.byteLength || length !== null && body.byteLength !== length) throw Error('invalid_length');
        const value = JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(body));
        if (route || erasure) {
          if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('invalid_control');
          if (Object.keys(value).length !== 0 && !(route?.[2] === 'retry'
              && Object.keys(value).sort().join(',') === 'expectedAttempts,requestId'
              && typeof value.requestId === 'string' && HEX.test(value.requestId)
              && Number.isInteger(value.expectedAttempts) && value.expectedAttempts >= 0 && value.expectedAttempts < 3)) {
            throw Error('invalid_control');
          }
        } else {
          for (const key of ['leaseId','profileId','policyId','assignmentSha256','submissionSha256']) {
            if (typeof value?.[key] !== 'string') throw Error('invalid_start');
            expected[key] = value[key];
          }
        }
      } catch { return reply(400, 'invalid_object_job'); }
    } else if (request.body) return reply(400, 'invalid_object_job');
    const transfer = Promise.resolve(fetcher(target.href, {
      method:request.method, redirect:'manual', signal:abort.signal,
      headers:{authorization:`Bearer ${secret}`, ...(body ? {'content-type':'application/json'} : {})}, body,
    })).then(response => {
      if (abort.signal.aborted) {
        if (response.body) void response.body.cancel().catch(() => {});
        throw Error('job_transport_timeout');
      }
      return response;
    });
    const response = await Promise.race([transfer, deadline]);
    try {
      const length = framed(response.headers, MAX_RESPONSE);
      const bytes = await bounded(response.body, MAX_RESPONSE, deadline);
      if (!bytes.byteLength || length !== null && length !== bytes.byteLength) throw Error('invalid_response_length');
      const value = JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(bytes));
      if (response.status !== 200) {
        if (value && Object.keys(value).join(',') === 'error' && ERRORS.get(value.error) === response.status) {
          return reply(response.status, value.error);
        }
        throw Error('unavailable');
      }
      const checked = erasure ? assignmentErasureResult(value, erasure[1])
        : route?.[2]==='settlement-evidence' ? objectSettlementEvidence(value,expected) : objectAuditResult(value, expected);
      if (!erasure && (route?.[2] === 'cancel' && !['cancelled','erasing','erased'].includes(checked.state)
          || route?.[2] === 'erase' && !['erasing','erased'].includes(checked.state)
          || ['erasing','erased'].includes(checked.state) && (checked.receiptSha256 !== null || checked.retryAt !== 0))) {
        throw Error('revocation_unconfirmed');
      }
      return Response.json(checked, {headers:{'cache-control':'no-store'}});
    } catch {
      if (response.body && !response.body.locked) void response.body.cancel().catch(() => {});
      return reply(503, 'object_verifier_unavailable');
    }
  } catch { return reply(503, 'object_verifier_unavailable'); }
  finally { clearTimeout(timer); abort.abort(); }
}

export default {fetch(request, env) { return handleObjectAuditJobs(request, env); }};
