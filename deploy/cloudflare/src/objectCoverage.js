// Every object boundary uses the same v7 exact-panorama operator receipt. Old
// historical-v1 receipts cannot establish the older capture's camera identity.
// This validates receipt structure; only the trusted importer establishes provenance.
export const COVERAGE_VALIDATOR = 'official-gen4-historical-v2-exact-pano';
export function officialGen4Coverage(alias) {
  if (!["l", "locations"].includes(alias)) throw Error("invalid_coverage_alias");
  return `${alias}.camera_generation='gen4' AND EXISTS (
    SELECT 1 FROM object_coverage c WHERE c.location_id=${alias}.id
      AND c.validator='${COVERAGE_VALIDATOR}'
      AND typeof(c.evidence_sha256)='text' AND length(c.evidence_sha256)=64
      AND c.evidence_sha256 NOT GLOB '*[^0-9a-f]*')`;
}

export async function objectCoverageComplete(db, rows) {
  const ids = rows.map(row => row.id);
  if (!ids.length || ids.some(id => !Number.isSafeInteger(id) || id < 1)
      || new Set(ids).size !== ids.length) return false;
  const covered = (await db.prepare(`SELECT l.id FROM locations l
    WHERE l.id IN (SELECT value FROM json_each(?)) AND l.lane='object'
      AND (${officialGen4Coverage("l")})`).bind(JSON.stringify(ids)).all()).results || [];
  return covered.length === ids.length;
}
