-- Schema-only readback of the confirmed Community D1, 9 October 2026.
-- Contains no accounts, credentials, searches, locations or other production rows.
-- Keep legacy CHECK/foreign-key constraints in the upgrade rehearsal.

CREATE TABLE accounts (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  units INTEGER NOT NULL DEFAULT 0 CHECK (units >= 0),
  recovery_hash TEXT UNIQUE
);

CREATE TABLE index_shards (
  r2_key TEXT PRIMARY KEY, lane TEXT NOT NULL, location_count INTEGER NOT NULL,
  bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at INTEGER NOT NULL
);

CREATE TABLE lease_items (
  lease_id TEXT NOT NULL REFERENCES leases(id),
  location_id INTEGER NOT NULL REFERENCES locations(id),
  PRIMARY KEY (lease_id, location_id)
);

CREATE TABLE leases (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  lane TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('active', 'submitted', 'expired')),
  generation INTEGER,
  pace TEXT
);

CREATE TABLE ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  units INTEGER NOT NULL,
  reason TEXT NOT NULL,
  reference TEXT NOT NULL UNIQUE
);

CREATE TABLE locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT NOT NULL,
  capture TEXT NOT NULL,
  lane TEXT NOT NULL CHECK (lane IN ('scene', 'object')),
  model TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'leased', 'published')),
  active_lease TEXT,
  lease_until INTEGER,
  output_sha256 TEXT,
  contributor_id TEXT,
  source TEXT,
  rights TEXT,
  attribution TEXT,
  lat REAL,
  lon REAL,
  heading REAL NOT NULL DEFAULT 0,
  pitch REAL NOT NULL DEFAULT 0,
  zoom REAL NOT NULL DEFAULT 0,
  country TEXT,
  camera_generation TEXT,
  generation INTEGER NOT NULL DEFAULT 0,
  queue_state TEXT NOT NULL DEFAULT 'pending', catalog_shard INTEGER,
  UNIQUE (asset_id, capture, lane, model)
);

CREATE TABLE "pose_catalog" (lane TEXT NOT NULL, shard_id INTEGER NOT NULL, r2_key TEXT NOT NULL, row_start INTEGER NOT NULL, row_count INTEGER NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, next_byte INTEGER NOT NULL DEFAULT 0, next_row INTEGER NOT NULL DEFAULT 0, assignee TEXT, assigned_at INTEGER, held INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (lane, shard_id));

CREATE TABLE published_index (
  location_id INTEGER PRIMARY KEY REFERENCES locations(id),
  index_text TEXT NOT NULL,
  output_sha256 TEXT NOT NULL,
  published_at INTEGER NOT NULL,
  embedding TEXT,
  segment_id TEXT
, four_view_sha256 TEXT, four_view_key TEXT, object_index_sha256 TEXT, object_index_key TEXT);

CREATE TABLE searches (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  idempotency_key TEXT NOT NULL,
  query TEXT NOT NULL,
  result_json TEXT NOT NULL,
  UNIQUE (account_id, idempotency_key)
);

CREATE INDEX locations_part_queue ON locations (lane, catalog_shard, state, lease_until, id);

CREATE INDEX locations_queue ON locations (lane, state, lease_until, id);
