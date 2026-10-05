"""Install the indexer programs used by the Terminal commands.

The scene program, the object program, and their model folders are not stored
in git. This downloads the published copy for this computer into the folders
the commands already look in. It does not write the live remainder queue, a
scheduled object list, or a shared CoreML cache.
"""

from __future__ import annotations

import argparse
import hashlib
from http.client import HTTPException
import json
import os
import platform
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .vision_index import LIVE_PATH_MARKERS, vision_support_root


RELEASE = "https://github.com/Andrew454545/vision-community/releases/download/mac-runtime-1"
MANIFEST_NAME = "runtime_manifest.json"


class BootstrapError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def manifest_path() -> Path:
    return Path(__file__).resolve().with_name(MANIFEST_NAME)


def load_manifest(path: Path | None = None) -> dict:
    payload = json.loads((path or manifest_path()).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise BootstrapError("invalid_runtime_manifest")
    return payload


def vision_root() -> Path:
    return vision_support_root()


def runtime_platform(system: str | None = None, machine: str | None = None) -> str:
    system_name = sys.platform if system is None else system
    machine_name = platform.machine() if machine is None else machine
    if system_name == "win32":
        system_name = "windows"
    elif system_name.startswith("linux"):
        system_name = "linux"
    elif system_name != "darwin":
        raise BootstrapError("unsupported_platform")
    machine_name = machine_name.lower()
    if machine_name in ("amd64", "x86_64"):
        arch = "x86_64"
    elif machine_name in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        raise BootstrapError("unsupported_platform")
    return f"{system_name}-{arch}"


def files_for_platform(manifest: dict, platform_name: str, *, lane: str = "all") -> list:
    if lane not in {"all", "scene", "object"}:
        raise BootstrapError("invalid_lane")
    chosen = []
    for entry in manifest["files"]:
        platforms = entry.get("platforms")
        if isinstance(platforms, list) and platform_name not in platforms:
            continue
        asset = str(entry.get("asset", ""))
        if lane == "scene" and (asset.startswith("object-") or asset.startswith("vision-object")):
            continue
        if lane == "object" and (asset.startswith("siglip-") or asset.startswith("mma-vision")):
            continue
        chosen.append(entry)
    has_scene = any(item.get("executable") and str(item.get("asset", "")).startswith("mma-vision") for item in chosen)
    has_object = any(item.get("executable") and str(item.get("asset", "")).startswith("vision-object") for item in chosen)
    if (lane in {"all", "scene"} and not has_scene) or (lane in {"all", "object"} and not has_object):
        raise BootstrapError("unsupported_platform")
    return chosen


def destination(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise BootstrapError("unsafe_runtime_path")
    parts = Path(relative).parts
    if any(part in ("", ".", "..") for part in parts):
        raise BootstrapError("unsafe_runtime_path")
    path = Path(root).joinpath(*parts)
    text = path.as_posix()
    for marker in LIVE_PATH_MARKERS:
        if marker in text:
            raise BootstrapError("refusing_live_vision_path")
    return path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _already_installed(path: Path, entry: dict) -> bool:
    if not path.is_file():
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    return size == int(entry["bytes"]) and file_sha256(path) == entry["sha256"]


def download_file(url: str, partial: Path, entry: dict) -> None:
    expected_size = entry.get("bytes")
    expected_sha = entry.get("sha256")
    if (type(expected_size) is not int or not 0 < expected_size <= 512 * 1024**2
            or not isinstance(expected_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha)):
        raise BootstrapError("invalid_runtime_manifest")
    if partial.is_symlink() or (partial.exists() and not partial.is_file()):
        raise BootstrapError("unsafe_runtime_path")
    partial.parent.mkdir(parents=True, exist_ok=True)
    size = partial.stat().st_size if partial.exists() else 0
    if size > expected_size:
        partial.unlink()
        raise BootstrapError("runtime_mismatch")
    if size == expected_size:
        if file_sha256(partial) != expected_sha:
            partial.unlink()
            raise BootstrapError("runtime_mismatch")
        return
    headers = {"User-Agent": "VISION-Community", "Accept-Encoding": "identity"}
    if size:
        headers["Range"] = f"bytes={size}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            status = getattr(response, "status", 200)
            response_headers = getattr(response, "headers", {})
            if response_headers.get("Content-Encoding", "identity").lower() != "identity":
                raise BootstrapError("runtime_download_failed")
            if status == 206:
                received_range = response_headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)", received_range)
                if (not match or int(match[1]) != size or int(match[3]) != expected_size
                        or not size <= int(match[2]) < expected_size):
                    # Retain the original prefix; never append an unverified offset.
                    raise BootstrapError("runtime_download_failed")
                response_limit = int(match[2]) - size + 1
                mode = "ab" if size else "wb"
            elif status == 200:
                # Some servers ignore Range. A complete response safely replaces
                # the partial download, rather than appending duplicate bytes.
                size, response_limit, mode = 0, expected_size, "wb"
            else:
                raise BootstrapError("runtime_download_failed")
            received = 0
            with partial.open(mode) as handle:
                while True:
                    chunk = response.read(min(1024 * 1024, response_limit - received + 1))
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > response_limit or size + len(chunk) > expected_size:
                        raise BootstrapError("runtime_mismatch")
                    handle.write(chunk)
                    size += len(chunk)
            if size < expected_size:
                raise BootstrapError("runtime_download_failed")
    except (OSError, urllib.error.URLError, HTTPException) as error:
        # The next retry/restart can use this bounded prefix. It is not installed
        # or executed until the complete immutable file passes its checksum.
        raise BootstrapError("runtime_download_failed") from error
    except BootstrapError as error:
        if error.code == "runtime_mismatch":
            partial.unlink(missing_ok=True)
        raise
    if file_sha256(partial) != expected_sha:
        partial.unlink(missing_ok=True)
        raise BootstrapError("runtime_mismatch")


def install_runtime(
    manifest: dict,
    root: Path,
    *,
    release: str = RELEASE,
    platform_name: str | None = None,
    lane: str = "all",
    progress=None,
) -> list[str]:
    actions = []
    entries = files_for_platform(manifest, platform_name or runtime_platform(), lane=lane)
    for number, entry in enumerate(entries, 1):
        if progress:
            progress(number, len(entries))
        path = destination(root, entry["path"])
        asset = entry["asset"]
        if _already_installed(path, entry):
            actions.append(f"present {asset}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".partial")
        print(f"Downloading {asset} ({int(entry['bytes']) // (1024 * 1024)} MB)", flush=True)
        download_file(f"{release.rstrip('/')}/{asset}", partial, entry)
        os.replace(partial, path)
        if entry.get("executable"):
            path.chmod(0o755)
        actions.append(f"installed {asset}")
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and verify the private VISION runtime.")
    parser.add_argument("--lane", choices=("scene", "object", "all"), default="all")
    args = parser.parse_args()
    try:
        actions = install_runtime(load_manifest(), vision_root(), lane=args.lane)
    except BootstrapError as error:
        print(error.code, file=sys.stderr)
        return 1
    installed = [line for line in actions if line.startswith("installed ")]
    if installed:
        print(f"Ready. Installed {len(installed)} files.")
    else:
        print("Ready. The indexer programs are already on this computer.")
    print("Open VISION to check whether contributions are available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
