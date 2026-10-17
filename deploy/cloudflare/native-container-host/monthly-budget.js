// Optional host allocation, not a provider invoice cap. All compute hosts must
// share an allocation authority before this can become a project-wide control.
export const MONTHLY_KEY = 'nativeMonthlyComputeBudgetV1';

export function monthlyPolicy(env) {
  if (env.NATIVE_MONTHLY_COMPUTE_POLICY === undefined) return null;
  const raw = env.NATIVE_MONTHLY_COMPUTE_POLICY;
  if (typeof raw !== 'string' || raw.length > 512) throw Error('invalid_monthly_policy');
  const p = JSON.parse(raw);
  if (!p || Object.keys(p).sort().join(',') !== 'limitCents,openingCents,requestCents,startCents'
      || !Number.isSafeInteger(p.limitCents) || p.limitCents < 0 || p.limitCents > 300
      || !Number.isSafeInteger(p.openingCents) || p.openingCents < 0 || p.openingCents > p.limitCents
      || !Number.isSafeInteger(p.requestCents) || p.requestCents < 1 || p.requestCents > 300
      || !Number.isSafeInteger(p.startCents) || p.startCents < 1 || p.startCents > 300)
    throw Error('invalid_monthly_policy');
  return p;
}

export function monthlyRecord(saved, policy, now) {
  if (!Number.isSafeInteger(now) || now < 0 || now > 8640000000000000) throw Error('invalid_monthly_clock');
  const date = new Date(now);
  const month = date.getUTCFullYear() * 12 + date.getUTCMonth();
  if (saved !== undefined && (!saved || Array.isArray(saved)
      || Object.keys(saved).sort().join(',') !== 'limitCents,month,requestCents,reservedCents,startCents,version'
      || saved.version !== 1 || !Number.isSafeInteger(saved.month) || saved.month < 1970 * 12 || saved.month > month
      || !Number.isSafeInteger(saved.reservedCents) || saved.reservedCents < 0 || saved.reservedCents > 300
      || !Number.isSafeInteger(saved.limitCents) || saved.limitCents < 0 || saved.limitCents > 300
      || !Number.isSafeInteger(saved.requestCents) || saved.requestCents < 1 || saved.requestCents > 300
      || !Number.isSafeInteger(saved.startCents) || saved.startCents < 1 || saved.startCents > 300))
    throw Error('invalid_monthly_record');
  if (saved === undefined || saved.month < month) return {
    version: 1, month, limitCents: policy.limitCents, reservedCents: policy.openingCents,
    requestCents: policy.requestCents, startCents: policy.startCents,
  };
  return {...saved, limitCents: Math.min(saved.limitCents, policy.limitCents),
    reservedCents: Math.max(saved.reservedCents, policy.openingCents),
    requestCents: Math.max(saved.requestCents, policy.requestCents),
    startCents: Math.max(saved.startCents, policy.startCents)};
}

export function nextMonthSeconds(now) {
  const d = new Date(now);
  return Math.ceil((Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1) - now) / 1000);
}
