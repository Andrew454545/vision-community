import assert from "node:assert/strict";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import { contributedArtifact, contributedObjectPrefixes } from "./publication.js";
import { objectCoverageComplete } from "./objectCoverage.js";

test("download authority comes from contributed publications, never storage presence", async () => {
  const sql = new DatabaseSync(":memory:");
  try {
    sql.exec(`CREATE TABLE locations (id INTEGER PRIMARY KEY, lane TEXT, state TEXT, contributor_id TEXT, camera_generation TEXT);
      CREATE TABLE object_coverage (location_id INTEGER PRIMARY KEY, validator TEXT, evidence_sha256 TEXT);
      CREATE TABLE published_index (location_id INTEGER, four_view_key TEXT, object_index_key TEXT);
      INSERT INTO locations VALUES (1, 'object', 'published', 'anonymous','gen4'),
        (2, 'object', 'published', NULL,'gen4'), (3, 'object', 'leased', 'anonymous','gen4'),
        (4, 'scene', 'published', 'anonymous','gen4');
      INSERT INTO object_coverage VALUES (1, 'official-gen4-historical-v2-exact-pano','${"a".repeat(64)}');
      INSERT INTO published_index VALUES (1, NULL, 'object-index-v4/approved/'),
        (2, NULL, 'object-index-v4/imported/'), (3, NULL, 'object-index-v4/pending/'),
        (4, 'four-view-v4/approved.i8', NULL);`);
    const db = { prepare(query) {
      const statement = sql.prepare(query);
      return { all: async () => ({results: statement.all()}),
        bind: (...args) => ({first: async () => statement.get(...args), all: async () => ({results: statement.all(...args)})}) };
    } };
    assert.deepEqual([...await contributedObjectPrefixes(db)], ["object-index-v4/approved/"]);
    assert.equal(await contributedArtifact(db, "object-index-v4/approved/manifest.json", "object"), true);
    for (const prefix of ["orphan", "imported", "pending"]) {
      assert.equal(await contributedArtifact(db, `object-index-v4/${prefix}/manifest.json`, "object"), false);
    }
    assert.equal(await contributedArtifact(db, "four-view-v4/approved.i8", "scene"), true);
    assert.equal(await contributedArtifact(db, "four-view-v4/orphan.i8", "scene"), false);
    assert.equal(await contributedArtifact(db, "four-view-v4/approved.i8", "object"), false);
    assert.equal(await objectCoverageComplete(db, [{id: 1}]), true);
    sql.exec("UPDATE object_coverage SET validator='official-gen4-historical-v1'");
    assert.equal(await objectCoverageComplete(db, [{id: 1}]), false);
    assert.deepEqual([...await contributedObjectPrefixes(db)], []);
    assert.equal(await contributedArtifact(db, 'object-index-v4/approved/manifest.json', 'object'), false);
    sql.exec("UPDATE object_coverage SET validator='official-gen4-historical-v2-exact-pano'");
    for (const evidence of ["", "a".repeat(63), "g".repeat(64), "A".repeat(64), Buffer.from("a".repeat(64))]) {
      sql.prepare("UPDATE object_coverage SET evidence_sha256=?").run(evidence);
      assert.equal(await objectCoverageComplete(db, [{id: 1}]), false);
      assert.deepEqual([...await contributedObjectPrefixes(db)], []);
      assert.equal(await contributedArtifact(db, "object-index-v4/approved/manifest.json", "object"), false);
    }
    sql.prepare("UPDATE object_coverage SET evidence_sha256=?").run("a".repeat(64));
    sql.exec("UPDATE locations SET camera_generation='gen3' WHERE id=1");
    assert.equal(await objectCoverageComplete(db, [{id: 1}]), false);
    assert.deepEqual([...await contributedObjectPrefixes(db)], []);
    sql.exec("UPDATE locations SET camera_generation='gen4',contributor_id='' WHERE id=1");
    assert.deepEqual([...await contributedObjectPrefixes(db)], []);
    assert.equal(await contributedArtifact(db, "object-index-v4/approved/manifest.json", "object"), false);
  } finally { sql.close(); }
});
