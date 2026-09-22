"""Index objects with the same program the VISION app uses.

The browser cannot run that model. This command shells out to
`vision-object index-segment`: the same 12-column TSV, the same hybrid
runtime (RF-DETR Medium, YOLOE-26L, OWLv2 PQ128), and the same version-4
six-face index.

It will not write the live VISION object index, its scheduled TSV, or the
CoreML cache that index is using. Pace only changes process priority. The
duty cycle stays at 25 percent, which is the VISION object indexer's duty.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import sys
import threading
import time
import zlib
from pathlib import Path

from .contribute import (
    DEFAULT_URL,
    RETRYABLE_CODES,
    CommunityClient,
    ContributeError,
    default_session_path,
    load_session,
    save_session,
)
from .pano import CLI_LEASE_CAP
from .vision_index import (
    VisionIndexError,
    assert_not_live_vision_path,
    keep_lease_alive,
    location_tsv_line,
    run_binary,
)


OBJECT_INDEX_MODEL = "vision-object-index-v4"
OBJECT_FEATURE = "vision-object-index"
OBJECT_ARCHITECTURE = "VISION Hybrid: RF-DETR Medium + YOLOE-26L + OWLv2 PQ128"
OBJECT_RANKING = "raw-confidence-position-neutral-v2"
OBJECT_COVERAGE = "complete-360x180-six-face-cube"
OBJECT_POSITION_POLICY = (
    "maximum raw model score; no heading, pitch, center, edge, sky, ground, or view-order weights"
)
OBJECT_GLOBAL_MODE = "explicit-contiguous-permutation-v1"
COMMON_MODEL_SHA256 = "00cc60ba7e18ea6b5afeca7d8d3d4a07be0d1e9969dbd1799719a4f802882fd2"
RUNTIME_IDENTITY = "58ee8c307523d3ac06da85d18fd3ad303d6a0442d4edc071918be5e2890b9353"
CODEBOOK_SHA256 = "f28e0e9aeb8bfcd547cad3d2a3d9aa546de74b647cd1cc058a5911bd7dafeb25"
GLOBAL_START = 0
DUTY_CYCLE_PERCENT = 25
CHECKPOINT_EVERY = 10
RECORD_BYTES = 32
GLOBAL_ID_BYTES = 12
SEMANTIC_RECORD_BYTES = 144
SEMANTIC_PROPOSALS = 16
# Same COCO class ids and file names as VISION's object indexer.
OBJECT_CLASSES = (
    (1, "person"), (2, "bicycle"), (3, "car"), (4, "motorcycle"), (5, "airplane"),
    (6, "bus"), (7, "train"), (8, "truck"), (9, "boat"), (10, "traffic light"),
    (11, "fire hydrant"), (13, "stop sign"), (14, "parking meter"), (15, "bench"),
    (16, "bird"), (17, "cat"), (18, "dog"), (19, "horse"), (20, "sheep"),
    (21, "cow"), (22, "elephant"), (23, "bear"), (24, "zebra"), (25, "giraffe"),
    (27, "backpack"), (28, "umbrella"), (31, "handbag"), (32, "tie"), (33, "suitcase"),
    (34, "frisbee"), (35, "skis"), (36, "snowboard"), (37, "sports ball"), (38, "kite"),
    (39, "baseball bat"), (40, "baseball glove"), (41, "skateboard"), (42, "surfboard"),
    (43, "tennis racket"), (44, "bottle"), (46, "wine glass"), (47, "cup"), (48, "fork"),
    (49, "knife"), (50, "spoon"), (51, "bowl"), (52, "banana"), (53, "apple"),
    (54, "sandwich"), (55, "orange"), (56, "broccoli"), (57, "carrot"), (58, "hot dog"),
    (59, "pizza"), (60, "donut"), (61, "cake"), (62, "chair"), (63, "couch"),
    (64, "potted plant"), (65, "bed"), (67, "dining table"), (70, "toilet"), (72, "tv"),
    (73, "laptop"), (74, "mouse"), (75, "remote"), (76, "keyboard"), (77, "cell phone"),
    (78, "microwave"), (79, "oven"), (80, "toaster"), (81, "sink"), (82, "refrigerator"),
    (84, "book"), (85, "clock"), (86, "vase"), (87, "scissors"), (88, "teddy bear"),
    (89, "hair drier"), (90, "toothbrush"),
)
HOT_CONCEPTS = ("bird nest", "clock")
HOT_FLOORS = (0.01, 0.03)
PACE_NICE = {"slow": 19, "medium": 8, "max": 0}


def default_binary() -> Path:
    override = os.environ.get("VISION_OBJECT_BINARY")
    if override:
        return Path(override)
    return Path.home() / "Library/Application Support/VISION/object-runtime/vision-object"


def default_model_dir() -> Path:
    override = os.environ.get("VISION_OBJECT_MODEL_DIR")
    if override:
        return Path(override)
    return Path.home() / "Library/Application Support/VISION/models/object-hybrid-v1"


def default_work_dir() -> Path:
    override = os.environ.get("VISION_COMMUNITY_OBJECT_WORK")
    if override:
        return Path(override)
    return Path.home() / "Library/Application Support/vision-community/object-index"


def class_file_name(class_id: int, name: str) -> str:
    return f"class-{int(class_id):02d}-{name.replace(' ', '-')}.bin"


def hot_file_name(concept_id: int, name: str) -> str:
    return f"hot-{int(concept_id):02d}-{name.replace(' ', '-')}.bin"


def storage_floor(class_id: int) -> float:
    if class_id in {5, 16, 17}:
        return 0.01
    if class_id in {2, 10, 11, 13, 14, 18, 27, 28, 64} or 31 <= class_id <= 61 or 73 <= class_id <= 77 or 84 <= class_id <= 90:
        return 0.03
    return 0.05


def global_id_record(global_id: int) -> bytes:
    body = int(global_id).to_bytes(8, "little")
    checksum = zlib.crc32(body) & 0xFFFFFFFF
    return body + checksum.to_bytes(4, "little")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source_id_for(lease_id: str) -> str:
    if not isinstance(lease_id, str) or len(lease_id) != 32 or any(ch not in "0123456789abcdef" for ch in lease_id):
        raise VisionIndexError("invalid_lease")
    return f"community-{lease_id}"


def object_tsv_lines(items: list[dict], *, global_start: int = GLOBAL_START) -> list[str]:
    ordered = sorted(items, key=lambda item: int(item["locationId"]))
    lines = []
    for offset, item in enumerate(ordered):
        lines.append(location_tsv_line(item) + "\t" + str(int(global_start) + offset))
    if not lines:
        raise VisionIndexError("no_locations")
    return lines


def write_object_tsv(items: list[dict], path: Path, *, global_start: int = GLOBAL_START) -> int:
    assert_not_live_vision_path(path)
    lines = object_tsv_lines(items, global_start=global_start)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def index_segment_arguments(
    *,
    model_dir: Path,
    source_tsv: Path,
    output_dir: Path,
    source_id: str,
    total: int,
    global_start: int,
    model_cache: Path,
) -> list[str]:
    model_dir = Path(model_dir)
    return [
        "index-segment",
        "--model", str(model_dir / "rfdetr-medium-576-b4.onnx"),
        "--model-manifest", str(model_dir / "object-model.json"),
        "--runtime-manifest", str(model_dir / "hybrid-object-runtime.json"),
        "--source-tsv", str(source_tsv),
        "--output-dir", str(output_dir),
        "--source-id", source_id,
        "--total-locations", str(int(total)),
        "--global-start", str(int(global_start)),
        "--duty-cycle-percent", str(DUTY_CYCLE_PERCENT),
        "--checkpoint-every", str(CHECKPOINT_EVERY),
        "--model-cache", str(model_cache),
    ]


def verify_arguments(
    *,
    source_tsv: Path,
    output_dir: Path,
    source_id: str,
    total: int,
    global_start: int,
    full: bool = False,
) -> list[str]:
    args = [
        "verify-index",
        "--source-tsv", str(source_tsv),
        "--index-dir", str(output_dir),
        "--manifest", str(Path(output_dir) / "manifest.json"),
        "--source-id", source_id,
        "--global-start", str(int(global_start)),
        "--indexed-locations", str(int(total)),
    ]
    if full:
        args.append("--full")
    return args


def _near(left, right, tolerance: float = 1e-5) -> bool:
    try:
        return math.isfinite(float(left)) and math.isfinite(float(right)) and abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def _item_id(item: dict) -> int:
    value = item.get("locationId", item.get("id"))
    if type(value) is not int:
        raise VisionIndexError("invalid_location")
    return value


def _item_pano(item: dict) -> str:
    pano = item.get("panoId") or item.get("assetId") or item.get("asset_id") or ""
    return str(pano)


def _item_lat(item: dict):
    return item.get("lat")


def _item_lng(item: dict):
    return item["lng"] if item.get("lng") is not None else item.get("lon")


def manifest_file_names(manifest: dict) -> list[str]:
    names = []
    for key in ("offsets", "metadata", "globalIds", "semantic"):
        entry = manifest.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("file"), str):
            names.append(entry["file"])
    for key in ("classes", "hotConcepts"):
        for entry in manifest.get(key) or []:
            if isinstance(entry, dict) and isinstance(entry.get("file"), str):
                names.append(entry["file"])
    quality = manifest.get("viewQuality")
    if isinstance(quality, dict) and isinstance(quality.get("file"), str):
        names.append(quality["file"])
    return names


def _safe_name(name: str) -> bool:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return False
    return all(ch.isalnum() or ch in ".-" for ch in name) and name.endswith(".bin")


def _file_entry(
    entry: dict,
    *,
    file_name: str,
    records: int,
    record_bytes: int,
    payload: bytes,
    require_record_bytes: bool = True,
) -> None:
    if entry.get("file") != file_name or entry.get("records") != records:
        raise VisionIndexError("verification_failed")
    # Class and hot-concept lanes store the size in bytes only. VISION's
    # manifest does not repeat recordBytes on those entries.
    stated = entry.get("recordBytes")
    if require_record_bytes:
        if stated != record_bytes:
            raise VisionIndexError("verification_failed")
    elif stated not in (None, record_bytes):
        raise VisionIndexError("verification_failed")
    expected = records * record_bytes
    if entry.get("bytes") != expected or len(payload) != expected:
        raise VisionIndexError("verification_failed")
    digest = entry.get("sha256")
    if not isinstance(digest, str) or digest != sha256_hex(payload):
        raise VisionIndexError("verification_failed")


def validate_object_index(
    manifest: dict,
    files: dict[str, bytes],
    source_tsv: bytes,
    items: list[dict],
    *,
    lease_id: str,
    global_start: int = GLOBAL_START,
) -> list[dict]:
    """Check a finished object index against the VISION v4 hybrid contract."""
    if not isinstance(manifest, dict) or not isinstance(files, dict):
        raise VisionIndexError("verification_failed")
    ordered = sorted(items, key=_item_id)
    total = len(ordered)
    if total < 1:
        raise VisionIndexError("verification_failed")
    source_id = source_id_for(lease_id)
    source_path = manifest.get("sourceTsv")
    if not isinstance(source_path, str) or not source_path:
        raise VisionIndexError("verification_failed")
    assert_not_live_vision_path(Path(source_path))
    contracts = manifest.get("contractVersions")
    if not isinstance(contracts, dict):
        raise VisionIndexError("verification_failed")
    expected_contracts = {
        "manifest": 4,
        "checkpoint": 4,
        "commonRecord": 3,
        "hotRecord": 1,
        "semanticRecord": 1,
        "metadataRecord": 1,
        "offsets": 1,
        "globalIds": 1,
    }
    if any(contracts.get(key) != value for key, value in expected_contracts.items()):
        raise VisionIndexError("verification_failed")
    if (
        manifest.get("version") != 4
        or manifest.get("feature") != OBJECT_FEATURE
        or manifest.get("architecture") != OBJECT_ARCHITECTURE
        or manifest.get("completed") is not True
        or manifest.get("sourceId") != source_id
        or manifest.get("modelSha256") != COMMON_MODEL_SHA256
        or manifest.get("runtimeIdentity") != RUNTIME_IDENTITY
        or manifest.get("rankingStrategy") != OBJECT_RANKING
        or manifest.get("viewStrategy") != "six-face-cube"
        or manifest.get("coverage") != OBJECT_COVERAGE
        or manifest.get("positionPolicy") != OBJECT_POSITION_POLICY
        or manifest.get("globalIdMode") != OBJECT_GLOBAL_MODE
        or manifest.get("imageSize") != 640
        or manifest.get("tileGrid") != 2
        or not _near(manifest.get("tileOverlap"), 0.2)
        or not _near(manifest.get("minimumRelativeClassScore"), 0.25)
        or not _near(manifest.get("smallObjectRelativeClassScore"), 0)
        or not _near(manifest.get("fullTileArtifactThreshold"), 0.98)
        or manifest.get("viewCount") != 6
        or manifest.get("faceSize") != 640
        or not _near(manifest.get("faceFov"), 90)
        or manifest.get("bandsPerFace") != 3
        or manifest.get("bandWidth") != 600
        or manifest.get("bandHeight") != 280
        or not _near(manifest.get("bandOffset"), 24)
        or not _near(manifest.get("bandFov"), 90)
        or manifest.get("recordBytes") != RECORD_BYTES
        or manifest.get("totalLocations") != total
        or manifest.get("indexedLocations") != total
        or manifest.get("globalStart") != int(global_start)
        or manifest.get("minimumGlobalLocation") != int(global_start)
        or manifest.get("maximumGlobalLocation") != int(global_start) + total - 1
        or manifest.get("sourceBytes") != len(source_tsv)
        or manifest.get("sourceSha256") != sha256_hex(source_tsv)
    ):
        raise VisionIndexError("verification_failed")
    if manifest.get("viewQuality") in (None, {}):
        if manifest.get("permanentlyInvalidLocations") not in (None, 0):
            raise VisionIndexError("verification_failed")
    countries = manifest.get("countries")
    if not isinstance(countries, list) or not countries or len(set(countries)) != len(countries):
        raise VisionIndexError("verification_failed")
    lines = [line for line in source_tsv.decode("utf-8").splitlines() if line.strip()]
    if len(lines) != total:
        raise VisionIndexError("verification_failed")
    tsv_countries = []
    expected_ids = []
    for offset, (line, item) in enumerate(zip(lines, ordered)):
        fields = line.split("\t")
        if len(fields) != 12 or fields[7] != _item_pano(item):
            raise VisionIndexError("verification_failed")
        if not _near(fields[2], _item_lat(item)) or not _near(fields[3], _item_lng(item)):
            raise VisionIndexError("verification_failed")
        global_id = int(global_start) + offset
        if fields[11] != str(global_id):
            raise VisionIndexError("verification_failed")
        expected_ids.append(global_id)
        if fields[8] and fields[8] not in tsv_countries:
            tsv_countries.append(fields[8])
    if not tsv_countries:
        tsv_countries = [""]
    if set(countries) != set(tsv_countries):
        raise VisionIndexError("verification_failed")
    for name in files:
        if not _safe_name(name):
            raise VisionIndexError("verification_failed")
    named = set(manifest_file_names(manifest))
    if set(files) != named:
        raise VisionIndexError("verification_failed")
    _file_entry(manifest["offsets"], file_name="location-offsets.bin", records=total, record_bytes=8, payload=files["location-offsets.bin"])
    _file_entry(manifest["metadata"], file_name="location-metadata.bin", records=total, record_bytes=8, payload=files["location-metadata.bin"])
    global_ids = files["global-location-ids.bin"]
    _file_entry(
        manifest["globalIds"],
        file_name="global-location-ids.bin",
        records=total,
        record_bytes=GLOBAL_ID_BYTES,
        payload=global_ids,
    )
    outputs = []
    for offset, global_id in enumerate(expected_ids):
        record = global_ids[offset * GLOBAL_ID_BYTES : (offset + 1) * GLOBAL_ID_BYTES]
        if record != global_id_record(global_id):
            raise VisionIndexError("verification_failed")
        outputs.append({
            "locationId": _item_id(ordered[offset]),
            "outputSha256": sha256_hex(record),
            "model": OBJECT_INDEX_MODEL,
        })
    classes = manifest.get("classes")
    if not isinstance(classes, list) or len(classes) != len(OBJECT_CLASSES):
        raise VisionIndexError("verification_failed")
    for entry, (class_id, name) in zip(classes, OBJECT_CLASSES):
        file_name = class_file_name(class_id, name)
        payload = files.get(file_name)
        if payload is None or entry.get("id") != class_id or entry.get("name") != name:
            raise VisionIndexError("verification_failed")
        if not _near(entry.get("storageFloor"), storage_floor(class_id)):
            raise VisionIndexError("verification_failed")
        records = entry.get("records")
        if type(records) is not int or records < 0:
            raise VisionIndexError("verification_failed")
        _file_entry(
            entry,
            file_name=file_name,
            records=records,
            record_bytes=RECORD_BYTES,
            payload=payload,
            require_record_bytes=False,
        )
    hot = manifest.get("hotConcepts")
    if not isinstance(hot, list) or len(hot) != len(HOT_CONCEPTS):
        raise VisionIndexError("verification_failed")
    for concept_id, (entry, name, floor) in enumerate(zip(hot, HOT_CONCEPTS, HOT_FLOORS)):
        file_name = hot_file_name(concept_id, name)
        payload = files.get(file_name)
        if payload is None or entry.get("id") != concept_id or entry.get("name") != name:
            raise VisionIndexError("verification_failed")
        if not _near(entry.get("storageFloor"), floor):
            raise VisionIndexError("verification_failed")
        records = entry.get("records")
        if type(records) is not int or records < 0:
            raise VisionIndexError("verification_failed")
        _file_entry(
            entry,
            file_name=file_name,
            records=records,
            record_bytes=RECORD_BYTES,
            payload=payload,
            require_record_bytes=False,
        )
    semantic = manifest.get("semantic")
    semantic_records = total * SEMANTIC_PROPOSALS
    semantic_payload = files.get("semantic-pq128.bin")
    if not isinstance(semantic, dict) or semantic_payload is None:
        raise VisionIndexError("verification_failed")
    if (
        semantic.get("codec") != "PQ128"
        or semantic.get("codebookSha256") != CODEBOOK_SHA256
        or semantic.get("embeddingDimensions") != 512
        or semantic.get("proposalsPerLocation") != SEMANTIC_PROPOSALS
    ):
        raise VisionIndexError("verification_failed")
    _file_entry(
        semantic,
        file_name="semantic-pq128.bin",
        records=semantic_records,
        record_bytes=SEMANTIC_RECORD_BYTES,
        payload=semantic_payload,
    )
    quality = manifest.get("viewQuality")
    if isinstance(quality, dict) and quality:
        payload = files.get(quality.get("file"))
        records = quality.get("records")
        record_bytes = quality.get("recordBytes")
        if payload is None or records != total or record_bytes != 8:
            raise VisionIndexError("verification_failed")
        _file_entry(quality, file_name=quality["file"], records=total, record_bytes=8, payload=payload)
    return outputs


def encode_object_submission(manifest: dict, files: dict[str, bytes], source_tsv: bytes) -> dict:
    return {
        "manifest": manifest,
        "sourceTsv": base64.b64encode(source_tsv).decode("ascii"),
        "files": {name: base64.b64encode(payload).decode("ascii") for name, payload in files.items()},
    }


def decode_object_submission(payload: dict) -> tuple[dict, dict[str, bytes], bytes]:
    if not isinstance(payload, dict) or not isinstance(payload.get("manifest"), dict):
        raise VisionIndexError("verification_failed")
    try:
        source_tsv = base64.b64decode(payload.get("sourceTsv") or "", validate=True)
    except (ValueError, TypeError) as error:
        raise VisionIndexError("verification_failed") from error
    encoded = payload.get("files")
    if not isinstance(encoded, dict):
        raise VisionIndexError("verification_failed")
    files = {}
    total = 0
    for name, value in encoded.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise VisionIndexError("verification_failed")
        try:
            blob = base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as error:
            raise VisionIndexError("verification_failed") from error
        total += len(blob)
        if total > 32_000_000:
            raise VisionIndexError("verification_failed")
        files[name] = blob
    return payload["manifest"], files, source_tsv


def _read_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def object_index_is_complete(index_dir: Path, total: int) -> bool:
    manifest = _read_json(Path(index_dir) / "manifest.json")
    if manifest and manifest.get("completed") is True and manifest.get("indexedLocations") == total:
        return True
    checkpoint = _read_json(Path(index_dir) / "checkpoint.json")
    if not checkpoint or checkpoint.get("feature") != OBJECT_FEATURE:
        return False
    try:
        cursor = int(checkpoint.get("nextLocationIndex") or 0)
    except (TypeError, ValueError):
        return False
    return checkpoint.get("completed") is True and cursor >= total


def _require_binary(program: Path, model_dir: Path) -> None:
    if not program.is_file() or not os.access(program, os.X_OK):
        raise VisionIndexError("vision_binary_missing")
    for name in ("rfdetr-medium-576-b4.onnx", "object-model.json", "hybrid-object-runtime.json"):
        if not (model_dir / name).is_file():
            raise VisionIndexError("vision_binary_missing")


def index_object_tsv(
    source_tsv: Path,
    *,
    output_dir: Path,
    source_id: str,
    total: int,
    global_start: int = GLOBAL_START,
    pace: str = "slow",
    binary: Path | None = None,
    model_dir: Path | None = None,
    model_cache: Path | None = None,
    runner=None,
    use_nice: bool = True,
) -> None:
    if pace not in PACE_NICE:
        raise VisionIndexError("invalid_pace")
    source_tsv = Path(source_tsv)
    output_dir = Path(output_dir)
    cache = Path(model_cache) if model_cache is not None else output_dir.parent / "coreml-cache"
    for path in (source_tsv, output_dir, cache):
        assert_not_live_vision_path(path)
    program = Path(binary) if binary is not None else default_binary()
    model = Path(model_dir) if model_dir is not None else default_model_dir()
    assert_not_live_vision_path(program)
    if runner is None:
        _require_binary(program, model)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    active = runner or _default_runner
    env = os.environ.copy()
    env["TMPDIR"] = str(output_dir.parent)
    nice_level = PACE_NICE[pace]
    restarts = 0
    while not object_index_is_complete(output_dir, total):
        before = _read_json(output_dir / "checkpoint.json")
        try:
            run_binary(
                program,
                index_segment_arguments(
                    model_dir=model,
                    source_tsv=source_tsv,
                    output_dir=output_dir,
                    source_id=source_id,
                    total=total,
                    global_start=global_start,
                    model_cache=cache,
                ),
                env=env,
                cwd=output_dir.parent,
                runner=active,
                nice_level=nice_level,
                use_nice=use_nice and runner is None,
            )
        except VisionIndexError:
            restarts += 1
            if runner is not None and restarts >= 5:
                raise
            print("still indexing; the VISION object indexer paused and will resume", file=sys.stderr, flush=True)
            if runner is None:
                time.sleep(min(900, restarts * 5))
            continue
        if object_index_is_complete(output_dir, total):
            break
        after = _read_json(output_dir / "checkpoint.json")
        moved = (after or {}).get("nextLocationIndex") != (before or {}).get("nextLocationIndex")
        restarts = 0 if moved else restarts + 1
        if runner is not None and restarts >= 5:
            raise VisionIndexError("vision_binary_failed")
        print("still indexing; resuming from the last saved place", file=sys.stderr, flush=True)
        if runner is None and not moved:
            time.sleep(min(900, max(1, restarts) * 5))
    for full in (False, True):
        stdout, _stderr = run_binary(
            program,
            verify_arguments(
                source_tsv=source_tsv,
                output_dir=output_dir,
                source_id=source_id,
                total=total,
                global_start=global_start,
                full=full,
            ),
            env=env,
            cwd=output_dir.parent,
            runner=active,
            nice_level=nice_level,
            use_nice=False,
        )
        start = stdout.find("{")
        end = stdout.rfind("}")
        try:
            report = json.loads(stdout[start : end + 1]) if start >= 0 else {}
        except json.JSONDecodeError as error:
            raise VisionIndexError("vision_binary_failed") from error
        if report.get("valid") is not True or report.get("indexVersion") != 4:
            raise VisionIndexError("verification_failed")
        if full and report.get("full") is not True:
            raise VisionIndexError("verification_failed")


def _default_runner(argv: list[str], env: dict, cwd: Path):
    import subprocess

    completed = subprocess.run(argv, env=env, cwd=str(cwd), capture_output=True, text=True, check=False)
    return completed.returncode, completed.stdout, completed.stderr


def load_indexed_files(index_dir: Path) -> tuple[dict, dict[str, bytes]]:
    manifest = _read_json(Path(index_dir) / "manifest.json")
    if not manifest:
        raise VisionIndexError("verification_failed")
    files = {}
    for name in manifest_file_names(manifest):
        path = Path(index_dir) / name
        assert_not_live_vision_path(path)
        try:
            files[name] = path.read_bytes()
        except OSError as error:
            raise VisionIndexError("verification_failed") from error
    return manifest, files


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
) -> dict:
    if pace not in PACE_NICE:
        raise VisionIndexError("invalid_pace")
    if batches is not None and batches < 1:
        raise VisionIndexError("invalid_batch")
    work_dir = Path(work_dir)
    assert_not_live_vision_path(work_dir)
    size = count if count is not None else CLI_LEASE_CAP["object"][pace]
    session = client or CommunityClient(url)
    stored = load_session(session_path, url) if session_path is not None else None
    if not recovery_code:
        recovery_code = os.environ.get("VISION_COMMUNITY_RECOVERY") or None
    if not recovery_code and stored:
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
    stalls = 0
    batch_failures = 0
    while batches is None or processed < batches:
        try:
            lease = session.lease("object", size, pace, part=part)
        except ContributeError as error:
            if error.code == "no_available_work":
                break
            if batches is not None or error.code not in RETRYABLE_CODES:
                raise VisionIndexError(error.code, error.status) from error
            stalls += 1
            print(f"still indexing; retrying after {error.code}", file=sys.stderr, flush=True)
            time.sleep(min(60, stalls * 2))
            continue
        stalls = 0
        lease_id = str(lease.get("leaseId") or "")
        items = lease.get("items") if isinstance(lease.get("items"), list) else []
        run_dir = work_dir / lease_id
        stop = threading.Event()
        beater = threading.Thread(target=keep_lease_alive, args=(session, lease_id, stop), daemon=True)
        beater.start()
        try:
            source_id = source_id_for(lease_id)
            tsv_path = run_dir / "locations.tsv"
            total = write_object_tsv(items, tsv_path, global_start=GLOBAL_START)
            index_dir = run_dir / "index"
            index_object_tsv(
                tsv_path,
                output_dir=index_dir,
                source_id=source_id,
                total=total,
                global_start=GLOBAL_START,
                pace=pace,
                binary=binary,
                model_dir=model_dir,
                model_cache=work_dir / "coreml-cache",
                runner=runner,
                use_nice=use_nice,
            )
            manifest, files = load_indexed_files(index_dir)
            source_tsv = tsv_path.read_bytes()
            outputs = validate_object_index(
                manifest, files, source_tsv, items, lease_id=lease_id, global_start=GLOBAL_START
            )
            try:
                session.renew(lease_id)
            except ContributeError:
                pass
            result = session.submit_object(lease_id, outputs, encode_object_submission(manifest, files, source_tsv))
        except VisionIndexError:
            stop.set()
            try:
                session.release(lease_id)
            except ContributeError:
                pass
            raise
        except Exception as error:
            stop.set()
            code = error.code if isinstance(error, ContributeError) else ""
            skip = batches is None and batch_failures >= 2 and code in {"", "verification_failed"}
            try:
                session.release(lease_id, skip=skip)
            except ContributeError:
                pass
            if batches is not None:
                raise
            batch_failures += 1
            stalls += 1
            print("still indexing; the last batch will be tried again", file=sys.stderr, flush=True)
            time.sleep(min(60, stalls * 2))
            continue
        finally:
            stop.set()
        batch_failures = 0
        accepted += int(result.get("accepted") or 0)
        units += int(result.get("unitsEarned") or 0)
        processed += 1
        print(f"indexed batch {processed}", file=sys.stderr, flush=True)
    report = {
        "ok": True,
        "model": OBJECT_INDEX_MODEL,
        "lane": "object",
        "pace": pace,
        "batches": processed,
        "accepted": accepted,
        "unitsEarned": units,
    }
    if created is not None:
        report["accountId"] = created.get("accountId")
        report["recoveryCode"] = created.get("recoveryCode")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--pace", choices=tuple(PACE_NICE), default="slow")
    parser.add_argument("--count", type=int)
    parser.add_argument("--batches", type=int)
    parser.add_argument("--part", type=int)
    parser.add_argument("--recovery-code", dest="recovery_code")
    parser.add_argument("--session-file", type=Path, dest="session_file")
    parser.add_argument("--no-save-session", action="store_true")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--model-dir", type=Path, dest="model_dir")
    parser.add_argument("--work-dir", type=Path, dest="work_dir")
    args = parser.parse_args()
    try:
        report = index_from_queue(
            url=args.url,
            pace=args.pace,
            batches=args.batches,
            count=args.count,
            part=args.part,
            recovery_code=args.recovery_code,
            work_dir=args.work_dir or default_work_dir(),
            session_path=args.session_file or default_session_path(),
            persist_session=not args.no_save_session,
            binary=args.binary,
            model_dir=args.model_dir,
        )
    except VisionIndexError as error:
        print(error.code, file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps({key: value for key, value in report.items() if key != "recoveryCode"}))


if __name__ == "__main__":
    main()
