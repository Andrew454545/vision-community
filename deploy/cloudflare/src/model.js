/** community-visual-v1 extractor for the trusted Worker. Bit-identical to visual.js. */

export const MODEL_ID = "community-visual-v1";
export const FACE_COUNT = 6;
export const FACE_SIZE = 16;
export const BYTES_PER_FACE = FACE_SIZE * FACE_SIZE * 3;
export const FACES_BYTES = FACE_COUNT * BYTES_PER_FACE;
export const SCENE_DIM = 96;
export const OBJECT_PROPOSALS = 16;
export const OBJECT_DIM = 8;
export const SEARCH_COST = 4; // prototype: one verified scene batch. Production is 100000.
export const UNITS = { scene: 1, object: 10 };
export const LEASE_SECONDS = 30 * 60;
export const MAX_LEASE = 1000;
export const RECOVERY_PEPPER = "VISION-COMMUNITY-RECOVERY-V1";

export async function sha256Hex(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function encodeUtf8(value) {
  return new TextEncoder().encode(value);
}

export function equalHex(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function seedBytes(assetId, capture, lane, model) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encodeUtf8(`${assetId}\n${capture}\n${lane}\n${model}`)));
}

export function renderFacesFromSeed(seed) {
  const out = new Uint8Array(FACES_BYTES);
  let state = 0n;
  for (let i = 7; i >= 0; i -= 1) state = (state << 8n) + BigInt(seed[i]);
  if (state === 0n) state = 1n;
  const mask = (1n << 64n) - 1n;
  for (let face = 0; face < FACE_COUNT; face += 1) {
    const faceBias = Number((state >> BigInt(face % 8)) & 255n);
    for (let y = 0; y < FACE_SIZE; y += 1) {
      for (let x = 0; x < FACE_SIZE; x += 1) {
        state = (state ^ ((state << 13n) & mask)) & mask;
        state = (state ^ (state >> 7n)) & mask;
        state = (state ^ ((state << 17n) & mask)) & mask;
        const idx = (face * FACE_SIZE * FACE_SIZE + y * FACE_SIZE + x) * 3;
        const radial = (x - 7) * (x - 7) + (y - 7) * (y - 7);
        out[idx] = Number((state + BigInt(faceBias + x * 13 + radial)) & 255n);
        out[idx + 1] = Number(((state >> 8n) + BigInt(y * 17 + face * 41)) & 255n);
        out[idx + 2] = Number(((state >> 16n) + BigInt(x * y + faceBias * 3)) & 255n);
      }
    }
  }
  return out;
}

function meanInt8(total, count) {
  return Math.max(-127, Math.min(127, Math.floor(total / count) - 128));
}

function toUint8(dims) {
  const out = new Uint8Array(dims.length);
  for (let i = 0; i < dims.length; i += 1) out[i] = dims[i] < 0 ? dims[i] + 256 : dims[i];
  return out;
}

export function sceneEmbedding(faces) {
  const dims = [];
  for (let face = 0; face < FACE_COUNT; face += 1) {
    const base = face * BYTES_PER_FACE;
    for (let qy = 0; qy < 2; qy += 1) {
      for (let qx = 0; qx < 2; qx += 1) {
        let sumR = 0, sumG = 0, sumB = 0, sumDx = 0;
        for (let y = 0; y < 8; y += 1) {
          let prevR = null;
          for (let x = 0; x < 8; x += 1) {
            const px = qx * 8 + x;
            const py = qy * 8 + y;
            const i = base + (py * FACE_SIZE + px) * 3;
            const r = faces[i], g = faces[i + 1], b = faces[i + 2];
            sumR += r; sumG += g; sumB += b;
            if (prevR !== null) sumDx += Math.abs(r - prevR);
            prevR = r;
          }
        }
        dims.push(meanInt8(sumR, 64), meanInt8(sumG, 64), meanInt8(sumB, 64), meanInt8(sumDx, 56));
      }
    }
  }
  return toUint8(dims);
}

export function objectEmbedding(faces) {
  const dims = [];
  const base = 0;
  for (let cy = 0; cy < 4; cy += 1) {
    for (let cx = 0; cx < 4; cx += 1) {
      let sumR = 0, sumG = 0, sumB = 0, sumDx = 0, sumDy = 0, grayMin = 255, grayMax = 0;
      for (let y = 0; y < 4; y += 1) {
        for (let x = 0; x < 4; x += 1) {
          const px = cx * 4 + x;
          const py = cy * 4 + y;
          const i = base + (py * FACE_SIZE + px) * 3;
          const r = faces[i], g = faces[i + 1], b = faces[i + 2];
          sumR += r; sumG += g; sumB += b;
          const gray = Math.floor((r + g + b) / 3);
          grayMin = Math.min(grayMin, gray);
          grayMax = Math.max(grayMax, gray);
          if (x) sumDx += Math.abs(r - faces[base + (py * FACE_SIZE + px - 1) * 3]);
          if (y) sumDy += Math.abs(r - faces[base + ((py - 1) * FACE_SIZE + px) * 3]);
        }
      }
      dims.push(
        meanInt8(sumR, 16),
        meanInt8(sumG, 16),
        meanInt8(sumB, 16),
        meanInt8((grayMin + grayMax) * 8, 16),
        meanInt8(grayMax - grayMin, 1),
        meanInt8(sumDx, 12),
        meanInt8(sumDy, 12),
        Math.max(-127, Math.min(127, (cx + cy * 4) * 8 - 60)),
      );
    }
  }
  return toUint8(dims);
}

export function embeddingFor(lane, faces) {
  return lane === "object" ? objectEmbedding(faces) : sceneEmbedding(faces);
}

export async function outputDigest(assetId, capture, lane, model, embedding) {
  const prefix = encodeUtf8(`${MODEL_ID}\n${assetId}\n${capture}\n${lane}\n${model}\n`);
  const digestInput = new Uint8Array(prefix.length + embedding.length);
  digestInput.set(prefix, 0);
  digestInput.set(embedding, prefix.length);
  return sha256Hex(digestInput);
}

export function signedInt8(data) {
  const out = [];
  for (let i = 0; i < data.length; i += 1) out.push(data[i] > 127 ? data[i] - 256 : data[i]);
  return out;
}

export function cosine(a, b) {
  if (a.length !== b.length || !a.length) return -1;
  const sa = signedInt8(a), sb = signedInt8(b);
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < sa.length; i += 1) {
    dot += sa[i] * sb[i];
    na += sa[i] * sa[i];
    nb += sb[i] * sb[i];
  }
  if (!na || !nb) return -1;
  return dot / Math.sqrt(na * nb);
}

export function maxRegionCosine(query, packed) {
  if (query.length === OBJECT_PROPOSALS * OBJECT_DIM) {
    let best = -1;
    for (let offset = 0; offset < query.length; offset += OBJECT_DIM) {
      best = Math.max(best, maxRegionCosine(query.subarray(offset, offset + OBJECT_DIM), packed));
    }
    return best;
  }
  if (query.length !== OBJECT_DIM) return -1;
  let best = -1;
  for (let offset = 0; offset < packed.length; offset += OBJECT_DIM) {
    best = Math.max(best, cosine(query, packed.subarray(offset, offset + OBJECT_DIM)));
  }
  return best;
}

export function meanEmbeddings(vectors) {
  const width = vectors[0].length;
  const totals = new Array(width).fill(0);
  for (const vector of vectors) {
    const signed = signedInt8(vector);
    for (let i = 0; i < width; i += 1) totals[i] += signed[i];
  }
  const count = vectors.length;
  const dims = totals.map((total) => Math.max(-127, Math.min(127, Math.trunc(total / count))));
  return toUint8(dims);
}

export function bytesToBase64(bytes) {
  let binary = "";
  bytes.forEach((value) => { binary += String.fromCharCode(value); });
  return btoa(binary);
}

export function base64ToBytes(value) {
  const binary = atob(value);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

export function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i += 1) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export function bytesToHex(bytes) {
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function randomHex(bytes) {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return bytesToHex(buf);
}

export function randomToken(bytes = 32) {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  let s = "";
  buf.forEach((b) => { s += String.fromCharCode(b); });
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
