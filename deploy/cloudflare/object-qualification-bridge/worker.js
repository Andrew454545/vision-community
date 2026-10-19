// Dedicated private binding for saved sample comparisons. No audit, native
// execution, upload, qualification authority, public route or startup trigger.
export const MAX_REQUEST = 4096, MAX_RESPONSE = 65536;
const ROUTE = '/object-qualifications/evidence';
const ID = /^[0-9a-f]{32}$/, HEX = /^[0-9a-f]{64}$/;
const exact = (v, keys) => v && typeof v === 'object' && !Array.isArray(v)
  && Object.keys(v).sort().join(',') === [...keys].sort().join(',');
const reply = (status, error) => Response.json({error}, {status, headers:{'cache-control':'no-store'}});

async function bounded(stream, maximum, deadline) {
  if (!stream) throw Error();
  const reader = stream.getReader(), chunks = [];
  let size = 0;
  try {
    // Bound tiny/empty chunks as well as bytes, so a timer gets to run.
    for (let i = 0; i < 8192; i++) {
      const {value, done} = await Promise.race([reader.read(), deadline]);
      if (done) {
        const bytes = new Uint8Array(size);
        let offset = 0;
        for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.byteLength;}
        return bytes;
      }
      if (!(value instanceof Uint8Array) || size + value.byteLength > maximum) throw Error();
      size += value.byteLength; chunks.push(value);
    }
    throw Error();
  } finally {void reader.cancel().catch(()=>{}); reader.releaseLock();}
}

function framed(headers, maximum) {
  if (headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json'
      || headers.has('content-encoding') || headers.has('transfer-encoding')) throw Error();
  const length = headers.get('content-length');
  if (length !== null && (!/^[0-9]{1,6}$/.test(length) || Number(length) < 1 || Number(length) > maximum)) throw Error();
  return length === null ? null : Number(length);
}

const requestFields = ['version','accountId','requestId','challenge','profileId','artifactSetSha256','policyId','policySha256'];
function validRequest(v) {
  return exact(v, requestFields) && v.version === 1
    && ['accountId','requestId','challenge'].every(k=>typeof v[k] === 'string' && ID.test(v[k]))
    && ['profileId','artifactSetSha256','policySha256'].every(k=>typeof v[k] === 'string' && HEX.test(v[k]))
    && typeof v.policyId === 'string' && /^[A-Za-z0-9_.-]{1,128}$/.test(v.policyId);
}

function checked(value, expected, now) {
  if (!exact(value, ['version','scope','accountId','requestId','challenge','artifactSetSha256','artifacts','report','issuedAt','expiresAt'])
      || value.version !== 1 || value.scope !== 'trusted-saved-object-sample-evidence-v1'
      || ['accountId','requestId','challenge','artifactSetSha256'].some(k=>value[k] !== expected[k])
      || !Number.isSafeInteger(value.issuedAt) || value.issuedAt < now - 65 || value.issuedAt > now + 2
      || !Number.isSafeInteger(value.expiresAt) || value.expiresAt <= now || value.expiresAt > value.issuedAt + 30
      || !exact(value.artifacts,['detectorProfileId','indexProfileId','detectorSettingsSha256','indexSettingsSha256','executionReceiptSha256'])
      || value.artifacts.detectorProfileId !== expected.profileId || value.artifacts.indexProfileId !== expected.profileId
      || !['detectorSettingsSha256','indexSettingsSha256','executionReceiptSha256'].every(k=>typeof value.artifacts[k] === 'string' && HEX.test(value.artifacts[k]))
      || value.artifacts.detectorSettingsSha256 !== value.artifacts.indexSettingsSha256) throw Error();
  const r = value.report;
  if (!r || r.version !== 1 || r.qualificationScope !== 'fixed-input-object-score-and-index-parity-only'
      || r.profileId !== expected.profileId || r.policyId !== expected.policyId || r.policySha256 !== expected.policySha256
      || ['qualified','serverAuthorization','productionQualified','currentEligibilityVerified','inferenceProvenanceVerified'].some(k=>r[k] !== false)
      || r.identicalInputBindingVerified !== true || r.acceptedContributions !== 0 || r.searchCreditsCreated !== 0
      || !['sampleCompatible','scoreCompatible','indexCompatible'].every(k=>typeof r[k] === 'boolean')
      || r.sampleCompatible !== (r.scoreCompatible && r.indexCompatible)) throw Error();
  // Complete numerical/profile/authority validation belongs to the registry;
  // this transport never turns a private report into an approval itself.
  return value;
}

export async function handleObjectQualification(request, env, fetcher = fetch, timeoutMs = 69000) {
  const url = new URL(request.url);
  if (url.pathname !== ROUTE || url.search || url.hash || request.method !== 'POST') return reply(404,'not_found');
  let target;
  const secret = env.OBJECT_SAMPLE_QUALIFIER_SECRET;
  try {
    target = new URL(env.OBJECT_SAMPLE_QUALIFIER_ORIGIN);
    if (target.protocol !== 'https:' || target.username || target.password || target.pathname !== '/' || target.search || target.hash
        || typeof secret !== 'string' || !/^[\x21-\x7e]{32,256}$/.test(secret)
        || !Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 69000) throw Error();
    target.pathname = ROUTE;
  } catch {return reply(503,'object_sample_host_unavailable');}
  const abort = new AbortController();
  let timer, upstream;
  const deadline = new Promise((_, reject)=>{timer=setTimeout(()=>{abort.abort();reject(Error());},timeoutMs);});
  void deadline.catch(()=>{});
  try {
    let body, expected;
    try {
      const size = framed(request.headers, MAX_REQUEST);
      body = await bounded(request.body, MAX_REQUEST, deadline);
      if (!body.byteLength || size !== null && size !== body.byteLength) throw Error();
      const text = new TextDecoder('utf-8',{fatal:true}).decode(body);
      expected = JSON.parse(text);
      const keys = [...text.matchAll(/"(?:[^"\\]|\\.)*"\s*:/g)].map(m=>JSON.parse(m[0].replace(/\s*:$/,'')));
      if (!validRequest(expected) || keys.length !== requestFields.length || new Set(keys).size !== keys.length) throw Error();
      // Canonical validated fields only; no duplicate JSON ambiguity reaches
      // the host, which additionally rejects duplicate keys in its own parser.
      body = JSON.stringify(expected);
    } catch {return reply(400,'invalid_object_sample_request');}
    const transfer = Promise.resolve().then(()=>fetcher(target.href, {
      method:'POST', redirect:'manual', signal:abort.signal,
      headers:{authorization:`Bearer ${secret}`,'content-type':'application/json'}, body,
    })).then(response=>{
      if (abort.signal.aborted) {if(response.body)void response.body.cancel().catch(()=>{});throw Error();}
      return response;
    });
    const response = upstream = await Promise.race([transfer, deadline]);
    const size = framed(response.headers, MAX_RESPONSE);
    const raw = await bounded(response.body, MAX_RESPONSE, deadline);
    if (!raw.byteLength || size !== null && size !== raw.byteLength) throw Error();
    const value = JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
    if (response.status !== 200) {
      if (response.status === 503 && exact(value,['error']) && value.error === 'object_sample_host_busy') return reply(503,value.error);
      throw Error();
    }
    return Response.json(checked(value,expected,Math.floor(Date.now()/1000)),{headers:{'cache-control':'no-store'}});
  } catch {return reply(503,'object_sample_host_unavailable');}
  finally {
    clearTimeout(timer);abort.abort();
    if (upstream?.body && !upstream.body.locked) void upstream.body.cancel().catch(()=>{});
  }
}

export default {fetch(request, env) {return handleObjectQualification(request, env);}};
