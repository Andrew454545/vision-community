"""Durable artifact store. R2 is the hosted sealed-segment copy.

The local filesystem remains the Python search backend. The Worker binds the
same bucket as INDEX. Scoped credentials must never be shipped to browsers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol


R2_BUCKET_NAME = "vision-community"
R2_BINDING = "INDEX"
FORBIDDEN_R2_BUCKETS = frozenset({"geonections-images"})


def assert_community_bucket(name: str) -> str:
    if name in FORBIDDEN_R2_BUCKETS:
        raise RuntimeError("refusing_unrelated_bucket")
    if name != R2_BUCKET_NAME:
        raise RuntimeError("unknown_r2_bucket")
    return name


def r2_public_status() -> dict:
    return {
        "provisioned": True,
        "bucket": R2_BUCKET_NAME,
        "binding": R2_BINDING,
        "publicAccess": False,
        "role": "sealed-segments",
    }


class ArtifactStore(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def backend(self) -> str: ...


class LocalArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if ".." in Path(key).parts or key.startswith("/"):
            raise ValueError("invalid_key")
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        meta = path.with_suffix(path.suffix + ".meta.json")
        meta.write_text(json.dumps({"contentType": content_type, "bytes": len(data)}), encoding="utf-8")

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def backend(self) -> str:
        return "local-disk"


class R2ArtifactStore:
    """Hosted sealed segments. Object I/O is the Worker INDEX binding, not this process."""

    def __init__(self, config: dict | None = None):
        self.bucket = assert_community_bucket((config or {}).get("bucket") or R2_BUCKET_NAME)

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        raise RuntimeError("r2_use_worker_binding")

    def get(self, key: str) -> bytes:
        raise RuntimeError("r2_use_worker_binding")

    def exists(self, key: str) -> bool:
        raise RuntimeError("r2_use_worker_binding")

    def backend(self) -> str:
        return "r2"
