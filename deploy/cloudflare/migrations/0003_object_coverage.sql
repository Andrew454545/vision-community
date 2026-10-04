-- Object work is admitted only after the trusted historical-coverage importer
-- records an official Gen 4 receipt. Volunteers and generic pose catalogs
-- must never write this table.
CREATE TABLE IF NOT EXISTS object_coverage (
  location_id INTEGER PRIMARY KEY REFERENCES locations(id),
  validator TEXT NOT NULL,
  evidence_sha256 TEXT NOT NULL,
  validated_at INTEGER NOT NULL
);
