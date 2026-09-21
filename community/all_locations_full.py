"""Stream the full ALL LOCATIONS pose catalog into Community.

Reads the MMA Arrow snapshot and the row-parallel camera-generation metadata
read-only. Writes VISION 11-column indexer shards (saved pan + generation).
Never copies embeddings, imagery, or the live remainder TSV.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
import sqlite3
import subprocess
import time
from pathlib import Path

from .all_locations_tail import pose_catalog_insert_sql, write_json
from .rank import canonicalize_country


KEY_PREFIX = "catalog/all-locations-full-v1"
CONTRACT = "vision-community-pose-catalog-v1"
MAP_ID = "all-locations"
EXPECTED_ROWS = 206_722_636
SHARD_ID_START = -20000
ROWS_PER_SHARD = 500_000
RIGHTS = "metadata-only-no-imagery"
CAMERA_CODES = {
    0: "unknown",
    1: "gen1",
    2: "gen2",
    3: "gen3",
    4: "gen4",
    5: "trekker",
    6: "badcam",
}
CAMERA_MASK = 7
ROAD_NAME_BIT = 8


def default_arrow() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "app.map-making.local"
        / "profiles"
        / "discord"
        / "arrow"
        / "92b6110c-b604-47d6-937a-8b5b78453678.arrow"
    )


def default_metadata() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "VISION"
        / "automation"
        / "work"
        / "all-locations.valid.metadata.bin"
    )


def default_badcam_bitset() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "VISION"
        / "automation"
        / "work"
        / "badcam-location-ids.bitset"
    )


def default_mma_db() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "app.map-making.local"
        / "profiles"
        / "discord"
        / "mma.db"
    )


def decode_metadata(byte: int) -> tuple[str, str]:
    camera = CAMERA_CODES.get(int(byte) & CAMERA_MASK, "unknown")
    road = "has road name" if int(byte) & ROAD_NAME_BIT else "no road name"
    return camera, road


def location_is_badcam(bitset: bytes | memoryview, location_id: int) -> bool:
    if location_id < 0:
        return False
    index = location_id // 8
    if index >= len(bitset):
        return False
    return bool(bitset[index] & (1 << (location_id % 8)))


def camera_for_location(byte: int, location_id: int, bitset: bytes | memoryview | None) -> tuple[str, str]:
    camera, road = decode_metadata(byte)
    if bitset is not None and location_is_badcam(bitset, location_id):
        camera = "badcam"
    return camera, road


def load_country_tags(database: Path | None = None, *, tags: dict | None = None) -> dict[int, str]:
    if tags is not None:
        source = tags
    else:
        database = Path(database) if database is not None else default_mma_db()
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT tags FROM maps WHERE name = ? LIMIT 1",
                ("ALL LOCATIONS",),
            ).fetchone()
        finally:
            connection.close()
        if not row or not row[0]:
            raise FileNotFoundError("all_locations_tags")
        source = json.loads(row[0])
    names = {}
    for key, value in source.items():
        name = value.get("name") if isinstance(value, dict) else None
        if not isinstance(name, str) or not name.strip():
            continue
        names[int(key)] = canonicalize_country(name.strip())
    return names


def country_from_tags(tag_ids, names: dict[int, str]) -> str:
    if not tag_ids:
        return ""
    for tag in tag_ids:
        country = names.get(int(tag))
        if country:
            return country
    return ""


def _format_number(value) -> str:
    number = float(value)
    if number == 0:
        return "0"
    return format(number, ".15g")


def format_indexer_line(
    *,
    location_id: int,
    lat: float,
    lng: float,
    heading: float,
    pitch: float,
    zoom: float,
    pano_id: str,
    country: str,
    camera_generation: str,
    road_name_state: str,
) -> str:
    return "\t".join(
        (
            MAP_ID,
            str(int(location_id)),
            _format_number(lat),
            _format_number(lng),
            _format_number(heading),
            _format_number(pitch),
            _format_number(zoom),
            pano_id,
            canonicalize_country(country),
            camera_generation or "unknown",
            road_name_state or "no road name",
        )
    ) + "\n"


class ShardWriter:
    def __init__(
        self,
        destination: Path,
        *,
        key_prefix: str,
        rows_per_shard: int,
        shard_id_start: int,
        on_close=None,
    ):
        self.destination = Path(destination)
        self.destination.mkdir(parents=True, exist_ok=True)
        self.key_prefix = key_prefix
        self.rows_per_shard = rows_per_shard
        self.shard_id = int(shard_id_start)
        self.on_close = on_close
        self.shards = []
        self.written = 0
        self.handle = None
        self.digest = None
        self.shard_rows = 0
        self.first = None
        self.last = None
        self.path = None

    def write(self, line: str) -> dict | None:
        if self.handle is None:
            self.path = self.destination / f"shard-{self.shard_id:05d}.tsv"
            self.handle = self.path.open("w", encoding="utf-8", newline="\n")
            self.digest = hashlib.sha256()
            self.shard_id += 1
        text = line if line.endswith("\n") else line + "\n"
        self.handle.write(text)
        self.digest.update(text.encode("utf-8"))
        pano = text.rstrip("\n\r").split("\t")[7]
        if self.first is None:
            self.first = pano
        self.last = pano
        self.shard_rows += 1
        self.written += 1
        if self.shard_rows >= self.rows_per_shard:
            return self.close_shard()
        return None

    def close_shard(self) -> dict | None:
        if self.handle is None:
            return None
        self.handle.close()
        shard = {
            "shardId": self.shard_id - 1,
            "file": self.path.name,
            "key": f"{self.key_prefix}/{self.path.name}",
            "rows": self.shard_rows,
            "bytes": self.path.stat().st_size,
            "sha256": self.digest.hexdigest(),
            "rowStart": self.written - self.shard_rows,
            "firstPanoId": self.first,
            "lastPanoId": self.last,
        }
        self.shards.append(shard)
        closed_path = self.path
        self.handle = None
        self.digest = None
        self.shard_rows = 0
        self.first = self.last = None
        self.path = None
        if self.on_close is not None:
            self.on_close(shard, closed_path)
        return shard

    def finish(self, extra: dict | None = None) -> dict:
        self.close_shard()
        manifest = {
            "version": 1,
            "contract": CONTRACT,
            "lane": "scene",
            "r2Prefix": self.key_prefix,
            "rowsPerShard": self.rows_per_shard,
            "totalRows": self.written,
            "rowStart": 0,
            "shards": self.shards,
            "rights": RIGHTS,
            "embeddingsCopied": False,
            "imageryCopied": False,
            "sourceFiles": ["all-locations-arrow", "camera-generation-metadata"],
            "liveSourceRewritten": False,
        }
        if extra:
            manifest.update(extra)
        write_json(self.destination / "manifest.json", manifest)
        return manifest


def iter_arrow_lines(
    arrow: Path,
    metadata: Path,
    countries: dict[int, str],
    *,
    badcam_bitset: Path | None = None,
    limit: int | None = None,
):
    import pyarrow.ipc as ipc

    meta_file = Path(metadata).open("rb")
    bitset_file = None
    bitset = None
    try:
        meta = mmap.mmap(meta_file.fileno(), 0, access=mmap.ACCESS_READ)
        if badcam_bitset is not None and Path(badcam_bitset).is_file():
            bitset_file = Path(badcam_bitset).open("rb")
            bitset = mmap.mmap(bitset_file.fileno(), 0, access=mmap.ACCESS_READ)
    except ValueError:
        meta_file.close()
        if bitset_file is not None:
            bitset_file.close()
        raise
    written = 0
    row_index = 0
    try:
        with Path(arrow).open("rb") as handle:
            reader = ipc.RecordBatchFileReader(handle)
            for batch_index in range(reader.num_record_batches):
                batch = reader.get_batch(batch_index)
                ids = batch.column("id")
                latitudes = batch.column("lat")
                longitudes = batch.column("lng")
                headings = batch.column("heading")
                pitches = batch.column("pitch")
                zooms = batch.column("zoom")
                panos = batch.column("pano_id")
                tags = batch.column("tags")
                for index in range(batch.num_rows):
                    if limit is not None and written >= limit:
                        return
                    if row_index >= len(meta):
                        raise ValueError("metadata_shorter_than_arrow")
                    pano = panos[index].as_py()
                    row_index += 1
                    if not isinstance(pano, str) or not pano.strip():
                        continue
                    pano = pano.strip()
                    if "maps.googleapis.com" in pano or pano.startswith("http"):
                        continue
                    location_id = int(ids[index].as_py())
                    camera, road = camera_for_location(meta[row_index - 1], location_id, bitset)
                    line = format_indexer_line(
                        location_id=location_id,
                        lat=float(latitudes[index].as_py()),
                        lng=float(longitudes[index].as_py()),
                        heading=float(headings[index].as_py()),
                        pitch=float(pitches[index].as_py()),
                        zoom=float(zooms[index].as_py()),
                        pano_id=pano,
                        country=country_from_tags(tags[index].as_py() or [], countries),
                        camera_generation=camera,
                        road_name_state=road,
                    )
                    written += 1
                    yield line
    finally:
        meta.close()
        meta_file.close()
        if bitset is not None:
            bitset.close()
        if bitset_file is not None:
            bitset_file.close()


def upload_shard(shard: dict, local: Path, *, bucket: str) -> None:
    last_error = None
    for attempt in range(8):
        try:
            subprocess.run(
                [
                    "npx",
                    "--yes",
                    "wrangler",
                    "r2",
                    "object",
                    "put",
                    f"{bucket}/{shard['key']}",
                    "--file",
                    str(local.resolve()),
                    "--remote",
                ],
                check=True,
                cwd=str(Path(__file__).resolve().parents[1] / "deploy" / "cloudflare"),
                env={**os.environ, "CI": "true"},
            )
            return
        except subprocess.CalledProcessError as error:
            last_error = error
            time.sleep(min(90, 5 * (2 ** attempt)))
    raise last_error


def build_catalog(
    destination: Path,
    *,
    arrow: Path | None = None,
    metadata: Path | None = None,
    badcam_bitset: Path | None = None,
    tags: dict | None = None,
    lines=None,
    rows_per_shard: int = ROWS_PER_SHARD,
    shard_id_start: int = SHARD_ID_START,
    limit: int | None = None,
    upload: bool = False,
    keep_shards: bool = False,
    bucket: str = "vision-community",
) -> dict:
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    state_path = destination / "upload-state.json"
    uploaded = []
    if state_path.is_file():
        try:
            uploaded = list(json.loads(state_path.read_text(encoding="utf-8")).get("uploaded") or [])
        except json.JSONDecodeError:
            uploaded = []
    already = set(uploaded)

    def after_close(shard: dict, path: Path) -> None:
        if upload:
            if shard["key"] not in already:
                upload_shard(shard, path, bucket=bucket)
                uploaded.append(shard["key"])
                already.add(shard["key"])
                write_json(state_path, {"uploaded": uploaded, "bucket": bucket})
            with (destination / "shards.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(shard, sort_keys=True) + "\n")
        if upload and not keep_shards:
            path.unlink(missing_ok=True)
        if upload:
            print(
                json.dumps(
                    {
                        "shard": shard["file"],
                        "key": shard["key"],
                        "rows": shard["rows"],
                        "totalRows": writer.written,
                        "uploaded": len(uploaded),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    writer = ShardWriter(
        destination,
        key_prefix=KEY_PREFIX,
        rows_per_shard=rows_per_shard,
        shard_id_start=shard_id_start,
        on_close=after_close,
    )
    source = lines
    if source is None:
        countries = load_country_tags(tags=tags)
        source = iter_arrow_lines(
            Path(arrow) if arrow is not None else default_arrow(),
            Path(metadata) if metadata is not None else default_metadata(),
            countries,
            badcam_bitset=Path(badcam_bitset) if badcam_bitset is not None else default_badcam_bitset(),
            limit=limit,
        )
    for line in source:
        writer.write(line)
    return writer.finish({"normalizedRows": writer.written, "uploadedKeys": uploaded})


def catalog_sql(manifest: dict) -> str:
    return pose_catalog_insert_sql(manifest, lanes=("scene", "object"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "sql", "upload"))
    parser.add_argument("--to", type=Path, default=Path("community/.data/all-locations-full"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--arrow", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--badcam-bitset", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rows-per-shard", type=int, default=ROWS_PER_SHARD)
    parser.add_argument("--keep-shards", action="store_true")
    args = parser.parse_args()
    if args.command == "sql":
        manifest_path = args.manifest or (args.to / "manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(catalog_sql(manifest))
        return
    report = build_catalog(
        args.to,
        arrow=args.arrow,
        metadata=args.metadata,
        badcam_bitset=args.badcam_bitset,
        limit=args.limit,
        rows_per_shard=args.rows_per_shard,
        upload=args.command == "upload",
        keep_shards=args.keep_shards,
    )
    if args.command == "build":
        print(json.dumps({"ok": True, "rows": report.get("totalRows"), "shards": len(report.get("shards") or [])}, sort_keys=True))
        return
    print(json.dumps({"ok": True, "rows": report.get("totalRows"), "uploaded": len(report.get("uploadedKeys") or [])}, sort_keys=True))


if __name__ == "__main__":
    main()
