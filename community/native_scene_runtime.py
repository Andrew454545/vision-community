"""Prepare a private native scene runtime from independently pinned operator inputs.

This packages an identity, not an inference approval. It performs no downloads,
model execution, account changes or deployment.
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import stat
from pathlib import Path

from . import native_scene_search as native
from .search_snapshot import HEX, encoded, file_digest, pinned_read, write_file

LAYOUT = {"version": 4, "viewsPerLocation": 4, "bytesPerLocation": 3080,
          "completeViewMask": 15, "feature": "four-view-index"}


def asset(root: Path, name: str, pin: dict) -> Path:
    if (not isinstance(pin, dict) or type(pin.get("bytes")) is not int
            or not 0 < pin["bytes"] <= 512 * 1024**2
            or not isinstance(pin.get("sha256"), str) or not HEX.fullmatch(pin["sha256"])):
        raise native.NativeSearchError("invalid_packaging_pin")
    source = native.relative_file(root, name)
    if source.stat().st_size != pin["bytes"] or file_digest(source) != pin["sha256"]:
        raise native.NativeSearchError("packaging_asset_changed")
    return source


def copy_asset(source: Path, target: Path, pin: dict):
    before = source.stat()
    with source.open("rb") as original, target.open("xb") as destination:
        shutil.copyfileobj(original, destination, 1024 * 1024)
        destination.flush()
        os.fsync(destination.fileno())
    os.chmod(target, stat.S_IMODE(before.st_mode) & 0o777)
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    if target.stat().st_size != pin["bytes"] or file_digest(target) != pin["sha256"]:
        raise native.NativeSearchError("packaging_copy_changed")


def prepare_runtime(build: Path, build_sha256: str, binary_dir: Path,
                    model_pins: Path, model_pins_sha256: str, models: Path,
                    countries: Path, countries_sha256: str, destination: Path,
                    policy_id: str, query_modes: list[str]) -> dict:
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Use a new runtime directory; preserve the existing runtime")
    modes = {mode for mode, _ in native.MODES.values()}
    if (not isinstance(policy_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", policy_id)
            or not isinstance(query_modes, list) or not query_modes
            or any(mode not in modes for mode in query_modes)
            or len(set(query_modes)) != len(query_modes)):
        raise native.NativeSearchError("invalid_packaging_configuration")
    build = native.plain_path(build)
    model_pins = native.plain_path(model_pins)
    countries = native.plain_path(countries)
    binary_dir = native.plain_path(binary_dir, directory=True)
    models = native.plain_path(models, directory=True)
    resolved = destination.resolve()
    if any(root == resolved or root in resolved.parents for root in (binary_dir, models)):
        raise native.NativeSearchError("packaging_output_overlaps_input")
    receipt = native.strict_json(pinned_read(build, build_sha256, 1024 * 1024))
    if (not isinstance(receipt, dict) or receipt.get("status") != "BUILD_AND_SYNTHETIC_TESTS_PASSED"
            or receipt.get("layout") != LAYOUT or receipt.get("productionQualified") is not False
            or not isinstance(receipt.get("features"), str)
            or "four-view-index" not in receipt["features"].split(",")
            or not set(receipt["features"].split(",")) <= {"four-view-index", "coreml"}
            or not isinstance(receipt.get("binary"), dict)
            or not isinstance(receipt.get("runtimeDLLs"), list)
            or not isinstance(receipt.get("sourceFiles"), list)):
        raise native.NativeSearchError("invalid_scene_build_receipt")
    country_sources = [item for item in receipt["sourceFiles"] if isinstance(item, dict)
                       and isinstance(item.get("path"), str)
                       and item["path"].replace("\\", "/") == "app/src/data/country-names.txt"]
    if (len(country_sources) != 1 or country_sources[0].get("sha256") != countries_sha256
            or type(country_sources[0].get("bytes")) is not int
            or countries.stat().st_size != country_sources[0]["bytes"]
            or file_digest(countries) != countries_sha256):
        raise native.NativeSearchError("compiled_countries_mismatch")
    sources, pins = {}, {}
    for item in [receipt["binary"], *receipt["runtimeDLLs"]]:
        if (not isinstance(item, dict) or not isinstance(item.get("file"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", item["file"])
                or item["file"] in ("runtime.json", "countries.txt", "models", ".", "..")
                or item["file"] in sources):
            raise native.NativeSearchError("invalid_scene_dependency")
        name = item["file"]
        pin = {k: item.get(k) for k in ("bytes", "sha256")}
        sources[name], pins[name] = asset(binary_dir, name, pin), pin
    model_document = native.strict_json(pinned_read(model_pins, model_pins_sha256, 1024 * 1024))
    if (not isinstance(model_document, dict) or not isinstance(model_document.get("files"), list)
            or len(model_document["files"]) != len(native.MODEL_FILES)):
        raise native.NativeSearchError("invalid_scene_model_inventory")
    names = set()
    for item in model_document["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise native.NativeSearchError("invalid_scene_model_inventory")
        name = item["path"].replace("\\", "/").split("/")[-1]
        if name not in native.MODEL_FILES or name in names:
            raise native.NativeSearchError("invalid_scene_model_inventory")
        names.add(name)
        pin = {k: item.get(k) for k in ("bytes", "sha256")}
        sources["models/" + name], pins["models/" + name] = asset(models, name, pin), pin
    sources["countries.txt"] = countries
    pins["countries.txt"] = {"bytes": countries.stat().st_size, "sha256": countries_sha256}
    if len(pins) > 16 or sum(pin["bytes"] for pin in pins.values()) > 1536 * 1024**2:
        raise native.NativeSearchError("runtime_size_limit")
    package = Path(native.__file__).parent
    config = {"version": 1, "contractVersion": native.CONTRACT, "nativeLayout": 4,
              "policyId": policy_id, "adapterSha256": file_digest(Path(native.__file__)),
              "pythonVersion": platform.python_version(),
              "sourceFiles": {name: {"bytes": (package/name).stat().st_size,
                                     "sha256": file_digest(package/name)} for name in native.SOURCE_FILES},
              "executable": receipt["binary"]["file"], "queryModes": query_modes, "files": pins}
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        (destination / "models").mkdir(mode=0o700)
        for name, source in sources.items():
            copy_asset(source, destination / name, pins[name])
        # Manifest last: partial copies cannot be started as a completed runtime.
        runtime_pin = write_file(destination / "runtime.json", encoded(config))
    except Exception:
        write_file(destination / "failure-report.json", encoded({"ready": False, "error": "runtime_packaging_failed"}))
        raise
    return {"ready": True, "runtimeSha256": runtime_pin["sha256"],
            "runtimeBytes": runtime_pin["bytes"], "payloadFiles": len(pins),
            "payloadBytes": sum(pin["bytes"] for pin in pins.values()),
            "nativeBuildSHA256": build_sha256, "modelPinsSHA256": model_pins_sha256,
            "identityOnly": True, "productionQualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("build", "binary-dir", "model-pins", "models", "countries", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("build-sha256", "model-pins-sha256", "countries-sha256", "policy-id"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--query-mode", action="append", required=True,
                        choices=sorted({mode for mode, _ in native.MODES.values()}))
    args = parser.parse_args()
    try:
        result = prepare_runtime(args.build, args.build_sha256, args.binary_dir, args.model_pins,
                                 args.model_pins_sha256, args.models, args.countries,
                                 args.countries_sha256, args.out, args.policy_id, args.query_mode)
    except Exception as error:
        code = str(error) if isinstance(error, native.NativeSearchError) else "runtime_packaging_failed"
        print(encoded({"ready": False, "error": code}).decode(), end="")
        return 1
    print(encoded(result).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
