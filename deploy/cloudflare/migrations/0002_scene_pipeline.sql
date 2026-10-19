-- Scene contributions remain fail-closed until SCENE_VERIFIER and SCENE_POLICY_ID
-- are configured in the staging/production Worker.
ALTER TABLE leases ADD COLUMN scene_qualification_id TEXT;
CREATE TABLE IF NOT EXISTS scene_qualifications (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  policy_id TEXT NOT NULL,
  canary_sha256 TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS scene_qualifications_lookup
  ON scene_qualifications (account_id, policy_id, profile_id, expires_at);
CREATE TABLE IF NOT EXISTS scene_candidates (
  lease_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  qualification_id TEXT NOT NULL,
  policy_id TEXT NOT NULL,
  submission_sha256 TEXT NOT NULL,
  artifact_key TEXT NOT NULL,
  records_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending', 'published', 'rejected'))
);
