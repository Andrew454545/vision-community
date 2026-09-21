/** Browser client for map-making.app. The API key never leaves this computer. */

const MMA_CLOUD = "https://map-making.app";
const MMA_KEY_STORE = "vision-community-mma-key";
const MMA_MAP_STORE = "vision-community-mma-map";
const MMA_EDIT_TYPE = 4;
const MMA_PANO_FLAG = 1;
const MMA_BATCH = 80;

function mmaStoredKey() {
  return (localStorage.getItem(MMA_KEY_STORE) || "").trim();
}

function mmaStoredMap() {
  return (localStorage.getItem(MMA_MAP_STORE) || "").trim();
}

function mmaSaveConnection(apiKey, mapId) {
  if (apiKey) localStorage.setItem(MMA_KEY_STORE, apiKey.trim());
  else localStorage.removeItem(MMA_KEY_STORE);
  if (mapId) localStorage.setItem(MMA_MAP_STORE, mapId);
  else localStorage.removeItem(MMA_MAP_STORE);
}

function mmaHeaders(apiKey) {
  return {
    accept: "application/json",
    "content-type": "application/json",
    authorization: `API ${apiKey}`,
  };
}

async function mmaRequest(path, apiKey, options = {}) {
  let response;
  try {
    response = await fetch(`${MMA_CLOUD}${path}`, {
      method: options.method || "GET",
      headers: mmaHeaders(apiKey),
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new Error("mma_unreachable");
  }
  if (response.status === 401 || response.status === 403) throw new Error("mma_unauthorized");
  if (!response.ok) throw new Error("mma_request_failed");
  const text = await response.text();
  return text ? JSON.parse(text) : {};
}

function mmaNormalizeMaps(payload) {
  const rows = Array.isArray(payload)
    ? payload
    : payload?.maps || payload?.data || payload?.items || [];
  return rows
    .filter((row) => row && (row.id || row.mapId))
    .map((row) => ({
      id: String(row.id || row.mapId),
      name: (row.name && String(row.name).trim()) || "Untitled map",
    }));
}

function mmaCloudLocations(document) {
  const coordinates = document?.customCoordinates || document?.locations || document?.coordinates || [];
  return coordinates
    .filter((row) => row && typeof (row.panoId || row.pano_id || row.pano) === "string")
    .map((row) => {
      const extra = row.extra && typeof row.extra === "object" ? row.extra : {};
      const tags = Array.isArray(extra.tags) ? extra.tags.filter((tag) => typeof tag === "string" && tag.trim()) : [];
      return {
        id: -1,
        flags: MMA_PANO_FLAG,
        location: { lat: Number(row.lat) || 0, lng: Number(row.lng ?? row.lon) || 0 },
        panoId: String(row.panoId || row.pano_id || row.pano).trim(),
        heading: Number(row.heading) || 0,
        pitch: Number(row.pitch) || 0,
        zoom: Number(row.zoom) || 0,
        tags,
        extra: Object.keys(extra).length ? extra : null,
      };
    });
}

async function mmaListMaps(apiKey) {
  return mmaNormalizeMaps(await mmaRequest("/api/maps", apiKey));
}

async function mmaCreateMap(apiKey, name) {
  const payload = await mmaRequest("/api/maps", apiKey, {
    method: "POST",
    body: { name: name || "VISION Community" },
  });
  const nested = payload?.map && typeof payload.map === "object" ? payload.map : payload;
  const id = nested?.id || nested?.mapId || payload?.id;
  if (!id) throw new Error("mma_create_failed");
  return { id: String(id), name: name || "VISION Community" };
}

async function mmaAddLocations(apiKey, mapId, document) {
  const rows = mmaCloudLocations(document);
  if (!rows.length) throw new Error("empty_mma_map");
  for (let index = 0; index < rows.length; index += MMA_BATCH) {
    const chunk = rows.slice(index, index + MMA_BATCH);
    await mmaRequest(`/api/maps/${mapId}/locations`, apiKey, {
      method: "POST",
      body: { edits: [{ action: { type: MMA_EDIT_TYPE }, create: chunk, remove: [] }] },
    });
  }
  return { added: rows.length, mapId, url: `${MMA_CLOUD}/maps/${mapId}` };
}

async function mmaSendMap(document, { apiKey, mapId, newMap } = {}) {
  let target = mapId;
  let name = document?.name || "VISION Community";
  if (newMap || !target) {
    const created = await mmaCreateMap(apiKey, name);
    target = created.id;
    name = created.name;
  }
  const result = await mmaAddLocations(apiKey, target, document);
  return { ...result, name };
}
