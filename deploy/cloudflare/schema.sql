-- VISION Community prototype ledger. Imagery is never stored.
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  units INTEGER NOT NULL DEFAULT 0 CHECK (units >= 0),
  recovery_hash TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS locations (
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
  queue_state TEXT NOT NULL DEFAULT 'pending',
  UNIQUE (asset_id, capture, lane, model)
);
CREATE INDEX IF NOT EXISTS locations_queue ON locations (lane, state, lease_until, id);
CREATE TABLE IF NOT EXISTS leases (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  lane TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('active', 'submitted', 'expired')),
  generation INTEGER,
  pace TEXT
);
CREATE TABLE IF NOT EXISTS lease_items (
  lease_id TEXT NOT NULL REFERENCES leases(id),
  location_id INTEGER NOT NULL REFERENCES locations(id),
  PRIMARY KEY (lease_id, location_id)
);
CREATE TABLE IF NOT EXISTS published_index (
  location_id INTEGER PRIMARY KEY REFERENCES locations(id),
  index_text TEXT NOT NULL,
  output_sha256 TEXT NOT NULL,
  published_at INTEGER NOT NULL,
  embedding TEXT,
  segment_id TEXT,
  four_view_sha256 TEXT,
  four_view_key TEXT
);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  units INTEGER NOT NULL,
  reason TEXT NOT NULL,
  reference TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS searches (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  idempotency_key TEXT NOT NULL,
  query TEXT NOT NULL,
  result_json TEXT NOT NULL,
  UNIQUE (account_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS pose_catalog (
  lane TEXT NOT NULL,
  shard_id INTEGER NOT NULL,
  r2_key TEXT NOT NULL,
  row_start INTEGER NOT NULL,
  row_count INTEGER NOT NULL,
  bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  next_byte INTEGER NOT NULL DEFAULT 0,
  next_row INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (lane, shard_id)
);
