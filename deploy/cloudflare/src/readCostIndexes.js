// Additive operator-maintenance indexes; never install from an HTTP request.
// Historical publications/leases and all authority/financial rows are retained.
export const READ_COST_INDEXES = Object.freeze([
  "CREATE INDEX IF NOT EXISTS locations_unpublished_lane_id ON locations(lane,id) WHERE state!='published'",
  'CREATE INDEX IF NOT EXISTS locations_active_lease_lookup ON locations(active_lease) WHERE active_lease IS NOT NULL',
  "CREATE INDEX IF NOT EXISTS leases_active_account_lookup ON leases(account_id,lane,expires_at DESC) WHERE state='active'",
]);

export async function prepareReadCostIndexes(db) {
  for (const statement of READ_COST_INDEXES) await db.prepare(statement).run();
}
