"""Operator-only, offline sealing of independently approved contributed scenes.

No network, account creation, imagery retrieval, database writes or uploads.
The inventory and approval policy must be pinned through trusted operator
configuration, never supplied by a volunteer or inferred from their checksums.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path

from .four_view import BYTES_PER_LOCATION, BYTES_PER_VIEW, valid_four_view_record
from .scene_quality import ApprovedSceneReferences, SceneQualityError

CONFIRMED_RESOURCE = {
    "accountId": "272760294910ef0b246980278aeb36e2",
    "databaseId": "ed4705fa-1190-41fa-86a0-02d755db1b2a",
    "bucket": "vision-community",
}
CONFIRMED_STAGING_RESOURCE = {
    "accountId": "272760294910ef0b246980278aeb36e2",
    "databaseId": "17043cb7-5dab-4a6f-84ca-19ae1c14cc05",
    "bucket": "vision-community-staging",
}
MAX_LOCATIONS = 100_000
MAX_INVENTORY_BYTES = 64 * 1024 * 1024
MAX_POLICY_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 1000 * BYTES_PER_LOCATION
INVENTORY_SQL = """SELECT l.id,l.asset_id,l.capture,l.lane,l.model,l.state,
 l.contributor_id,l.lat,l.lon,l.heading,l.pitch,l.zoom,l.country,l.camera_generation,
 l.output_sha256 AS location_output_sha256,i.output_sha256,i.four_view_sha256,i.four_view_key
 FROM locations l JOIN published_index i ON i.location_id=l.id
 WHERE l.lane='scene' AND l.state='published'
 AND l.contributor_id IS NOT NULL AND l.contributor_id!=''
 AND i.four_view_key IS NOT NULL AND i.four_view_key!='' ORDER BY l.id"""
HEX = re.compile(r"[0-9a-f]{64}\Z")


class SnapshotError(ValueError):
    pass


def resource_for_environment(environment: str) -> dict:
    """Operator-selected confirmed pair; never inferred from inventory data."""
    if environment == "production":
        return dict(CONFIRMED_RESOURCE)
    if environment == "staging":
        return dict(CONFIRMED_STAGING_RESOURCE)
    raise SnapshotError("invalid_snapshot_environment")


def snapshot_resource(document: dict, environment: str | None = None) -> dict:
    # Older independently sealed v1 snapshots came only from production.
    resource = document.get("resource", CONFIRMED_RESOURCE)
    if resource not in (CONFIRMED_RESOURCE, CONFIRMED_STAGING_RESOURCE):
        raise SnapshotError("invalid_snapshot_resource")
    if environment is not None and resource != resource_for_environment(environment):
        raise SnapshotError("snapshot_environment_mismatch")
    return dict(resource)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def bounded_read(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise SnapshotError("input_too_large")
    return raw


def pinned_read(path: Path, expected: str, limit: int) -> bytes:
    if not isinstance(expected, str) or not HEX.fullmatch(expected):
        raise SnapshotError("invalid_checksum_pin")
    raw = bounded_read(path, limit)
    if digest(raw) != expected:
        raise SnapshotError("input_checksum_mismatch")
    return raw


def cache_file(cache: Path, key: str) -> Path:
    # R2 keys are labels, never filesystem paths. Reject ambiguous keys and use
    # a hash filename so even a hostile inventory cannot escape the cache.
    if (not isinstance(key, str) or not key.startswith("four-view-v4/") or not key.endswith(".i8")
            or any(part in ("", ".", "..") for part in key.split("/"))
            or not re.fullmatch(r"[A-Za-z0-9_/-]+\.i8", key)):
        raise SnapshotError("invalid_artifact_key")
    root = Path(cache).resolve()
    path = root / (digest(key.encode("utf-8")) + ".i8")
    if path.resolve().parent != root:
        raise SnapshotError("artifact_outside_cache")
    return path


def valid_record(raw: bytes) -> bool:
    return valid_four_view_record(raw) and all(
        any(raw[offset + 2:offset + BYTES_PER_VIEW])
        for offset in range(0, BYTES_PER_LOCATION, BYTES_PER_VIEW))


def clean_text(value, *, required=False, maximum=1000) -> str:
    if (not isinstance(value, str) or len(value) > maximum
            or (required and not value.strip()) or any(ord(char) < 32 for char in value)):
        raise SnapshotError("invalid_publication_metadata")
    return value


def validate_row(row: dict, approvals: ApprovedSceneReferences) -> dict:
    if (not isinstance(row, dict) or row.get("lane") != "scene" or row.get("state") != "published"
            or not isinstance(row.get("contributor_id"), str) or not row["contributor_id"].strip()
            or type(row.get("id")) is not int or row["id"] < 1
            or not isinstance(row.get("output_sha256"), str) or not HEX.fullmatch(row["output_sha256"])
            or row.get("four_view_sha256") != row["output_sha256"]
            or row.get("location_output_sha256") != row["output_sha256"]):
        raise SnapshotError("not_a_contributed_scene_publication")
    for key in ("lat", "lon", "heading", "pitch", "zoom"):
        if type(row.get(key)) not in (int, float) or not math.isfinite(row[key]):
            raise SnapshotError("invalid_publication_metadata")
    if abs(row["lat"]) > 90 or abs(row["lon"]) > 180 or abs(row["pitch"]) > 90 or not 0 <= row["zoom"] <= 5:
        raise SnapshotError("invalid_publication_metadata")
    for key in ("asset_id", "capture", "model"):
        clean_text(row.get(key), required=True)
    clean_text(row.get("country") or "")
    clean_text(row.get("camera_generation") or "")
    if not approvals.verify(row, row["output_sha256"]):
        raise SnapshotError("publication_not_independently_approved")
    return row


def write_file(path: Path, raw: bytes) -> dict:
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return {"bytes": len(raw), "sha256": digest(raw)}


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def build_snapshot(inventory: Path, inventory_sha256: str, policy: Path, policy_sha256: str,
                   cache: Path, destination: Path, *, previous: Path | None = None,
                   previous_sha256: str | None = None, environment: str = "production") -> dict:
    """Seal one new directory; publish the checksummed manifest last.

    Refuse overwrites. A failed new directory retains a redacted failure report
    and any partial files but never a sealed snapshot manifest.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        resource = resource_for_environment(environment)
        raw_inventory = pinned_read(Path(inventory), inventory_sha256, MAX_INVENTORY_BYTES)
        document = json.loads(raw_inventory)
        if (not isinstance(document, dict) or document.get("version") != 1
                or document.get("resource") != resource
                or not isinstance(document.get("rows"), list) or not 0 < len(document["rows"]) <= MAX_LOCATIONS):
            raise SnapshotError("invalid_community_inventory")
        pinned_read(Path(policy), policy_sha256, MAX_POLICY_BYTES)
        approvals = ApprovedSceneReferences.load(Path(policy), policy_sha256)
        rows = sorted((validate_row(row, approvals) for row in document["rows"]), key=lambda row: row["id"])
        if len({row["id"] for row in rows}) != len(rows):
            raise SnapshotError("duplicate_location_id")
        previous_members = []
        if previous is not None or previous_sha256 is not None:
            if previous is None or previous_sha256 is None:
                raise SnapshotError("previous_snapshot_pin_required")
            verify_snapshot(previous, previous_sha256, environment=environment)
            previous_members = json.loads(bounded_read(Path(previous) / "members.json", MAX_INVENTORY_BYTES))
            by_id = {row["id"]: row for row in rows}
            if any(member["locationId"] not in by_id for member in previous_members):
                raise SnapshotError("snapshot_history_changed")
            prior_ids = {member["locationId"] for member in previous_members}
            rows = [by_id[member["locationId"]] for member in previous_members] + [row for row in rows if row["id"] not in prior_ids]
        grouped = {}
        members = []
        for ordinal, row in enumerate(rows):
            key = row["four_view_key"]
            path = cache_file(cache, key)
            grouped.setdefault(key, (path, []))[1].append((ordinal, row))
            members.append({"sourceIndex": ordinal, "locationId": row["id"], "outputSha256": row["output_sha256"],
                            "pose": {"lat": row["lat"], "lng": row["lon"], "heading": row["heading"],
                                     "pitch": row["pitch"], "zoom": row["zoom"], "panoId": row["asset_id"],
                                     "capture": row["capture"], "country": row.get("country") or "",
                                     "cameraGeneration": row.get("camera_generation") or ""}})
        if members[:len(previous_members)] != previous_members:
            raise SnapshotError("snapshot_history_changed")
        payload = destination / "scene-records.i8"
        artifacts = []
        with payload.open("xb") as output:
            output.truncate(len(rows) * BYTES_PER_LOCATION)
            for key, (path, selected) in sorted(grouped.items()):
                blob = bounded_read(path, MAX_ARTIFACT_BYTES)
                if not blob or len(blob) % BYTES_PER_LOCATION:
                    raise SnapshotError("invalid_scene_artifact")
                offsets = {}
                for offset in range(0, len(blob), BYTES_PER_LOCATION):
                    record = blob[offset:offset + BYTES_PER_LOCATION]
                    if not valid_record(record):
                        raise SnapshotError("invalid_scene_artifact")
                    offsets.setdefault(digest(record), offset)
                for ordinal, row in selected:
                    offset = offsets.get(row["output_sha256"])
                    if offset is None:
                        raise SnapshotError("published_record_missing_from_artifact")
                    output.seek(ordinal * BYTES_PER_LOCATION)
                    output.write(blob[offset:offset + BYTES_PER_LOCATION])
                artifacts.append({"keySha256": digest(key.encode("utf-8")), "bytes": len(blob), "sha256": digest(blob)})
            output.flush()
            os.fsync(output.fileno())
        files = {"scene-records.i8": {"bytes": payload.stat().st_size, "sha256": file_digest(payload)},
                 "members.json": write_file(destination / "members.json", encoded(members))}
        manifest = {"version": 1, "scope": "operator-sealed-contributed-scenes", "lane": "scene",
                    "resource": resource,
                    "locations": len(rows), "bytesPerLocation": BYTES_PER_LOCATION,
                    "inventorySha256": inventory_sha256, "approvalPolicyId": approvals.policy_id,
                    "approvalPolicySha256": policy_sha256, "inputModel": approvals.input_model,
                    "outputModel": "vision-four-view-v4", "roadNameAuthority": "unavailable",
                    "previousSnapshotSha256": previous_sha256,
                    "files": files, "artifacts": artifacts}
        sealed = encoded(manifest)
        # The marker is written atomically after every payload is durable.
        temporary = destination / "snapshot.json.tmp"
        write_file(temporary, sealed)
        temporary.replace(destination / "snapshot.json")
        return {"locations": len(rows), "snapshotSha256": digest(sealed), "files": files}
    except Exception as failure:
        code = str(failure) if isinstance(failure, (SnapshotError, SceneQualityError)) else "snapshot_build_failed"
        write_file(destination / "failure-report.json", encoded({"sealed": False, "error": code}))
        raise


def verify_snapshot(root: Path, expected_sha256: str, *, environment: str | None = None) -> dict:
    """Verify an operator-pinned bundle before an engine can use its members."""
    root = Path(root)
    if (root / "snapshot.json").resolve().parent != root.resolve():
        raise SnapshotError("snapshot_file_outside_root")
    document = json.loads(pinned_read(root / "snapshot.json", expected_sha256, MAX_INVENTORY_BYTES))
    if (not isinstance(document, dict) or document.get("version") != 1
            or document.get("scope") != "operator-sealed-contributed-scenes" or document.get("lane") != "scene"
            or type(document.get("locations")) is not int or not 0 < document["locations"] <= MAX_LOCATIONS
            or document.get("bytesPerLocation") != BYTES_PER_LOCATION or document.get("outputModel") != "vision-four-view-v4"
            or set(document.get("files", {})) != {"scene-records.i8", "members.json"}):
        raise SnapshotError("invalid_snapshot_manifest")
    snapshot_resource(document, environment)
    for name, expected in document["files"].items():
        path = root / name
        if path.resolve().parent != root.resolve():
            raise SnapshotError("snapshot_file_outside_root")
        limit = document["locations"] * BYTES_PER_LOCATION if name == "scene-records.i8" else MAX_INVENTORY_BYTES
        if (not isinstance(expected, dict) or type(expected.get("bytes")) is not int or not 0 < expected["bytes"] <= limit
                or not isinstance(expected.get("sha256"), str) or not HEX.fullmatch(expected["sha256"])
                or path.stat().st_size != expected["bytes"] or file_digest(path) != expected["sha256"]):
            raise SnapshotError("snapshot_file_checksum_mismatch")
    if document["files"]["scene-records.i8"]["bytes"] != document["locations"] * BYTES_PER_LOCATION:
        raise SnapshotError("invalid_snapshot_geometry")
    members = json.loads(bounded_read(root / "members.json", MAX_INVENTORY_BYTES))
    if not isinstance(members, list) or len(members) != document["locations"]:
        raise SnapshotError("invalid_snapshot_members")
    seen = set()
    with (root / "scene-records.i8").open("rb") as handle:
        for ordinal, member in enumerate(members):
            record = handle.read(BYTES_PER_LOCATION)
            if (not isinstance(member, dict) or type(member.get("locationId")) is not int or member["locationId"] < 1
                    or member["locationId"] in seen or member.get("sourceIndex") != ordinal
                    or not valid_record(record) or digest(record) != member.get("outputSha256")):
                raise SnapshotError("invalid_snapshot_members")
            seen.add(member["locationId"])
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--artifact-cache", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--previous-sha256")
    parser.add_argument("--environment", choices=("production", "staging"), default="production")
    args = parser.parse_args()
    try:
        report = build_snapshot(args.inventory, args.inventory_sha256, args.policy, args.policy_sha256,
                                args.artifact_cache, args.out, previous=args.previous, previous_sha256=args.previous_sha256,
                                environment=args.environment)
    except FileExistsError:
        print(json.dumps({"sealed": False, "error": "destination_already_exists"}))
        raise SystemExit(1)
    except Exception:
        failure_report = args.out / "failure-report.json"
        print(json.dumps({"sealed": False, "error": "snapshot_build_failed",
                          "failureReport": "failure-report.json" if failure_report.is_file() else None}))
        raise SystemExit(1)
    print(json.dumps({"sealed": True, **report}))


if __name__ == "__main__":
    main()
