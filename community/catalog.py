"""Catalog import: panorama metadata only. Imagery is never persisted.

Google's Street View policy exempts panorama IDs from the caching restriction.
This importer stores pano IDs, pose, country, and capture metadata so volunteers
can process a location and so search can emit map-making.app JSON. JPEG/PNG
bytes, tile URLs, and API keys are rejected.

TSV shards are streamed row-by-row. Do not load a 200M catalog into RAM.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

from .features import MODEL_ID
from .source import SourceError, canonical_job_id, parse_catalog


TSV_FIELDS = (
    "location_id",
    "source_id",
    "source_row",
    "country",
    "country_code",
    "lat",
    "lng",
    "pano_id",
    "capture_year",
    "capture_month",
    "camera_generation",
    "heading",
    "pitch",
    "zoom",
)


def _capture(year, month) -> str:
    year = (year or "").strip()
    month = (month or "").strip()
    if year and month:
        return f"{year}-{month.zfill(2)}"
    return year or "unknown"


def _metadata_job(record: dict) -> dict | None:
    if not isinstance(record, dict):
        raise SourceError("invalid_catalog")
    for banned in ("image", "images", "faces", "jpeg", "png", "url", "tileUrl"):
        if record.get(banned):
            raise SourceError("imagery_payload_forbidden")
    pano_id = record.get("panoId") or record.get("pano_id") or record.get("assetId")
    if not isinstance(pano_id, str) or not 4 <= len(pano_id) <= 80:
        raise SourceError("invalid_pano_id")
    if "maps.googleapis.com" in pano_id or pano_id.startswith("http"):
        raise SourceError("imagery_url_forbidden")
    lane = record.get("lane") or "scene"
    model = record.get("model") or MODEL_ID
    capture = record.get("capture") or _capture(record.get("capture_year"), record.get("capture_month"))
    if lane not in {"scene", "object"}:
        raise SourceError("invalid_lane")
    try:
        lat = float(record.get("lat"))
        lng = float(record.get("lng") if record.get("lng") is not None else record.get("lon"))
        heading = float(record.get("heading") or 0)
        pitch = float(record.get("pitch") or 0)
        zoom = float(record.get("zoom") or 0)
    except (TypeError, ValueError) as error:
        raise SourceError("invalid_coordinates") from error
    return {
        "assetId": pano_id,
        "panoId": pano_id,
        "capture": capture,
        "lane": lane,
        "model": model,
        "jobId": canonical_job_id(pano_id, capture, lane, model),
        "lat": lat,
        "lon": lng,
        "heading": heading,
        "pitch": pitch,
        "zoom": zoom,
        "country": record.get("country") if isinstance(record.get("country"), str) else "",
        "cameraGeneration": record.get("cameraGeneration") or record.get("camera_generation") or "",
        "source": "street-metadata",
        "rights": "metadata-only-no-imagery",
        "attribution": "Panorama metadata only. Imagery is not stored.",
        "label": "",
    }


def parse_street_metadata_catalog(document: dict) -> list[dict]:
    if document.get("persistImagery") is True:
        raise SourceError("imagery_persistence_forbidden")
    locations = document.get("locations")
    if not isinstance(locations, list):
        raise SourceError("invalid_catalog")
    rows = []
    seen = set()
    for record in locations:
        job = _metadata_job(record)
        identity = (job["assetId"], job["capture"], job["lane"], job["model"])
        if identity in seen:
            continue
        seen.add(identity)
        rows.append(job)
    return rows


def _tsv_record(row: dict, *, lane: str, model: str) -> dict:
    return {
        "panoId": row["pano_id"].strip(),
        "lat": row.get("lat"),
        "lng": row.get("lng") or row.get("lon"),
        "heading": row.get("heading") or 0,
        "pitch": row.get("pitch") or 0,
        "zoom": row.get("zoom") or 0,
        "country": row.get("country") or "",
        "cameraGeneration": row.get("camera_generation") or "",
        "capture": _capture(row.get("capture_year"), row.get("capture_month")),
        "lane": lane,
        "model": model,
    }


def parse_tsv(text: str, *, lane: str = "scene", model: str = MODEL_ID) -> dict:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    if reader.fieldnames is None or "pano_id" not in reader.fieldnames or "lat" not in reader.fieldnames:
        raise SourceError("invalid_catalog")
    locations = []
    for row in reader:
        if not row.get("pano_id"):
            continue
        locations.append(_tsv_record(row, lane=lane, model=model))
    return {"source": "street-metadata", "persistImagery": False, "locations": locations}


def iter_tsv(path: Path, *, lane: str = "scene", model: str = MODEL_ID):
    """Yield metadata jobs from a TSV shard without loading the file into RAM."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or "pano_id" not in reader.fieldnames or "lat" not in reader.fieldnames:
            raise SourceError("invalid_catalog")
        for row in reader:
            if not row.get("pano_id"):
                continue
            yield _metadata_job(_tsv_record(row, lane=lane, model=model))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jobs(document: dict, *, grant=None) -> list[dict]:
    source = document.get("source") or document.get("rights")
    if source == "street-metadata":
        return parse_street_metadata_catalog(document)
    return parse_catalog(document, grant=grant)


def load_catalog_path(path: Path, *, grant=None) -> list[dict]:
    if path.suffix in {".tsv", ".txt"}:
        return list(iter_tsv(path))
    text = path.read_text(encoding="utf-8")
    document = json.loads(text)
    if not isinstance(document, dict):
        raise SourceError("invalid_catalog")
    return load_jobs(document, grant=grant)
