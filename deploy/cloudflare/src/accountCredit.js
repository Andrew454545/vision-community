// Explicit account-only refresh. Corpus/work dashboards remain separate.
import { SearchError } from './searchLedger.js';
import { searchCost } from './searchPricing.js';
import { requireSearchQueue, maintainSearchQueue, searchCredit } from './searchQueue.js';

export async function accountCredit(env, account) {
  let balance;
  if (env.SEARCH_DELIVERY === 'queued-v1') {
    // Preserve the existing bounded reservation expiry and financial authority.
    await requireSearchQueue(env.DB);
    await maintainSearchQueue(env.DB);
    balance = await searchCredit(env.DB, account);
  } else {
    const row = await env.DB.prepare('SELECT units FROM accounts WHERE id=? AND deleted_at IS NULL').bind(account).first();
    if (!row) throw new SearchError('unauthorized', 401);
    balance = {units: row.units};
  }
  const cost = searchCost(env);
  return {creditContractVersion: 1, accountId: account, ...balance, searchCost: cost,
    searchesAvailable: cost === null ? 0 : Math.floor(balance.units / cost)};
}
