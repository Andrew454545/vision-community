"""map-making.app JSON maps, matching the local VISION export.

A search returns this document so a user can open it on map-making.app, which
loads Street View live. This project stores panorama metadata and derived
embeddings only. It does not persist Street View imagery.
"""

from __future__ import annotations

import json
import math

from .features import MODEL_ID
from .rank import canonicalize_country


MAX_REFERENCE_EXAMPLES = 100
RESULT_PRUNE_METERS = 100
SCENE_MODEL_NAME = "SigLIP B/16 224"
OBJECT_LANE_MODELS = {
    "common": "RF-DETR Medium 1.10.0",
    "hot": "YOLOE-26L 8.4.143",
    "semantic": "OWLv2 Base Patch16 + PQ128",
}


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


def _coordinates(document) -> list:
    if isinstance(document, dict):
        for key in ("customCoordinates", "locations", "coordinates"):
            value = document.get(key)
            if isinstance(value, list):
                return value
        return []
    if isinstance(document, list):
        return document
    return []


def evenly_sample(values: list, limit: int = MAX_REFERENCE_EXAMPLES) -> list:
    if len(values) <= limit:
        return values
    if limit <= 1:
        return values[:1]
    last = len(values) - 1
    return [values[int(round(index / (limit - 1) * last))] for index in range(limit)]


def parse_map(document: dict) -> dict:
    coordinates = _coordinates(document)
    if not coordinates:
        raise MMAError("invalid_mma_map")
    name = (
        document.get("name")
        if isinstance(document, dict) and isinstance(document.get("name"), str) and document["name"].strip()
        else "VISION Community"
    )
    examples = []
    seen = set()
    for row in coordinates:
        if not isinstance(row, dict):
            continue
        pano_id = row.get("panoId") or row.get("pano_id") or row.get("pano")
        if not isinstance(pano_id, str) or not pano_id.strip():
            continue
        pano_id = pano_id.strip()
        if "maps.googleapis.com" in pano_id or pano_id.startswith("http"):
            raise MMAError("imagery_url_forbidden")
        heading = _number(row.get("heading"))
        pitch = _number(row.get("pitch"))
        zoom = _number(row.get("zoom"))
        key = f"{pano_id}|{heading}|{pitch}|{zoom}"
        if key in seen:
            continue
        seen.add(key)
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        capture = extra.get("panoDate") if isinstance(extra.get("panoDate"), str) else ""
        examples.append(
            {
                "panoId": pano_id,
                "lat": _number(row.get("lat")),
                "lng": _number(row.get("lng", row.get("lon"))),
                "heading": heading,
                "pitch": pitch,
                "zoom": zoom,
                "capture": capture or "unknown",
                "country": (extra.get("tags") or [""])[0] if isinstance(extra.get("tags"), list) else "",
            }
        )
    examples = evenly_sample(examples)
    if not examples:
        raise MMAError("empty_mma_map")
    return {"name": name, "examples": examples}


def vision_round(value: float) -> float:
    """Match VISION's 7-decimal score rounding."""
    scaled = float(value) * 10_000_000
    if scaled >= 0:
        rounded = math.floor(scaled + 0.5)
    else:
        rounded = math.ceil(scaled - 0.5)
    return rounded / 10_000_000


def object_model_name(lane: str | None) -> str:
    return OBJECT_LANE_MODELS.get(lane or "", SCENE_MODEL_NAME)


def search_location_extra(
    *,
    country: str,
    camera_generation: str,
    score: float,
    min_score: float,
    rank: int,
    query_name: str,
    mode: str,
    heading_offset: int,
    source_index: int,
    processed_locations: int,
    model: str,
    object_class: str | None = None,
    object_class_id: int | None = None,
    object_lane: str | None = None,
    object_confidence: float | None = None,
    object_support: int | None = None,
    object_box_area: float | None = None,
) -> dict:
    country = canonicalize_country(country)
    return {
        "tags": [country] if country else [""],
        "visionCameraGeneration": camera_generation or "unknown",
        "visionScore": vision_round(score),
        "visionMinScore": vision_round(min_score),
        "visionRank": int(rank),
        "visionQuery": query_name,
        "visionQueryMode": mode,
        "visionHeadingOffset": int(heading_offset),
        "visionSourceIndex": int(source_index),
        "visionProcessedLocations": int(processed_locations),
        "visionModel": model,
        "visionPruneMeters": RESULT_PRUNE_METERS,
        "visionObjectClass": object_class,
        "visionObjectClassId": object_class_id,
        "visionObjectLane": object_lane,
        "visionObjectConfidence": None if object_confidence is None else vision_round(object_confidence),
        "visionObjectSupport": object_support,
        "visionObjectBoxArea": None if object_box_area is None else vision_round(object_box_area),
    }


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
    heading_offset: int = 0,
) -> dict:
    country = canonicalize_country(country)
    extra = {
        "tags": [country],
        "visionCameraGeneration": camera_generation or "unknown",
        "visionScore": round(float(score), 7),
        "visionMinScore": round(float(min_score), 7),
        "visionRank": int(rank),
        "visionQuery": query_name,
        "visionQueryMode": "objects" if lane == "object" else "scene",
        "visionHeadingOffset": int(heading_offset),
        "visionSourceIndex": 0,
        "visionProcessedLocations": int(processed_locations),
        "visionModel": MODEL_ID,
        "visionPruneMeters": RESULT_PRUNE_METERS,
    }
    if lane == "object":
        extra["visionObjectLane"] = "object"
        extra["visionObjectConfidence"] = round(float(score), 7)
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


def dump_map(document: dict) -> str:
    """Pretty-print an MMA map the same way VISION.app writes search JSON."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
