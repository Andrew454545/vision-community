"""Install the indexer programs used by the Terminal commands.

The scene program, the object program, and their model folders are not stored
in git. This downloads the published copy for this computer into the folders
the commands already look in. It does not write the live remainder queue, a
scheduled object list, or a shared CoreML cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
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


def files_for_platform(manifest: dict, platform_name: str) -> list:
    chosen = []
    for entry in manifest["files"]:
        platforms = entry.get("platforms")
        if isinstance(platforms, list) and platform_name not in platforms:
            continue
        chosen.append(entry)
    has_scene = any(item.get("executable") and str(item.get("asset", "")).startswith("mma-vision") for item in chosen)
    has_object = any(item.get("executable") and str(item.get("asset", "")).startswith("vision-object") for item in chosen)
    if not has_scene or not has_object:
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
    request = urllib.request.Request(url, headers={"User-Agent": "VISION-Community"})
    digest = hashlib.sha256()
    size = 0
    partial.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    except (OSError, urllib.error.URLError) as error:
        partial.unlink(missing_ok=True)
        raise BootstrapError("runtime_download_failed") from error
    if size != int(entry["bytes"]) or digest.hexdigest() != entry["sha256"]:
        partial.unlink(missing_ok=True)
        raise BootstrapError("runtime_mismatch")


def install_runtime(
    manifest: dict,
    root: Path,
    *,
    release: str = RELEASE,
    platform_name: str | None = None,
) -> list[str]:
    actions = []
    for entry in files_for_platform(manifest, platform_name or runtime_platform()):
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


def ensure_requirements() -> None:
    try:
        import PIL  # noqa: F401
    except ImportError:
        import subprocess

        requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements)],
            check=False,
        )
        if completed.returncode != 0:
            raise BootstrapError("install_pillow")


def main() -> int:
    try:
        ensure_requirements()
        actions = install_runtime(load_manifest(), vision_root())
    except BootstrapError as error:
        print(error.code, file=sys.stderr)
        return 1
    installed = [line for line in actions if line.startswith("installed ")]
    if installed:
        print(f"Ready. Installed {len(installed)} files.")
    else:
        print("Ready. The indexer programs are already on this computer.")
    print("Next: open the site, get an account, then paste the scene or object command in this folder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
