// Persisted schema contract: requests read one row and never perform upgrades.
import { PRIVACY_FENCES } from "./accountPrivacy.js";

export const SCHEMA_REVISION = 1;
export const SCHEMA_CONTRACT = "vision-community-d1-v1-20261004";
export const SCHEMA_READ = "SELECT revision,contract FROM community_schema_revision WHERE slot=1";
const required = {
  accounts:["id","token_hash","units","recovery_hash","deleted_at"],
  locations:["id","asset_id","capture","lane","model","state","active_lease","lease_until","output_sha256","contributor_id","source","rights","attribution","lat","lon","heading","pitch","zoom","country","camera_generation","generation","queue_state","catalog_shard"],
  leases:["id","account_id","lane","expires_at","state","generation","pace","scene_qualification_id"],
  lease_items:["lease_id","location_id"],
  published_index:["location_id","index_text","output_sha256","published_at","embedding","segment_id","four_view_sha256","four_view_key","object_index_sha256","object_index_key"],
  ledger:["id","account_id","units","reason","reference"],
  searches:["id","account_id","idempotency_key","query","result_json"],
  pose_catalog:["lane","shard_id","r2_key","row_start","row_count","bytes","sha256","next_byte","next_row","assignee","assigned_at","held"],
  index_shards:["r2_key","lane","location_count","bytes","sha256","created_at"],
  object_coverage:["location_id","validator","evidence_sha256","validated_at"],
  scene_qualifications:["id","account_id","profile_id","policy_id","canary_sha256","expires_at","created_at"],
  scene_candidates:["lease_id","account_id","qualification_id","policy_id","submission_sha256","artifact_key","records_json","created_at","state"],
  account_artifact_writes:["artifact_key","account_id","lease_id","sha256","bytes","created_at"],
  account_deletion_receipts:["account_id","request_key","deleted_at","units_forfeited"],
  account_cleanup:["artifact_key","account_id","created_at","state"],
  account_deletion_archives:["account_id","sha256","archived_at"],
};
const quote = value => "'" + value.replaceAll("'","''") + "'";
export const normalizedSql = value => value.replace(/IF NOT EXISTS/ig,"").replace(/[\s;]/g,"").toLowerCase();
const normalizedStored = "lower(replace(replace(replace(replace(replace(replace(sql,'IF NOT EXISTS',''),'if not exists',''),' ',''),char(10),''),char(13),''),char(9),''))";
const fenceChecks = PRIVACY_FENCES.map(statement => {
  const name=statement.match(/CREATE TRIGGER IF NOT EXISTS (\w+)/)[1];
  return `EXISTS(SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=${quote(name)} AND replace(${normalizedStored},';','')=${quote(normalizedSql(statement))})`;
});
const columnChecks = Object.entries(required).map(([table,columns]) =>
  `(SELECT COUNT(*) FROM pragma_table_info(${quote(table)}) WHERE name IN (${columns.map(quote).join(",")}))=${columns.length}`);
const indexes=["locations_queue","locations_part_queue","scene_qualifications_lookup","account_artifact_writes_owner","published_index_four_view_key","account_cleanup_pending"];
export const SCHEMA_CHECK = [...columnChecks,...fenceChecks,
  `(SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name IN (${indexes.map(quote).join(",")}))=${indexes.length}`].join(" AND ");
export const SCHEMA_REVISION_SQL = [
  `CREATE TABLE IF NOT EXISTS community_schema_revision(
    slot INTEGER PRIMARY KEY CHECK(slot=1),revision INTEGER NOT NULL CHECK(revision>=1),
    contract TEXT NOT NULL,installed_at INTEGER NOT NULL)`,
  `INSERT INTO community_schema_revision(slot,revision,contract,installed_at)
    SELECT 1,CASE WHEN (${SCHEMA_CHECK}) AND NOT EXISTS
      (SELECT 1 FROM community_schema_revision WHERE revision>${SCHEMA_REVISION} OR contract!=${quote(SCHEMA_CONTRACT)})
      THEN ${SCHEMA_REVISION} ELSE 0 END,${quote(SCHEMA_CONTRACT)},CAST(strftime('%s','now') AS INTEGER)
    ON CONFLICT(slot) DO UPDATE SET revision=excluded.revision,contract=excluded.contract`
];

export class SchemaError extends Error {
  constructor() { super("schema_update_required"); this.status=503; }
}
export async function requireSchema(env) {
  try {
    const row=await env.DB.prepare(SCHEMA_READ).first();
    if (row?.revision!==SCHEMA_REVISION || row?.contract!==SCHEMA_CONTRACT) throw new SchemaError();
  } catch { throw new SchemaError(); }
}
