"""map-making.app JSON maps, matching the local VISION export.

A search returns this document so a user can open it on map-making.app, which
loads Street View live. This project stores panorama metadata and derived
embeddings only. It does not persist Street View imagery.
"""

from __future__ import annotations

from .features import MODEL_ID


MAX_REFERENCE_EXAMPLES = 100


class MMAError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _number(value, default=0.0) -> float:
    if value is None or value == "":
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise MMAError("invalid_mma_number") from error


def parse_map(document: dict) -> dict:
    if not isinstance(document, dict) or not isinstance(document.get("customCoordinates"), list):
        raise MMAError("invalid_mma_map")
    if len(document["customCoordinates"]) < 1:
        raise MMAError("empty_mma_map")
    if len(document["customCoordinates"]) > MAX_REFERENCE_EXAMPLES:
        raise MMAError("too_many_references")
    name = document.get("name") if isinstance(document.get("name"), str) and document["name"].strip() else "VISION Community"
    examples = []
    for row in document["customCoordinates"]:
        if not isinstance(row, dict):
            raise MMAError("invalid_mma_location")
        pano_id = row.get("panoId") or row.get("pano_id")
        if not isinstance(pano_id, str) or not 4 <= len(pano_id) <= 80:
            raise MMAError("invalid_pano_id")
        if "maps.googleapis.com" in pano_id or pano_id.startswith("http"):
            raise MMAError("imagery_url_forbidden")
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        capture = extra.get("panoDate") if isinstance(extra.get("panoDate"), str) else ""
        examples.append(
            {
                "panoId": pano_id,
                "lat": _number(row.get("lat")),
                "lng": _number(row.get("lng", row.get("lon"))),
                "heading": _number(row.get("heading")),
                "pitch": _number(row.get("pitch")),
                "zoom": _number(row.get("zoom")),
                "capture": capture or "unknown",
                "country": (extra.get("tags") or [""])[0] if isinstance(extra.get("tags"), list) else "",
            }
        )
    return {"name": name, "examples": examples}


def location_record(
    *,
    lat: float,
    lng: float,
    heading: float,
    pitch: float,
    zoom: float,
    pano_id: str,
    rank: int,
    score: float,
    query_name: str,
    lane: str,
    country: str = "",
    camera_generation: str = "",
    processed_locations: int = 0,
    min_score: float = 0.0,
) -> dict:
    tags = [item for item in (country, lane) if item]
    extra = {
        "tags": tags,
        "visionCameraGeneration": camera_generation or "unknown",
        "visionScore": round(float(score), 6),
        "visionMinScore": round(float(min_score), 6),
        "visionRank": int(rank),
        "visionQuery": query_name,
        "visionQueryMode": lane,
        "visionHeadingOffset": 0,
        "visionSourceIndex": 0,
        "visionProcessedLocations": int(processed_locations),
        "visionModel": MODEL_ID,
        "visionPruneMeters": 25,
        "visionObjectClass": None,
        "visionObjectClassId": None,
        "visionObjectLane": lane if lane == "object" else None,
        "visionObjectConfidence": round(float(score), 6) if lane == "object" else None,
        "visionObjectSupport": None,
        "visionObjectBoxArea": None,
    }
    return {
        "lat": float(lat),
        "lng": float(lng),
        "heading": float(heading),
        "pitch": float(pitch),
        "zoom": float(zoom),
        "panoId": pano_id,
        "extra": extra,
    }


def build_map(name: str, coordinates: list[dict]) -> dict:
    title = name.strip() if isinstance(name, str) and name.strip() else "VISION Community"
    return {"name": title, "customCoordinates": coordinates}
