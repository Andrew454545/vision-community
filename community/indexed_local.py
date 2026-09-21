"""Add the local VISION-indexed pose catalog to Community. Metadata only.

The 20.96M already-indexed scene locations live on this computer as TSV pose
rows plus SigLIP embeddings. Community never copies those embeddings or any
imagery. Volunteers still extract community-visual-v1 from Street View. The
shared queue just gets the same panorama IDs and poses so that work is not
invented from scratch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from .all_locations_tail import pose_catalog_insert_sql, split_shards, write_json
from .rank import canonicalize_country


KEY_PREFIX = "catalog/vision-indexed-v1"
CONTRACT = "vision-community-pose-catalog-v1"
EXPECTED_ROWS = 20_955_444
SEALED_NO_ROAD = 6_500_000
SHARD_ID_START = -5000
MAP_ID = "vision-indexed"
RIGHTS = "metadata-only-no-imagery"


def vision_support() -> Path:
    return Path.home() / "Library" / "Application Support" / "VISION"


def _normalize_parts(parts: list[str]) -> list[str] | None:
    if not parts or not any(part.strip() for part in parts):
        return None
    if len(parts) == 11:
        if parts[0] == "map_id" and parts[7] == "pano_id":
            return None
        country = canonicalize_country(parts[8])
        return [
            parts[0] or MAP_ID,
            parts[1],
            parts[2],
            parts[3],
            parts[4],
            parts[5],
            parts[6],
            parts[7].strip(),
            country,
            parts[9],
            parts[10],
        ]
    if len(parts) == 9:
        pano = parts[7].strip()
        if not pano:
            return None
        return [
            MAP_ID,
            parts[1] or parts[0],
            parts[2],
            parts[3],
            parts[4],
            parts[5],
            parts[6],
            pano,
            canonicalize_country(parts[8]),
            "",
            "",
        ]
    return None


def normalize_indexer_line(text: str) -> str | None:
    text = text.rstrip("\n\r")
    if not text.strip():
        return None
    parts = _normalize_parts(text.split("\t"))
    if parts is None or not parts[7]:
        return None
    return "\t".join(parts) + "\n"


def remainder_sealed_tsvs(support: Path) -> list[Path]:
    registry = support / "vision-four-view-remainder-indexes" / "current.json"
    if not registry.is_file():
        raise FileNotFoundError(registry)
    document = json.loads(registry.read_text(encoding="utf-8"))
    sources = document.get("sources") if isinstance(document, dict) else None
    if not isinstance(sources, list):
        raise ValueError("invalid_remainder_registry")
    chosen = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        if int(source.get("endLocation") or 0) > SEALED_NO_ROAD:
            continue
        path = Path(source.get("sourceTsv") or "")
        if not path.is_file():
            raise FileNotFoundError(path)
        chosen.append((int(source.get("startLocation") or 0), path))
    chosen.sort()
    return [path for _start, path in chosen]


def indexed_local_sources(support: Path | None = None) -> list[Path]:
    support = Path(support) if support is not None else vision_support()
    legacy = support / "legacy-four-view" / "all-locations.accepted.tsv"
    one_view = (
        support
        / "vision-app-indexes"
        / "snapshots"
        / "checkpoint-000007961872-badcam-1d838be1992e-cacheless-v1"
        / "locations.tsv"
    )
    missing = [path for path in (legacy, one_view) if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing[0])
    return [legacy, one_view, *remainder_sealed_tsvs(support)]


def iter_normalized_lines(paths: list[Path]):
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                normalized = normalize_indexer_line(line)
                if normalized is not None:
                    yield normalized


def build_catalog(destination: Path, *, sources: list[Path] | None = None) -> dict:
    """Write pose-only shards. Never reads embeddings, masks, or imagery."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    paths = sources if sources is not None else indexed_local_sources()
    staging = destination / "_normalized.tsv"
    written = 0
    with staging.open("w", encoding="utf-8", newline="\n") as handle:
        for line in iter_normalized_lines(paths):
            handle.write(line)
            written += 1
    manifest = split_shards(
        staging,
        destination,
        key_prefix=KEY_PREFIX,
        lane="scene",
        shard_id_start=SHARD_ID_START,
    )
    manifest["contract"] = CONTRACT
    manifest["rights"] = RIGHTS
    manifest["embeddingsCopied"] = False
    manifest["imageryCopied"] = False
    manifest["sourceFiles"] = ["legacy-four-view", "one-view-checkpoint", "four-view-no-road-sealed"]
    manifest["normalizedRows"] = written
    write_json(destination / "manifest.json", manifest)
    staging.unlink(missing_ok=True)
    return manifest


def catalog_sql(manifest: dict) -> str:
    return pose_catalog_insert_sql(manifest, lanes=("scene", "object"))


def upload_shards(manifest: dict, source_dir: Path, *, bucket: str = "vision-community") -> dict:
    source_dir = Path(source_dir)
    uploaded = 0
    for shard in manifest.get("shards") or []:
        local = (source_dir / shard["file"]).resolve()
        key = shard["key"]
        subprocess.run(
            ["npx", "--yes", "wrangler", "r2", "object", "put", f"{bucket}/{key}", "--file", str(local), "--remote"],
            check=True,
            cwd=str(Path(__file__).resolve().parents[1] / "deploy" / "cloudflare"),
        )
        uploaded += 1
    return {"uploaded": uploaded, "bucket": bucket, "prefix": KEY_PREFIX}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "sql", "upload"))
    parser.add_argument("--to", type=Path, default=Path("community/.data/indexed-local"))
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        report = build_catalog(args.to)
        print(json.dumps({"ok": True, "rows": report.get("totalRows"), "shards": len(report.get("shards") or [])}, sort_keys=True))
        return
    manifest_path = args.manifest or (args.to / "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if args.command == "sql":
        print(catalog_sql(manifest))
        return
    report = upload_shards(manifest, manifest_path.parent)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
