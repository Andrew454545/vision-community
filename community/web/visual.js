/* Bit-identical community-visual-v1 extractor for the browser worker. */
const MODEL_ID = "community-visual-v1";
const FACE_COUNT = 6;
const FACE_SIZE = 16;
const BYTES_PER_FACE = FACE_SIZE * FACE_SIZE * 3;
const FACES_BYTES = FACE_COUNT * BYTES_PER_FACE;
const SCENE_DIM = 96;
const OBJECT_PROPOSALS = 16;
const OBJECT_DIM = 8;

function sha256Hex(bytes) {
  return crypto.subtle.digest("SHA-256", bytes).then((digest) =>
    Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")
  );
}

function encodeUtf8(value) {
  return new TextEncoder().encode(value);
}

async function seedBytes(assetId, capture, lane, model) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encodeUtf8(`${assetId}\n${capture}\n${lane}\n${model}`)));
}

function renderFacesFromSeed(seed) {
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
  const value = Math.floor(total / count) - 128;
  return Math.max(-127, Math.min(127, value));
}

function toUint8(dims) {
  const out = new Uint8Array(dims.length);
  for (let i = 0; i < dims.length; i += 1) out[i] = dims[i] < 0 ? dims[i] + 256 : dims[i];
  return out;
}

function sceneEmbedding(faces) {
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
  if (dims.length !== SCENE_DIM) throw new Error("scene_dim");
  return toUint8(dims);
}

function objectEmbedding(faces) {
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
          if (x) {
            const left = base + (py * FACE_SIZE + px - 1) * 3;
            sumDx += Math.abs(r - faces[left]);
          }
          if (y) {
            const up = base + ((py - 1) * FACE_SIZE + px) * 3;
            sumDy += Math.abs(r - faces[up]);
          }
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

function embeddingFor(lane, faces) {
  return lane === "object" ? objectEmbedding(faces) : sceneEmbedding(faces);
}

function bytesToBase64(bytes) {
  let binary = "";
  bytes.forEach((value) => { binary += String.fromCharCode(value); });
  return btoa(binary);
}

async function processItem(item) {
  let faces;
  if (item.faces) {
    const raw = atob(item.faces);
    faces = Uint8Array.from(raw, (ch) => ch.charCodeAt(0));
  } else {
    faces = renderFacesFromSeed(await seedBytes(item.assetId, item.capture, item.lane, item.model));
  }
  const embedding = embeddingFor(item.lane, faces);
  const prefix = encodeUtf8(`${MODEL_ID}\n${item.assetId}\n${item.capture}\n${item.lane}\n${item.model}\n`);
  const digestInput = new Uint8Array(prefix.length + embedding.length);
  digestInput.set(prefix, 0);
  digestInput.set(embedding, prefix.length);
  return {
    locationId: item.locationId,
    model: item.model,
    embeddingSha256: await sha256Hex(embedding),
    outputSha256: await sha256Hex(digestInput),
    embedding: bytesToBase64(embedding),
  };
}

window.VISIONVisual = {
  MODEL_ID, FACE_COUNT, FACES_BYTES, processItem, renderFacesFromSeed, embeddingFor, seedBytes,
};
