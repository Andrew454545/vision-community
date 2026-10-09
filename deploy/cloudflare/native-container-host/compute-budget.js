// One bounded durable record for the existing single-instance native host.
// This limits operations and starts, not the entire Cloudflare invoice.
export const BUDGET_KEY = 'nativeComputeBudgetV1';
const DAY_MS = 86400000;
const FIELDS = 'day,requestLimit,requests,startLimit,starts,version';

export class ComputeBudgetError extends Error {
  constructor(code, now) {
    super(code);
    this.retryAfter = code === 'native_compute_budget_exhausted'
      ? Math.ceil((DAY_MS - now % DAY_MS) / 1000) : 60;
  }
}

function limits(env) {
  const parse = (value, maximum) => {
    if (typeof value !== 'string' || !/^[1-9][0-9]{0,4}$/.test(value)
        || Number(value) > maximum) throw Error('invalid_budget_configuration');
    return Number(value);
  };
  return {requestLimit:parse(env.NATIVE_DAILY_COMPUTE_REQUESTS,10000),
    startLimit:parse(env.NATIVE_DAILY_CONTAINER_STARTS,1000)};
}

function current(saved, configured, now) {
  if (!Number.isSafeInteger(now) || now < 0 || now > 8640000000000000) throw Error('invalid_budget_clock');
  const day = Math.floor(now / DAY_MS);
  if (saved !== undefined) {
    if (!saved || typeof saved !== 'object' || Array.isArray(saved)
        || Object.keys(saved).sort().join(',') !== FIELDS || saved.version !== 1
        || !Number.isSafeInteger(saved.day) || saved.day < 0 || saved.day > day
        || !Number.isSafeInteger(saved.requests) || saved.requests < 0
        || !Number.isSafeInteger(saved.starts) || saved.starts < 0
        || !Number.isSafeInteger(saved.requestLimit) || saved.requestLimit < 1 || saved.requestLimit > 10000
        || !Number.isSafeInteger(saved.startLimit) || saved.startLimit < 1 || saved.startLimit > 1000
        || saved.requests > 10000 || saved.starts > 1000) throw Error('invalid_budget_record');
  }
  if (saved === undefined || saved.day < day) return {version:1,day,...configured,requests:0,starts:0};
  // A redeploy/config increase cannot reset or raise today's sealed allowance.
  // Lowered limits apply immediately and remain sticky until the next UTC day.
  return {...saved,requestLimit:Math.min(saved.requestLimit,configured.requestLimit),
    startLimit:Math.min(saved.startLimit,configured.startLimit)};
}

export async function reserveCompute(storage, env, kind, now = Date.now()) {
  try {
    const configured = limits(env);
    if (!['request','start'].includes(kind) || typeof storage?.transaction !== 'function'
        || typeof storage?.sync !== 'function') throw Error('invalid_budget_storage');
    const exhausted = await storage.transaction(async transaction => {
      const saved = await transaction.get(BUDGET_KEY);
      const record = current(saved,configured,now);
      const field = kind === 'request' ? 'requests' : 'starts';
      if (record.requests > record.requestLimit || record.starts > record.startLimit
          || record[field] >= (kind === 'request' ? record.requestLimit : record.startLimit)) {
        // Persist a lowered allowance even when usage already exceeds it. A
        // later config increase cannot reopen this same UTC day's budget.
        if (JSON.stringify(record) !== JSON.stringify(saved)) await transaction.put(BUDGET_KEY,record);
        return true;
      }
      record[field]++;
      await transaction.put(BUDGET_KEY,record);
      return false;
    });
    // No native side effect before the allowance is durably reserved. Failed or
    // interrupted work is never refunded; an uncertain write cannot grant work.
    await storage.sync();
    if (exhausted) throw new ComputeBudgetError('native_compute_budget_exhausted',now);
  } catch (error) {
    if (error instanceof ComputeBudgetError) throw error;
    throw new ComputeBudgetError('native_compute_budget_unavailable',now);
  }
}

export async function computeBudgetStatus(storage, env, now = Date.now()) {
  try {
    const record = current(await storage.get(BUDGET_KEY),limits(env),now);
    return {configured:true,utcDay:record.day,requests:record.requests,starts:record.starts,
      requestLimit:record.requestLimit,startLimit:record.startLimit,
      requestsRemaining:Math.max(0,record.requestLimit-record.requests),
      startsRemaining:Math.max(0,record.startLimit-record.starts)};
  } catch {
    return {configured:false,reason:'native_compute_budget_unavailable'};
  }
}
