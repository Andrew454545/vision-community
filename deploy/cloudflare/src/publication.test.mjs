import assert from "node:assert/strict";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import { contributedArtifact, contributedObjectPrefixes } from "./publication.js";

test("download authority comes from contributed publications, never storage presence", async () => {
  const sql = new DatabaseSync(":memory:");
  try {
    sql.exec(`CREATE TABLE locations (id INTEGER PRIMARY KEY, lane TEXT, state TEXT, contributor_id TEXT);
      CREATE TABLE object_coverage (location_id INTEGER PRIMARY KEY, validator TEXT);
      CREATE TABLE published_index (location_id INTEGER, four_view_key TEXT, object_index_key TEXT);
      INSERT INTO locations VALUES (1, 'object', 'published', 'anonymous'),
        (2, 'object', 'published', NULL), (3, 'object', 'leased', 'anonymous'),
        (4, 'scene', 'published', 'anonymous');
      INSERT INTO object_coverage VALUES (1, 'official-gen4-historical-v1');
      INSERT INTO published_index VALUES (1, NULL, 'object-index-v4/approved/'),
        (2, NULL, 'object-index-v4/imported/'), (3, NULL, 'object-index-v4/pending/'),
        (4, 'four-view-v4/approved.i8', NULL);`);
    const db = { prepare(query) {
      const statement = sql.prepare(query);
      return { all: async () => ({results: statement.all()}),
        bind: (...args) => ({first: async () => statement.get(...args)}) };
    } };
    assert.deepEqual([...await contributedObjectPrefixes(db)], ["object-index-v4/approved/"]);
    assert.equal(await contributedArtifact(db, "object-index-v4/approved/manifest.json", "object"), true);
    for (const prefix of ["orphan", "imported", "pending"]) {
      assert.equal(await contributedArtifact(db, `object-index-v4/${prefix}/manifest.json`, "object"), false);
    }
    assert.equal(await contributedArtifact(db, "four-view-v4/approved.i8", "scene"), true);
    assert.equal(await contributedArtifact(db, "four-view-v4/orphan.i8", "scene"), false);
    assert.equal(await contributedArtifact(db, "four-view-v4/approved.i8", "object"), false);
  } finally { sql.close(); }
});
