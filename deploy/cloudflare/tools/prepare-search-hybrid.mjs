// Operator-only offline migration. No endpoint performs setup.
import { HYBRID_SCHEMA,HYBRID_CONTRACT_SQL } from '../src/searchHybridSchema.js';
import { requireSearchQueue } from '../src/searchQueue.js';
export async function prepareSearchHybrid(db) {
  await requireSearchQueue(db);
  const existing=await db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='search_hybrid_revision'").first();
  if(existing&&!await db.prepare('SELECT 1 FROM search_cloud_budget WHERE slot=1').first())throw Error('hybrid_budget_reconciliation_required');
  // Never reinterpret an already running legacy claim as safely stopped.
  if(await db.prepare("SELECT 1 FROM search_jobs WHERE state='claimed' LIMIT 1").first())throw Error('hybrid_running_claims_require_reconciliation');
  await db.batch([...HYBRID_SCHEMA,HYBRID_CONTRACT_SQL,
    ...(!existing?[`INSERT INTO search_cloud_budget VALUES (1,'uninitialized-v1','${'0'.repeat(64)}')`]:[])]
    .map(sql=>db.prepare(sql)));
}
