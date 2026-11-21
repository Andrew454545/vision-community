-- Explicit maintenance SQL. Validate the confirmed database binding first.
CREATE INDEX IF NOT EXISTS locations_unpublished_lane_id ON locations(lane,id) WHERE state!='published';

CREATE INDEX IF NOT EXISTS locations_active_lease_lookup ON locations(active_lease) WHERE active_lease IS NOT NULL;

CREATE INDEX IF NOT EXISTS leases_active_account_lookup ON leases(account_id,lane,expires_at DESC) WHERE state='active';
