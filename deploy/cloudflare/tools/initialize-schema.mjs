// Explicit offline/operator schema preparation. Never called by HTTP requests.
import { migrateAccountPrivacy } from "../src/accountPrivacy.js";
import { SCENE_PIPELINE_SCHEMA } from "../src/scenePipeline.js";
import { SCHEMA_REVISION_SQL } from "../src/schemaRevision.js";

const SCHEMA = `
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
  units INTEGER NOT NULL DEFAULT 0 CHECK (units >= 0), recovery_hash TEXT UNIQUE, deleted_at INTEGER
);
CREATE TABLE IF NOT EXISTS locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT NOT NULL, capture TEXT NOT NULL,
  lane TEXT NOT NULL, model TEXT NOT NULL, label TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'pending', active_lease TEXT, lease_until INTEGER,
  output_sha256 TEXT, contributor_id TEXT, source TEXT, rights TEXT, attribution TEXT,
  lat REAL, lon REAL, heading REAL NOT NULL DEFAULT 0, pitch REAL NOT NULL DEFAULT 0,
  zoom REAL NOT NULL DEFAULT 0, country TEXT, camera_generation TEXT,
  generation INTEGER NOT NULL DEFAULT 0, queue_state TEXT NOT NULL DEFAULT 'pending',
  UNIQUE (asset_id, capture, lane, model)
);
CREATE INDEX IF NOT EXISTS locations_queue ON locations (lane, state, lease_until, id);
CREATE TABLE IF NOT EXISTS leases (
  id TEXT PRIMARY KEY, account_id TEXT NOT NULL, lane TEXT NOT NULL,
  expires_at INTEGER NOT NULL, state TEXT NOT NULL, generation INTEGER, pace TEXT,
  scene_qualification_id TEXT
);
CREATE TABLE IF NOT EXISTS lease_items (
  lease_id TEXT NOT NULL, location_id INTEGER NOT NULL, PRIMARY KEY (lease_id, location_id)
);
CREATE TABLE IF NOT EXISTS published_index (
  location_id INTEGER PRIMARY KEY, index_text TEXT NOT NULL, output_sha256 TEXT NOT NULL,
  published_at INTEGER NOT NULL, embedding TEXT, segment_id TEXT
);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL, units INTEGER NOT NULL,
  reason TEXT NOT NULL, reference TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS searches (
  id TEXT PRIMARY KEY, account_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
  query TEXT NOT NULL, result_json TEXT NOT NULL, UNIQUE (account_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS pose_catalog (
  lane TEXT NOT NULL, shard_id INTEGER NOT NULL, r2_key TEXT NOT NULL,
  row_start INTEGER NOT NULL, row_count INTEGER NOT NULL, bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL, next_byte INTEGER NOT NULL DEFAULT 0, next_row INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (lane, shard_id)
);
CREATE TABLE IF NOT EXISTS index_shards (
  r2_key TEXT PRIMARY KEY, lane TEXT NOT NULL, location_count INTEGER NOT NULL,
  bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS object_coverage (
  location_id INTEGER PRIMARY KEY REFERENCES locations(id),
  validator TEXT NOT NULL, evidence_sha256 TEXT NOT NULL, validated_at INTEGER NOT NULL
);
`;

export async function initializeSchema(env) {
  for (const statement of SCHEMA.split(";").map((item) => item.trim()).filter(Boolean)) {
    await env.DB.prepare(statement).run();
  }
  await migratePoseCatalog(env);
  await migrateWorkParts(env);
  await migrateFourView(env);
  for (const statement of SCENE_PIPELINE_SCHEMA.split(";").map((item) => item.trim()).filter(Boolean)) {
    await env.DB.prepare(statement).run();
  }
  await env.DB.prepare('CREATE INDEX IF NOT EXISTS scene_qualifications_lookup ON scene_qualifications(account_id,policy_id,profile_id,expires_at)').run();
  const leaseColumns = await tableColumns(env, "leases");
  if (!leaseColumns.includes("scene_qualification_id")) {
    await env.DB.prepare("ALTER TABLE leases ADD COLUMN scene_qualification_id TEXT").run();
  }
  await migrateAccountPrivacy(env);
}

async function migratePoseCatalog(env) {
  const row = await env.DB.prepare("SELECT sql FROM sqlite_master WHERE name='pose_catalog'").first();
  if (!row?.sql || !row.sql.includes("r2_key TEXT NOT NULL UNIQUE")) return;
  await env.DB.prepare(`CREATE TABLE pose_catalog_v2 (
    lane TEXT NOT NULL, shard_id INTEGER NOT NULL, r2_key TEXT NOT NULL,
    row_start INTEGER NOT NULL, row_count INTEGER NOT NULL, bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL, next_byte INTEGER NOT NULL DEFAULT 0, next_row INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (lane, shard_id)
  )`).run();
  await env.DB.prepare("INSERT OR IGNORE INTO pose_catalog_v2 SELECT * FROM pose_catalog").run();
  await env.DB.prepare("DROP TABLE pose_catalog").run();
  await env.DB.prepare("ALTER TABLE pose_catalog_v2 RENAME TO pose_catalog").run();
}

async function tableColumns(env, table) {
  return ((await env.DB.prepare(`PRAGMA table_info(${table})`).all()).results || []).map((row) => row.name);
}

async function migrateFourView(env) {
  const cols = await tableColumns(env, "published_index");
  if (!cols.includes("four_view_sha256")) {
    await env.DB.prepare("ALTER TABLE published_index ADD COLUMN four_view_sha256 TEXT").run();
  }
  if (!cols.includes("four_view_key")) {
    await env.DB.prepare("ALTER TABLE published_index ADD COLUMN four_view_key TEXT").run();
  }
  if (!cols.includes("object_index_sha256")) {
    await env.DB.prepare("ALTER TABLE published_index ADD COLUMN object_index_sha256 TEXT").run();
  }
  if (!cols.includes("object_index_key")) {
    await env.DB.prepare("ALTER TABLE published_index ADD COLUMN object_index_key TEXT").run();
  }
}

async function migrateWorkParts(env) {
  const locationCols = await tableColumns(env, "locations");
  const addedShard = !locationCols.includes("catalog_shard");
  if (addedShard) {
    await env.DB.prepare("ALTER TABLE locations ADD COLUMN catalog_shard INTEGER").run();
  }
  const catalogCols = await tableColumns(env, "pose_catalog");
  if (!catalogCols.includes("assignee")) {
    await env.DB.prepare("ALTER TABLE pose_catalog ADD COLUMN assignee TEXT").run();
  }
  if (!catalogCols.includes("assigned_at")) {
    await env.DB.prepare("ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER").run();
  }
  if (!catalogCols.includes("held")) {
    await env.DB.prepare("ALTER TABLE pose_catalog ADD COLUMN held INTEGER NOT NULL DEFAULT 0").run();
  }
  await env.DB.prepare(
    "CREATE INDEX IF NOT EXISTS locations_part_queue ON locations (lane, catalog_shard, state, lease_until, id)"
  ).run();
  if (addedShard) {
    await env.DB.prepare(
      `UPDATE locations SET catalog_shard = (
          SELECT p.shard_id FROM pose_catalog p
          WHERE p.lane = locations.lane AND p.r2_key LIKE 'catalog/all-locations-tail-v1/%'
          ORDER BY p.shard_id LIMIT 1
       )
       WHERE catalog_shard IS NULL
         AND COALESCE(source, '') = 'street-metadata'
         AND asset_id NOT LIKE 'Prototype%'
         AND asset_id NOT LIKE 'synthetic:%'
         AND asset_id NOT LIKE 'CommunityPano%'
         AND EXISTS (
           SELECT 1 FROM pose_catalog p
           WHERE p.lane = locations.lane AND p.r2_key LIKE 'catalog/all-locations-tail-v1/%'
         )`
    ).run();
  }
}


export async function prepareDatabase(db) {
  await initializeSchema({DB:db});
  await db.batch(SCHEMA_REVISION_SQL.map(statement=>db.prepare(statement)));
}
