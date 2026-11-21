// Export semantics from VISION 9811448e3e05259e08f5106ab5a7740dce0c6b4a:
// VisionEngine.makeQuery/makeObjectQuery/makeOutput and VisionModels.
export const SEARCH_CONTRACT_VERSION = 2;
export const SCENE_QUERY_MODES = new Map([
  [0, ["contrastive50", 0.8842786]],
  [25, ["title25Contrastive50", 0.83858335]],
  [50, ["title50Contrastive50", 0.6531793]],
  [75, ["title75Contrastive50", 0.36236486]],
  [100, ["textOnly", 0.01]],
]);
export const OBJECT_CONFIDENCE = { highRecall: 0.03, balanced: 0.08, precise: 0.20 };
const OBJECT_MODELS = { common: "RF-DETR Medium 1.10.0", hot: "YOLOE-26L 8.4.143",
  semantic: "OWLv2 Base Patch16 + PQ128" };

export function querySemantics(query) {
  const [mode, minimumScore] = query.lane === "object"
    ? ["objects", OBJECT_CONFIDENCE[query.objectConfidence]]
    : SCENE_QUERY_MODES.get(query.descriptionWeight) || [];
  return { mode, minimumScore, text: query.prompt || `visual examples for ${query.queryName}` };
}

export function validHitObject(object, minimumScore) {
  if (!object || typeof object !== "object" || Array.isArray(object)
      || !Object.hasOwn(OBJECT_MODELS, object.lane)
      || typeof object.className !== "string" || !object.className.trim() || object.className.length > 1000
      || !Number.isFinite(object.confidence) || object.confidence < minimumScore || object.confidence > 1
      || !Number.isInteger(object.supportCount) || object.supportCount < 1 || object.supportCount > 255
      || !Number.isFinite(object.bboxArea) || object.bboxArea < 0 || object.bboxArea > 1) return false;
  return object.lane === "common"
    ? Number.isInteger(object.classId) && object.classId > 0 && object.classId <= 90
    : object.classId == null;
}

export function visionRound(value) {
  const rounded = Math.sign(value) * Math.floor(Math.abs(value) * 10000000 + 0.5) / 10000000;
  return rounded === 0 ? 0 : rounded;
}

export function exportSearchMap(query, hits, processedLocations) {
  const { mode, minimumScore, text } = querySemantics(query);
  return { name: query.queryName, customCoordinates: hits.map((hit, index) => {
    const object = hit.object;
    return {
      lat: hit.pose.lat, lng: hit.pose.lng, heading: hit.pose.heading, pitch: hit.pose.pitch, zoom: hit.pose.zoom,
      panoId: hit.pose.panoId, extra: {
        tags: [hit.pose.country], visionCameraGeneration: hit.pose.cameraGeneration,
        visionScore: visionRound(hit.score), visionMinScore: visionRound(minimumScore), visionRank: index + 1,
        visionQuery: text, visionQueryMode: mode, visionHeadingOffset: object ? 0 : hit.viewOffset * 90,
        visionSourceIndex: hit.sourceIndex, visionProcessedLocations: processedLocations,
        visionModel: object ? OBJECT_MODELS[object.lane] : "SigLIP B/16 224", visionPruneMeters: 100,
        ...(object ? { visionObjectClass: object.className, visionObjectClassId: object.classId ?? null,
          visionObjectLane: object.lane, visionObjectConfidence: visionRound(object.confidence),
          visionObjectSupport: object.supportCount, visionObjectBoxArea: visionRound(object.bboxArea) } : {}),
      },
    };
  }) };
}
