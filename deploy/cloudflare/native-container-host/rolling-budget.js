// A calendar counter alone permits two allowances around month-end. Keep a
// bounded rolling 31-day history as an additional host-level admission fence.
export const ROLLING_KEY = 'nativeRollingComputeBudgetV1';
export const WINDOW_MS = 31 * 86400000;
const integer = (n, min, max) => Number.isSafeInteger(n) && n >= min && n <= max;
const exact = (v, keys) => v && typeof v === 'object' && !Array.isArray(v)
  && Object.keys(v).sort().join(',') === keys;
export const rollingTotal = r => r.reservations.reduce((sum, event) => sum + event.cents, 0);

export function rollingRecord(saved, policy, now, legacyMonth) {
  if (!integer(now, 0, 8640000000000000)) throw Error('invalid_rolling_clock');
  if (saved !== undefined) {
    if (!exact(saved, 'lastAt,limitCents,openingCents,requestCents,reservations,startCents,version')
        || saved.version !== 1 || !integer(saved.lastAt, 0, now)
        || !integer(saved.limitCents, 0, 300) || !integer(saved.openingCents, 0, 300)
        || !integer(saved.requestCents, 1, 300) || !integer(saved.startCents, 1, 300)
        || !Array.isArray(saved.reservations) || saved.reservations.length > 300)
      throw Error('invalid_rolling_record');
    let previous = 0;
    for (const event of saved.reservations) {
      if (!exact(event, 'at,cents') || !integer(event.at, previous, saved.lastAt)
          || !integer(event.cents, 1, 300)) throw Error('invalid_rolling_record');
      previous = event.at;
    }
    if (rollingTotal(saved) > 300) throw Error('invalid_rolling_record');
  }
  // Treat uncertain legacy reservations as recent, not as free capacity. Do
  // not rewrite the existing monthly record or infer its individual timestamps.
  const legacy = saved === undefined ? legacyMonth?.reservedCents ?? 0 : 0;
  const events = saved === undefined ? (legacy ? [{at: now, cents: legacy}] : [])
    : saved.reservations.filter(event => event.at > now - WINDOW_MS).map(event => ({...event}));
  const active = events.length > 0;
  const record = {version: 1, lastAt: now,
    limitCents: active ? Math.min(saved?.limitCents ?? legacyMonth?.limitCents ?? policy.limitCents, policy.limitCents) : policy.limitCents,
    requestCents: active ? Math.max(saved?.requestCents ?? legacyMonth?.requestCents ?? 1, policy.requestCents) : policy.requestCents,
    startCents: active ? Math.max(saved?.startCents ?? legacyMonth?.startCents ?? 1, policy.startCents) : policy.startCents,
    openingCents: active && saved ? saved.openingCents : 0, reservations: events};
  if (policy.openingCents > record.openingCents) {
    const missing = Math.max(0, policy.openingCents - rollingTotal(record));
    if (missing) record.reservations.push({at: now, cents: missing});
    record.openingCents = policy.openingCents;
  }
  return record;
}

export function rollingRetrySeconds(record, cents, now) {
  let remaining = rollingTotal(record);
  for (const event of record.reservations) {
    remaining -= event.cents;
    if (remaining + cents <= record.limitCents)
      return Math.max(1, Math.ceil((event.at + WINDOW_MS - now) / 1000));
  }
  // Zero/too-small allocation requires an operator change, not busy polling.
  return 86400;
}
