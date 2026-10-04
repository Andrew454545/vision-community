// Result, debit and ledger entry are one D1 transaction. Work can fail before
// this point without spending credit; a lost response can replay the result.
export class SearchError extends Error {
  constructor(code, status = 503) { super(code); this.code = code; this.status = status; }
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
  await db.batch([
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
  ]);
  const saved = await replaySearch(db, account, key, digest);
  if (saved) return saved;
  const owner = await db.prepare("SELECT id FROM accounts WHERE id=? AND deleted_at IS NULL").bind(account).first();
  throw new SearchError(owner ? "insufficient_credit" : "unauthorized", owner ? 402 : 401);
}
