"""Rights-aware import contract and canonical job identity.

Real Google Street View imagery, undocumented Google endpoints, and any
owner API key are rejected. A source may be enabled only with an explicit
rights grant covering fetch, volunteer redistribution, derived indexes,
and result display.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Iterable


GOOGLE_PREFIXES = ("google:", "gsv:", "pano:", "streetview:")
SYNTHETIC_PREFIX = "synthetic:"
WIKIMEDIA_PREFIX = "wikimedia:"
REQUIRED_RIGHTS = (
    "fetch",
    "transform",
    "redistribute_to_workers",
    "retain_derived_index",
    "display_search_results",
)


class SourceError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def canonical_job_id(asset_id: str, capture: str, lane: str, model: str) -> str:
    payload = f"{asset_id}\n{capture}\n{lane}\n{model}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def synthetic_coordinates(asset_id: str) -> tuple[float, float]:
    digest = hashlib.sha256(asset_id.encode("utf-8")).digest()
    lat = (int.from_bytes(digest[:4], "big") / 2**32) * 140 - 70
    lon = (int.from_bytes(digest[4:8], "big") / 2**32) * 360 - 180
    return round(lat, 6), round(lon, 6)


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def assert_not_google(asset_id: str) -> None:
    lowered = asset_id.casefold()
    if lowered.startswith(GOOGLE_PREFIXES) or "maps.googleapis.com" in lowered or "streetview" in lowered:
        raise SourceError("google_source_forbidden")


def validate_rights(grant: dict | None, *, source_kind: str) -> dict:
    if source_kind == "synthetic":
        if not grant or grant.get("rights") != "synthetic-test-data":
            raise SourceError("synthetic_rights_marker_missing")
        return {
            "source": "synthetic",
            "rights": "synthetic-test-data",
            "attribution": "Invented test imagery. Not a real place.",
            "enabled": True,
        }
    if not isinstance(grant, dict):
        raise SourceError("rights_grant_required")
    if grant.get("source") != source_kind:
        raise SourceError("rights_source_mismatch")
    missing = [item for item in REQUIRED_RIGHTS if item not in grant.get("permits", [])]
    if missing:
        raise SourceError("rights_incomplete")
    if grant.get("writtenEvidence") is not True:
        raise SourceError("written_rights_evidence_required")
    if not isinstance(grant.get("attribution"), str) or not grant["attribution"].strip():
        raise SourceError("attribution_required")
    return {
        "source": source_kind,
        "rights": "granted",
        "attribution": grant["attribution"].strip(),
        "enabled": True,
    }


def parse_catalog(document: dict, *, grant: dict | None = None) -> list[dict]:
    if not isinstance(document, dict) or not isinstance(document.get("locations"), list):
        raise SourceError("invalid_catalog")
    declared = document.get("source") or document.get("rights")
    if declared in {"synthetic-test-data", "synthetic"}:
        rights = validate_rights({"rights": "synthetic-test-data"}, source_kind="synthetic")
        source_kind = "synthetic"
    elif declared == "wikimedia":
        rights = validate_rights(grant or document.get("grant"), source_kind="wikimedia")
        source_kind = "wikimedia"
        # A rights-complete Wikimedia grant still does not start network ingest here.
        # Callers must pass ingest=True to the importer after the owner confirms volume.
        rights = {**rights, "enabled": False, "blocked": "ingest_not_started"}
    elif declared in {"google", "streetview"}:
        raise SourceError("google_source_forbidden")
    else:
        raise SourceError("unknown_source")

    rows = []
    seen = set()
    for record in document["locations"]:
        if not isinstance(record, dict):
            raise SourceError("invalid_catalog")
        asset_id = record.get("assetId")
        capture = record.get("capture")
        lane = record.get("lane")
        model = record.get("model")
        if any(not isinstance(field, str) or not field or len(field) > 300 for field in (asset_id, capture, lane, model)):
            raise SourceError("invalid_catalog")
        assert_not_google(asset_id)
        if source_kind == "synthetic" and not asset_id.startswith(SYNTHETIC_PREFIX):
            raise SourceError("synthetic_prefix_required")
        if source_kind == "wikimedia" and not asset_id.startswith(WIKIMEDIA_PREFIX):
            raise SourceError("wikimedia_prefix_required")
        if lane not in {"scene", "object"}:
            raise SourceError("invalid_lane")
        identity = (asset_id, capture, lane, model)
        if identity in seen:
            continue
        seen.add(identity)
        lat, lon = record.get("lat"), record.get("lon")
        if lat is None or lon is None:
            lat, lon = synthetic_coordinates(asset_id)
        try:
            lat_f, lon_f = float(lat), float(lon)
        except (TypeError, ValueError) as error:
            raise SourceError("invalid_coordinates") from error
        rows.append(
            {
                "assetId": asset_id,
                "capture": capture,
                "lane": lane,
                "model": model,
                "jobId": canonical_job_id(asset_id, capture, lane, model),
                "lat": lat_f,
                "lon": lon_f,
                "source": rights["source"],
                "rights": rights["rights"],
                "attribution": rights["attribution"],
                "label": record.get("label") if isinstance(record.get("label"), str) else "",
            }
        )
    return rows


def apply_spatial_duplicates(rows: Iterable[dict], existing: Iterable[dict], *, meters: float = 25.0) -> list[dict]:
    """Honor VISION's inclusive 25 m spatial duplicate rule within a capture/lane/model."""
    indexed = list(existing)
    result = []
    for row in rows:
        deferred = False
        for other in indexed:
            if (
                other["lane"] == row["lane"]
                and other["capture"] == row["capture"]
                and other["model"] == row["model"]
                and other["assetId"] != row["assetId"]
                and haversine_meters(row["lat"], row["lon"], other["lat"], other["lon"]) <= meters
            ):
                deferred = True
                break
        item = dict(row)
        item["queueState"] = "deferred" if deferred else "pending"
        result.append(item)
        indexed.append(item)
    return result


def load_catalog_file(path, *, grant=None) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SourceError("invalid_catalog")
    return document
