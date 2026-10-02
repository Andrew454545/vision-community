// Storage existence is not publication authority. Only contributed, published
// rows authorize downloads; this also excludes orphaned failed submissions.
import { officialGen4Coverage } from "./objectCoverage.js";
export async function contributedArtifact(db, key, lane) {
  if (!["scene", "object"].includes(lane)) return false;
  const column = lane === "scene" ? "four_view_key" : "object_index_key";
  const reference = lane === "scene" ? key : key.slice(0, key.lastIndexOf("/") + 1);
  return !!await db.prepare(`SELECT 1 FROM published_index i JOIN locations l ON l.id=i.location_id
    WHERE i.${column}=? AND l.lane=? AND l.state='published'
      AND l.contributor_id IS NOT NULL AND l.contributor_id!=''
      AND (? != 'object' OR (${officialGen4Coverage("l")}))
      LIMIT 1`).bind(reference, lane, lane).first();
}

export async function contributedObjectPrefixes(db) {
  const rows = await db.prepare(`SELECT DISTINCT i.object_index_key FROM published_index i
    JOIN locations l ON l.id=i.location_id WHERE l.lane='object' AND l.state='published'
      AND l.contributor_id IS NOT NULL AND l.contributor_id!='' AND i.object_index_key IS NOT NULL
      AND (${officialGen4Coverage("l")})`).all();
  return new Set((rows.results || []).map(row => row.object_index_key));
}
