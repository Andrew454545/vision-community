"""Checksummed, versioned segments with atomic registry publication.

Mirrors VISION's sealed-segment idea: a segment is immutable once published,
every file has a SHA-256, and a registry load fails closed on mismatch or
duplicate source ids. Pose metadata is sealed beside embeddings so search can
emit map-making.app JSON without keeping imagery. Capacity is 500,000.
"""

from __future__ import annotations

import hashlib
import json
import mmap
import os
import struct
from pathlib import Path

from .features import MODEL_ID, MODEL_VERSION, record_bytes


SEGMENT_FORMAT_VERSION = 1
REGISTRY_VERSION = 1
DEFAULT_CAPACITY = 500_000
POSE_STRUCT = struct.Struct("<Qddddd64s16s32s16s")  # 176 bytes


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


def _pad(value: str, size: int) -> bytes:
    raw = (value or "").encode("utf-8")[:size]
    return raw + b"\x00" * (size - len(raw))


def pack_pose(record: dict) -> bytes:
    return POSE_STRUCT.pack(
        int(record["locationId"]),
        float(record.get("lat") or 0),
        float(record.get("lng") or record.get("lon") or 0),
        float(record.get("heading") or 0),
        float(record.get("pitch") or 0),
        float(record.get("zoom") or 0),
        _pad(str(record.get("panoId") or record.get("assetId") or ""), 64),
        _pad(str(record.get("capture") or ""), 16),
        _pad(str(record.get("country") or ""), 32),
        _pad(str(record.get("cameraGeneration") or ""), 16),
    )


def unpack_pose(blob: bytes) -> dict:
    location_id, lat, lng, heading, pitch, zoom, pano, capture, country, camera = POSE_STRUCT.unpack(blob)
    def clean(raw: bytes) -> str:
        return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
    return {
        "locationId": location_id,
        "lat": lat,
        "lng": lng,
        "heading": heading,
        "pitch": pitch,
        "zoom": zoom,
        "panoId": clean(pano),
        "capture": clean(capture),
        "country": clean(country),
        "cameraGeneration": clean(camera),
    }


class SegmentRegistry:
    def __init__(self, root: Path, *, capacity: int = DEFAULT_CAPACITY):
        if capacity < 1:
            raise ValueError("capacity")
        self.root = Path(root)
        self.capacity = capacity
        self.segments_dir = self.root / "segments"
        self.registry_path = self.root / "registry.json"
        self.segments_dir.mkdir(parents=True, exist_ok=True)
        self._document = None
        if not self.registry_path.exists():
            self._write_registry({"version": REGISTRY_VERSION, "model": MODEL_ID, "sources": []})

    def _write_registry(self, document: dict) -> None:
        payload = json.dumps(document, sort_keys=True, indent=2).encode("utf-8")
        _atomic_write(self.registry_path, payload)
        self._document = document

    def load(self, *, verify: bool = True) -> dict:
        if self._document is not None and not verify:
            return self._document
        document = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if document.get("version") != REGISTRY_VERSION:
            raise SegmentError("unsupported_registry_version")
        seen = set()
        for source in document.get("sources") or []:
            source_id = source.get("id")
            if not source_id or source_id in seen:
                raise SegmentError("duplicate_or_missing_source_id")
            seen.add(source_id)
            if not verify:
                continue
            folder = self.root / source["path"]
            manifest_path = folder / "segment.json"
            if _sha256_file(manifest_path) != source["sha256"]:
                raise SegmentError("checksum_mismatch:segment.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if _sha256_file(folder / "embeddings.bin") != manifest["embeddingsSha256"]:
                raise SegmentError("checksum_mismatch:embeddings.bin")
            if _sha256_file(folder / "ids.bin") != manifest["idsSha256"]:
                raise SegmentError("checksum_mismatch:ids.bin")
            poses_path = folder / "poses.bin"
            if manifest.get("posesSha256"):
                if not poses_path.is_file() or _sha256_file(poses_path) != manifest["posesSha256"]:
                    raise SegmentError("checksum_mismatch:poses.bin")
            if manifest.get("id") != source_id:
                raise SegmentError("manifest_id_mismatch")
        self._document = document
        return document

    def publish(self, *, lane: str, location_ids: list[int], embeddings: bytes, poses: list[dict] | None = None) -> dict:
        if lane not in {"scene", "object"}:
            raise SegmentError("invalid_lane")
        width = record_bytes(lane)
        if len(location_ids) == 0 or len(location_ids) > self.capacity:
            raise SegmentError("invalid_count")
        if len(embeddings) != len(location_ids) * width:
            raise SegmentError("embedding_length")
        if len(set(location_ids)) != len(location_ids):
            raise SegmentError("duplicate_location")
        if poses is not None and len(poses) != len(location_ids):
            raise SegmentError("pose_length")
        existing = self.load(verify=False)
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
        poses_sha = None
        if poses is not None:
            poses_blob = b"".join(pack_pose(record) for record in poses)
            _atomic_write(folder / "poses.bin", poses_blob)
            poses_sha = hashlib.sha256(poses_blob).hexdigest()
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
            "posesSha256": poses_sha,
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

    def iter_records(self, lane: str | None = None, *, verify: bool = False):
        document = self.load(verify=verify)
        for source in document["sources"]:
            if lane is not None and source["lane"] != lane:
                continue
            folder = self.root / source["path"]
            manifest = json.loads((folder / "segment.json").read_text(encoding="utf-8"))
            width = manifest["recordBytes"]
            count = manifest["count"]
            emb_path = folder / "embeddings.bin"
            ids_path = folder / "ids.bin"
            poses_path = folder / "poses.bin"
            with emb_path.open("rb") as emb_handle, ids_path.open("rb") as ids_handle:
                embeddings = mmap.mmap(emb_handle.fileno(), 0, access=mmap.ACCESS_READ)
                ids = mmap.mmap(ids_handle.fileno(), 0, access=mmap.ACCESS_READ)
                poses = None
                pose_handle = None
                try:
                    if poses_path.is_file():
                        pose_handle = poses_path.open("rb")
                        poses = mmap.mmap(pose_handle.fileno(), 0, access=mmap.ACCESS_READ)
                    for index in range(count):
                        location_id = int.from_bytes(ids[index * 8 : index * 8 + 8], "little")
                        vector = bytes(embeddings[index * width : (index + 1) * width])
                        record = {
                            "locationId": location_id,
                            "lane": source["lane"],
                            "embedding": vector,
                            "segmentId": source["id"],
                        }
                        if poses is not None:
                            record["pose"] = unpack_pose(
                                bytes(poses[index * POSE_STRUCT.size : (index + 1) * POSE_STRUCT.size])
                            )
                        yield record
                finally:
                    embeddings.close()
                    ids.close()
                    if poses is not None:
                        poses.close()
                    if pose_handle is not None:
                        pose_handle.close()
