// Content checks for v4 Object transport. A valid hash/record does not attest
// inference, official coverage, qualification or independent publication audit.
const MAX_LOCATIONS = 1000;
const MAX_BYTES = 32_000_000;
const CAMERAS = new Map([["badcam",1],["gen1",2],["gen2",3],["gen3",4],["gen4",5],["trekker",6]]);
const ROAD_TRUE = new Set(["1", "true", "has road name", "has_road_name"]);
function require(value) { if (!value) throw new Error("verification_failed"); }
function view(raw) { return new DataView(raw.buffer, raw.byteOffset, raw.byteLength); }
export function crc32(raw) {
  let value = 0xffffffff;
  for (const byte of raw) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit++) value = ((value >>> 1) ^ (0xedb88320 & -(value & 1))) >>> 0;
  }
  return (~value) >>> 0;
}
export function crc8(raw) {
  let value = 0;
  for (const byte of raw) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit++) value = ((value << 1) ^ (value & 128 ? 7 : 0)) & 255;
  }
  return value;
}
export function crc16(raw) {
  let value = 0xffff;
  for (const byte of raw) {
    value ^= byte << 8;
    for (let bit = 0; bit < 8; bit++) value = ((value << 1) ^ (value & 0x8000 ? 0x1021 : 0)) & 65535;
  }
  return value;
}
function checked32(raw) {
  require(raw.length === 8 && view(raw).getUint32(4, true) === crc32(raw.subarray(0,4)));
  return view(raw);
}
function half(bits) {
  const sign = bits & 32768 ? -1 : 1, exponent = (bits >>> 10) & 31, fraction = bits & 1023;
  return sign * (exponent === 31 ? (fraction ? NaN : Infinity)
    : exponent ? (1 + fraction / 1024) * 2 ** (exponent - 15) : fraction * 2 ** -24);
}
function semanticRecord(raw) {
  const data = view(raw);
  require(raw.length === 144 && data.getUint16(142, true) === crc16(raw.subarray(0,142))
    && raw[141] === 1 && raw[140] < 6);
  const shift = half(data.getUint16(136,true)), scale = half(data.getUint16(138,true));
  require(data.getUint16(128,true) < data.getUint16(132,true)
    && data.getUint16(130,true) < data.getUint16(134,true)
    && Number.isFinite(shift) && Number.isFinite(scale) && scale > 0);
  return raw[140];
}
function placeholder(raw) {
  return raw.subarray(0,128).every(byte => byte === 0)
    && raw.subarray(128,142).every((byte,i) => byte === [0,0,0,0,255,255,255,255,0,0,0,60,0,1][i]);
}
function popcount(value) { let count = 0; for (; value; value &= value - 1) count++; return count; }

export function validateFeatureContents(manifest, files, source) {
  const total = manifest.totalLocations, countries = manifest.countries;
  require(Number.isSafeInteger(total) && total >= 1 && total <= MAX_LOCATIONS
    && files && typeof files === "object" && Object.keys(files).length <= 87
    && Object.values(files).every(raw => raw instanceof Uint8Array)
    && Object.values(files).reduce((sum,raw) => sum + raw.length,0) <= MAX_BYTES
    && source instanceof Uint8Array && source.length > 0 && source.length <= 1024 * 1024
    && Array.isArray(countries) && countries.length > 0 && countries.length <= 65536
    && countries.every(country => typeof country === "string") && new Set(countries).size === countries.length);
  const countryIds = new Map(countries.map((country,i) => [country,i]));
  const offsets = files["location-offsets.bin"], metadata = files["location-metadata.bin"];
  require(offsets?.length === total * 8 && metadata?.length === total * 8);
  const positions = [0];
  for (let i = 0; i < source.length; i++) if (source[i] === 10 && i + 1 < source.length) positions.push(i + 1);
  require(positions.length === total);
  const expected = [];
  for (let i = 0; i < total; i++) {
    const position = positions[i], end = positions[i+1] ?? source.length;
    require(view(offsets).getBigUint64(i*8,true) === BigInt(position));
    const row = new TextDecoder("utf-8", {fatal:true}).decode(source.subarray(position,end))
      .replace(/\n$/, "").replace(/\r$/, "");
    const fields = row.split("\t");
    require(fields.length === 12 && fields.every(field => !/[\x00-\x1f\x7f]/.test(field))
      && countryIds.has(fields[8]) && fields.slice(2,7).every(field => /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(field)));
    const values = fields.slice(2,7).map(Number);
    require(values.every(Number.isFinite) && values[0] >= -90 && values[0] <= 90
      && values[1] >= -180 && values[1] <= 180 && values[2] >= 0 && values[2] <= 360
      && values[3] >= -90 && values[3] <= 90 && values[4] >= 0 && values[4] <= 4);
    const data = checked32(metadata.subarray(i*8,(i+1)*8));
    const identity = [countryIds.get(fields[8]), CAMERAS.get(fields[9].trim().toLowerCase()) ?? 0,
      ROAD_TRUE.has(fields[10].trim().toLowerCase()) ? 1 : 0];
    require(data.getUint8(3) <= 1 && data.getUint16(0,true) === identity[0]
      && data.getUint8(2) === identity[1] && data.getUint8(3) === identity[2]);
    expected.push(identity);
  }
  const quality = manifest.viewQuality;
  require(quality == null || (typeof quality === "object" && !Array.isArray(quality)));
  const masks = new Array(total).fill(63);
  if (quality && Object.keys(quality).length) {
    const raw = files[quality.file];
    require(raw?.length === total * 8);
    const counts = {keptViews:0,blurRejectedViews:0,darkTunnelRejectedViews:0,
      fullyRejectedLocations:0,permanentlyInvalidLocations:0};
    for (let i = 0; i < total; i++) {
      const data = checked32(raw.subarray(i*8,(i+1)*8));
      const assessed = data.getUint8(0), keep = data.getUint8(1), blur = data.getUint8(2), flags = data.getUint8(3);
      require(!(flags & 64));
      const invalid = !!(flags & 128), dark = flags & 63;
      require(invalid ? assessed === 0 && keep === 0 && blur === 0 && dark === 0
        : assessed === 63 && !((keep | blur) & 192) && (keep | blur | dark) === 63
          && !(keep & blur) && !(keep & dark) && !(blur & dark));
      masks[i] = keep;
      counts.keptViews += popcount(keep); counts.blurRejectedViews += popcount(blur);
      counts.darkTunnelRejectedViews += popcount(dark);
      counts.fullyRejectedLocations += keep === 0 ? 1 : 0;
      counts.permanentlyInvalidLocations += invalid ? 1 : 0;
    }
    for (const [key,value] of Object.entries(counts)) {
      const supplied = key === "permanentlyInvalidLocations" ? (quality[key] ?? 0) : quality[key];
      require(Number.isSafeInteger(supplied) && supplied === value);
    }
    require(Number.isSafeInteger(manifest.permanentlyInvalidLocations ?? 0)
      && (manifest.permanentlyInvalidLocations ?? 0) === counts.permanentlyInvalidLocations);
  } else require(Number.isSafeInteger(manifest.permanentlyInvalidLocations ?? 0)
    && (manifest.permanentlyInvalidLocations ?? 0) === 0);
  let count = 0;
  for (const entry of [...manifest.classes,...manifest.hotConcepts]) {
    const raw = files[entry.file];
    require(raw && raw.length % 32 === 0 && raw.length <= total * 32);
    let previous = -1;
    for (let start = 0; start < raw.length; start += 32) {
      const record = raw.subarray(start,start+32), data = view(record);
      require(record[31] === crc8(record.subarray(0,31)) && record[28] <= 1);
      const local = data.getUint32(0,true), score = data.getFloat32(4,true), heading = data.getFloat32(8,true);
      const pitch = data.getFloat32(12,true), zoom = data.getFloat32(16,true), area = data.getFloat32(20,true);
      const confidence = data.getUint16(29,true) / 65535;
      require(previous < local && local < total && masks[local] !== 0 && record[27] > 0
        && data.getUint16(24,true) === expected[local][0] && record[26] === expected[local][1]
        && record[28] === expected[local][2] && [score,heading,pitch,zoom,area].every(Number.isFinite)
        && score >= 0 && score <= 1 && score + 1e-7 >= entry.storageFloor
        && Math.abs(score-confidence) <= 0.5/65535 + 1e-7 && heading >= 0 && heading < 360
        && pitch >= -90 && pitch <= 90 && zoom >= 0 && zoom <= 4 && area >= 0 && area <= 1);
      previous = local; count++;
    }
  }
  const raw = files["semantic-pq128.bin"];
  require(raw?.length === total * 16 * 144);
  for (let ordinal = 0; ordinal < total * 16; ordinal++) {
    const record = raw.subarray(ordinal*144,(ordinal+1)*144), face = semanticRecord(record), keep = masks[Math.floor(ordinal/16)];
    require(keep ? !!(keep & (1 << face)) : placeholder(record));
  }
  return {locations:total,commonAndHotRecords:count,semanticRecords:total*16,
    qualityRecords:quality && Object.keys(quality).length ? total : 0};
}
