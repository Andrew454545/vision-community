"""Durable artifact store. R2 is an interface, not a default backend.

The local filesystem is used until the owner approves bucket creation.
Scoped credentials must never be shipped to browsers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol


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
    """Refuses to run until the owner explicitly creates a bucket and passes config."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        raise RuntimeError("r2_bucket_not_created")

    def get(self, key: str) -> bytes:
        raise RuntimeError("r2_bucket_not_created")

    def exists(self, key: str) -> bool:
        raise RuntimeError("r2_bucket_not_created")

    def backend(self) -> str:
        return "r2-unprovisioned"
