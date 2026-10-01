"""Index and search places with the same four-view program VISION.app uses.

The browser cannot run that model. This command shells out to
`mma-vision index-four-views`: the same 11-column TSV, the same SigLIP model
directory, and the same version-4 index (4 views, 3080 bytes per place).

It will not write the live VISION remainder queue, checkpoint, or index.
Point VISION_FOUR_VIEW_BINARY and VISION_MODEL_DIR at the program and the
siglip-b16-224-canonical folder on computers that do not already have them.

The command keeps going until the queue is empty or you press Control-C.
A clean pause in the VISION indexer is resumed from its checkpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path

from .contribute import (
    DEFAULT_URL,
    RETRYABLE_CODES,
    RETRY_STATUSES,
    CommunityClient,
    ContributeError,
    default_session_path,
    load_session,
    save_session,
)
from .four_view import (
    BYTES_PER_LOCATION,
    LAYOUT_VERSION,
    SHARD_LOCATIONS,
    VISION_FOUR_VIEW_MODEL,
    VIEWS_PER_LOCATION,
    valid_four_view_record,
)
from .mma import RESULT_PRUNE_METERS, SCENE_MODEL_NAME, build_map, dump_map, search_location_extra
from .pano import CLI_LEASE_CAP
from .prompt import snap_description_weight
from .rank import cap_by_country, clamp_max_per_country, clamp_result_count, canonicalize_country, exclude_used


REQUIRED_MODEL_FILES = (
    "vision_model.onnx",
    "vision_model_fp32.onnx",
    "text_model.onnx",
    "tokenizer.json",
)
LIVE_PATH_MARKERS = (
    "four-view-remainder-work",
    "all-locations-four-view-no-road-remainder-badcam-v1",
    "four-view-published-segments",
    "no-road-after-one-view-prefix.badcam.tsv",
    "object-indexes",
    "object-runtime-legacy-mixed",
    "scheduled-sources",
    "object-hybrid-v1/coreml-cache",
)


def vision_support_root() -> Path:
    override = os.environ.get("VISION_COMMUNITY_RUNTIME_ROOT")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "VISION"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/VISION"
    return Path.home() / ".local/share/VISION"


def community_support_root() -> Path:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "vision-community"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/vision-community"
    return Path.home() / ".local/share/vision-community"


def program_name(stem: str) -> str:
    if sys.platform == "win32" and not stem.endswith(".exe"):
        return f"{stem}.exe"
    return stem
# Keep the measured batch shape fixed. One inference thread is the conservative
# baseline, not a guarantee of identical bytes across machines or live images.
# Pace changes scheduling priority only; extra threads require calibration.
PACE = {
    "slow": {"threads": 1, "nice": 19, "concurrency": 8, "chunk": 16, "batch": 16, "sessions": 1, "duty": 100, "thermal": 2},
    "medium": {"threads": 1, "nice": 8, "concurrency": 8, "chunk": 16, "batch": 16, "sessions": 1, "duty": 100, "thermal": 2},
    "max": {"threads": 1, "nice": 0, "concurrency": 8, "chunk": 16, "batch": 16, "sessions": 1, "duty": 100, "thermal": 2},
}
THREAD_ENVIRONMENT_KEYS = ("RAYON_NUM_THREADS", "VISION_ORT_THREADS", "OMP_NUM_THREADS", "ORT_NUM_THREADS")
SCENE_GRAPH_MESSAGE = "[vision] scene image graph: vision_model_fp32.onnx (explicit input)"


def require_scene_execution(stderr: str, inference_threads: int) -> None:
    """Reject old runtimes that silently ignore the requested graph or CPU pool."""
    lines = stderr.splitlines()
    pool = f"[vision] ONNX Runtime global threads: {inference_threads}, spinning disabled"
    if SCENE_GRAPH_MESSAGE not in lines or pool not in lines:
        raise VisionIndexError("vision_scene_runtime_update_required")


INDEX_TIMEOUT_SECONDS = 2 * 60 * 60
MAX_INDEX_FAILURES = 3
MAX_NO_PROGRESS = 5
MAX_QUEUE_FAILURES = 5
# Keep ownership for a bounded outer retry so the same verified checkpoint can
# resume. These errors never authorize uploading incomplete records.
RETRYABLE_NATIVE_CODES = frozenset({
    "vision_binary_failed", "vision_binary_timeout", "vision_no_progress", "vision_retry_limit",
})


class VisionIndexError(RuntimeError):
    def __init__(self, code: str, status: int = 0):
        super().__init__(code)
        self.code = code
        self.status = status


def default_binary() -> Path:
    override = os.environ.get("VISION_FOUR_VIEW_BINARY")
    if override:
        return Path(override)
    # The CPU fp32 build is the measured Community candidate. Live-image trials
    # showed differences; parity with Andrew's reference is not established.
    return vision_support_root() / "bin" / program_name("mma-vision")


def default_model_dir() -> Path:
    override = os.environ.get("VISION_MODEL_DIR")
    if override:
        return Path(override)
    return vision_support_root() / "models/siglip-b16-224-canonical"


def default_work_dir() -> Path:
    override = os.environ.get("VISION_COMMUNITY_FOUR_VIEW_WORK")
    if override:
        return Path(override)
    return community_support_root() / "four-view"


def assert_not_live_vision_path(path: Path) -> None:
    text = str(Path(path).expanduser())
    try:
        text = str(Path(path).expanduser().resolve())
    except OSError:
        pass
    for marker in LIVE_PATH_MARKERS:
        if marker in text:
            raise VisionIndexError("refusing_live_vision_path")


def parse_json_stdout(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise VisionIndexError("vision_binary_failed")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise VisionIndexError("vision_binary_failed") from error
    if not isinstance(payload, dict):
        raise VisionIndexError("vision_binary_failed")
    return payload


def require_model_dir(path: Path) -> None:
    assert_not_live_vision_path(path)
    missing = [name for name in REQUIRED_MODEL_FILES if not (path / name).is_file()]
    if missing:
        raise VisionIndexError("vision_model_missing")


def require_layout(layout: dict) -> None:
    if (
        layout.get("version") != LAYOUT_VERSION
        or layout.get("bytesPerLocation") != BYTES_PER_LOCATION
        or layout.get("viewsPerLocation") != VIEWS_PER_LOCATION
        or layout.get("feature") != "four-view-index"
    ):
        raise VisionIndexError("wrong_vision_layout")


def format_tsv_number(value) -> str:
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise VisionIndexError("invalid_location")
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return format(number, ".16g")


def tsv_field(value: str) -> str:
    text = str(value or "")
    if "\t" in text or "\n" in text or "\r" in text:
        raise VisionIndexError("invalid_location")
    return text


def location_tsv_line(item: dict) -> str:
    try:
        fields = [
            tsv_field(item.get("mapId") or "vision-community"),
            format_tsv_number(item.get("sourceLocationId") or item["locationId"]),
            format_tsv_number(item["lat"]),
            format_tsv_number(item.get("lng") if item.get("lng") is not None else item["lon"]),
            format_tsv_number(item.get("heading") or 0),
            format_tsv_number(item.get("pitch") or 0),
            format_tsv_number(item.get("zoom") or 0),
            tsv_field(item.get("panoId") or item.get("assetId")),
            tsv_field(item.get("country") or ""),
            tsv_field(item.get("cameraGeneration") or ""),
            tsv_field(item.get("roadName") or "no road name"),
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise VisionIndexError("invalid_location") from error
    if not fields[7]:
        raise VisionIndexError("invalid_location")
    return "\t".join(fields)


def write_locations_tsv(items: list[dict], path: Path) -> int:
    assert_not_live_vision_path(path)
    lines = [location_tsv_line(item) for item in items]
    if not lines:
        raise VisionIndexError("no_locations")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def iter_location_lines(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 8 and parts[0] == "map_id" and parts[7] == "pano_id":
                continue
            if len(parts) != 11:
                raise VisionIndexError("invalid_location_tsv")
            yield line


def count_locations(path: Path) -> int:
    total = 0
    for _line in iter_location_lines(path):
        total += 1
    if total < 1:
        raise VisionIndexError("no_locations")
    return total


def four_view_input(*, total: int, pace: str, run_id: str) -> dict:
    settings = PACE[pace]
    return {
        "version": 1,
        "runId": run_id,
        "totalLocations": total,
        "topK": 1,
        "resultPruneMeters": RESULT_PRUNE_METERS,
        "chunkSize": settings["chunk"],
        "concurrency": settings["concurrency"],
        "checkpointEvery": min(2000, max(1, total)),
        "shardLocations": SHARD_LOCATIONS,
        "queries": [
            {
                "name": "same-way",
                "query": "a street view panorama",
                "mode": "contrastive50",
                "minSimilarity": 0.99,
                "examples": [],
            }
        ],
        "embeddingBatchSize": settings["batch"],
        "imageEncoderSessions": settings["sessions"],
        "dutyCyclePercent": settings["duty"],
        # The current Windows binary exposes a macOS-only temperature check.
        # Null avoids its permanent retry loop; OS/hardware protection remains.
        "thermalStateLimit": None if sys.platform == "win32" else settings["thermal"],
        "seedResults": None,
        # The native default CPU graph is int8. Unknown JSON fields are ignored
        # by older binaries, so require_scene_execution also checks execution.
        "sceneFp32": True,
    }


SCENE_QUERY_MODES = {
    0: ("contrastive50", 0.8842786),
    25: ("title25Contrastive50", 0.83858335),
    50: ("title50Contrastive50", 0.6531793),
    75: ("title75Contrastive50", 0.36236486),
    100: ("textOnly", 0.01),
}


def scene_candidate_count(result_count: int, max_per_country: int, *, excluding: bool) -> int:
    limit = clamp_result_count(result_count)
    per_country = clamp_max_per_country(max_per_country)
    if per_country >= limit and not excluding:
        return limit
    return min(10_000, max(limit, limit * 4))


def examples_from_map(document) -> list[dict]:
    rows = document if isinstance(document, list) else []
    if isinstance(document, dict):
        rows = document.get("customCoordinates") or document.get("locations") or document.get("coordinates") or []
    seen = set()
    usable = []
    for location in rows if isinstance(rows, list) else []:
        if not isinstance(location, dict):
            continue
        pano = location.get("panoId") or location.get("pano_id") or location.get("pano")
        if not isinstance(pano, str) or not pano.strip():
            continue
        try:
            heading = float(location.get("heading") or 0)
            pitch = float(location.get("pitch") or 0)
            zoom = float(location.get("zoom") or 0)
        except (TypeError, ValueError):
            heading, pitch, zoom = 0.0, 0.0, 0.0
        key = (pano.strip(), heading, pitch, zoom)
        if key in seen:
            continue
        seen.add(key)
        usable.append({"panoId": pano.strip(), "heading": heading, "pitch": pitch, "zoom": zoom})
    if len(usable) <= 100:
        return usable
    if len(usable) == 1:
        return usable[:1]
    picked = []
    for index in range(100):
        fraction = index / 99
        picked.append(usable[round(fraction * (len(usable) - 1))])
    return picked


def search_input(
    prompt: str,
    *,
    run_id: str = "vision-community-four-view-search",
    view_direction: str = "bestOfFour",
    result_count: int = 50,
    max_per_country: int = 25,
    reject_road_names: bool = False,
    country_mode: str = "all",
    countries: list[str] | None = None,
    camera_generations: list[str] | None = None,
    output_name: str = "",
    description_weight: int | None = None,
    examples: list[dict] | None = None,
    excluding: bool = False,
) -> dict:
    from .features import view_offsets_for

    text = prompt.strip()
    samples = list(examples or [])
    if not text and not samples:
        raise VisionIndexError("invalid_query")
    if not text:
        text = f"visual examples for {(output_name or 'VISION Community').strip() or 'VISION Community'}"
    names = [item for item in (countries or []) if item]
    include = names if country_mode == "include" else []
    exclude = names if country_mode == "exclude" else []
    weight = snap_description_weight(description_weight, has_json=bool(samples), has_prompt=bool(prompt.strip()))
    mode, minimum = SCENE_QUERY_MODES[weight]
    title = output_name.strip() or "VISION Community"
    return {
        "runId": run_id,
        "queries": [
            {
                "name": title,
                "query": text,
                "mode": mode,
                "minSimilarity": minimum,
                "examples": samples,
                "cameraGenerations": list(camera_generations or []),
                "includeCountries": include,
                "excludeCountries": exclude,
                "rejectRoadNames": bool(reject_road_names),
                "viewOffsets": list(view_offsets_for(view_direction, "scene")),
            }
        ],
        "topK": scene_candidate_count(result_count, max_per_country, excluding=excluding),
        "chunkSize": 4096,
        "concurrency": 1,
        "resultPruneMeters": RESULT_PRUNE_METERS,
    }


def write_json(path: Path, payload: dict) -> None:
    assert_not_live_vision_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def inference_environment(work: Path, inference_threads: int = 1) -> dict:
    if type(inference_threads) is not int or not 1 <= inference_threads <= 64:
        raise VisionIndexError("invalid_inference_threads")
    env = os.environ.copy()
    for key in THREAD_ENVIRONMENT_KEYS:
        env[key] = str(inference_threads)
    env["TMPDIR"] = str(work)
    return env


@lru_cache(maxsize=64)
def _identity_hash(path: str, size: int, modified_ns: int) -> str:
    # Cache only within this process and invalidate on file metadata changes.
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict | None:
    if not path.is_file():
        return None
    info = path.stat()
    return {"bytes": info.st_size, "sha256": _identity_hash(str(path.resolve()), info.st_size, info.st_mtime_ns)}


def default_runner(argv: list[str], env: dict, cwd: Path):
    """Bound one native process and preserve logs even on timeout or failure."""
    cwd = Path(cwd)
    stem = cwd / f"process-{time.time_ns()}-{secrets.token_hex(3)}"
    stdout_path = stem.with_suffix(".stdout.log")
    stderr_path = stem.with_suffix(".stderr.log")
    timeout = 60 if "index-layout" in argv else INDEX_TIMEOUT_SECONDS
    started = time.monotonic()
    outcome = {"status": "STARTED", "timeoutSeconds": timeout}
    launch_options = {}
    if sys.platform == "win32":
        # Scheduling priority does not alter the calibrated model, batch shape
        # or inference thread environment. Native helpers need no console window.
        launch_options["creationflags"] = subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            completed = subprocess.run(argv, env=env, cwd=str(cwd), stdout=stdout,
                                       stderr=stderr, check=False, timeout=timeout, **launch_options)
        outcome.update(status="EXITED", exitCode=completed.returncode)
    except subprocess.TimeoutExpired as error:
        # subprocess.run kills and waits for the direct native process first.
        outcome["status"] = "TIMEOUT"
        raise VisionIndexError("vision_binary_timeout") from error
    except OSError as error:
        outcome["status"] = "LAUNCH_FAILED"
        raise VisionIndexError("vision_binary_launch_failed") from error
    except KeyboardInterrupt:
        outcome["status"] = "INTERRUPTED"
        raise
    finally:
        outcome["wallSeconds"] = time.monotonic() - started
        write_json(stem.with_suffix(".exit.json"), outcome)
    # Layout stdout is a small JSON object; large indexing logs stay on disk.
    def read_tail(path):
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 1024 * 1024))
            return handle.read().decode("utf-8", errors="replace")
    return completed.returncode, read_tail(stdout_path), read_tail(stderr_path)


def command_prefix(binary: Path, *, nice_level: int | None, use_nice: bool) -> list[str]:
    argv = [str(binary)]
    if use_nice and nice_level is not None and sys.platform != "win32":
        argv = ["nice", "-n", str(int(nice_level)), *argv]
    return argv


def run_binary(binary: Path, args: list[str], *, env: dict, cwd: Path, runner, nice_level: int | None, use_nice: bool):
    argv = [*command_prefix(binary, nice_level=nice_level, use_nice=use_nice), *args]
    code, stdout, stderr = runner(argv, env, cwd)
    if code != 0:
        raise VisionIndexError("vision_binary_failed")
    return stdout, stderr


def checkpoint_state(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def index_is_complete(checkpoint: Path, index_dir: Path, total: int) -> bool:
    state = checkpoint_state(checkpoint)
    if state is None:
        return False
    if state.get("nextLocationIndex") != total or state.get("incompleteLocations") != 0:
        if state.get("completed") is True:
            raise VisionIndexError("incomplete_index")
        return False
    return True


def require_complete_index(checkpoint: Path, index_dir: Path, total: int) -> None:
    """A preallocated shard or completed flag alone does not prove success."""
    if not index_is_complete(checkpoint, index_dir, total):
        raise VisionIndexError("incomplete_index")
    manifest = checkpoint_state(Path(index_dir) / "manifest.json")
    if manifest is None or manifest.get("indexedLocations") != total:
        raise VisionIndexError("incomplete_index")
    require_layout({**manifest, "feature": "four-view-index"})
    if manifest.get("shardLocations") != SHARD_LOCATIONS:
        raise VisionIndexError("wrong_vision_layout")
    expected = {(f"shard-{number:06d}.i8") for number in range((total + SHARD_LOCATIONS - 1) // SHARD_LOCATIONS)}
    if {path.name for path in Path(index_dir).glob("shard-*.i8")} != expected:
        raise VisionIndexError("unexpected_shards")
    for number in range(len(expected)):
        count = min(SHARD_LOCATIONS, total - number * SHARD_LOCATIONS)
        shard = Path(index_dir) / f"shard-{number:06d}.i8"
        mask = shard.with_suffix(".mask")
        if not mask.is_file() or mask.read_bytes() != b"\x0f" * count:
            raise VisionIndexError("incomplete_view_mask")
        if shard.stat().st_size != count * BYTES_PER_LOCATION:
            raise VisionIndexError("short_embedding")
        with shard.open("rb") as handle:
            for _ in range(count):
                if not valid_four_view_record(handle.read(BYTES_PER_LOCATION)):
                    raise VisionIndexError("invalid_embedding")


def keep_lease_alive(session: CommunityClient, lease_id: str, stop: threading.Event) -> None:
    while not stop.wait(300):
        try:
            session.renew(lease_id)
        except ContributeError:
            pass


def read_location_record(index_dir: Path, location_index: int, *, shard_locations: int = SHARD_LOCATIONS, validate: bool = True) -> bytes:
    if location_index < 0:
        raise VisionIndexError("invalid_location")
    shard = location_index // shard_locations
    offset = (location_index % shard_locations) * BYTES_PER_LOCATION
    path = Path(index_dir) / f"shard-{shard:06d}.i8"
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            record = handle.read(BYTES_PER_LOCATION)
    except OSError as error:
        raise VisionIndexError("short_embedding") from error
    if len(record) != BYTES_PER_LOCATION:
        raise VisionIndexError("short_embedding")
    if validate and not valid_four_view_record(record):
        raise VisionIndexError("invalid_embedding")
    return record


def index_locations_tsv(
    locations_tsv: Path,
    *,
    index_dir: Path,
    checkpoint: Path,
    output: Path,
    input_path: Path | None = None,
    binary: Path | None = None,
    model_dir: Path | None = None,
    pace: str = "slow",
    run_id: str = "vision-community-four-view-v4",
    runner=None,
    use_nice: bool = True,
    inference_threads: int = 1,
    progress_callback=None,
) -> dict:
    if pace not in PACE:
        raise VisionIndexError("invalid_pace")
    locations_tsv = Path(locations_tsv).expanduser().resolve()
    index_dir = Path(index_dir).expanduser().resolve()
    checkpoint = Path(checkpoint).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    for path in (locations_tsv, index_dir, checkpoint, output):
        assert_not_live_vision_path(path)
    total = count_locations(locations_tsv)
    model = (Path(model_dir) if model_dir is not None else default_model_dir()).expanduser().resolve()
    program = (Path(binary) if binary is not None else default_binary()).expanduser().resolve()
    if runner is None:
        require_model_dir(model)
        if not program.is_file() or not os.access(program, os.X_OK):
            raise VisionIndexError("vision_binary_missing")
    else:
        assert_not_live_vision_path(model)
    settings = PACE[pace]
    work = index_dir.parent
    work.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    spec_path = Path(input_path).expanduser().resolve() if input_path is not None else work / "input.json"
    expected_spec = four_view_input(total=total, pace=pace, run_id=run_id)
    env = inference_environment(work, inference_threads)
    provenance = {
        "version": 1, "platform": sys.platform, "inferenceThreads": inference_threads,
        "threadEnvironment": {key: env[key] for key in THREAD_ENVIRONMENT_KEYS},
        "locations": file_identity(locations_tsv), "binary": file_identity(program),
        "models": {name: file_identity(model / name) for name in REQUIRED_MODEL_FILES},
        "input": expected_spec, "customRunner": runner is not None,
        "qualityStatus": "EXPLORATORY_NOT_APPROVED",
    }
    provenance_path = work / "index-run.json"
    if not checkpoint.is_file():
        # Never reuse preallocated or orphaned files without a matching checkpoint.
        if any(index_dir.iterdir()):
            raise VisionIndexError("unverified_checkpoint")
        write_json(spec_path, expected_spec)
        write_json(provenance_path, provenance)
    elif not spec_path.is_file():
        raise VisionIndexError("vision_input_missing")
    elif checkpoint_state(spec_path) != expected_spec or checkpoint_state(provenance_path) != provenance:
        raise VisionIndexError("checkpoint_configuration_mismatch")
    active = runner or default_runner
    failures = stalled = attempts = 0
    # Allow a clean checkpoint per chunk, but never an unbounded resume cycle.
    max_attempts = (total + settings["chunk"] - 1) // settings["chunk"] + MAX_NO_PROGRESS

    def progress(event):
        if progress_callback is not None:
            state = checkpoint_state(checkpoint) or {}
            progress_callback({"event": event, "attempt": attempts, "totalLocations": total,
                               "completedLocations": state.get("nextLocationIndex", 0)})

    try:
        layout_stdout, _stderr = run_binary(
            program, ["index-layout"], env=env, cwd=work, runner=active,
            nice_level=settings["nice"], use_nice=use_nice and runner is None,
        )
        require_layout(parse_json_stdout(layout_stdout))
        while not index_is_complete(checkpoint, index_dir, total):
            if attempts >= max_attempts:
                raise VisionIndexError("vision_retry_limit")
            attempts += 1
            before = checkpoint_state(checkpoint) or {}
            progress("indexing")
            try:
                _stdout, execution_stderr = run_binary(
                    program,
                    ["index-four-views", "--input", str(spec_path), "--model-dir", str(model),
                     "--locations-tsv", str(locations_tsv), "--index-dir", str(index_dir),
                     "--checkpoint", str(checkpoint), "--output", str(output)],
                    env=env, cwd=work, runner=active, nice_level=settings["nice"],
                    use_nice=use_nice and runner is None,
                )
                require_scene_execution(execution_stderr, inference_threads)
            except VisionIndexError as error:
                failures += 1
                if error.code != "vision_binary_failed" or failures >= MAX_INDEX_FAILURES:
                    raise
                print("The indexer stopped; retrying from its saved checkpoint.", file=sys.stderr, flush=True)
                if runner is None:
                    time.sleep(min(30, failures * 5))
                continue
            if index_is_complete(checkpoint, index_dir, total):
                break
            after = checkpoint_state(checkpoint) or {}
            moved = isinstance(after.get("nextLocationIndex"), int) and after["nextLocationIndex"] > before.get("nextLocationIndex", 0)
            stalled = 0 if moved else stalled + 1
            if stalled >= MAX_NO_PROGRESS:
                raise VisionIndexError("vision_no_progress")
            progress("resume")
            if runner is None and not moved:
                time.sleep(min(30, stalled * 5))
        require_complete_index(checkpoint, index_dir, total)
        record = read_location_record(index_dir, 0)
        progress("complete")
    except (Exception, KeyboardInterrupt) as error:
        write_json(work / "failure.json", {
            "ok": False, "code": getattr(error, "code", type(error).__name__),
            "attempts": attempts, "failedAttempts": failures, "noProgressAttempts": stalled,
            "totalLocations": total, "evidencePreserved": True,
        })
        raise
    return {
        "ok": True,
        "model": VISION_FOUR_VIEW_MODEL,
        "locations": total,
        "bytesPerLocation": BYTES_PER_LOCATION,
        "indexDir": str(index_dir),
        "firstRecordSha256": hashlib.sha256(record).hexdigest(),
        "inferenceThreads": inference_threads,
        "attempts": attempts,
        "qualityStatus": "EXPLORATORY_NOT_APPROVED",
    }


def outputs_for_items(items: list[dict], index_dir: Path) -> list[dict]:
    import base64
    import hashlib

    outputs = []
    for index, item in enumerate(items):
        record = read_location_record(index_dir, index)
        digest = hashlib.sha256(record).hexdigest()
        outputs.append(
            {
                "locationId": int(item["locationId"]),
                "outputSha256": digest,
                "embeddingSha256": digest,
                "embedding": base64.b64encode(record).decode("ascii"),
                "model": VISION_FOUR_VIEW_MODEL,
            }
        )
    return outputs


def index_from_queue(
    *,
    url: str,
    pace: str = "slow",
    batches: int | None = None,
    count: int | None = None,
    part: int | None = None,
    recovery_code: str | None = None,
    work_dir: Path,
    session_path: Path | None = None,
    persist_session: bool = False,
    client: CommunityClient | None = None,
    binary: Path | None = None,
    model_dir: Path | None = None,
    runner=None,
    use_nice: bool = True,
    progress_callback=None,
) -> dict:
    if pace not in PACE:
        raise VisionIndexError("invalid_pace")
    if batches is not None and batches < 1:
        raise VisionIndexError("invalid_batch")
    work_dir = Path(work_dir)
    assert_not_live_vision_path(work_dir)
    size = count if count is not None else CLI_LEASE_CAP["scene"][pace]
    if type(size) is not int or size < 1:
        raise VisionIndexError("invalid_count")
    session = client or CommunityClient(url)
    stored = load_session(session_path, url) if session_path is not None else None
    if not recovery_code and not session.token:
        recovery_code = os.environ.get("VISION_COMMUNITY_RECOVERY") or None
    if not recovery_code and not session.token and stored:
        code = stored.get("recoveryCode")
        recovery_code = code if isinstance(code, str) and code else None
    created = None
    recovered = None
    if recovery_code:
        recovered = session.recover(recovery_code)
    elif not session.token:
        created = session.create_account()
        recovery_code = created.get("recoveryCode") if isinstance(created, dict) else None
    if persist_session and session_path is not None and recovery_code:
        account_id = None
        if created:
            account_id = created.get("accountId")
        elif recovered:
            account_id = recovered.get("accountId")
        save_session(session_path, url=url, account_id=account_id, recovery_code=recovery_code)
    accepted = 0
    units = 0
    processed = 0
    indexes = []
    stalls = 0
    batch_failures = 0
    while batches is None or processed < batches:
        try:
            lease = session.lease("scene", size, pace, part=part)
        except ContributeError as error:
            if error.code == "no_available_work":
                break
            if batches is not None or error.code not in RETRYABLE_CODES:
                raise VisionIndexError(error.code, error.status) from error
            stalls += 1
            if stalls >= MAX_QUEUE_FAILURES:
                raise VisionIndexError(error.code, error.status) from error
            print(f"still indexing; retrying after {error.code}", file=sys.stderr, flush=True)
            time.sleep(min(60, stalls * 2))
            continue
        stalls = 0
        lease_id = str(lease.get("leaseId") or "")
        if not re.fullmatch(r"[0-9a-f]{32}", lease_id):
            raise VisionIndexError("invalid_lease")
        items = lease.get("items") if isinstance(lease.get("items"), list) else []
        run_dir = work_dir / lease_id
        stop = threading.Event()
        beater = threading.Thread(
            target=keep_lease_alive, args=(session, lease_id, stop), daemon=True
        )
        beater.start()
        try:
            write_locations_tsv(items, run_dir / "locations.tsv")
            index_locations_tsv(
                run_dir / "locations.tsv",
                index_dir=run_dir / "index",
                checkpoint=run_dir / "checkpoint.json",
                output=run_dir / "output.json",
                input_path=run_dir / "input.json",
                binary=binary,
                model_dir=model_dir,
                pace=pace,
                runner=runner,
                use_nice=use_nice,
                progress_callback=progress_callback,
            )
            try:
                session.renew(lease_id)
            except ContributeError as error:
                if error.code in {"expired_lease", "lease_lost", "unknown_lease"}:
                    # Never offer a finished checkpoint after the server has
                    # explicitly said this account no longer owns its lease.
                    raise VisionIndexError(error.code, error.status) from error
                transient = error.code == "network_error" or (
                    error.status in RETRY_STATUSES
                    and error.code in {"http_error", "renew_failed", "internal_error", "rate_limited"}
                )
                if not transient:
                    raise
            result = session.submit(lease_id, outputs_for_items(items, run_dir / "index"))
            # The guided desktop client asks the trusted verifier to audit a
            # quarantined submission. CLI clients retain the existing submit
            # response and never gain approval from this local branch.
            if hasattr(session, "audit_submission") and result.get("pendingAudit"):
                result = session.audit_submission(str(result.get("submissionId") or lease_id))
        except (VisionIndexError, KeyboardInterrupt) as error:
            stop.set()
            retain_lease = isinstance(error, KeyboardInterrupt) or error.code in RETRYABLE_NATIVE_CODES
            if not retain_lease:
                try:
                    if not getattr(session, "submission_is_saved", lambda _lease: False)(lease_id):
                        session.release(lease_id)
                except ContributeError:
                    pass
            raise
        except Exception as error:
            stop.set()
            code = error.code if isinstance(error, ContributeError) else ""
            try:
                if not getattr(session, "submission_is_saved", lambda _lease: False)(lease_id):
                    session.release(lease_id)
            except ContributeError:
                pass
            batch_failures += 1
            if batches is not None or batch_failures >= MAX_QUEUE_FAILURES or code not in RETRYABLE_CODES:
                raise
            stalls += 1
            print("still indexing; the last batch will be tried again", file=sys.stderr, flush=True)
            time.sleep(min(60, stalls * 2))
            continue
        finally:
            stop.set()
            beater.join(timeout=1)
        batch_failures = 0
        accepted += int(result.get("accepted") or 0)
        units += int(result.get("unitsEarned") or 0)
        processed += 1
        indexes.append(str(run_dir / "index"))
        print(f"indexed batch {processed}", file=sys.stderr, flush=True)
        if progress_callback is not None:
            progress_callback({"event": "batch", "batches": processed, "accepted": accepted, "unitsEarned": units})
    report = {
        "ok": True,
        "model": VISION_FOUR_VIEW_MODEL,
        "lane": "scene",
        "pace": pace,
        "batches": processed,
        "accepted": accepted,
        "unitsEarned": units,
        "indexes": indexes,
    }
    if created is not None:
        report["accountId"] = created.get("accountId")
        report["recoveryCode"] = created.get("recoveryCode")
    try:
        me = session.me()
        report["units"] = int(me.get("units") or 0)
        cost = int(me.get("searchCost") or 100000)
        report["searchCost"] = cost
        report["unitsRemainingToSearch"] = max(0, cost - int(me.get("units") or 0))
    except ContributeError:
        pass
    return report


def default_shared_scene_dir() -> Path:
    override = os.environ.get("VISION_COMMUNITY_SHARED_SCENES")
    if override:
        return Path(override)
    return community_support_root() / "shared-index/scenes"


def discover_indexes(work_dir: Path) -> list[Path]:
    work_dir = Path(work_dir)
    found = []
    direct = work_dir / "index" / "manifest.json"
    if direct.is_file():
        found.append(work_dir)
    if work_dir.is_dir():
        for child in sorted(work_dir.iterdir()):
            if child.is_dir() and (child / "index" / "manifest.json").is_file():
                found.append(child)
    return found


def import_published_scenes(session: CommunityClient, search_id: str, destination: Path) -> int:
    """Turn stored four-view records back into the shard directory VISION searches."""
    destination = Path(destination)
    assert_not_live_vision_path(destination)
    catalog = session.scene_index_catalog(search_id)
    imported = 0
    for entry in catalog.get("indexes") or []:
        key = str(entry.get("key") or "")
        lease_id = Path(key).stem
        locations = entry.get("locations") if isinstance(entry.get("locations"), list) else []
        if not re.fullmatch(r"[0-9a-f]{32}", lease_id) or not locations:
            continue
        blob = session.scene_index_file(search_id, key)
        if len(blob) != len(locations) * BYTES_PER_LOCATION:
            continue
        target = destination / lease_id
        index_dir = target / "index"
        index_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            location_tsv_line(item)
            for item in locations
            if isinstance(item, dict)
        ]
        if len(lines) != len(locations):
            continue
        (target / "locations.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (index_dir / "shard-000000.i8").write_bytes(blob)
        (index_dir / "manifest.json").write_text(
            json.dumps({"indexedLocations": len(lines), "bytesPerLocation": BYTES_PER_LOCATION, "version": 4}),
            encoding="utf-8",
        )
        imported += 1
    return imported


def load_tsv_table(path: Path) -> list[list[str]]:
    return [line.split("\t") for line in iter_location_lines(path)]


def hits_from_output(payload: dict):
    queries = payload.get("queries") if isinstance(payload.get("queries"), list) else []
    if not queries and isinstance(payload.get("hits"), list):
        queries = [{"name": "VISION Community", "hits": payload["hits"]}]
    for query in queries:
        if not isinstance(query, dict):
            continue
        name = query.get("name") if isinstance(query.get("name"), str) else "VISION Community"
        for hit in query.get("hits") or []:
            if isinstance(hit, dict):
                yield name, hit


def map_from_search(payload: dict, locations_tsv: Path, *, prompt: str, min_score: float | None = None) -> dict | None:
    from .features import wrap_heading

    table = load_tsv_table(locations_tsv)
    coordinates = []
    rank = 0
    for name, hit in hits_from_output(payload):
        location = hit.get("location") if isinstance(hit.get("location"), dict) else {}
        index = hit.get("locationIndex")
        row = table[index] if isinstance(index, int) and 0 <= index < len(table) else None
        lat = location.get("lat", row[2] if row else None)
        lng = location.get("lng", row[3] if row else None)
        pano = location.get("panoId") or (row[7] if row else "")
        if lat is None or lng is None or not pano:
            continue
        offset = int(hit.get("viewOffset") or 0)
        base_heading = float(location.get("heading", row[4] if row else 0) or 0)
        rank += 1
        score = float(hit.get("similarity") or hit.get("score") or 0)
        country = canonicalize_country(str(location.get("country") or (row[8] if row else "") or ""))
        camera = str(location.get("cameraGeneration") or (row[9] if row else "") or "")
        source_index = index if isinstance(index, int) else 0
        coordinates.append(
            {
                "lat": float(lat),
                "lng": float(lng),
                "heading": wrap_heading(base_heading + offset * 90),
                "pitch": float(location.get("pitch", row[5] if row else 0) or 0),
                "zoom": float(location.get("zoom", row[6] if row else 0) or 0),
                "panoId": pano,
                "extra": search_location_extra(
                    country=country,
                    camera_generation=camera,
                    score=score,
                    min_score=0 if min_score is None else min_score,
                    rank=rank,
                    query_name=name or prompt,
                    mode="scene",
                    heading_offset=offset * 90,
                    source_index=source_index,
                    processed_locations=len(table),
                    model=SCENE_MODEL_NAME,
                ),
            }
        )
    if not coordinates:
        return None
    return build_map(prompt, coordinates)


def finish_scene_coordinates(
    coordinates: list[dict],
    *,
    result_count: int,
    max_per_country: int,
    exclude_map=None,
    output_name: str = "",
    prompt: str = "",
    processed_locations: int | None = None,
) -> dict | None:
    from .service import ServiceError, _exclude_points

    def scene_order(item: dict):
        extra = item.get("extra") or {}
        source_index = extra.get("visionSourceIndex")
        return (-(extra.get("visionScore") or 0), source_index if isinstance(source_index, int) else 0)

    ordered = sorted(coordinates, key=scene_order)
    if exclude_map is not None:
        try:
            points = _exclude_points(exclude_map)
        except ServiceError as error:
            raise VisionIndexError(error.code if getattr(error, "code", None) else "invalid_mma_map") from error
        ordered = exclude_used(ordered, points)
    ranked = []
    for item in ordered:
        tags = (item.get("extra") or {}).get("tags") or []
        ranked.append({**item, "country": tags[0] if tags else ""})
    limited = cap_by_country(ranked, clamp_result_count(result_count), clamp_max_per_country(max_per_country))
    cleaned = []
    for rank, item in enumerate(limited, start=1):
        row = dict(item)
        row.pop("country", None)
        extra = row.setdefault("extra", {})
        extra["visionRank"] = rank
        if processed_locations is not None:
            extra["visionProcessedLocations"] = int(processed_locations)
        cleaned.append(row)
    if not cleaned:
        return None
    title = output_name.strip() or prompt.strip() or "VISION Community"
    return build_map(title, cleaned)


def search_indexes(
    work_dir: Path,
    prompt: str,
    *,
    binary: Path | None = None,
    model_dir: Path | None = None,
    runner=None,
    use_nice: bool = True,
    view_direction: str = "bestOfFour",
    result_count: int = 50,
    max_per_country: int = 25,
    reject_road_names: bool = False,
    country_mode: str = "all",
    countries: list[str] | None = None,
    camera_generations: list[str] | None = None,
    import_cutoff: int | None = None,
    output_name: str = "",
    description_weight: int | None = None,
    examples: list[dict] | None = None,
    exclude_map=None,
    extra_roots: list[Path] | None = None,
) -> dict:
    runs = []
    seen = set()
    for root in [work_dir, *(extra_roots or [])]:
        for run_dir in discover_indexes(root):
            if run_dir in seen:
                continue
            seen.add(run_dir)
            runs.append(run_dir)
    if not runs:
        raise VisionIndexError("index_missing")
    program = Path(binary) if binary is not None else default_binary()
    model = Path(model_dir) if model_dir is not None else default_model_dir()
    if runner is None:
        require_model_dir(model)
        if not program.is_file() or not os.access(program, os.X_OK):
            raise VisionIndexError("vision_binary_missing")
    active = runner or default_runner
    maps = []
    searched = 0
    processed_locations = 0
    cursor = 0
    for run_dir in runs:
        locations = run_dir / "locations.tsv"
        index_dir = run_dir / "index"
        if not locations.is_file():
            continue
        indexed = sum(1 for line in locations.read_text(encoding="utf-8").splitlines() if line.strip())
        source_start = cursor
        cursor += indexed
        if import_cutoff is not None and source_start < int(import_cutoff):
            continue
        for path in (locations, index_dir, run_dir):
            assert_not_live_vision_path(path)
        spec = run_dir / "search-input.json"
        output = run_dir / "search-output.json"
        request = search_input(
            prompt,
            view_direction=view_direction,
            result_count=result_count,
            max_per_country=max_per_country,
            reject_road_names=reject_road_names,
            country_mode=country_mode,
            countries=countries,
            camera_generations=camera_generations,
            output_name=output_name,
            description_weight=description_weight,
            examples=examples,
            excluding=exclude_map is not None,
        )
        minimum = float(request["queries"][0]["minSimilarity"])
        write_json(spec, request)
        env = inference_environment(run_dir)
        run_binary(
            program,
            [
                "search-four-view-index",
                "--input",
                str(spec),
                "--model-dir",
                str(model),
                "--locations-tsv",
                str(locations),
                "--index-dir",
                str(index_dir),
                "--profile-cache-dir",
                str(run_dir / "profile-cache"),
                "--output",
                str(output),
            ],
            env=env,
            cwd=run_dir,
            runner=active,
            nice_level=19,
            use_nice=use_nice and runner is None,
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
        searched += 1
        processed_locations += indexed
        built = map_from_search(payload, locations, prompt=prompt, min_score=minimum)
        if built is not None:
            maps.append(built)
    coordinates = []
    for document in maps:
        coordinates.extend(document.get("customCoordinates") or [])
    if not searched:
        raise VisionIndexError("index_missing")
    return {
        "ok": True,
        "model": VISION_FOUR_VIEW_MODEL,
        "indexes": searched,
        "map": finish_scene_coordinates(
            coordinates,
            result_count=result_count,
            max_per_country=max_per_country,
            exclude_map=exclude_map,
            output_name=output_name,
            prompt=prompt,
            processed_locations=processed_locations,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--pace", choices=tuple(PACE), default="slow")
    parser.add_argument(
        "--batches",
        type=int,
        default=None,
        help="stop after this many batches; omit to keep going until the queue is empty or you press Control-C",
    )
    parser.add_argument("--count", type=int)
    parser.add_argument("--part", type=int)
    parser.add_argument("--recovery-code", dest="recovery_code")
    parser.add_argument("--session-file", type=Path, dest="session_file")
    parser.add_argument("--no-save-session", action="store_true")
    parser.add_argument("--locations-tsv", type=Path, dest="locations_tsv")
    parser.add_argument("--index-dir", type=Path, dest="index_dir")
    parser.add_argument("--work-dir", type=Path, dest="work_dir")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--model-dir", type=Path, dest="model_dir")
    parser.add_argument("--inference-threads", type=int, default=1,
                        help="experimental manual indexing only; queue contributions always use one inference thread")
    parser.add_argument("--search", action="store_true")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--result-count", type=int, default=200)
    parser.add_argument("--max-per-country", type=int, default=25)
    parser.add_argument("--description-weight", type=int, default=50)
    parser.add_argument("--output-name", default="")
    parser.add_argument("--query", type=Path, help="map-making.app JSON used as visual examples")
    parser.add_argument("--exclude", type=Path, help="previous map JSON; hide results within 25 m")
    parser.add_argument("--view-direction", default="bestOfFour")
    parser.add_argument("--country-mode", choices=("all", "include", "exclude"), default="all")
    parser.add_argument("--countries", default="")
    parser.add_argument("--camera-generations", default="")
    parser.add_argument("--reject-road-names", action="store_true")
    parser.add_argument("--import-cutoff", type=int, default=None)
    args = parser.parse_args()
    if args.inference_threads != 1 and (args.locations_tsv is None or args.search):
        parser.error("--inference-threads requires manual --locations-tsv indexing; it cannot be used for contributions or search")
    work_dir = args.work_dir or default_work_dir()
    try:
        if args.search:
            query_map = json.loads(args.query.read_text(encoding="utf-8")) if args.query is not None else None
            exclude_map = json.loads(args.exclude.read_text(encoding="utf-8")) if args.exclude is not None else None
            examples = examples_from_map(query_map) if query_map is not None else []
            prompt = args.prompt.strip()
            if not prompt and not examples:
                raise VisionIndexError("invalid_query")
            target = args.index_dir.parent if args.index_dir is not None else work_dir
            shared = default_shared_scene_dir()
            assert_not_live_vision_path(shared)
            session_path = args.session_file or default_session_path()
            code = args.recovery_code or os.environ.get("VISION_COMMUNITY_RECOVERY")
            stored = load_session(session_path, args.url)
            if not code and stored:
                code = stored.get("recoveryCode")
            if not code:
                raise VisionIndexError("recovery_code_required")
            client = CommunityClient(args.url)
            client.recover(str(code))
            account = client.me()
            if int(account.get("units") or 0) < int(account.get("searchCost") or 100000):
                raise VisionIndexError("insufficient_credit")
            remote = int(account.get("sceneIndexes") or 0)
            if not discover_indexes(target) and not discover_indexes(shared) and remote <= 0:
                raise VisionIndexError("index_missing")
            countries = [part.strip() for part in args.countries.split(",") if part.strip()]
            cameras = [part.strip() for part in args.camera_generations.split(",") if part.strip()]
            search_body = {
                "lane": "scene",
                "prompt": prompt,
                "outputName": args.output_name,
                "viewDirection": args.view_direction,
                "resultCount": args.result_count,
                "maxPerCountry": args.max_per_country,
                "descriptionWeight": args.description_weight,
                "countryFilterMode": args.country_mode,
                "countries": countries,
                "cameraGenerations": cameras,
                "queryMap": query_map,
                "excludeMap": exclude_map,
                "rejectRoadNames": args.reject_road_names,
                "idempotencyKey": secrets.token_hex(16),
            }
            authorized = None
            if remote:
                authorized = client.authorize_local_search(search_body)
                import_published_scenes(client, str(authorized.get("searchId") or ""), shared)
            result = search_indexes(
                target,
                prompt,
                binary=args.binary,
                model_dir=args.model_dir,
                max_per_country=args.max_per_country,
                output_name=args.output_name,
                description_weight=args.description_weight,
                examples=examples,
                exclude_map=exclude_map,
                view_direction=args.view_direction,
                result_count=args.result_count,
                reject_road_names=args.reject_road_names,
                import_cutoff=args.import_cutoff,
                country_mode=args.country_mode,
                countries=countries,
                camera_generations=cameras,
                extra_roots=[shared],
            )
            if authorized is None:
                authorized = client.authorize_local_search(search_body)
            if not authorized.get("local"):
                raise VisionIndexError("search_failed")
            print(dump_map(result["map"] or build_map(prompt, [])))
            return
        if args.locations_tsv is not None:
            index_dir = args.index_dir or (work_dir / "manual" / "index")
            report = index_locations_tsv(
                args.locations_tsv,
                index_dir=index_dir,
                checkpoint=index_dir.parent / "checkpoint.json",
                output=index_dir.parent / "output.json",
                input_path=index_dir.parent / "input.json",
                binary=args.binary,
                model_dir=args.model_dir,
                pace=args.pace,
                inference_threads=args.inference_threads,
            )
        else:
            report = index_from_queue(
                url=args.url,
                pace=args.pace,
                batches=args.batches,
                count=args.count,
                part=args.part,
                recovery_code=args.recovery_code,
                work_dir=work_dir,
                session_path=args.session_file or default_session_path(),
                persist_session=not args.no_save_session,
                binary=args.binary,
                model_dir=args.model_dir,
            )
    except (VisionIndexError, ContributeError) as error:
        parser.exit(1, f"{error.code}\n")
    except KeyboardInterrupt:
        parser.exit(130, "interrupted\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
