"""Export published Community locations for the local VISION indexer.

Volunteers claim exclusive catalog work. The browser extractor is
community-visual-v1 and is not searchable by VISION.app. This handoff writes
the 11-column headerless TSV the local four-view / object indexer already
consumes, plus an MMA JSON map of the same poses.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .mma import build_map, location_record
from .rank import canonicalize_country


INDEXER_COLUMNS = (
    "map_id",
    "location_id",
    "lat",
    "lng",
    "heading",
    "pitch",
    "zoom",
    "pano_id",
    "country",
    "camera_generation",
    "road_name_state",
)
MAP_ID = "vision-community"
ROAD_NAME_STATE = "no road name"
HANDOFF_CONTRACT = "vision-community-handoff-v1"


def _tsv_cell(value) -> str:
    text = "" if value is None else str(value)
    if "\t" in text or "\n" in text or "\r" in text:
        raise ValueError("tsv_control_character")
    return text


def indexer_row(record: dict, *, location_id: int) -> list[str]:
    return [
        MAP_ID,
        str(int(location_id)),
        _tsv_cell(record["lat"]),
        _tsv_cell(record["lng"]),
        _tsv_cell(record.get("heading") or 0),
        _tsv_cell(record.get("pitch") or 0),
        _tsv_cell(record.get("zoom") or 0),
        _tsv_cell(record["panoId"]),
        canonicalize_country(record.get("country") or ""),
        _tsv_cell(record.get("cameraGeneration") or "unknown"),
        ROAD_NAME_STATE,
    ]


def write_indexer_tsv(records: list[dict], path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for index, record in enumerate(records, start=1):
        lines.append("\t".join(indexer_row(record, location_id=index)))
    payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    path.write_bytes(payload)
    return {
        "path": str(path),
        "rows": len(records),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "columns": list(INDEXER_COLUMNS),
        "headerless": True,
    }


def published_records(database: Path, *, lane: str | None = None) -> list[dict]:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        query = """
            SELECT l.id, l.asset_id, l.capture, l.lane, l.lat, l.lon, l.heading, l.pitch, l.zoom,
                   l.country, l.camera_generation
            FROM locations l
            JOIN published_index i ON i.location_id = l.id
            WHERE l.state='published'
        """
        params: tuple = ()
        if lane is not None:
            query += " AND l.lane=?"
            params = (lane,)
        query += " ORDER BY l.id"
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()
    records = []
    for row in rows:
        records.append(
            {
                "locationId": row["id"],
                "panoId": row["asset_id"],
                "capture": row["capture"],
                "lane": row["lane"],
                "lat": row["lat"] or 0,
                "lng": row["lon"] or 0,
                "heading": row["heading"] or 0,
                "pitch": row["pitch"] or 0,
                "zoom": row["zoom"] or 0,
                "country": row["country"] or "",
                "cameraGeneration": row["camera_generation"] or "",
            }
        )
    return records


def records_from_d1_rows(rows: list[dict]) -> list[dict]:
    records = []
    for row in rows:
        records.append(
            {
                "locationId": row.get("id") or row.get("location_id"),
                "panoId": row.get("asset_id") or row.get("panoId"),
                "capture": row.get("capture") or "",
                "lane": row.get("lane") or "scene",
                "lat": row.get("lat") or 0,
                "lng": row.get("lon") or row.get("lng") or 0,
                "heading": row.get("heading") or 0,
                "pitch": row.get("pitch") or 0,
                "zoom": row.get("zoom") or 0,
                "country": row.get("country") or "",
                "cameraGeneration": row.get("camera_generation") or row.get("cameraGeneration") or "",
            }
        )
    return records


def records_from_d1_document(document) -> list[dict]:
    if isinstance(document, list) and document and isinstance(document[0], dict) and "results" in document[0]:
        rows = document[0]["results"]
    elif isinstance(document, dict) and "results" in document:
        rows = document["results"]
    elif isinstance(document, list):
        rows = document
    else:
        raise ValueError("invalid_d1_json")
    if not isinstance(rows, list):
        raise ValueError("invalid_d1_json")
    return records_from_d1_rows(rows)


def mma_map(records: list[dict], *, name: str) -> dict:
    coordinates = [
        location_record(
            lat=record["lat"],
            lng=record["lng"],
            heading=record["heading"],
            pitch=record["pitch"],
            zoom=record["zoom"],
            pano_id=record["panoId"],
            rank=index,
            score=0.0,
            query_name=name,
            lane=record["lane"],
            country=record.get("country") or "",
            camera_generation=record.get("cameraGeneration") or "",
            processed_locations=len(records),
        )
        for index, record in enumerate(records, start=1)
    ]
    return build_map(name, coordinates)


def export_vision(
    records: list[dict],
    destination: Path,
    *,
    source: str,
) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    by_lane = {"scene": [], "object": []}
    for record in records:
        lane = record.get("lane") or "scene"
        if lane not in by_lane:
            raise ValueError("invalid_lane")
        by_lane[lane].append(record)
    artifacts = {}
    for lane, rows in by_lane.items():
        artifacts[lane] = write_indexer_tsv(rows, destination / f"{lane}-published.tsv")
        (destination / f"{lane}-published.json").write_text(
            json.dumps(mma_map(rows, name=f"VISION Community {lane}"), indent=2) + "\n",
            encoding="utf-8",
        )
        artifacts[lane]["mmaJson"] = str(destination / f"{lane}-published.json")
    manifest = {
        "version": 1,
        "contract": HANDOFF_CONTRACT,
        "source": source,
        "mapId": MAP_ID,
        "productionReady": False,
        "searchableByVisionApp": False,
        "reason": (
            "This TSV is a location queue for the local VISION four-view/object "
            "indexer. Community browser embeddings are community-visual-v1 and "
            "cannot be merged into the SigLIP / RF-DETR / YOLOE / OWLv2 index."
        ),
        "columns": list(INDEXER_COLUMNS),
        "lanes": artifacts,
        "counts": {lane: len(rows) for lane, rows in by_lane.items()},
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def export_from_database(database: Path, destination: Path) -> dict:
    return export_vision(published_records(database), destination, source=str(database))
