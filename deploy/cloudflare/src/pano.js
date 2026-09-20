/** VISION-matching Street View view plan and ephemeral thumbnail decode. */

import jpegJs from "jpeg-js";
import { FACE_COUNT, FACE_SIZE, FACES_BYTES } from "./model.js";

export const THUMB_SIZE = 64;
export const FACE_FOV = 90;
export const THUMBNAIL_ENDPOINT = "https://geo0.ggpht.com/cbk";
export const VIEW_USER_AGENT = "VISION-Community-view/1";
export const QUERY_VIEW_CAP = 4;
export const STREET_LEASE_CAP = {
  scene: { slow: 1, medium: 4, max: 8 },
  object: { slow: 1, medium: 2, max: 4 },
};
export const CLI_LEASE_CAP = {
  scene: { slow: 16, medium: 64, max: 128 },
  object: { slow: 8, medium: 32, max: 64 },
};

const INVENTED_PREFIXES = ["synthetic:", "Prototype", "CommunityPano", "wikimedia:"];

export function usesStreetViews(panoId) {
  if (typeof panoId !== "string" || !panoId.trim()) return false;
  const identity = panoId.trim();
  if (identity.includes("maps.googleapis.com") || identity.startsWith("http")) return false;
  return !INVENTED_PREFIXES.some((prefix) => identity.startsWith(prefix));
}

export function wrapHeading(heading) {
  const value = Number(heading) || 0;
  return ((value % 360) + 360) % 360;
}

export function thumbnailFov(zoom) {
  const z = Number.isFinite(Number(zoom)) ? Number(zoom) : 0;
  const fov = (360 / Math.PI) * Math.atan(0.75 * 2 ** (1 - z));
  return Math.min(120, Math.max(30, fov));
}

export function viewPlan(lane, heading = 0, pitch = 0, zoom = 0) {
  const baseHeading = wrapHeading(heading);
  const posePitch = Number(pitch) || 0;
  const poseZoom = Number(zoom) || 0;
  const ringPitch = lane === "object" ? 0 : posePitch;
  const ringFov = lane === "object" ? FACE_FOV : thumbnailFov(poseZoom);
  const views = [];
  for (let offset = 0; offset < 4; offset += 1) {
    views.push({ yaw: wrapHeading(baseHeading + offset * 90), pitch: ringPitch, fov: ringFov });
  }
  views.push({ yaw: baseHeading, pitch: 90, fov: FACE_FOV });
  views.push({ yaw: baseHeading, pitch: -90, fov: FACE_FOV });
  if (views.length !== FACE_COUNT) throw new Error("view_count");
  return views;
}

function queryNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "0";
  if (Number.isInteger(number)) return String(number);
  return String(Number(number.toPrecision(6)));
}

export function thumbnailUrl(panoId, yaw, pitch, fov, width = THUMB_SIZE, height = THUMB_SIZE) {
  const     params = new URLSearchParams({
    cb_client: "apiv3",
    output: "thumbnail",
    panoid: panoId,
    w: String(width),
    h: String(height),
    yaw: queryNumber(yaw),
    pitch: queryNumber(-Number(pitch)),
    thumbfov: String(Math.round(Math.min(120, Math.max(30, Number(fov) || 0)))),
  });
  return `${THUMBNAIL_ENDPOINT}?${params}`;
}

export function downsampleBox(rgb, width, height, size = FACE_SIZE) {
  if (!rgb || width <= 0 || height <= 0 || rgb.length < width * height * 3) {
    throw new Error("invalid_thumbnail");
  }
  if (width === size && height === size) return rgb.slice(0, size * size * 3);
  const out = new Uint8Array(size * size * 3);
  for (let y = 0; y < size; y += 1) {
    const y0 = Math.floor((y * height) / size);
    let y1 = Math.floor(((y + 1) * height) / size);
    if (y1 <= y0) y1 = y0 + 1;
    for (let x = 0; x < size; x += 1) {
      const x0 = Math.floor((x * width) / size);
      let x1 = Math.floor(((x + 1) * width) / size);
      if (x1 <= x0) x1 = x0 + 1;
      const count = (y1 - y0) * (x1 - x0);
      let sumR = 0, sumG = 0, sumB = 0;
      for (let py = y0; py < y1; py += 1) {
        const row = py * width * 3;
        for (let px = x0; px < x1; px += 1) {
          const index = row + px * 3;
          sumR += rgb[index];
          sumG += rgb[index + 1];
          sumB += rgb[index + 2];
        }
      }
      const dest = (y * size + x) * 3;
      out[dest] = Math.floor(sumR / count);
      out[dest + 1] = Math.floor(sumG / count);
      out[dest + 2] = Math.floor(sumB / count);
    }
  }
  return out;
}

export function decodeJpegRgb(payload) {
  const decoded = jpegJs.decode(payload, { useTArray: true, formatAsRGBA: true });
  const pixels = decoded.data;
  const rgb = new Uint8Array(decoded.width * decoded.height * 3);
  for (let i = 0, o = 0; i < pixels.length; i += 4, o += 3) {
    rgb[o] = pixels[i];
    rgb[o + 1] = pixels[i + 1];
    rgb[o + 2] = pixels[i + 2];
  }
  return { rgb, width: decoded.width, height: decoded.height };
}

async function fetchThumbnail(url) {
  let lastError = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: { "User-Agent": VIEW_USER_AGENT },
        cf: { cacheTtl: 0, cacheEverything: false },
      });
      if (!response.ok) throw new Error("view_unavailable");
      const payload = new Uint8Array(await response.arrayBuffer());
      if (!payload.length) throw new Error("view_unavailable");
      return payload;
    } catch (error) {
      lastError = error;
      if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, 400 * (attempt + 1)));
    }
  }
  throw lastError || new Error("view_unavailable");
}

export async function renderStreetFaces(location, fetchBytes = fetchThumbnail) {
  const panoId = location.panoId || location.assetId || location.asset_id;
  if (!usesStreetViews(panoId)) throw new Error("not_a_street_pano");
  const lane = location.lane || "scene";
  const faces = new Uint8Array(FACES_BYTES);
  const views = viewPlan(lane, location.heading || 0, location.pitch || 0, location.zoom || 0);
  let offset = 0;
  for (const view of views) {
    const jpeg = await fetchBytes(thumbnailUrl(panoId, view.yaw, view.pitch, view.fov));
    const { rgb, width, height } = decodeJpegRgb(jpeg);
    const face = downsampleBox(rgb, width, height);
    faces.set(face, offset);
    offset += face.length;
  }
  if (offset !== FACES_BYTES) throw new Error("invalid_thumbnail");
  return faces;
}

export async function renderLocationFaces(location, seedFaces) {
  const panoId = location.panoId || location.assetId || location.asset_id;
  if (usesStreetViews(panoId)) return renderStreetFaces(location);
  return seedFaces();
}

export function streetLeaseCap(lane, pace) {
  return leaseCap(lane, pace, "browser");
}

export function leaseCap(lane, pace, client = "browser") {
  const table = client === "cli" ? CLI_LEASE_CAP : STREET_LEASE_CAP;
  const caps = table[lane] || table.scene;
  return caps[pace] || caps.medium;
}
