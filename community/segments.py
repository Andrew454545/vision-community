"""Checksummed, versioned segments with atomic registry publication.

Mirrors VISION's sealed-segment idea: a segment is immutable once published,
every file has a SHA-256, and a registry load fails closed on mismatch or
duplicate source ids. Community segment capacity is 500,000 locations. Tests
may use a smaller capacity without changing the format.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .features import MODEL_ID, MODEL_VERSION, record_bytes


SEGMENT_FORMAT_VERSION = 1
REGISTRY_VERSION = 1
DEFAULT_CAPACITY = 500_000


class SegmentError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


class SegmentRegistry:
    def __init__(self, root: Path, *, capacity: int = DEFAULT_CAPACITY):
        if capacity < 1:
            raise ValueError("capacity")
        self.root = Path(root)
        self.capacity = capacity
        self.segments_dir = self.root / "segments"
        self.registry_path = self.root / "registry.json"
        self.segments_dir.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._write_registry({"version": REGISTRY_VERSION, "model": MODEL_ID, "sources": []})

    def _write_registry(self, document: dict) -> None:
        payload = json.dumps(document, sort_keys=True, indent=2).encode("utf-8")
        _atomic_write(self.registry_path, payload)

    def load(self) -> dict:
        document = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if document.get("version") != REGISTRY_VERSION:
            raise SegmentError("unsupported_registry_version")
        seen = set()
        for source in document.get("sources") or []:
            source_id = source.get("id")
            if not source_id or source_id in seen:
                raise SegmentError("duplicate_or_missing_source_id")
            seen.add(source_id)
            folder = self.root / source["path"]
            manifest_path = folder / "segment.json"
            if _sha256_file(manifest_path) != source["sha256"]:
                raise SegmentError("checksum_mismatch:segment.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if _sha256_file(folder / "embeddings.bin") != manifest["embeddingsSha256"]:
                raise SegmentError("checksum_mismatch:embeddings.bin")
            if _sha256_file(folder / "ids.bin") != manifest["idsSha256"]:
                raise SegmentError("checksum_mismatch:ids.bin")
            if manifest.get("id") != source_id:
                raise SegmentError("manifest_id_mismatch")
        return document

    def publish(self, *, lane: str, location_ids: list[int], embeddings: bytes) -> dict:
        if lane not in {"scene", "object"}:
            raise SegmentError("invalid_lane")
        width = record_bytes(lane)
        if len(location_ids) == 0 or len(location_ids) > self.capacity:
            raise SegmentError("invalid_count")
        if len(embeddings) != len(location_ids) * width:
            raise SegmentError("embedding_length")
        if len(set(location_ids)) != len(location_ids):
            raise SegmentError("duplicate_location")
        existing = self.load()
        already = set()
        for source in existing["sources"]:
            folder = self.root / source["path"]
            ids = (folder / "ids.bin").read_bytes()
            for offset in range(0, len(ids), 8):
                already.add(int.from_bytes(ids[offset : offset + 8], "little"))
        if already.intersection(location_ids):
            raise SegmentError("location_already_published")

        serial = len(existing["sources"]) + 1
        source_id = f"{lane}-{serial:06d}"
        rel = f"segments/{source_id}"
        folder = self.root / rel
        folder.mkdir(parents=True, exist_ok=False)
        ids_blob = b"".join(int(location_id).to_bytes(8, "little") for location_id in location_ids)
        _atomic_write(folder / "embeddings.bin", embeddings)
        _atomic_write(folder / "ids.bin", ids_blob)
        manifest = {
            "version": SEGMENT_FORMAT_VERSION,
            "id": source_id,
            "lane": lane,
            "model": MODEL_ID,
            "modelVersion": MODEL_VERSION,
            "count": len(location_ids),
            "capacity": self.capacity,
            "recordBytes": width,
            "completed": True,
            "embeddingsSha256": hashlib.sha256(embeddings).hexdigest(),
            "idsSha256": hashlib.sha256(ids_blob).hexdigest(),
        }
        _atomic_write(folder / "segment.json", json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8"))
        manifest_sha = _sha256_file(folder / "segment.json")
        sources = list(existing["sources"])
        sources.append(
            {
                "id": source_id,
                "path": rel,
                "lane": lane,
                "count": len(location_ids),
                "sha256": manifest_sha,
            }
        )
        self._write_registry({**existing, "sources": sources})
        return {"id": source_id, "sha256": manifest_sha, "count": len(location_ids)}

    def iter_records(self, lane: str | None = None):
        document = self.load()
        for source in document["sources"]:
            if lane is not None and source["lane"] != lane:
                continue
            folder = self.root / source["path"]
            manifest = json.loads((folder / "segment.json").read_text(encoding="utf-8"))
            width = manifest["recordBytes"]
            embeddings = (folder / "embeddings.bin").read_bytes()
            ids = (folder / "ids.bin").read_bytes()
            count = manifest["count"]
            for index in range(count):
                location_id = int.from_bytes(ids[index * 8 : index * 8 + 8], "little")
                vector = embeddings[index * width : (index + 1) * width]
                yield {
                    "locationId": location_id,
                    "lane": source["lane"],
                    "embedding": vector,
                    "segmentId": source["id"],
                }
