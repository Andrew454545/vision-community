// Result, debit and ledger entry are one D1 transaction. Work can fail before
// this point without spending credit; a lost response can replay the result.
export class SearchError extends Error {
  constructor(code, status = 503) { super(code); this.code = code; this.status = status; }
}

export const SEARCH_REQUEST_SECONDS = 3600;
export function requireFreshSearchRequest(key, now = Math.floor(Date.now() / 1000), { allowLegacy = false } = {}) {
  // Paid replies are replayed before this check. Both delivery modes refuse an
  // old unpaid timestamped key, including after queue tombstones are pruned or
  // the operator rolls back to synchronous delivery. Historical clients retain
  // their original key format on the legacy synchronous route.
  if (allowLegacy && !key.startsWith('q1.')) return;
  const issued = /^q1\.([0-9]{10})\.[0-9a-f]{32}$/.exec(key);
  if (!issued || Number(issued[1]) > now + 300 || now - Number(issued[1]) > SEARCH_REQUEST_SECONDS)
    throw new SearchError('search_request_expired', 400);
}

export async function replaySearch(db, account, key, digest) {
  const saved = await db.prepare(`SELECT s.query,s.result_json FROM searches s JOIN accounts a ON a.id=s.account_id
    WHERE s.account_id=? AND s.idempotency_key=? AND a.deleted_at IS NULL`)
    .bind(account, key).first();
  if (!saved) return null;
  if (saved.query !== digest) throw new SearchError("idempotency_conflict", 409);
  return JSON.parse(saved.result_json);
}

export async function settleSearch(db, account, key, digest, result, cost) {
  if (!Number.isSafeInteger(cost) || cost <= 0) throw new SearchError("search_unavailable");
  const replay = await replaySearch(db, account, key, digest);
  if (replay) return replay;
  const reference = `search:${result.searchId}`;
  try { await db.batch([
    db.prepare(`INSERT INTO ledger (account_id,units,reason,reference)
      SELECT id,?,'search',? FROM accounts WHERE id=? AND units>=? AND deleted_at IS NULL
        AND NOT EXISTS (SELECT 1 FROM searches WHERE account_id=? AND idempotency_key=?)`)
      .bind(-cost, reference, account, cost, account, key),
    db.prepare(`INSERT INTO searches (id,account_id,idempotency_key,query,result_json)
      SELECT ?,?,?,?,? WHERE EXISTS
        (SELECT 1 FROM ledger d JOIN accounts a ON a.id=d.account_id
          WHERE d.account_id=? AND d.reference=? AND d.reason='search' AND a.deleted_at IS NULL)`)
      .bind(result.searchId, account, key, digest, JSON.stringify(result), account, reference),
    db.prepare(`UPDATE accounts SET units=units-? WHERE id=? AND deleted_at IS NULL AND EXISTS
      (SELECT 1 FROM searches WHERE id=? AND account_id=? AND idempotency_key=?)`)
      .bind(cost, account, result.searchId, account, key),
  ]); } catch (failure) {
    // Optional queue guards also fence older synchronous writers during a
    // rollback. The whole failed transaction (including its ledger) rolls back.
    if (String(failure.message).includes('search_credit_reserved')) throw new SearchError('insufficient_credit', 402);
    throw failure;
  }
  const saved = await replaySearch(db, account, key, digest);
  if (saved) return saved;
  const owner = await db.prepare("SELECT id FROM accounts WHERE id=? AND deleted_at IS NULL").bind(account).first();
  throw new SearchError(owner ? "insufficient_credit" : "unauthorized", owner ? 402 : 401);
}
