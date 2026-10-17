import assert from "node:assert/strict";
import test from "node:test";
import { parseSceneReferences, loadSceneReferences, sceneCapabilities } from "./sceneQuality.js";
import { sha256Hex } from "./model.js";

const hash = "a".repeat(64);
const row = { asset_id: "reference-pano", capture: "2026-01", lane: "scene",
  model: "community-visual-v1", lat: 10, lon: 20, heading: 90, pitch: 0, zoom: 0 };
const manifest = {
  version: 1, policyId: "test-only", inputModel: row.model, outputModel: "vision-four-view-v4",
  references: [{ assetId: row.asset_id, capture: row.capture, lat: row.lat, lng: row.lon,
    heading: row.heading, pitch: row.pitch, zoom: row.zoom, approvedSha256: [hash] }],
};

test("approved digest is bound to source, capture, pose and model", () => {
  const policy = parseSceneReferences(manifest);
  assert.equal(policy.covers(row), true);
  assert.equal(policy.verify(row, hash), true);
  assert.equal(policy.verify(row, "b".repeat(64)), false);
  for (const [key, value] of Object.entries({ asset_id: "other", capture: "other", lane: "object",
    model: "other", lat: 11, lon: 21, heading: 91, pitch: 1, zoom: 1 })) {
    assert.equal(policy.covers({ ...row, [key]: value }), false, key);
    assert.equal(policy.verify({ ...row, [key]: value }, hash), false, key);
  }
});

test("missing or malformed policy never enables contributions", async () => {
  assert.equal(await loadSceneReferences({}), null);
  assert.equal(sceneCapabilities(null).sceneContributions.ready, false);
  assert.throws(() => parseSceneReferences({ ...manifest, references: [] }));
  assert.throws(() => parseSceneReferences({ ...manifest, references: [manifest.references[0], manifest.references[0]] }));
  assert.throws(() => parseSceneReferences({ ...manifest, references: [{ ...manifest.references[0], lat: null }] }));
});

test("reference object must match the pinned checksum", async () => {
  const bytes = new TextEncoder().encode(JSON.stringify(manifest));
  const env = { SCENE_REFERENCE_KEY: "approved.json", SCENE_REFERENCE_SHA256: "0".repeat(64),
    SCENE_REFERENCES: { get: async () => ({ size: bytes.length, arrayBuffer: async () => bytes.buffer }) } };
  assert.equal(await loadSceneReferences(env), null);
  env.SCENE_REFERENCE_SHA256 = await sha256Hex(bytes);
  assert.equal((await loadSceneReferences(env)).verify(row, hash), true);
  env.SCENE_REFERENCES.get = async () => { throw new Error("unavailable"); };
  assert.equal(await loadSceneReferences(env), null);
});
