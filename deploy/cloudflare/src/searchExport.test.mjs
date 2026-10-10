import assert from "node:assert/strict";
import test from "node:test";
import { exportSearchMap, querySemantics, validHitObject, visionRound } from "./searchExport.js";

const query = { lane: "scene", prompt: "red door", queryName: "My map", descriptionWeight: 50 };
const hit = { score: 0.712345678, sourceIndex: 42, viewOffset: 3,
  pose: { lat: 10, lng: 20, heading: 270, pitch: 0, zoom: 0, panoId: "synthetic", country: "Italy", cameraGeneration: "gen4" } };

test("scene export preserves VISION query semantics, threshold and registry ordinal", () => {
  assert.deepEqual(exportSearchMap(query, [hit], 100).customCoordinates[0], {
    lat: 10, lng: 20, heading: 270, pitch: 0, zoom: 0, panoId: "synthetic", extra: {
      tags: ["Italy"], visionCameraGeneration: "gen4", visionScore: 0.7123457,
      visionMinScore: 0.6531793, visionRank: 1, visionQuery: "red door",
      visionQueryMode: "title50Contrastive50", visionHeadingOffset: 270, visionSourceIndex: 42,
      visionProcessedLocations: 100, visionModel: "SigLIP B/16 224", visionPruneMeters: 100,
    },
  });
  const expected = [[0, "contrastive50", 0.8842786], [25, "title25Contrastive50", 0.83858335],
    [50, "title50Contrastive50", 0.6531793], [75, "title75Contrastive50", 0.36236486], [100, "textOnly", 0.01]];
  for (const [descriptionWeight, mode, minimumScore] of expected) {
    assert.deepEqual(querySemantics({ ...query, descriptionWeight, prompt: "" }),
      { mode, minimumScore, text: "visual examples for My map" });
  }
});

test("all object lanes export VISION model names and detection evidence without scene offsets", () => {
  for (const [lane, model] of [["common", "RF-DETR Medium 1.10.0"], ["hot", "YOLOE-26L 8.4.143"],
    ["semantic", "OWLv2 Base Patch16 + PQ128"]]) {
    const object = { lane, className: "car", classId: lane === "common" ? 3 : null,
      confidence: 0.812345678, supportCount: 2, bboxArea: 0.12345678 };
    assert.equal(validHitObject(object, 0.08), true);
    const extra = exportSearchMap({ ...query, lane: "object", objectConfidence: "balanced" },
      [{ ...hit, object }], 100).customCoordinates[0].extra;
    assert.equal(extra.visionQueryMode, "objects");
    assert.equal(extra.visionHeadingOffset, 0);
    assert.equal(extra.visionMinScore, 0.08);
    assert.equal(extra.visionModel, model);
    assert.equal(extra.visionObjectLane, lane);
    assert.equal(extra.visionObjectClassId, object.classId);
    assert.equal(extra.visionObjectConfidence, 0.8123457);
    assert.equal(extra.visionObjectBoxArea, 0.1234568);
  }
  for (const [objectConfidence, minimumScore] of [["highRecall", 0.03], ["balanced", 0.08], ["precise", 0.2]])
    assert.equal(querySemantics({ ...query, lane: "object", objectConfidence }).minimumScore, minimumScore);
});

test("invalid detection evidence is rejected and rounding matches Swift ties away from zero", () => {
  const object = { lane: "common", className: "car", classId: 3, confidence: 0.8, supportCount: 2, bboxArea: 0.1 };
  for (const change of [{ lane: "other" }, { classId: null }, { className: "" }, { confidence: 0.01 },
    { confidence: 1.1 }, { supportCount: 0 }, { bboxArea: 2 }, { bboxArea: null }])
    assert.equal(validHitObject({ ...object, ...change }, 0.08), false);
  assert.equal(visionRound(0.00000005), 0.0000001);
  assert.equal(visionRound(-0.00000005), -0.0000001);
  assert.equal(visionRound(-0.00000001), 0);
});
