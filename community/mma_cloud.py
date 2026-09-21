"""Send Community search JSON to map-making.app using the user's own API key.

The key never touches the Community Worker. This is the same API the official
GeoGuessr integration uses: list maps, create a map, then POST location edits.
"""

from __future__ import annotations

import json
import os
import stat
import urllib.error
import urllib.request
from pathlib import Path

from .mma import MMAError, _coordinates


CLOUD_URL = "https://map-making.app"
EDIT_TYPE_IMPORT = 4
PANO_FLAG = 1
BATCH = 80
SESSION_NAME = "mma.json"


class CloudError(RuntimeError):
    def __init__(self, code: str, status: int = 0):
        super().__init__(code)
        self.code = code
        self.status = status


def default_cloud_session_path() -> Path:
    override = os.environ.get("VISION_COMMUNITY_MMA_SESSION")
    if override:
        return Path(override)
    return Path.home() / ".config" / "vision-community" / SESSION_NAME


def load_cloud_session(path: Path | None = None) -> dict:
    target = path or default_cloud_session_path()
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_cloud_session(payload: dict, path: Path | None = None) -> Path:
    target = path or default_cloud_session_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return target


def cloud_locations(document: dict) -> list[dict]:
    coordinates = _coordinates(document)
    if not coordinates:
        raise MMAError("empty_mma_map")
    rows = []
    for row in coordinates:
        if not isinstance(row, dict):
            continue
        pano_id = row.get("panoId") or row.get("pano_id") or row.get("pano")
        if not isinstance(pano_id, str) or not pano_id.strip():
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        tags = extra.get("tags") if isinstance(extra.get("tags"), list) else []
        names = [str(tag) for tag in tags if isinstance(tag, str) and tag.strip()]
        rows.append(
            {
                "id": -1,
                "flags": PANO_FLAG,
                "location": {
                    "lat": float(row.get("lat") or 0),
                    "lng": float(row.get("lng", row.get("lon")) or 0),
                },
                "panoId": pano_id.strip(),
                "heading": float(row.get("heading") or 0),
                "pitch": float(row.get("pitch") or 0),
                "zoom": float(row.get("zoom") or 0),
                "tags": names,
                "extra": extra or None,
            }
        )
    if not rows:
        raise MMAError("empty_mma_map")
    return rows


def _chunks(rows: list[dict], size: int = BATCH):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def _headers(api_key: str) -> dict[str, str]:
    key = api_key.strip() if isinstance(api_key, str) else ""
    if not key:
        raise CloudError("mma_missing_key")
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"API {key}",
    }


def _request(url: str, api_key: str, *, method: str = "GET", body=None) -> object:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers=_headers(api_key), method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            raise CloudError("mma_unauthorized", error.code) from error
        raise CloudError("mma_request_failed", error.code) from error
    except urllib.error.URLError as error:
        raise CloudError("mma_unreachable") from error
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise CloudError("mma_request_failed") from error


def normalize_maps(payload) -> list[dict]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("maps") or payload.get("data") or payload.get("items") or []
    else:
        rows = []
    maps = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        map_id = row.get("id") or row.get("mapId")
        if map_id is None:
            continue
        name = row.get("name") if isinstance(row.get("name"), str) and row["name"].strip() else "Untitled map"
        maps.append({"id": str(map_id), "name": name})
    return maps


def map_id_of(payload) -> str:
    if isinstance(payload, dict):
        nested = payload.get("map") if isinstance(payload.get("map"), dict) else payload
        map_id = nested.get("id") or nested.get("mapId") or payload.get("id")
        if map_id is not None:
            return str(map_id)
    raise CloudError("mma_create_failed")


def list_maps(api_key: str, *, origin: str = CLOUD_URL) -> list[dict]:
    return normalize_maps(_request(f"{origin.rstrip('/')}/api/maps", api_key))


def create_map(api_key: str, name: str, *, origin: str = CLOUD_URL) -> dict:
    title = name.strip() if isinstance(name, str) and name.strip() else "VISION Community"
    payload = _request(f"{origin.rstrip('/')}/api/maps", api_key, method="POST", body={"name": title})
    map_id = map_id_of(payload)
    return {"id": map_id, "name": title}


def add_map_locations(api_key: str, map_id: str, document: dict, *, origin: str = CLOUD_URL) -> dict:
    if not isinstance(map_id, str) or not map_id.strip():
        raise CloudError("mma_no_map")
    rows = cloud_locations(document)
    added = 0
    for chunk in _chunks(rows):
        _request(
            f"{origin.rstrip('/')}/api/maps/{map_id.strip()}/locations",
            api_key,
            method="POST",
            body={"edits": [{"action": {"type": EDIT_TYPE_IMPORT}, "create": chunk, "remove": []}]},
        )
        added += len(chunk)
    return {"mapId": map_id.strip(), "added": added, "url": f"{origin.rstrip('/')}/maps/{map_id.strip()}"}


def send_map(
    document: dict,
    *,
    api_key: str,
    map_id: str | None = None,
    new_map: bool = False,
    origin: str = CLOUD_URL,
) -> dict:
    name = document.get("name") if isinstance(document, dict) else None
    if new_map or not map_id:
        created = create_map(api_key, name or "VISION Community", origin=origin)
        map_id = created["id"]
        map_name = created["name"]
    else:
        map_name = name or "map-making.app"
    result = add_map_locations(api_key, map_id, document, origin=origin)
    result["name"] = map_name
    return result
