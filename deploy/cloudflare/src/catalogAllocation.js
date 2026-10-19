// These families overlap the owner's indexed/reserved corpus. A database hold
// is operational state; clearing it must never revive a retired allocation.
export const RETIRED_CATALOG_PREFIXES = Object.freeze([
  'catalog/all-locations-tail-v1/',
  'catalog/all-locations-full-v1/',
  'catalog/vision-indexed-v1/',
]);

function alias(value) {
  if (!/^[a-z_][a-z0-9_]*$/i.test(value)) throw Error('invalid_sql_alias');
  return value;
}

export function availableCatalogSql(table = 'pose_catalog') {
  table = alias(table);
  return `(COALESCE(${table}.held,0)=0 AND ${RETIRED_CATALOG_PREFIXES
    .map(prefix => `${table}.r2_key NOT LIKE '${prefix}%'`).join(' AND ')})`;
}

export function availableLocationSql(table = 'locations') {
  table = alias(table);
  // Operator-prepared uncataloged pools still need their independent Scene or
  // official-Gen4 Object evidence. A missing catalog registration fails closed.
  return `(${table}.catalog_shard IS NULL OR EXISTS (SELECT 1 FROM pose_catalog allocation
    WHERE allocation.lane=${table}.lane AND allocation.shard_id=${table}.catalog_shard
      AND ${availableCatalogSql('allocation')}))`;
}

export function freshLeaseItemSql() {
  // NULL violates lease_items.location_id's existing NOT NULL constraint, so a
  // late hold or competing claim rolls back the entire D1 batch, including the
  // lease header. Selection before an awaited R2 read is not authorization.
  return `INSERT INTO lease_items(lease_id,location_id) VALUES (?,
    (SELECT id FROM locations WHERE id=? AND ${availableLocationSql()}
      AND COALESCE(queue_state,'pending')='pending'
      AND (state='pending' OR (state='leased' AND lease_until<=?))))`;
}
