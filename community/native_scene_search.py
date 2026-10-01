"""Private native VISION scene adapter for operator-sealed contributions.

This is an engine, not an approval policy. Pin the runtime and contribution
snapshot independently. It never creates accounts, spends credits, imports the
reference corpus or distributes indexes. The public gateway owns settlement.
"""
from __future__ import annotations

import argparse
import hmac
import json
import math
import os
import platform
import re
import stat
import subprocess
import tempfile
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .features import VIEW_DIRECTION_OFFSETS
from .four_view import BYTES_PER_LOCATION, SHARD_LOCATIONS
from .search_snapshot import (HEX, MAX_INVENTORY_BYTES, SnapshotError, bounded_read,
                             digest, encoded, file_digest, pinned_read, verify_snapshot,
                             write_file)

CONTRACT = 2
MAX_REQUEST = 8 * 1024 * 1024 + 64 * 1024  # Gateway's bounded JSON plus contract envelope.
MAX_RESPONSE = 4 * 1024 * 1024
MAX_NATIVE_OUTPUT = 32 * 1024 * 1024
MAX_CANDIDATES = 10_000  # Native topK limit; exhaustion never silently truncates.
MODES = {0: ("contrastive50", .8842786), 25: ("title25Contrastive50", .83858335),
         50: ("title50Contrastive50", .6531793), 75: ("title75Contrastive50", .36236486),
         100: ("textOnly", .01)}
MODEL_FILES = ("vision_model.onnx", "vision_model_fp32.onnx", "text_model.onnx", "tokenizer.json")
SOURCE_FILES = ("__init__.py", "native_scene_search.py", "search_snapshot.py", "scene_quality.py", "four_view.py", "features.py")
GENS = {"unknown", "badcam", "gen1", "gen2", "gen3", "gen4", "trekker"}
QUERY_KEYS = {"lane", "prompt", "examples", "excluded", "queryName", "descriptionWeight",
              "viewDirection", "resultCount", "maxPerCountry", "filters", "objectConfidence",
              "rejectRoadNames", "minimumGlobalLocation"}


class NativeSearchError(ValueError):
    """Fixed public error code; native paths/prompts/stderr stay private."""


def plain_path(path: Path, *, directory=False) -> Path:
    path = Path(path).absolute()
    for current in [*reversed(path.parents), path]:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise NativeSearchError("linked_engine_path")
    info = path.stat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise NativeSearchError("invalid_engine_path")
    return path


def relative_file(root: Path, name: str) -> Path:
    if (not isinstance(name, str) or len(name) > 200
            or not re.fullmatch(r"[A-Za-z0-9_.\-/]+", name)
            or any(p in ("", ".", "..") for p in name.split("/"))):
        raise NativeSearchError("invalid_runtime_file")
    return plain_path(root / name)


def strict_json(raw: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise NativeSearchError("duplicate_json_field")
            result[key] = value
        return result
    def invalid(_):
        raise NativeSearchError("nonfinite_json")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def query_bytes(raw: bytes) -> bytes:
    """Preserve the gateway's exact JSON.stringify spelling/order of its query.

    Re-encoding parsed floats in Python would change exponent spellings and
    break the gateway fingerprint for valid coordinates such as 1e-7.
    Duplicate fields and nonfinite values are rejected separately by strict_json.
    """
    source = raw.decode("utf-8")
    decoder = json.JSONDecoder()
    position = source.index("{") + 1
    while True:
        while source[position].isspace() or source[position] == ",":
            position += 1
        if source[position] == "}":
            break
        key, position = decoder.raw_decode(source, position)
        while source[position].isspace():
            position += 1
        if source[position] != ":":
            raise NativeSearchError("invalid_request")
        position += 1
        while source[position].isspace():
            position += 1
        start = position
        _, position = decoder.raw_decode(source, position)
        if key == "query":
            return source[start:position].encode("utf-8")
    raise NativeSearchError("invalid_request")


def model_identity(root: Path) -> str:
    return "|".join(f"{name}:{(root/name).stat().st_size}:{int((root/name).stat().st_mtime)}"
                    for name in MODEL_FILES)


def fnv_file(path: Path) -> str:
    value = 0xcbf29ce484222325
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            for byte in chunk:
                value = ((value ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    return f"fnv1a64:{value:016x}"


def text(value, maximum, required=False):
    if (not isinstance(value, str) or len(value) > maximum or (required and not value.strip())
            or any(ord(c) < 32 for c in value)):
        raise NativeSearchError("invalid_search_query")
    return value


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_pose(pose, countries, *, member=False):
    if (not isinstance(pose, dict) or any(not finite(pose.get(k)) for k in ("lat", "lng", "heading", "pitch", "zoom"))
            or abs(pose["lat"]) > 90 or abs(pose["lng"]) > 180 or abs(pose["pitch"]) > 90
            or not 0 <= pose["zoom"] <= 5):
        raise NativeSearchError("invalid_scene_pose")
    pano = text(pose.get("panoId"), 1000, True)
    if any(c in pano for c in "\t\r\n"):
        raise NativeSearchError("invalid_scene_pose")
    if member and (pose.get("country") not in countries or pose.get("cameraGeneration") not in GENS):
        raise NativeSearchError("invalid_scene_pose")


class NativeSceneRuntime:
    """Independently pinned native executable/model identity shared by services."""
    def __init__(self, runtime: Path, runtime_sha256: str):
        self.runtime_path = plain_path(runtime)
        self.runtime_root = self.runtime_path.parent
        self.runtime_sha256 = runtime_sha256
        config = strict_json(pinned_read(self.runtime_path, runtime_sha256, 1024 * 1024))
        if (not isinstance(config, dict) or config.get("version") != 1
                or config.get("contractVersion") != CONTRACT or config.get("nativeLayout") != 4
                or config.get("adapterSha256") != file_digest(Path(__file__))
                or config.get("pythonVersion") != platform.python_version()
                or not isinstance(config.get("sourceFiles"), dict) or set(config["sourceFiles"]) != set(SOURCE_FILES)
                or not isinstance(config.get("policyId"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", config["policyId"])
                or not isinstance(config.get("queryModes"), list) or not config["queryModes"]
                or len(set(config["queryModes"])) != len(config["queryModes"])
                or any(mode not in {v[0] for v in MODES.values()} for mode in config["queryModes"])
                or not isinstance(config.get("files"), dict) or not 6 <= len(config["files"]) <= 16):
            raise NativeSearchError("invalid_native_runtime")
        self.config = config
        self.binary = relative_file(self.runtime_root, config.get("executable"))
        required = {config["executable"], "countries.txt", *(f"models/{n}" for n in MODEL_FILES)}
        if not required.issubset(config["files"]):
            raise NativeSearchError("incomplete_native_runtime")
        self.models = plain_path(self.runtime_root / "models", directory=True)
        self.verify_runtime()
        raw_countries = bounded_read(self.runtime_root / "countries.txt", 128 * 1024).decode("utf-8")
        self.countries = set(raw_countries.splitlines())
        if not self.countries or "" in self.countries:
            raise NativeSearchError("invalid_native_countries")

    def verify_runtime(self):
        if digest(bounded_read(plain_path(self.runtime_path), 1024 * 1024)) != self.runtime_sha256:
            raise NativeSearchError("runtime_changed")
        if self.config["adapterSha256"] != file_digest(Path(__file__)):
            raise NativeSearchError("adapter_changed")
        for name, pin in self.config["sourceFiles"].items():
            path = plain_path(Path(__file__).parent / name)
            if (not isinstance(pin, dict) or type(pin.get("bytes")) is not int or not 0 <= pin["bytes"] <= 1024*1024
                    or path.stat().st_size != pin["bytes"] or file_digest(path) != pin.get("sha256")):
                raise NativeSearchError("engine_source_changed")
        total = 0
        for name, pin in self.config["files"].items():
            if (not isinstance(pin, dict) or type(pin.get("bytes")) is not int
                    or not 0 < pin["bytes"] <= 512 * 1024**2
                    or not isinstance(pin.get("sha256"), str) or not HEX.fullmatch(pin["sha256"])):
                raise NativeSearchError("invalid_runtime_file_pin")
            total += pin["bytes"]
            if total > 1536 * 1024**2:
                raise NativeSearchError("runtime_size_limit")
            path = relative_file(self.runtime_root, name)
            if path.stat().st_size != pin["bytes"] or file_digest(path) != pin["sha256"]:
                raise NativeSearchError("runtime_file_changed")
        expected = set(self.config["files"]) | {self.runtime_path.name}
        expected_dirs = {str(p).replace("\\", "/") for name in self.config["files"]
                         for p in Path(name).parents if str(p) != "."}
        actual = set()
        for current, dirs, files in os.walk(self.runtime_root, followlinks=False):
            for name in dirs:
                path = plain_path(Path(current) / name, directory=True)
                if path.relative_to(self.runtime_root).as_posix() not in expected_dirs:
                    raise NativeSearchError("unpinned_runtime_directory")
            for name in files:
                actual.add((Path(current) / name).relative_to(self.runtime_root).as_posix())
                if len(actual) > 17:
                    raise NativeSearchError("unpinned_runtime_file")
        if actual != expected:
            raise NativeSearchError("unpinned_runtime_file")


class NativeSceneEngine(NativeSceneRuntime):
    def __init__(self, runtime: Path, runtime_sha256: str, snapshot: Path, snapshot_sha256: str,
                 work: Path, *, timeout=110):
        if type(timeout) not in (int, float) or not 0 < timeout <= 110:
            raise NativeSearchError("invalid_native_timeout")
        super().__init__(runtime, runtime_sha256)
        self.snapshot_sha256 = snapshot_sha256
        self.snapshot = plain_path(snapshot, directory=True)
        self.work = plain_path(work, directory=True)
        if any(self.work == root or root in self.work.parents for root in (self.runtime_root, self.snapshot)):
            raise NativeSearchError("engine_work_overlaps_input")
        self.timeout = timeout
        self.busy = threading.BoundedSemaphore(1)
        self.snapshot_manifest = verify_snapshot(self.snapshot, snapshot_sha256)
        for name in ("snapshot.json", "members.json", "scene-records.i8"):
            plain_path(self.snapshot / name)
        self.members = strict_json(bounded_read(self.snapshot / "members.json", MAX_INVENTORY_BYTES))
        for member in self.members:
            if not member["locationId"] < 2**53 or type(member["sourceIndex"]) is not int:
                raise NativeSearchError("invalid_scene_member")
            validate_pose(member.get("pose"), self.countries, member=True)
        self.index = self.work / "index"
        self.prepare_index()

    def prepare_index(self):
        # Entirely new immutable mount. Never copy an existing native manifest or
        # reference corpus. Ordinals and records come only from the pinned bundle.
        self.index.mkdir(mode=0o700, exist_ok=False)
        try:
            source = self.index / "locations.tsv"
            lines = []
            for member in self.members:
                p = member["pose"]
                fields = ["community", member["locationId"], *(p[k] for k in ("lat", "lng", "heading", "pitch", "zoom")),
                          p["panoId"], p["country"], p["cameraGeneration"], "false"]
                lines.append("\t".join(str(v) for v in fields) + "\n")
            write_file(source, "".join(lines).encode("utf-8"))
            pins = {"locations.tsv": {"bytes": source.stat().st_size, "sha256": file_digest(source)}}
            with (self.snapshot / "scene-records.i8").open("rb") as original:
                for shard, start in enumerate(range(0, len(self.members), SHARD_LOCATIONS)):
                    count = min(SHARD_LOCATIONS, len(self.members) - start)
                    name = f"shard-{shard:06}.i8"
                    with (self.index / name).open("xb") as target:
                        remaining = count * BYTES_PER_LOCATION
                        while remaining:
                            chunk = original.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise NativeSearchError("short_snapshot_payload")
                            target.write(chunk)
                            remaining -= len(chunk)
                        target.flush()
                        os.fsync(target.fileno())
                    pins[name] = {"bytes": (self.index / name).stat().st_size, "sha256": file_digest(self.index / name)}
                    mask = f"shard-{shard:06}.mask"
                    pins[mask] = write_file(self.index / mask, bytes([15]) * count)
                if original.read(1):
                    raise NativeSearchError("extra_snapshot_payload")
            manifest = {"version": 4, "runId": self.snapshot_sha256,
                        "modelDir": str(self.models), "sourceTsv": str(source), "sourceBytes": source.stat().st_size,
                        "sourcePrefixHash": fnv_file(source), "inputFingerprint": self.runtime_sha256,
                        "modelIdentity": model_identity(self.models), "totalLocations": len(self.members),
                        "indexedLocations": len(self.members), "embeddingDimension": 768, "viewsPerLocation": 4,
                        "storage": "four quarter-turn scaled int8 vectors; little-endian binary16 scale",
                        "bytesPerLocation": BYTES_PER_LOCATION, "shardLocations": SHARD_LOCATIONS,
                        "completed": True, "updatedAtUnixMs": 0}
            pins["manifest.json"] = write_file(self.index / "manifest.json", encoded(manifest))
            verify_snapshot(self.snapshot, self.snapshot_sha256)
            self.verify_runtime()
            self.mount = {"version": 1, "runtimeSha256": self.runtime_sha256,
                          "snapshotSha256": self.snapshot_sha256, "files": pins}
            write_file(self.index / "mount.json", encoded(self.mount))  # Complete marker last.
        except Exception:
            write_file(self.index / "failure-report.json", encoded({"ready": False, "error": "native_mount_failed"}))
            raise

    def verify_mount(self):
        if strict_json(bounded_read(plain_path(self.index / "mount.json"), 128 * 1024)) != self.mount:
            raise NativeSearchError("native_mount_changed")
        if set(p.name for p in self.index.iterdir()) != {*self.mount["files"], "mount.json"}:
            raise NativeSearchError("native_mount_changed")
        for name, pin in self.mount["files"].items():
            path = plain_path(self.index / name)
            if path.stat().st_size != pin["bytes"] or file_digest(path) != pin["sha256"]:
                raise NativeSearchError("native_mount_changed")
        if model_identity(self.models) != strict_json(bounded_read(self.index / "manifest.json", 128*1024))["modelIdentity"]:
            raise NativeSearchError("native_model_metadata_changed")

    def validate_request(self, request, raw_query=None):
        if (not isinstance(request, dict) or set(request) != {"contractVersion", "policyId", "runtimeSha256",
                                                             "snapshotSha256", "requestSha256", "query"}
                or request.get("contractVersion") != CONTRACT or request.get("policyId") != self.config["policyId"]
                or request.get("runtimeSha256") != self.runtime_sha256
                or request.get("snapshotSha256") != self.snapshot_sha256
                or not isinstance(request.get("requestSha256"), str) or not HEX.fullmatch(request["requestSha256"])):
            raise NativeSearchError("search_identity_mismatch")
        q = request["query"]
        if not isinstance(q, dict) or set(q) != QUERY_KEYS or q.get("lane") != "scene":
            raise NativeSearchError("unsupported_search_lane")
        # Hash the original normalized gateway field order, before any conversion.
        raw = raw_query if raw_query is not None else json.dumps(q, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if strict_json(raw) != q:
            raise NativeSearchError("search_request_mismatch")
        if digest(raw) != request["requestSha256"]:
            raise NativeSearchError("search_request_mismatch")
        prompt, name = text(q["prompt"], 8000), text(q["queryName"], 200, True)
        if (type(q["descriptionWeight"]) is not int or q["descriptionWeight"] not in MODES
                or q["viewDirection"] not in VIEW_DIRECTION_OFFSETS or type(q["rejectRoadNames"]) is not bool
                or type(q["resultCount"]) is not int or not 1 <= q["resultCount"] <= 10_000
                or type(q["maxPerCountry"]) is not int or not 1 <= q["maxPerCountry"] <= 10_000
                or (q["minimumGlobalLocation"] is not None
                    and (type(q["minimumGlobalLocation"]) is not int or not 0 <= q["minimumGlobalLocation"] < 2**53))):
            raise NativeSearchError("invalid_search_query")
        mode, minimum = MODES[q["descriptionWeight"]]
        if mode not in self.config["queryModes"]:
            raise NativeSearchError("unsupported_query_mode")
        if q["rejectRoadNames"]:
            raise NativeSearchError("road_authority_unavailable")
        if not isinstance(q["examples"], list) or len(q["examples"]) > 4:
            raise NativeSearchError("invalid_search_query")
        for pose in q["examples"]:
            validate_pose(pose, self.countries)
        if not prompt.strip() and not q["examples"]:
            raise NativeSearchError("invalid_search_query")
        if (mode == "textOnly" and (not prompt.strip() or q["examples"])) or (mode != "textOnly" and not q["examples"]):
            raise NativeSearchError("invalid_search_query")
        if not isinstance(q["excluded"], list) or len(q["excluded"]) > 10_000:
            raise NativeSearchError("invalid_search_query")
        for point in q["excluded"]:
            if (not isinstance(point, dict) or not finite(point.get("lat")) or not finite(point.get("lng"))
                    or abs(point["lat"]) > 90 or abs(point["lng"]) > 180
                    or not isinstance(point.get("panoId", ""), str)):
                raise NativeSearchError("invalid_search_query")
        filters = q["filters"]
        if (not isinstance(filters, dict) or set(filters) != {"mode", "countries", "generations"}
                or filters["mode"] not in ("all", "include", "exclude")
                or not isinstance(filters["countries"], list) or len(filters["countries"]) > 300
                or any(c not in self.countries for c in filters["countries"])
                or len(set(filters["countries"])) != len(filters["countries"])
                or (filters["mode"] == "all" and filters["countries"])
                or (filters["mode"] == "include" and not filters["countries"])
                or not isinstance(filters["generations"], list) or len(filters["generations"]) > 6
                or any(g not in GENS - {"unknown"} for g in filters["generations"])
                or len(set(filters["generations"])) != len(filters["generations"])):
            raise NativeSearchError("invalid_search_query")
        definition = {"name": name, "query": prompt or f"visual examples for {name}", "mode": mode,
                      "minSimilarity": minimum, "examples": [{k: p[k] for k in ("panoId", "heading", "pitch", "zoom")} for p in q["examples"]],
                      "cameraGenerations": filters["generations"],
                      "includeCountries": filters["countries"] if filters["mode"] == "include" else [],
                      "excludeCountries": filters["countries"] if filters["mode"] == "exclude" else [],
                      "rejectRoadNames": False, "viewOffsets": list(VIEW_DIRECTION_OFFSETS[q["viewDirection"]])}
        return definition

    def search(self, request, *, raw_query=None):
        definition = self.validate_request(request, raw_query)
        if not self.busy.acquire(blocking=False):
            raise NativeSearchError("search_engine_busy")
        try:
            self.verify_runtime()
            self.verify_mount()
            verify_snapshot(self.snapshot, self.snapshot_sha256)
            with tempfile.TemporaryDirectory(prefix="query-", dir=self.work) as temporary:
                job = Path(temporary)
                os.chmod(job, 0o700)
                budget = min(MAX_CANDIDATES, len(self.members))
                native_input = {"runId": request["requestSha256"], "queries": [definition], "topK": budget,
                                "chunkSize": 1024, "concurrency": 1, "resultPruneMeters": 0}
                write_file(job / "input.json", encoded(native_input))
                command = [str(self.binary), "search-four-view-index", "--input", str(job / "input.json"),
                           "--model-dir", str(self.models), "--locations-tsv", str(self.index / "locations.tsv"),
                           "--index-dir", str(self.index), "--profile-cache-dir", str(job / "profiles"),
                           "--output", str(job / "output.json")]
                run_native(command, job, self.timeout)
                output = strict_json(bounded_read(plain_path(job / "output.json"), MAX_NATIVE_OUTPUT))
                self.verify_runtime()
                self.verify_mount()
                verify_snapshot(self.snapshot, self.snapshot_sha256)
                hits = self.select_hits(request["query"], definition, output, budget)
                response = {k: v for k, v in request.items() if k != "query"}
                response.update(processedLocations=len(self.members), hits=hits)
                if len(encoded(response)) > MAX_RESPONSE:
                    raise NativeSearchError("search_response_limit")
                return response
        except Exception as failure:
            # Query scratch (including text/model caches and native stderr) is
            # removed on both paths. Retain only a fixed-code, no-prompt report.
            code = str(failure) if isinstance(failure, NativeSearchError) else "native_search_failed"
            # A repeated outage must not create an unlimited collection of files.
            # Keep the first report for each fixed code; never overwrite it. Raw
            # query evidence belongs in a deliberate private diagnostic study.
            if not re.fullmatch(r"[a-z0-9_]{1,80}", code):
                code = "native_search_failed"
            try:
                write_file(self.work / f"failure-{code}.json", encoded({"success": False, "error": code}))
            except FileExistsError:
                pass
            raise NativeSearchError(code) from None
        finally:
            self.busy.release()

    def select_hits(self, query, definition, output, budget):
        if (not isinstance(output, dict) or output.get("version") != 4 or output.get("completed") is not True
                or output.get("totalLocations") != len(self.members) or output.get("nextLocationIndex") != len(self.members)
                or any(output.get(k) != 0 for k in ("fetchErrors", "inferenceErrors", "incompleteLocations"))
                or not isinstance(output.get("queries"), list) or len(output["queries"]) != 1):
            raise NativeSearchError("incomplete_native_search")
        result = output["queries"][0]
        if (any(result.get(k) != definition[k] for k in ("name", "query", "mode"))
                or not isinstance(result.get("hits"), list) or len(result["hits"]) > budget):
            raise NativeSearchError("invalid_native_search")
        accepted, seen, panos, counts = [], set(), set(), Counter()
        prior = None
        for hit in result["hits"]:
            ordinal, score, view = hit.get("locationIndex"), hit.get("similarity"), hit.get("viewOffset")
            if (type(ordinal) is not int or not 0 <= ordinal < len(self.members) or ordinal in seen
                    or not finite(score) or not definition["minSimilarity"] <= score <= 1
                    or type(view) is not int or view not in definition["viewOffsets"]
                    or (prior is not None and (-score, ordinal) < prior)):
                raise NativeSearchError("invalid_native_search")
            seen.add(ordinal)
            prior = (-score, ordinal)
            member, native = self.members[ordinal], hit.get("location")
            pose = member["pose"]
            if (not isinstance(native, dict) or any(native.get(k) != pose[k] for k in ("panoId", "country", "cameraGeneration"))
                    or any(not finite(native.get(k)) or round(native[k], 7) != round(pose[k], 7)
                           for k in ("lat", "lng", "heading", "pitch", "zoom"))):
                raise NativeSearchError("native_pose_mismatch")
            filters = query["filters"]
            if ((filters["mode"] == "include" and pose["country"] not in filters["countries"])
                    or (filters["mode"] == "exclude" and pose["country"] in filters["countries"])
                    or (filters["generations"] and pose["cameraGeneration"] not in filters["generations"])):
                raise NativeSearchError("native_filter_mismatch")
            if (len(accepted) >= query["resultCount"] or pose["panoId"] in panos
                    or (query["minimumGlobalLocation"] is not None and ordinal < query["minimumGlobalLocation"])
                    or any(p.get("panoId") == pose["panoId"] or distance(p, pose) < 25 for p in query["excluded"])
                    or counts[pose["country"]] >= query["maxPerCountry"]
                    or any(distance(self.members[h["sourceIndex"]]["pose"], pose) < 100 for h in accepted)):
                continue
            accepted.append({"locationId": member["locationId"], "outputSha256": member["outputSha256"],
                             "sourceIndex": ordinal, "score": score, "viewOffset": view})
            panos.add(pose["panoId"])
            counts[pose["country"]] += 1
        if len(accepted) < query["resultCount"] and len(result["hits"]) == budget and budget < len(self.members):
            raise NativeSearchError("search_candidate_budget_exceeded")
        return accepted


def distance(a, b):
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(math.radians(b["lng"]-a["lng"])/2)**2
    return 12742000 * math.asin(min(1, math.sqrt(value)))


def run_native(command, job: Path, timeout: float):
    # No shell and no inherited credentials/provider overrides. On Windows keep
    # the window hidden; the executable's adjacent, pinned DLLs remain available.
    environment = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TMP", "TEMP", "PATH") if k in os.environ}
    for key in ("RAYON_NUM_THREADS", "VISION_ORT_THREADS", "OMP_NUM_THREADS", "ORT_NUM_THREADS"):
        environment[key] = "1"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (job / "stdout.log").open("xb") as stdout, (job / "stderr.log").open("xb") as stderr:
        child = subprocess.Popen(command, cwd=job, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=stdout, stderr=stderr, creationflags=creationflags)
        deadline = time.monotonic() + timeout
        try:
            while child.poll() is None:
                if time.monotonic() >= deadline:
                    raise NativeSearchError("native_search_timeout")
                for name in ("stdout.log", "stderr.log", "output.json", "output.tmp"):
                    path = job / name
                    if path.exists() and path.stat().st_size > (MAX_NATIVE_OUTPUT if name.startswith("output") else 1024*1024):
                        raise NativeSearchError("native_output_limit")
                time.sleep(.05)
            if child.returncode:
                raise NativeSearchError("native_search_failed")
            for name in ("stdout.log", "stderr.log", "output.json", "output.tmp"):
                path = job / name
                if path.exists() and path.stat().st_size > (MAX_NATIVE_OUTPUT if name.startswith("output") else 1024*1024):
                    raise NativeSearchError("native_output_limit")
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()


def discard_small_body(handler):
    """Drain a small rejected request so Windows delivers the error response.

    Closing with unread request bytes can reset the connection before 401/404
    arrives. Never drain ambiguous framing or a large untrusted body.
    """
    lengths = handler.headers.get_all('Content-Length', [])
    if (len(lengths) != 1 or handler.headers.get('Transfer-Encoding') is not None
            or not re.fullmatch(r'[0-9]{1,5}', lengths[0]) or int(lengths[0]) > 65536):
        return
    handler.connection.settimeout(.2)
    try:
        handler.rfile.read(int(lengths[0]))
    except OSError:
        pass
    finally:
        handler.connection.settimeout(5)


def make_server(engine, secret: str, *, port=0):
    if not isinstance(secret, str) or len(secret) < 32 or any(ord(c) < 33 or ord(c) > 126 for c in secret):
        raise NativeSearchError("private_engine_secret_required")
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *_):
            pass  # Never log authorization, prompts, query maps or result poses.

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def reply(self, status, document):
            raw = encoded(document)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + secret).encode()):
                discard_small_body(self)
                self.reply(401, {"error": "unauthorized"})
                return
            if self.path != "/search":
                discard_small_body(self)
                self.reply(404, {"error": "not_found"})
                return
            lengths = self.headers.get_all("Content-Length", [])
            if (len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0])
                    or not 0 < int(lengths[0]) <= MAX_REQUEST or self.headers.get("Transfer-Encoding")
                    or self.headers.get("Content-Type", "").split(";")[0] != "application/json"):
                self.reply(400, {"error": "invalid_request"})
                return
            try:
                raw = self.rfile.read(int(lengths[0]))
                if len(raw) != int(lengths[0]):
                    raise NativeSearchError("invalid_request")
                request = strict_json(raw)
                response = engine.search(request, raw_query=query_bytes(raw))
                self.reply(200, response)
            except (OSError, ValueError, KeyError, TypeError, SnapshotError):
                self.reply(503, {"error": "search_unavailable"})
    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 8
        # Bound even authenticated slow/header-reading connections. The engine
        # independently permits only one active native process per instance.
        def __init__(self, *args):
            self.slots = threading.BoundedSemaphore(8)
            super().__init__(*args)
        def process_request(self, request, address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, address)
            except Exception:
                self.slots.release()
                raise
        def process_request_thread(self, request, address):
            try:
                super().process_request_thread(request, address)
            finally:
                self.slots.release()
    return Server(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--runtime-sha256", required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--work", type=Path, required=True, help="New private mount directory")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    args.work.mkdir(mode=0o700, parents=True, exist_ok=False)
    server = None
    try:
        engine = NativeSceneEngine(args.runtime, args.runtime_sha256, args.snapshot, args.snapshot_sha256, args.work)
        server = make_server(engine, os.environ.get("VISION_SEARCH_ENGINE_SECRET", ""), port=args.port)
        print(json.dumps({"ready": True, "bind": "127.0.0.1", "port": server.server_port,
                          "locations": len(engine.members), "scope": "private-native-scene-adapter"}), flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception:
        print(json.dumps({"ready": False, "error": "private_engine_start_failed"}), flush=True)
        raise SystemExit(1)
    finally:
        if server is not None:
            server.server_close()


if __name__ == "__main__":
    main()
