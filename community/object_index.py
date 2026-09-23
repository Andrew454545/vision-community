"""Index objects with the same program the VISION app uses.

The browser cannot run that model. This command shells out to
`vision-object index-segment`: the same 12-column TSV, the same hybrid
runtime (RF-DETR Medium, YOLOE-26L, OWLv2 PQ128), and the same version-4
six-face index.

It will not write the live VISION segment files, scheduled TSV, checkpoint,
or the CoreML cache that index is using. Finished community indexes are
added to the local app's object catalog beside the official sources. Pace
only changes process priority. The duty cycle stays at 25 percent, which is
the VISION object indexer's duty.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import secrets
import shutil
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
    community_support_root,
    keep_lease_alive,
    location_tsv_line,
    program_name,
    run_binary,
    vision_support_root,
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
COMMUNITY_GLOBAL_BASE = 2**32
COMMUNITY_GLOBAL_STRIDE = 2**16
OBJECT_CAPABILITIES = [
    "common",
    "hot",
    "semantic",
    "exactAim",
    "fullSphere",
    "explicitGlobalIds",
]
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


def installed_object_binary() -> Path:
    if sys.platform == "win32":
        return vision_support_root() / "bin" / program_name("vision-object")
    return vision_support_root() / "object-runtime" / program_name("vision-object")


def object_uses_cpu(platform_name: str | None = None) -> bool:
    """Mac builds include CoreML. Windows and Linux builds run the same models on CPU."""
    return (sys.platform if platform_name is None else platform_name) != "darwin"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def running_indexer_executable(lines) -> Path | None:
    """Return the vision-object that is already indexing on this computer."""
    found = None
    for line in lines:
        if "index-segment" not in line or "vision-object" not in line:
            continue
        for part in line.split():
            name = Path(part).name.lower()
            if name not in ("vision-object", "vision-object.exe"):
                continue
            if "vision-community" in part:
                continue
            found = Path(part)
    return found


def process_commands() -> list[str]:
    import subprocess

    try:
        completed = subprocess.run(
            ["ps", "-axww", "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    return completed.stdout.splitlines()


def copy_object_binary(source: Path) -> Path:
    """Copy a running indexer out of its live folder so Community can execute it."""
    source = Path(source)
    digest = file_sha256(source)
    destination_dir = community_support_root() / "bin"
    destination = destination_dir / f"vision-object-{digest[:16]}"
    if destination.is_file() and file_sha256(destination) == digest:
        return destination
    destination_dir.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    shutil.copy2(source, temporary)
    temporary.chmod(0o755)
    os.replace(temporary, destination)
    return destination


def default_binary() -> Path:
    override = os.environ.get("VISION_OBJECT_BINARY")
    if override:
        return Path(override)
    installed = installed_object_binary()
    running = running_indexer_executable(process_commands())
    if running is None or not running.is_file():
        return installed
    try:
        if installed.is_file() and running.resolve() == installed.resolve():
            return installed
    except OSError:
        pass
    if installed.is_file() and file_sha256(running) == file_sha256(installed):
        return installed
    try:
        return copy_object_binary(running)
    except OSError:
        return installed


def default_model_dir() -> Path:
    override = os.environ.get("VISION_OBJECT_MODEL_DIR")
    if override:
        return Path(override)
    return vision_support_root() / "models/object-hybrid-v1"


def default_work_dir() -> Path:
    override = os.environ.get("VISION_COMMUNITY_OBJECT_WORK")
    if override:
        return Path(override)
    return community_support_root() / "object-index"


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
    arguments = [
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
    if object_uses_cpu():
        arguments.append("--cpu")
    return arguments


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
    if runner is None and processed:
        _publish_finished_object_indexes([work_dir, default_shared_dir()])
    return report


CONFIDENCE_FLOORS = {"highRecall": 0.03, "balanced": 0.08, "precise": 0.20}
CLASS_ALIASES = {
    1: ("people", "human", "humans"),
    2: ("bike", "bikes", "cycle", "cycles"),
    3: ("automobile", "automobiles", "vehicle", "vehicles"),
    4: ("motorbike", "motorbikes"),
    5: ("plane", "planes", "aircraft", "aeroplane", "aeroplanes", "jet", "jets"),
    16: ("birds",),
    17: ("cats", "kitten", "kittens"),
    18: ("dogs", "puppy", "puppies"),
    37: ("ball", "balls"),
    63: ("sofa", "sofas"),
    64: ("plant", "plants", "houseplant", "houseplants"),
    72: ("television", "televisions"),
    77: ("phone", "phones", "smartphone", "smartphones", "mobile phone"),
    82: ("fridge", "fridges"),
    89: ("hair dryer", "hair dryers"),
}
HOT_ALIASES = (
    ("bird nest", "bird nests", "nest", "nests"),
    ("clock", "clocks"),
)
QUERY_GLUE = frozenset({
    "a", "an", "and", "anywhere", "find", "me", "object", "objects", "or",
    "pano", "panorama", "show", "the", "things",
})
PLURAL_EXCEPTIONS = {"person": "people", "mouse": "mice", "sheep": "sheep", "knife": "knives"}


def default_shared_dir() -> Path:
    override = os.environ.get("VISION_COMMUNITY_SHARED_INDEX")
    if override:
        return Path(override)
    return community_support_root() / "shared-index/objects"


def _plural(name: str) -> str:
    if name in PLURAL_EXCEPTIONS:
        return PLURAL_EXCEPTIONS[name]
    if name.endswith(("ch", "sh", "s", "x", "z")):
        return name + "es"
    if name.endswith("y") and len(name) > 1 and name[-2] not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


def _class_phrases(class_id: int, name: str) -> tuple[str, ...]:
    return (name, _plural(name), *CLASS_ALIASES.get(class_id, ()))


def _normalized_prompt(prompt: str) -> str:
    flattened = "".join(character if character.isalnum() else " " for character in prompt.lower())
    return " ".join(flattened.split())


def query_plan(prompt: str) -> dict:
    """Route an object prompt the same way VISION does."""
    text = prompt.strip()
    normalized = _normalized_prompt(text)
    for concept_id, phrases in enumerate(HOT_ALIASES):
        if normalized in phrases:
            return {"route": "hot", "classIds": [], "hotConceptId": concept_id, "semanticText": None}
    remaining = f" {normalized} "
    phrases = []
    for class_id, name in OBJECT_CLASSES:
        for phrase in _class_phrases(class_id, name):
            phrases.append((phrase, class_id))
    phrases.sort(key=lambda item: (-len(item[0].split()), item[0]))
    found = set()
    for phrase, class_id in phrases:
        needle = f" {phrase} "
        if needle in remaining:
            found.add(class_id)
            remaining = remaining.replace(needle, " ")
    leftover = set(remaining.split())
    if found and leftover <= QUERY_GLUE:
        return {
            "route": "common",
            "classIds": [class_id for class_id, _name in OBJECT_CLASSES if class_id in found],
            "hotConceptId": None,
            "semanticText": None,
        }
    return {"route": "semantic", "classIds": [], "hotConceptId": None, "semanticText": text}


def discover_object_sources(root: Path) -> list[dict]:
    root = Path(root)
    manifests = []
    direct = root / "manifest.json"
    if direct.is_file():
        manifests.append(direct)
    if root.is_dir():
        for child in sorted(root.iterdir()):
            for candidate in (child / "manifest.json", child / "index" / "manifest.json"):
                if candidate.is_file():
                    manifests.append(candidate)
    sources = []
    seen = set()
    for manifest_path in manifests:
        if manifest_path in seen:
            continue
        seen.add(manifest_path)
        manifest = _read_json(manifest_path)
        if not manifest or manifest.get("completed") is not True:
            continue
        index_dir = manifest_path.parent
        source_tsv = index_dir / "locations.tsv"
        if not source_tsv.is_file():
            parent_tsv = index_dir.parent / "locations.tsv"
            source_tsv = parent_tsv if parent_tsv.is_file() else source_tsv
        if not source_tsv.is_file():
            continue
        for path in (manifest_path, index_dir, source_tsv):
            assert_not_live_vision_path(path)
        sources.append({
            "id": str(manifest.get("sourceId") or index_dir.name),
            "sourceTsv": str(source_tsv),
            "indexDir": str(index_dir),
            "manifestPath": str(manifest_path),
            "globalStart": int(manifest.get("globalStart") or 0),
            "indexedLocations": int(manifest.get("indexedLocations") or 0),
        })
    return [source for source in sources if source["indexedLocations"] > 0]


def object_search_input(
    prompt: str,
    sources: list[dict],
    *,
    confidence: str = "balanced",
    result_count: int = 200,
    max_per_country: int = 25,
    country_mode: str = "all",
    countries: list[str] | None = None,
    camera_generations: list[str] | None = None,
    reject_road_names: bool = False,
    minimum_global_location: int | None = None,
    output_name: str = "",
    model_dir: Path,
    model_cache: Path,
) -> dict:
    if confidence not in CONFIDENCE_FLOORS:
        raise VisionIndexError("invalid_confidence")
    plan = query_plan(prompt)
    if not prompt.strip():
        raise VisionIndexError("invalid_query")
    names = [item for item in (countries or []) if item]
    requested = max(1, int(result_count))
    per_country = max(1, int(max_per_country))
    candidate_count = requested if per_country >= requested else min(10000, requested * 4)
    query = {
        "name": output_name.strip() or "VISION Community",
        "query": prompt.strip(),
        "classIds": plan["classIds"],
        "route": plan["route"],
        "hotConceptId": plan["hotConceptId"],
        "semanticText": plan["semanticText"],
        "minimumConfidence": CONFIDENCE_FLOORS[confidence],
        "resultCount": candidate_count,
        "cameraGenerations": list(camera_generations or []),
        "includeCountries": names if country_mode == "include" else [],
        "excludeCountries": names if country_mode == "exclude" else [],
        "rejectRoadNames": bool(reject_road_names),
    }
    if minimum_global_location is not None:
        query["minimumGlobalLocation"] = int(minimum_global_location)
    return {
        "contractVersion": 2,
        "runId": "vision-community-object-search",
        "queries": [query],
        "sources": sources,
        "resultPruneMeters": 100,
        "runtimeManifest": str(Path(model_dir) / "hybrid-object-runtime.json"),
        "modelCache": str(model_cache),
        "cpu": False,
    }


def map_from_object_search(
    payload: dict,
    *,
    prompt: str,
    output_name: str,
    result_count: int,
    max_per_country: int,
    min_score: float = 0.08,
) -> dict:
    from .features import wrap_heading
    from .mma import build_map, object_model_name, search_location_extra
    from .rank import canonicalize_country, cap_by_country, clamp_max_per_country, clamp_result_count

    queries = payload.get("queries") if isinstance(payload, dict) else None
    query = queries[0] if isinstance(queries, list) and queries and isinstance(queries[0], dict) else {}
    hits = query.get("hits") if isinstance(query.get("hits"), list) else []
    processed = int(payload.get("totalLocations") or 0)
    title = output_name.strip() or (query.get("name") if isinstance(query.get("name"), str) else "") or prompt.strip() or "VISION Community"
    records = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        location = hit.get("location") if isinstance(hit.get("location"), dict) else {}
        found = hit.get("object") if isinstance(hit.get("object"), dict) else {}
        pano = location.get("panoId") or location.get("pano_id") or ""
        if not pano:
            continue
        score = float(hit.get("similarity") or 0)
        source_index = hit.get("locationIndex")
        source_index = int(source_index) if isinstance(source_index, int) else 0
        country = canonicalize_country(str(location.get("country") or ""))
        lane = found.get("lane") if isinstance(found.get("lane"), str) else None
        class_id = found.get("classId")
        records.append({
            "score": score,
            "source_index": source_index,
            "country": country,
            "row": {
                "lat": float(location.get("lat") or 0),
                "lng": float(location.get("lng") or 0),
                "heading": wrap_heading(float(found.get("heading") if found.get("heading") is not None else location.get("heading") or 0)),
                "pitch": float(found.get("pitch") if found.get("pitch") is not None else location.get("pitch") or 0),
                "zoom": float(found.get("zoom") if found.get("zoom") is not None else location.get("zoom") or 0),
                "panoId": str(pano),
                "extra": search_location_extra(
                    country=country,
                    camera_generation=str(location.get("cameraGeneration") or location.get("camera_generation") or ""),
                    score=score,
                    min_score=min_score,
                    rank=1,
                    query_name=title,
                    mode="objects",
                    heading_offset=0,
                    source_index=source_index,
                    processed_locations=processed,
                    model=object_model_name(lane),
                    object_class=found.get("className") if isinstance(found.get("className"), str) else None,
                    object_class_id=int(class_id) if isinstance(class_id, int) else None,
                    object_lane=lane,
                    object_confidence=float(found["confidence"]) if found.get("confidence") is not None else None,
                    object_support=int(found["supportCount"]) if found.get("supportCount") is not None else None,
                    object_box_area=float(found["bboxArea"]) if found.get("bboxArea") is not None else None,
                ),
            },
        })
    records.sort(key=lambda item: (-item["score"], item["source_index"]))
    limited = cap_by_country(
        [item["row"] | {"country": item["country"], "score": item["score"]} for item in records],
        clamp_result_count(result_count),
        clamp_max_per_country(max_per_country),
    )
    coordinates = []
    for rank, item in enumerate(limited, start=1):
        row = {key: value for key, value in item.items() if key not in {"country", "score"}}
        row.setdefault("extra", {})["visionRank"] = rank
        coordinates.append(row)
    return build_map(title, coordinates)


def search_object_indexes(
    sources: list[dict],
    prompt: str,
    *,
    output_dir: Path,
    confidence: str = "balanced",
    result_count: int = 200,
    max_per_country: int = 25,
    country_mode: str = "all",
    countries: list[str] | None = None,
    camera_generations: list[str] | None = None,
    reject_road_names: bool = False,
    minimum_global_location: int | None = None,
    output_name: str = "",
    binary: Path | None = None,
    model_dir: Path | None = None,
    model_cache: Path | None = None,
    runner=None,
) -> dict:
    if not sources:
        raise VisionIndexError("index_missing")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    program = Path(binary) if binary is not None else default_binary()
    model = Path(model_dir) if model_dir is not None else default_model_dir()
    cache = Path(model_cache) if model_cache is not None else output_dir / "coreml-cache"
    assert_not_live_vision_path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    spec = output_dir / "object-search-input.json"
    result_path = output_dir / "object-search-result.json"
    payload = object_search_input(
        prompt,
        sources,
        confidence=confidence,
        result_count=result_count,
        max_per_country=max_per_country,
        country_mode=country_mode,
        countries=countries,
        camera_generations=camera_generations,
        reject_road_names=reject_road_names,
        minimum_global_location=minimum_global_location,
        output_name=output_name,
        model_dir=model,
        model_cache=cache,
    )
    spec.write_text(json.dumps(payload), encoding="utf-8")
    stdout, _stderr = run_binary(
        program,
        ["search", "--input", str(spec), "--output", str(result_path)],
        env=os.environ.copy(),
        cwd=output_dir,
        runner=runner or _default_runner,
        nice_level=19,
        use_nice=runner is None,
    )
    if result_path.is_file():
        report = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        report = json.loads(stdout[stdout.find("{") : stdout.rfind("}") + 1] or "{}")
    return map_from_object_search(
        report,
        prompt=prompt,
        output_name=output_name,
        result_count=result_count,
        max_per_country=max_per_country,
        min_score=CONFIDENCE_FLOORS[confidence],
    )


def import_published_objects(session: CommunityClient, search_id: str, destination: Path) -> int:
    """Download finished object indexes into a folder the object search reads."""
    destination = Path(destination)
    assert_not_live_vision_path(destination)
    catalog = session.object_index_catalog(search_id)
    imported = 0
    for entry in catalog.get("indexes") or []:
        prefix = str(entry.get("prefix") or "")
        lease_id = prefix.strip("/").split("/")[-1]
        target = destination / lease_id
        target.mkdir(parents=True, exist_ok=True)
        for item in entry.get("files") or []:
            key = str(item.get("key") or "")
            name = Path(key).name
            if not name or name.startswith("."):
                continue
            target.joinpath(name).write_bytes(session.object_index_file(search_id, key))
        if (target / "manifest.json").is_file() and (target / "locations.tsv").is_file():
            imported += 1
    return imported


def default_object_registry() -> Path:
    return vision_support_root() / "object-indexes/current.json"


def default_app_object_dir() -> Path:
    override = os.environ.get("VISION_COMMUNITY_APP_OBJECTS")
    if override:
        return Path(override)
    return community_support_root() / "vision-app-objects"


def community_global_start(source_id: str, count: int) -> int:
    """Place a community index above the official corpus without overlapping another lease."""
    lease = source_id.removeprefix("community-")
    if lease == source_id or len(lease) < 9 or any(ch not in "0123456789abcdef" for ch in lease):
        raise VisionIndexError("invalid_lease")
    if count < 1 or count > COMMUNITY_GLOBAL_STRIDE:
        raise VisionIndexError("invalid_lease")
    start = COMMUNITY_GLOBAL_BASE + int(lease[:9], 16) * COMMUNITY_GLOBAL_STRIDE
    if start + count >= 2**53:
        raise VisionIndexError("invalid_lease")
    return start


def restamp_global_ids(tsv: str, records: bytes, old_start: int, new_start: int) -> tuple[str, bytes]:
    if len(records) % 12 != 0:
        raise VisionIndexError("verification_failed")
    rewritten = []
    for offset in range(0, len(records), 12):
        chunk = records[offset : offset + 12]
        old = int.from_bytes(chunk[:8], "little")
        if chunk != global_id_record(old):
            raise VisionIndexError("verification_failed")
        rewritten.append(global_id_record(new_start + (old - int(old_start))))
    lines = []
    for line in tsv.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) < 12:
            raise VisionIndexError("verification_failed")
        old = int(fields[11])
        fields[11] = str(new_start + (old - int(old_start)))
        lines.append("\t".join(fields))
    if len(lines) != len(records) // 12:
        raise VisionIndexError("verification_failed")
    return "\n".join(lines) + "\n", b"".join(rewritten)


def _tsv_column_count(path: Path) -> int:
    with Path(path).open(encoding="utf-8") as handle:
        line = handle.readline()
    if not line.strip():
        return 0
    return len(line.rstrip("\n").split("\t"))


def stage_app_object_index(index_dir: Path, destination_root: Path) -> dict | None:
    """Copy a finished index and give it a global range the official catalog will not use."""
    index_dir = Path(index_dir)
    manifest = _read_json(index_dir / "manifest.json")
    if not manifest or manifest.get("completed") is not True or int(manifest.get("version") or 0) != 4:
        return None
    source_id = str(manifest.get("sourceId") or "")
    count = int(manifest.get("indexedLocations") or 0)
    try:
        new_start = community_global_start(source_id, count)
    except VisionIndexError:
        return None
    source_tsv = index_dir / "locations.tsv"
    if not source_tsv.is_file():
        source_tsv = index_dir.parent / "locations.tsv"
    global_ids = index_dir / "global-location-ids.bin"
    if not source_tsv.is_file() or not global_ids.is_file():
        return None
    for path in (index_dir, source_tsv, destination_root):
        assert_not_live_vision_path(path)
    staged = Path(destination_root) / source_id
    if staged.exists():
        shutil.rmtree(staged)
    staged_index = staged / "index"
    staged_index.mkdir(parents=True)
    for item in index_dir.iterdir():
        if item.is_file() and item.name != "locations.tsv":
            shutil.copy2(item, staged_index / item.name)
    tsv_text, records = restamp_global_ids(
        source_tsv.read_text(encoding="utf-8"),
        global_ids.read_bytes(),
        int(manifest.get("globalStart") or 0),
        new_start,
    )
    staged_tsv = staged / "locations.tsv"
    staged_tsv.write_text(tsv_text, encoding="utf-8")
    (staged_index / "global-location-ids.bin").write_bytes(records)
    staged_manifest_path = staged_index / "manifest.json"
    staged_manifest = json.loads(staged_manifest_path.read_text(encoding="utf-8"))
    tsv_bytes = staged_tsv.read_bytes()
    staged_tsv_path = str(staged_tsv.resolve())
    staged_manifest["sourceTsv"] = staged_tsv_path
    staged_manifest["sourceBytes"] = len(tsv_bytes)
    staged_manifest["sourceSha256"] = sha256_hex(tsv_bytes)
    staged_manifest["globalStart"] = new_start
    staged_manifest["minimumGlobalLocation"] = new_start
    staged_manifest["maximumGlobalLocation"] = new_start + count - 1
    global_meta = staged_manifest.get("globalIds")
    if isinstance(global_meta, dict):
        global_meta["records"] = count
        global_meta["bytes"] = len(records)
        global_meta["sha256"] = sha256_hex(records)
    staged_manifest_path.write_text(json.dumps(staged_manifest, indent=2) + "\n", encoding="utf-8")
    columns = _tsv_column_count(staged_tsv)
    return {
        "id": source_id,
        "label": f"Community {source_id.removeprefix('community-')[:8]}",
        "globalStart": new_start,
        "indexedLocations": count,
        "sourceTsv": staged_tsv_path,
        "indexDir": str(staged_index.resolve()),
        "manifestPath": str(staged_manifest_path.resolve()),
        "sourceColumnCount": columns,
        "cameraMetadataVerified": columns >= 10,
        "roadNamesKnownAbsent": columns < 11,
        "indexVersion": 4,
        "modelIdentity": staged_manifest.get("modelSha256"),
        "runtimeIdentity": staged_manifest.get("runtimeIdentity"),
        "capabilities": list(OBJECT_CAPABILITIES),
    }


def _ranges_overlap(left: dict, right: dict) -> bool:
    left_start = int(left["globalStart"])
    right_start = int(right["globalStart"])
    return left_start < right_start + int(right["indexedLocations"]) and right_start < left_start + int(left["indexedLocations"])


def publish_object_catalog(entries: list[dict], registry_path: Path) -> int:
    registry_path = Path(registry_path)
    if not registry_path.is_file():
        raise VisionIndexError("vision_registry_missing")
    original = registry_path.read_text(encoding="utf-8")
    catalog = json.loads(original)
    sources = catalog.get("sources")
    if catalog.get("version") != 2 or catalog.get("feature") != "vision-object-index" or not isinstance(sources, list):
        raise VisionIndexError("vision_registry_unusable")
    official = [source for source in sources if not str(source.get("id") or "").startswith("community-")]
    accepted = []
    for entry in entries:
        if any(_ranges_overlap(entry, source) for source in official + accepted):
            continue
        accepted.append(entry)
    combined = sorted(official + accepted, key=lambda source: (int(source["globalStart"]), str(source["id"])))
    previous_end = 0
    for source in combined:
        start = int(source["globalStart"])
        count = int(source["indexedLocations"])
        if start < previous_end or count < 1:
            raise VisionIndexError("vision_registry_unusable")
        previous_end = start + count
    catalog["sources"] = combined
    if registry_path.read_text(encoding="utf-8") != original:
        raise VisionIndexError("vision_registry_changed")
    temporary = registry_path.with_name(registry_path.name + ".community-tmp")
    temporary.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, registry_path)
    return len(accepted)


def publish_local_object_indexes(
    roots: list[Path],
    *,
    registry_path: Path | None = None,
    destination: Path | None = None,
) -> int:
    registry = Path(registry_path) if registry_path is not None else default_object_registry()
    folder = Path(destination) if destination is not None else default_app_object_dir()
    assert_not_live_vision_path(folder)
    entries = []
    seen = set()
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        assert_not_live_vision_path(root)
        for source in discover_object_sources(root):
            source_id = source["id"]
            if source_id in seen:
                continue
            seen.add(source_id)
            entry = stage_app_object_index(Path(source["indexDir"]), folder)
            if entry is not None:
                entries.append(entry)
    if not entries:
        return 0
    if registry == default_object_registry():
        backup = folder.parent / "object-registry-backup.json"
        if registry.is_file() and not backup.exists():
            backup.write_bytes(registry.read_bytes())
    return publish_object_catalog(entries, registry)


def _publish_finished_object_indexes(roots: list[Path]) -> None:
    try:
        count = publish_local_object_indexes(roots)
    except VisionIndexError as error:
        print(f"local VISION app was not updated ({error.code})", file=sys.stderr, flush=True)
        return
    if count:
        print(f"added {count} object index{'es' if count != 1 else ''} to the local VISION app", file=sys.stderr, flush=True)


def search_from_account(
    *,
    url: str,
    prompt: str,
    confidence: str = "balanced",
    result_count: int = 200,
    max_per_country: int = 25,
    country_mode: str = "all",
    countries: list[str] | None = None,
    camera_generations: list[str] | None = None,
    reject_road_names: bool = False,
    minimum_global_location: int | None = None,
    output_name: str = "",
    recovery_code: str | None = None,
    work_dir: Path,
    shared_dir: Path,
    session_path: Path | None = None,
    binary: Path | None = None,
    model_dir: Path | None = None,
    runner=None,
    client: CommunityClient | None = None,
) -> dict:
    work_dir = Path(work_dir)
    shared_dir = Path(shared_dir)
    assert_not_live_vision_path(work_dir)
    assert_not_live_vision_path(shared_dir)
    session = client or CommunityClient(url)
    stored = load_session(session_path, url) if session_path is not None else None
    code = recovery_code or os.environ.get("VISION_COMMUNITY_RECOVERY")
    if not code and stored:
        saved = stored.get("recoveryCode")
        code = saved if isinstance(saved, str) and saved else None
    if not code:
        raise VisionIndexError("recovery_code_required")
    session.recover(str(code))
    account = session.me()
    sources = discover_object_sources(work_dir) + discover_object_sources(shared_dir)
    remote = int(account.get("objectIndexes") or 0)
    if not sources and remote <= 0:
        raise VisionIndexError("index_missing")
    if int(account.get("units") or 0) < int(account.get("searchCost") or 100000):
        raise VisionIndexError("insufficient_credit")
    search_dir = work_dir / "search"
    search_dir.mkdir(parents=True, exist_ok=True)
    authorized = None
    if remote:
        authorized = session.authorize_local_search({
            "lane": "object",
            "prompt": prompt,
            "outputName": output_name,
            "resultCount": result_count,
            "maxPerCountry": max_per_country,
            "countryFilterMode": country_mode,
            "countries": list(countries or []),
            "cameraGenerations": list(camera_generations or []),
            "objectConfidence": confidence,
            "idempotencyKey": secrets.token_hex(16),
        })
        import_published_objects(session, str(authorized.get("searchId") or ""), shared_dir)
        sources = discover_object_sources(work_dir) + discover_object_sources(shared_dir)
    document = search_object_indexes(
        sources,
        prompt,
        output_dir=search_dir,
        confidence=confidence,
        result_count=result_count,
        max_per_country=max_per_country,
        country_mode=country_mode,
        countries=countries,
        camera_generations=camera_generations,
        reject_road_names=reject_road_names,
        minimum_global_location=minimum_global_location,
        output_name=output_name,
        binary=binary,
        model_dir=model_dir,
        model_cache=work_dir / "coreml-cache",
        runner=runner,
    )
    if runner is None:
        _publish_finished_object_indexes([work_dir, shared_dir])
    if authorized is None:
        session.authorize_local_search({
            "lane": "object",
            "prompt": prompt,
            "outputName": output_name,
            "resultCount": result_count,
            "maxPerCountry": max_per_country,
            "countryFilterMode": country_mode,
            "countries": list(countries or []),
            "cameraGenerations": list(camera_generations or []),
            "objectConfidence": confidence,
            "idempotencyKey": secrets.token_hex(16),
        })
    return document


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
    parser.add_argument("--search", action="store_true")
    parser.add_argument("--register-local", action="store_true", help="add finished object indexes to the local VISION app")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--confidence", choices=tuple(CONFIDENCE_FLOORS), default="balanced")
    parser.add_argument("--result-count", type=int, default=200)
    parser.add_argument("--max-per-country", type=int, default=25)
    parser.add_argument("--output-name", default="")
    parser.add_argument("--country-mode", choices=("all", "include", "exclude"), default="all")
    parser.add_argument("--countries", default="")
    parser.add_argument("--camera-generations", default="")
    parser.add_argument("--reject-road-names", action="store_true")
    parser.add_argument("--import-cutoff", type=int, default=None)
    args = parser.parse_args()
    work_dir = args.work_dir or default_work_dir()
    try:
        if args.import_cutoff is not None and args.import_cutoff < 0:
            raise VisionIndexError("invalid_query")
        if args.register_local and not args.search:
            registered = publish_local_object_indexes([work_dir, default_shared_dir()])
            print(json.dumps({"ok": True, "registered": registered}))
            return
        if args.search:
            from .mma import dump_map

            countries = [part.strip() for part in args.countries.split(",") if part.strip()]
            cameras = [part.strip() for part in args.camera_generations.split(",") if part.strip()]
            document = search_from_account(
                url=args.url,
                prompt=args.prompt,
                confidence=args.confidence,
                result_count=args.result_count,
                max_per_country=args.max_per_country,
                country_mode=args.country_mode,
                countries=countries,
                camera_generations=cameras,
                reject_road_names=args.reject_road_names,
                minimum_global_location=args.import_cutoff,
                output_name=args.output_name,
                recovery_code=args.recovery_code,
                work_dir=work_dir,
                shared_dir=default_shared_dir(),
                session_path=args.session_file or default_session_path(),
                binary=args.binary,
                model_dir=args.model_dir,
            )
            print(dump_map(document))
            return
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
    except (VisionIndexError, ContributeError) as error:
        print(error.code, file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps({key: value for key, value in report.items() if key != "recoveryCode"}))


if __name__ == "__main__":
    main()
