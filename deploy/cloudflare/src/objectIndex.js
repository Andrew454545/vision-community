import { sha256Hex } from "./model.js";

export const OBJECT_INDEX_MODEL = "vision-object-index-v4";
export const OBJECT_ARCHITECTURE = "VISION Hybrid: RF-DETR Medium + YOLOE-26L + OWLv2 PQ128";
export const COMMON_MODEL_SHA256 = "00cc60ba7e18ea6b5afeca7d8d3d4a07be0d1e9969dbd1799719a4f802882fd2";
export const RUNTIME_IDENTITY = "58ee8c307523d3ac06da85d18fd3ad303d6a0442d4edc071918be5e2890b9353";
export const CODEBOOK_SHA256 = "f28e0e9aeb8bfcd547cad3d2a3d9aa546de74b647cd1cc058a5911bd7dafeb25";
export const OBJECT_POSITION_POLICY = "maximum raw model score; no heading, pitch, center, edge, sky, ground, or view-order weights";

const OBJECT_CLASSES = [
  [1, "person"], [2, "bicycle"], [3, "car"], [4, "motorcycle"], [5, "airplane"],
  [6, "bus"], [7, "train"], [8, "truck"], [9, "boat"], [10, "traffic light"],
  [11, "fire hydrant"], [13, "stop sign"], [14, "parking meter"], [15, "bench"],
  [16, "bird"], [17, "cat"], [18, "dog"], [19, "horse"], [20, "sheep"],
  [21, "cow"], [22, "elephant"], [23, "bear"], [24, "zebra"], [25, "giraffe"],
  [27, "backpack"], [28, "umbrella"], [31, "handbag"], [32, "tie"], [33, "suitcase"],
  [34, "frisbee"], [35, "skis"], [36, "snowboard"], [37, "sports ball"], [38, "kite"],
  [39, "baseball bat"], [40, "baseball glove"], [41, "skateboard"], [42, "surfboard"],
  [43, "tennis racket"], [44, "bottle"], [46, "wine glass"], [47, "cup"], [48, "fork"],
  [49, "knife"], [50, "spoon"], [51, "bowl"], [52, "banana"], [53, "apple"],
  [54, "sandwich"], [55, "orange"], [56, "broccoli"], [57, "carrot"], [58, "hot dog"],
  [59, "pizza"], [60, "donut"], [61, "cake"], [62, "chair"], [63, "couch"],
  [64, "potted plant"], [65, "bed"], [67, "dining table"], [70, "toilet"], [72, "tv"],
  [73, "laptop"], [74, "mouse"], [75, "remote"], [76, "keyboard"], [77, "cell phone"],
  [78, "microwave"], [79, "oven"], [80, "toaster"], [81, "sink"], [82, "refrigerator"],
  [84, "book"], [85, "clock"], [86, "vase"], [87, "scissors"], [88, "teddy bear"],
  [89, "hair drier"], [90, "toothbrush"],
];
const HOT_CONCEPTS = ["bird nest", "clock"];
const HOT_FLOORS = [0.01, 0.03];
const LIVE_MARKERS = [
  "four-view-remainder-work",
  "all-locations-four-view-no-road-remainder-badcam-v1",
  "four-view-published-segments",
  "no-road-after-one-view-prefix.badcam.tsv",
  "object-indexes",
  "object-runtime-legacy-mixed",
  "scheduled-sources",
  "object-hybrid-v1/coreml-cache",
];

export function crc32(bytes) {
  let value = 0xffffffff;
  for (let index = 0; index < bytes.length; index += 1) {
    value ^= bytes[index];
    for (let bit = 0; bit < 8; bit += 1) {
      const mask = -(value & 1);
      value = ((value >>> 1) ^ (0xedb88320 & mask)) >>> 0;
    }
  }
  return (~value) >>> 0;
}

export function globalIdRecord(globalId) {
  const body = new Uint8Array(8);
  new DataView(body.buffer).setBigUint64(0, BigInt(globalId), true);
  const record = new Uint8Array(12);
  record.set(body, 0);
  new DataView(record.buffer).setUint32(8, crc32(body), true);
  return record;
}

function storageFloor(classId) {
  if (classId === 5 || classId === 16 || classId === 17) return 0.01;
  if ([2, 10, 11, 13, 14, 18, 27, 28, 64].includes(classId) || (classId >= 31 && classId <= 61) || (classId >= 73 && classId <= 77) || (classId >= 84 && classId <= 90)) {
    return 0.03;
  }
  return 0.05;
}

function classFileName(classId, name) {
  return `class-${String(classId).padStart(2, "0")}-${name.replaceAll(" ", "-")}.bin`;
}

function hotFileName(conceptId, name) {
  return `hot-${String(conceptId).padStart(2, "0")}-${name.replaceAll(" ", "-")}.bin`;
}

function near(left, right) {
  return typeof left === "number" && typeof right === "number" && Math.abs(left - right) <= 1e-5;
}

function safeName(name) {
  return typeof name === "string" && /^[A-Za-z0-9][A-Za-z0-9.-]*\.bin$/.test(name);
}

function sameBytes(left, right) {
  if (!left || !right || left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) return false;
  }
  return true;
}

async function fileEntry(entry, fileName, records, recordBytes, payload, requireRecordBytes = true) {
  if (!entry || entry.file !== fileName || entry.records !== records) return false;
  // Class and hot-concept lanes omit recordBytes, matching VISION's manifest.
  if (requireRecordBytes) {
    if (entry.recordBytes !== recordBytes) return false;
  } else if (entry.recordBytes != null && entry.recordBytes !== recordBytes) {
    return false;
  }
  const expected = records * recordBytes;
  if (entry.bytes !== expected || !payload || payload.length !== expected) return false;
  return entry.sha256 === await sha256Hex(payload);
}

function manifestNames(manifest) {
  const names = [];
  for (const key of ["offsets", "metadata", "globalIds", "semantic"]) {
    if (manifest[key]?.file) names.push(manifest[key].file);
  }
  for (const key of ["classes", "hotConcepts"]) {
    for (const entry of manifest[key] || []) {
      if (entry?.file) names.push(entry.file);
    }
  }
  if (manifest.viewQuality?.file) names.push(manifest.viewQuality.file);
  return names;
}

export async function validateObjectIndex(manifest, files, sourceTsv, items, leaseId) {
  if (!manifest || !files || !sourceTsv || !Array.isArray(items)) throw new Error("verification_failed");
  if (typeof leaseId !== "string" || !/^[0-9a-f]{32}$/.test(leaseId)) throw new Error("verification_failed");
  const ordered = [...items].sort((left, right) => left.locationId - right.locationId);
  const total = ordered.length;
  if (total < 1) throw new Error("verification_failed");
  const sourceId = `community-${leaseId}`;
  const sourcePath = manifest.sourceTsv;
  if (typeof sourcePath !== "string" || LIVE_MARKERS.some((marker) => sourcePath.includes(marker))) {
    throw new Error("verification_failed");
  }
  const contracts = manifest.contractVersions || {};
  const expectedContracts = {
    manifest: 4, checkpoint: 4, commonRecord: 3, hotRecord: 1,
    semanticRecord: 1, metadataRecord: 1, offsets: 1, globalIds: 1,
  };
  if (Object.entries(expectedContracts).some(([key, value]) => contracts[key] !== value)) {
    throw new Error("verification_failed");
  }
  const sourceSha = await sha256Hex(sourceTsv);
  const globalStart = 0;
  if (
    manifest.version !== 4
    || manifest.feature !== "vision-object-index"
    || manifest.architecture !== OBJECT_ARCHITECTURE
    || manifest.completed !== true
    || manifest.sourceId !== sourceId
    || manifest.modelSha256 !== COMMON_MODEL_SHA256
    || manifest.runtimeIdentity !== RUNTIME_IDENTITY
    || manifest.rankingStrategy !== "raw-confidence-position-neutral-v2"
    || manifest.viewStrategy !== "six-face-cube"
    || manifest.coverage !== "complete-360x180-six-face-cube"
    || manifest.positionPolicy !== OBJECT_POSITION_POLICY
    || manifest.globalIdMode !== "explicit-contiguous-permutation-v1"
    || manifest.imageSize !== 640
    || manifest.tileGrid !== 2
    || !near(manifest.tileOverlap, 0.2)
    || !near(manifest.minimumRelativeClassScore, 0.25)
    || !near(manifest.smallObjectRelativeClassScore, 0)
    || !near(manifest.fullTileArtifactThreshold, 0.98)
    || manifest.viewCount !== 6
    || manifest.faceSize !== 640
    || !near(manifest.faceFov, 90)
    || manifest.bandsPerFace !== 3
    || manifest.bandWidth !== 600
    || manifest.bandHeight !== 280
    || !near(manifest.bandOffset, 24)
    || !near(manifest.bandFov, 90)
    || manifest.recordBytes !== 32
    || manifest.totalLocations !== total
    || manifest.indexedLocations !== total
    || manifest.globalStart !== globalStart
    || manifest.minimumGlobalLocation !== globalStart
    || manifest.maximumGlobalLocation !== globalStart + total - 1
    || manifest.sourceBytes !== sourceTsv.length
    || manifest.sourceSha256 !== sourceSha
  ) {
    throw new Error("verification_failed");
  }
  if (!manifest.viewQuality && manifest.permanentlyInvalidLocations) throw new Error("verification_failed");
  if (!Array.isArray(manifest.countries) || !manifest.countries.length || new Set(manifest.countries).size !== manifest.countries.length) {
    throw new Error("verification_failed");
  }
  const lines = new TextDecoder().decode(sourceTsv).split(/\r?\n/).filter((line) => line.trim());
  if (lines.length !== total) throw new Error("verification_failed");
  const countries = [];
  const outputs = [];
  const globalIds = files["global-location-ids.bin"];
  for (let offset = 0; offset < total; offset += 1) {
    const fields = lines[offset].split("\t");
    const item = ordered[offset];
    const pano = item.panoId || item.assetId || item.asset_id || "";
    if (fields.length !== 12 || fields[7] !== pano) throw new Error("verification_failed");
    if (!near(Number(fields[2]), Number(item.lat)) || !near(Number(fields[3]), Number(item.lng ?? item.lon))) {
      throw new Error("verification_failed");
    }
    if (fields[11] !== String(globalStart + offset)) throw new Error("verification_failed");
    if (fields[8] && !countries.includes(fields[8])) countries.push(fields[8]);
    const record = globalIds?.subarray(offset * 12, (offset + 1) * 12);
    if (!sameBytes(record, globalIdRecord(globalStart + offset))) throw new Error("verification_failed");
    outputs.push({ locationId: item.locationId, outputSha256: await sha256Hex(record), model: OBJECT_INDEX_MODEL });
  }
  const expectedCountries = countries.length ? countries : [""];
  if (new Set(manifest.countries).size !== expectedCountries.length || expectedCountries.some((name) => !manifest.countries.includes(name))) {
    throw new Error("verification_failed");
  }
  const names = manifestNames(manifest);
  const fileNames = Object.keys(files);
  if (fileNames.length !== names.length || fileNames.some((name) => !names.includes(name) || !safeName(name))) {
    throw new Error("verification_failed");
  }
  if (!await fileEntry(manifest.offsets, "location-offsets.bin", total, 8, files["location-offsets.bin"])) throw new Error("verification_failed");
  if (!await fileEntry(manifest.metadata, "location-metadata.bin", total, 8, files["location-metadata.bin"])) throw new Error("verification_failed");
  if (!await fileEntry(manifest.globalIds, "global-location-ids.bin", total, 12, globalIds)) throw new Error("verification_failed");
  if (!Array.isArray(manifest.classes) || manifest.classes.length !== OBJECT_CLASSES.length) throw new Error("verification_failed");
  for (let index = 0; index < OBJECT_CLASSES.length; index += 1) {
    const [classId, name] = OBJECT_CLASSES[index];
    const entry = manifest.classes[index];
    const fileName = classFileName(classId, name);
    if (entry?.id !== classId || entry?.name !== name || !near(entry?.storageFloor, storageFloor(classId))) {
      throw new Error("verification_failed");
    }
    if (typeof entry.records !== "number" || entry.records < 0) throw new Error("verification_failed");
    if (!await fileEntry(entry, fileName, entry.records, 32, files[fileName], false)) throw new Error("verification_failed");
  }
  if (!Array.isArray(manifest.hotConcepts) || manifest.hotConcepts.length !== HOT_CONCEPTS.length) throw new Error("verification_failed");
  for (let index = 0; index < HOT_CONCEPTS.length; index += 1) {
    const entry = manifest.hotConcepts[index];
    const fileName = hotFileName(index, HOT_CONCEPTS[index]);
    if (entry?.id !== index || entry?.name !== HOT_CONCEPTS[index] || !near(entry?.storageFloor, HOT_FLOORS[index])) {
      throw new Error("verification_failed");
    }
    if (typeof entry.records !== "number" || entry.records < 0) throw new Error("verification_failed");
    if (!await fileEntry(entry, fileName, entry.records, 32, files[fileName], false)) throw new Error("verification_failed");
  }
  const semantic = manifest.semantic;
  const semanticRecords = total * 16;
  if (
    semantic?.codec !== "PQ128"
    || semantic?.codebookSha256 !== CODEBOOK_SHA256
    || semantic?.embeddingDimensions !== 512
    || semantic?.proposalsPerLocation !== 16
    || !await fileEntry(semantic, "semantic-pq128.bin", semanticRecords, 144, files["semantic-pq128.bin"])
  ) {
    throw new Error("verification_failed");
  }
  if (manifest.viewQuality && Object.keys(manifest.viewQuality).length) {
    const quality = manifest.viewQuality;
    if (!await fileEntry(quality, quality.file, total, 8, files[quality.file])) throw new Error("verification_failed");
  }
  return outputs;
}
