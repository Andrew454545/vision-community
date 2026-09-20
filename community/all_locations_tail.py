"""Reserve the unprocessed tail of a live VISION indexer TSV.

Local VISION reads that queue from the front. Community takes only the tail so
the two do not collide. The live source file is never rewritten: shrinking it
would abort the running remainder checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .catalog import iter_indexer_tsv
from .features import MODEL_ID

INSERT_COLUMNS = (
    "asset_id",
    "capture",
    "lane",
    "model",
    "label",
    "source",
    "rights",
    "attribution",
    "lat",
    "lon",
    "heading",
    "pitch",
    "zoom",
    "country",
    "camera_generation",
    "queue_state",
)
RIGHTS = "metadata-only-no-imagery"
ATTRIBUTION = "Panorama metadata only. Imagery is not stored."
SOURCE = "street-metadata"


def sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        raise TypeError("boolean")
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def copy_tail(source: Path, destination: Path, rows: int) -> dict:
    if rows < 1:
        raise ValueError("rows")
    return _write_copied_tsv(destination, _tail_lines(source, rows))


def copy_tail_window(source: Path, destination: Path, *, tail_rows: int, skip_last: int) -> dict:
    """Copy `tail_rows - skip_last` rows that sit immediately before an already reserved tail."""
    take = int(tail_rows) - int(skip_last)
    if take < 1 or skip_last < 0:
        raise ValueError("rows")
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    tail = subprocess.Popen(["tail", "-n", str(tail_rows), str(source)], stdout=subprocess.PIPE)
    try:
        head = subprocess.run(
            ["head", "-n", str(take)],
            stdin=tail.stdout,
            check=True,
            capture_output=True,
        )
    finally:
        if tail.stdout:
            tail.stdout.close()
        tail.wait()
    if tail.returncode not in (0, None):
        raise subprocess.CalledProcessError(tail.returncode or 1, "tail")
    return _write_copied_tsv(destination, head.stdout)


def _tail_lines(source: Path, rows: int) -> bytes:
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    return subprocess.run(["tail", "-n", str(rows), str(source)], check=True, capture_output=True).stdout


def _write_copied_tsv(destination: Path, payload: bytes) -> dict:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload if payload.endswith(b"\n") or not payload else payload + b"\n")
    copied = 0
    digest = hashlib.sha256()
    first = last = None
    with destination.open("rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            copied += 1
            digest.update(line if line.endswith(b"\n") else line + b"\n")
            parts = line.decode("utf-8").rstrip("\n\r").split("\t")
            if len(parts) != 11:
                raise ValueError("invalid_catalog")
            pano = parts[7]
            if first is None:
                first = pano
            last = pano
    return {
        "path": str(destination.resolve()),
        "rows": copied,
        "bytes": destination.stat().st_size,
        "sha256": digest.hexdigest(),
        "firstPanoId": first,
        "lastPanoId": last,
    }


def reservation(
    *,
    source_tsv: Path,
    source_rows: int,
    source_bytes: int,
    local_next_location_index: int,
    tail: dict,
    live_source_rewritten: bool = False,
) -> dict:
    reserved_from = source_rows - int(tail["rows"])
    if reserved_from < 0:
        raise ValueError("tail_longer_than_source")
    if local_next_location_index >= reserved_from:
        raise ValueError("tail_overlaps_local_cursor")
    return {
        "version": 1,
        "contract": "vision-community-all-locations-tail-v1",
        "sourceTsv": str(Path(source_tsv).resolve()),
        "sourceRows": source_rows,
        "sourceBytes": source_bytes,
        "localNextLocationIndex": local_next_location_index,
        "reservedFromLocationIndex": reserved_from,
        "reservedRows": tail["rows"],
        "tailTsv": tail["path"],
        "tailBytes": tail["bytes"],
        "tailSha256": tail["sha256"],
        "firstPanoId": tail["firstPanoId"],
        "lastPanoId": tail["lastPanoId"],
        "liveSourceRewritten": live_source_rewritten,
        "reason": (
            "Community volunteers process this tail. Local VISION continues from "
            "the front of the same ALL LOCATIONS queue and must not be given a "
            "truncated source while its remainder checkpoint is still running."
        ),
    }


def jobs_from_tail(path: Path, *, lane: str = "scene", skip_asset_ids: set[str] | None = None):
    skip = skip_asset_ids or set()
    for job in iter_indexer_tsv(path, lane=lane, model=MODEL_ID):
        if job["assetId"] in skip:
            continue
        yield job


def insert_sql(jobs: list[dict], *, values_per_statement: int = 25) -> list[str]:
    if values_per_statement < 1:
        raise ValueError("values_per_statement")
    statements = []
    prefix = "INSERT OR IGNORE INTO locations (" + ", ".join(INSERT_COLUMNS) + ") VALUES\n"
    for start in range(0, len(jobs), values_per_statement):
        chunk = jobs[start : start + values_per_statement]
        rows = []
        for job in chunk:
            rows.append(
                "  ("
                + ", ".join(
                    (
                        sql_literal(job["assetId"]),
                        sql_literal(job["capture"]),
                        sql_literal(job["lane"]),
                        sql_literal(job["model"]),
                        sql_literal(""),
                        sql_literal(SOURCE),
                        sql_literal(RIGHTS),
                        sql_literal(ATTRIBUTION),
                        sql_literal(job["lat"]),
                        sql_literal(job["lon"]),
                        sql_literal(job["heading"]),
                        sql_literal(job["pitch"]),
                        sql_literal(job["zoom"]),
                        sql_literal(job["country"] or ""),
                        sql_literal(job["cameraGeneration"] or ""),
                        sql_literal("pending"),
                    )
                )
                + ")"
            )
        statements.append(prefix + ",\n".join(rows) + ";")
    return statements


def write_sql_files(jobs: list[dict], directory: Path, *, rows_per_file: int = 2000) -> list[Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for index, start in enumerate(range(0, len(jobs), rows_per_file)):
        chunk = jobs[start : start + rows_per_file]
        path = directory / f"tail-{index:03d}.sql"
        path.write_text("\n".join(insert_sql(chunk)) + "\n", encoding="utf-8")
        written.append(path)
    return written


def split_shards(
    source: Path,
    destination: Path,
    *,
    rows_per_shard: int = 50_000,
    limit: int | None = None,
    key_prefix: str = "catalog/all-locations-tail-v1",
    lane: str = "scene",
    row_start: int = 0,
    shard_id_start: int = 0,
) -> dict:
    """Cut a tail TSV into pose-only shards. Does not rewrite the live source."""
    if rows_per_shard < 1:
        raise ValueError("rows_per_shard")
    source = Path(source)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    shards = []
    shard_id = int(shard_id_start)
    written = 0
    handle = None
    digest = None
    first = last = None
    shard_rows = 0

    def close_shard():
        nonlocal handle, digest, shard_rows, first, last
        if handle is None:
            return
        handle.close()
        path = Path(handle.name)
        shards.append(
            {
                "shardId": shard_id - 1,
                "file": path.name,
                "key": f"{key_prefix}/{path.name}",
                "rows": shard_rows,
                "bytes": path.stat().st_size,
                "sha256": digest.hexdigest(),
                "rowStart": row_start + written - shard_rows,
                "firstPanoId": first,
                "lastPanoId": last,
            }
        )
        handle = None
        digest = None
        shard_rows = 0
        first = last = None

    with source.open("r", encoding="utf-8") as reader:
        for line in reader:
            if limit is not None and written >= limit:
                break
            if not line.strip():
                continue
            parts = line.rstrip("\n\r").split("\t")
            if len(parts) != 11:
                close_shard()
                raise ValueError("invalid_catalog")
            if handle is None:
                path = destination / f"shard-{shard_id:05d}.tsv"
                handle = path.open("w", encoding="utf-8", newline="\n")
                digest = hashlib.sha256()
                shard_id += 1
            text = line if line.endswith("\n") else line + "\n"
            handle.write(text)
            digest.update(text.encode("utf-8"))
            pano = parts[7]
            if first is None:
                first = pano
            last = pano
            shard_rows += 1
            written += 1
            if shard_rows >= rows_per_shard:
                close_shard()
    close_shard()
    manifest = {
        "version": 1,
        "contract": "vision-community-pose-catalog-v1",
        "lane": lane,
        "r2Prefix": key_prefix,
        "rowsPerShard": rows_per_shard,
        "totalRows": written,
        "rowStart": row_start,
        "shards": shards,
    }
    write_json(destination / "manifest.json", manifest)
    return manifest


def write_json(path: Path, document: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def pose_catalog_insert_sql(manifest: dict, *, lanes: tuple[str, ...] = ("scene",)) -> str:
    """SQL to register shards without moving pose rows into D1."""
    shards = manifest.get("shards") or []
    lines = []
    for lane in lanes:
        for shard in shards:
            lines.append(
                "INSERT OR IGNORE INTO pose_catalog "
                "(lane, shard_id, r2_key, row_start, row_count, bytes, sha256, next_byte, next_row) VALUES ("
                + ", ".join(
                    (
                        sql_literal(lane),
                        sql_literal(int(shard["shardId"])),
                        sql_literal(shard["key"]),
                        sql_literal(int(shard["rowStart"])),
                        sql_literal(int(shard["rows"])),
                        sql_literal(int(shard["bytes"])),
                        sql_literal(shard["sha256"]),
                        "0",
                        "0",
                    )
                )
                + ");"
            )
    return "\n".join(lines) + "\n"
