// These approvals must be written by a trusted operator after independent
// reference review. A contributor's checksum is never a quality attestation.
import { sha256Hex } from "./model.js";

export const SCENE_OUTPUT_MODEL = "vision-four-view-v4";
const digestPattern = /^[0-9a-f]{64}$/;
const poseKeys = ["lat", "lng", "heading", "pitch", "zoom"];

function referenceKey(entry) {
  return JSON.stringify([entry.assetId, entry.capture, ...poseKeys.map((key) => entry[key])]);
}

export function parseSceneReferences(manifest) {
  if (!manifest || manifest.version !== 1 || manifest.outputModel !== SCENE_OUTPUT_MODEL ||
      typeof manifest.inputModel !== "string" || !manifest.inputModel ||
      typeof manifest.policyId !== "string" || !manifest.policyId ||
      !Array.isArray(manifest.references) || !manifest.references.length) {
    throw new Error("invalid_scene_reference_policy");
  }
  const approved = new Map();
  for (const entry of manifest.references) {
    if (!entry || typeof entry.assetId !== "string" || !entry.assetId ||
        typeof entry.capture !== "string" || !entry.capture ||
        poseKeys.some((key) => typeof entry[key] !== "number" || !Number.isFinite(entry[key])) ||
        !Array.isArray(entry.approvedSha256) || !entry.approvedSha256.length ||
        entry.approvedSha256.some((value) => typeof value !== "string" || !digestPattern.test(value))) {
      throw new Error("invalid_scene_reference_policy");
    }
    const key = referenceKey(entry);
    if (approved.has(key)) throw new Error("duplicate_scene_reference");
    approved.set(key, new Set(entry.approvedSha256));
  }
  const rowKey = (row) => row.lane === "scene" && row.model === manifest.inputModel
    ? referenceKey({ assetId: row.asset_id, capture: row.capture, lat: row.lat, lng: row.lon,
      heading: row.heading, pitch: row.pitch, zoom: row.zoom }) : null;
  return {
    policyId: manifest.policyId,
    covers: (row) => approved.has(rowKey(row)),
    verify: (row, digest) => approved.get(rowKey(row))?.has(digest) === true,
  };
}

export async function loadSceneReferences(env) {
  // This bucket must not be shared with any contributor-writable artifact path.
  if (!env.SCENE_REFERENCES || typeof env.SCENE_REFERENCE_KEY !== "string" ||
      !env.SCENE_REFERENCE_KEY || !digestPattern.test(env.SCENE_REFERENCE_SHA256 || "")) return null;
  try {
    const object = await env.SCENE_REFERENCES.get(env.SCENE_REFERENCE_KEY);
    if (!object || object.size > 4_000_000) return null;
    const bytes = new Uint8Array(await object.arrayBuffer());
    if (bytes.length > 4_000_000 || await sha256Hex(bytes) !== env.SCENE_REFERENCE_SHA256) return null;
    return parseSceneReferences(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)));
  } catch {
    return null;
  }
}

export function sceneCapabilities(references) {
  return { version: 1, sceneContributions: {
    ready: references !== null,
    reason: references === null ? "scene_verification_unavailable" : null,
    model: SCENE_OUTPUT_MODEL,
    policyId: references?.policyId || null,
    verification: "independently-approved-output-digests",
    scope: "preapproved-locations-only",
  } };
}
