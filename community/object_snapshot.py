"""Offline, operator-pinned snapshots of audited, contributed Gen4 objects.

Publication checksums cover global IDs, not calculated object features. Require
separate trusted approval of the entire feature bundle before copying it. This
tool makes no network requests, creates no accounts and approves no inference.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import struct
from pathlib import Path

from .object_index import (CODEBOOK_SHA256, COMMON_MODEL_SHA256, OBJECT_INDEX_MODEL,
                           RUNTIME_IDENTITY, manifest_file_names, object_tsv_lines,
                           validate_object_index)
from .search_snapshot import (HEX, MAX_INVENTORY_BYTES,
                             MAX_LOCATIONS, SnapshotError, bounded_read, clean_text,
                             digest, encoded, pinned_read, write_file,
                             resource_for_environment, snapshot_resource)
from .vision_index import VisionIndexError

VALIDATOR = "official-gen4-historical-v2-exact-pano"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 32_000_000
MAX_SNAPSHOT_BYTES = 2 * 1024**3
MAX_SNAPSHOT_METADATA_BYTES = 64 * 1024 * 1024
MAX_BATCH_LOCATIONS = 1000
KEY = re.compile(r"object-index-v4/([0-9a-f]{32})/\Z")
FILE = re.compile(r"[a-z0-9][a-z0-9.-]*\.bin\Z")
INVENTORY_SQL = """SELECT l.id,l.asset_id,l.capture,l.lane,l.model,l.state,
 l.contributor_id,l.lat,l.lon,l.heading,l.pitch,l.zoom,l.country,l.camera_generation,
 l.output_sha256 AS location_output_sha256,i.output_sha256,i.object_index_sha256,i.object_index_key,
 c.validator AS coverage_validator,c.evidence_sha256 AS coverage_evidence_sha256
 FROM locations l JOIN published_index i ON i.location_id=l.id
 JOIN object_coverage c ON c.location_id=l.id
 WHERE l.lane='object' AND l.state='published' AND l.camera_generation='gen4'
 AND l.contributor_id IS NOT NULL AND l.contributor_id!=''
 AND i.object_index_key IS NOT NULL AND i.object_index_key!='' ORDER BY l.id"""
MANIFEST_SCALARS = (
    "version", "feature", "architecture", "sourceId", "sourceBytes", "sourceSha256",
    "modelSha256", "runtimeIdentity", "totalLocations", "indexedLocations", "globalStart",
    "globalIdMode", "minimumGlobalLocation", "maximumGlobalLocation", "imageSize", "tileGrid",
    "tileOverlap", "minimumRelativeClassScore", "smallObjectRelativeClassScore",
    "fullTileArtifactThreshold", "rankingStrategy", "viewStrategy", "viewCount", "faceSize",
    "faceFov", "bandsPerFace", "bandWidth", "bandHeight", "bandOffset", "bandFov",
    "recordBytes", "positionPolicy", "coverage", "fetchErrors", "inferenceErrors",
    "permanentlyInvalidLocations", "completed",
)
ENTRY_FIELDS = ("file", "recordBytes", "records", "bytes", "sha256")
CLASS_FIELDS = (*ENTRY_FIELDS, "id", "name", "storageFloor")
SEMANTIC_FIELDS = (*ENTRY_FIELDS, "codec", "codebookSha256", "embeddingDimensions", "proposalsPerLocation")
QUALITY_FIELDS = (*ENTRY_FIELDS, "policy", "implementationIdentity", "viewCount", "blurAreaFractionExclusive",
                  "tileGrid", "tunnelVisionProbabilityInclusive", "tunnelEvidencePolicy",
                  "tunnelEvidenceManifestSha256", "tunnelEvidenceQualifiedViews", "tunnelEvidenceMapMatchRecords",
                  "tunnelEvidenceVisualScoreRecords", "keptViews", "blurRejectedViews", "darkTunnelRejectedViews",
                  "fullyRejectedLocations", "permanentlyInvalidLocations", "invalidLocationPolicy",
                  "protectedAuthorityManifestSha256")
CONTRACT_FIELDS = ("manifest", "checkpoint", "commonRecord", "hotRecord", "semanticRecord",
                   "metadataRecord", "offsets", "globalIds")


def cache_directory(cache: Path, key: str) -> Path:
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise SnapshotError("invalid_object_artifact_key")
    root = Path(cache).resolve()
    folder = root / digest(key.encode())
    if folder.resolve().parent != root:
        raise SnapshotError("artifact_outside_cache")
    return folder


def child_file(root: Path, name: str) -> Path:
    path = root / name
    if path.resolve().parent != root.resolve():
        raise SnapshotError("snapshot_file_outside_root")
    return path


def validate_quality_structure(quality: dict, locations: int, invalid: int) -> None:
    """Validate quality contents, without asserting protected import authority.

    Only the offline frozen-input comparator uses this directly. Publication
    must use validate_quality, which also requires the protected authority pin.
    """
    counts = ("keptViews", "blurRejectedViews", "darkTunnelRejectedViews", "fullyRejectedLocations")
    if (type(locations) is not int or locations < 1 or quality.get("file") != "view-quality.bin"
            or quality.get("policy") != "vision-per-view-quality-v1" or quality.get("viewCount") != 6
            or quality.get("blurAreaFractionExclusive") != 0.5 or quality.get("tileGrid") != 8
            or quality.get("tunnelVisionProbabilityInclusive") != 0.85
            or not isinstance(quality.get("implementationIdentity"), str)
            or not HEX.fullmatch(quality["implementationIdentity"])
            or any(type(quality.get(field)) is not int or not 0 <= quality[field] <= locations * 6 for field in counts)):
        raise SnapshotError("invalid_object_view_quality")
    rejected = quality.get("permanentlyInvalidLocations", 0)
    if (type(rejected) is not int or not 0 <= rejected <= quality["fullyRejectedLocations"] <= locations
            or rejected != invalid or sum(quality[field] for field in counts[:3]) + rejected * 6 != locations * 6
            or (quality.get("invalidLocationPolicy") is not None and quality["invalidLocationPolicy"] !=
                "quality-lane-tombstone:definitive-google-pano-or-repeated-image-decode-v1")
            or (rejected and quality.get("invalidLocationPolicy") is None)):
        raise SnapshotError("invalid_object_view_quality")
    evidence_counts = ("tunnelEvidenceQualifiedViews", "tunnelEvidenceMapMatchRecords", "tunnelEvidenceVisualScoreRecords")
    for field in evidence_counts:
        if field in quality and (type(quality[field]) is not int or not 0 <= quality[field] < 2**63):
            raise SnapshotError("invalid_object_view_quality")
    if quality.get("tunnelEvidencePolicy") == "none-darkness-never-rejects-v1":
        if (quality.get("tunnelEvidenceManifestSha256") is not None or quality["darkTunnelRejectedViews"]
                or any(quality.get(field, 0) for field in evidence_counts)):
            raise SnapshotError("invalid_object_view_quality")
    elif quality.get("tunnelEvidencePolicy") == "sealed-external-map-plus-tunnel-vision-exact-pano-coordinate-v1":
        if (not isinstance(quality.get("tunnelEvidenceManifestSha256"), str)
                or not HEX.fullmatch(quality["tunnelEvidenceManifestSha256"])
                or any(field not in quality for field in evidence_counts)
                or quality["darkTunnelRejectedViews"] > quality["tunnelEvidenceQualifiedViews"]):
            raise SnapshotError("invalid_object_view_quality")
    else:
        raise SnapshotError("invalid_object_view_quality")


def validate_quality(quality: dict, locations: int, invalid: int) -> None:
    # Reference: VISION VisionModels.validateProtectedGen4ViewQuality. Retain
    # evidence identities and semantics, never the Mac's absolute file paths.
    validate_quality_structure(quality, locations, invalid)
    if (not isinstance(quality.get("protectedAuthorityManifestSha256"), str)
            or not HEX.fullmatch(quality["protectedAuthorityManifestSha256"])):
        raise SnapshotError("invalid_object_view_quality")


def public_manifest(document: dict) -> dict:
    """Allowlist fields; never propagate local paths or arbitrary extra metadata."""
    if not isinstance(document, dict):
        raise SnapshotError("invalid_object_artifact")
    if "frozenViewsManifestSha256" in document:
        raise SnapshotError("diagnostic_object_artifact")
    result = {key: document[key] for key in MANIFEST_SCALARS if key in document}
    if any(isinstance(value, (dict, list)) for value in result.values()):
        raise SnapshotError("invalid_object_artifact")
    for counter in ("fetchErrors", "inferenceErrors", "permanentlyInvalidLocations"):
        if counter in result and (type(result[counter]) is not int or result[counter] < 0):
            raise SnapshotError("invalid_object_artifact")
    result["sourceTsv"] = "locations.tsv"
    contracts = document.get("contractVersions")
    countries = document.get("countries")
    if not isinstance(contracts, dict) or not isinstance(countries, list):
        raise SnapshotError("invalid_object_artifact")
    result["contractVersions"] = {key: contracts.get(key) for key in CONTRACT_FIELDS}
    result["countries"] = [clean_text(country, maximum=100) for country in countries]
    for key in ("offsets", "metadata", "globalIds", "semantic", "viewQuality"):
        entry = document.get(key)
        if key == "viewQuality" and entry in (None, {}):
            continue
        if not isinstance(entry, dict):
            raise SnapshotError("invalid_object_artifact")
        fields = SEMANTIC_FIELDS if key == "semantic" else QUALITY_FIELDS if key == "viewQuality" else ENTRY_FIELDS
        result[key] = {field: entry[field] for field in fields if field in entry}
    for key in ("classes", "hotConcepts"):
        entries = document.get(key)
        if not isinstance(entries, list) or len(entries) > 100:
            raise SnapshotError("invalid_object_artifact")
        if any(not isinstance(entry, dict) for entry in entries):
            raise SnapshotError("invalid_object_artifact")
        result[key] = [{field: entry[field] for field in CLASS_FIELDS if field in entry} for entry in entries]
    # Entry values are scalars too. Nested or free-form metadata must not leak.
    for key in ("offsets", "metadata", "globalIds", "semantic", "viewQuality", "classes", "hotConcepts"):
        entries = result.get(key, [])
        if isinstance(entries, dict):
            entries = [entries]
        if any(isinstance(value, (dict, list)) for entry in entries for value in entry.values()):
            raise SnapshotError("invalid_object_artifact")
    if "viewQuality" in result:
        validate_quality(result["viewQuality"], result.get("totalLocations"), result.get("permanentlyInvalidLocations", 0))
    return result


def row_member(row: dict, input_model: str) -> dict:
    if (not isinstance(row, dict) or row.get("lane") != "object" or row.get("state") != "published"
            or row.get("model") != input_model or type(row.get("id")) is not int or row["id"] < 1
            or not isinstance(row.get("contributor_id"), str) or not row["contributor_id"].strip()
            or row.get("camera_generation") != "gen4" or row.get("coverage_validator") != VALIDATOR
            or not isinstance(row.get("coverage_evidence_sha256"), str)
            or not HEX.fullmatch(row["coverage_evidence_sha256"])
            or not isinstance(row.get("output_sha256"), str) or not HEX.fullmatch(row["output_sha256"])
            or row.get("location_output_sha256") != row["output_sha256"]
            or not isinstance(row.get("object_index_sha256"), str) or not HEX.fullmatch(row["object_index_sha256"])):
        raise SnapshotError("not_a_covered_contributed_object")
    for field in ("lat", "lon", "heading", "pitch", "zoom"):
        if type(row.get(field)) not in (int, float) or not math.isfinite(row[field]):
            raise SnapshotError("invalid_publication_metadata")
    if abs(row["lat"]) > 90 or abs(row["lon"]) > 180 or abs(row["pitch"]) > 90 or not 0 <= row["zoom"] <= 5:
        raise SnapshotError("invalid_publication_metadata")
    return {"locationId": row["id"], "outputSha256": row["output_sha256"],
            "coverageEvidenceSha256": row["coverage_evidence_sha256"],
            "pose": {"lat": row["lat"], "lng": row["lon"], "heading": row["heading"],
                     "pitch": row["pitch"], "zoom": row["zoom"],
                     "panoId": clean_text(row.get("asset_id"), required=True),
                     "capture": clean_text(row.get("capture"), required=True),
                     "country": clean_text(row.get("country") or "", maximum=100),
                     "cameraGeneration": "gen4"}}


def load_policy(path: Path, checksum: str) -> dict:
    policy = json.loads(pinned_read(path, checksum, MAX_INVENTORY_BYTES))
    if (not isinstance(policy, dict) or policy.get("version") != 1
            or policy.get("verification") != "independently-audited-object-inference"
            or policy.get("outputModel") != OBJECT_INDEX_MODEL or policy.get("runtimeIdentity") != RUNTIME_IDENTITY
            or policy.get("coverageValidator") != VALIDATOR
            or not isinstance(policy.get("artifacts"), list) or not 0 < len(policy["artifacts"]) <= MAX_LOCATIONS):
        raise SnapshotError("invalid_object_approval_policy")
    clean_text(policy.get("policyId"), required=True, maximum=128)
    clean_text(policy.get("inputModel"), required=True, maximum=128)
    approved = {}
    for artifact in policy["artifacts"]:
        if (not isinstance(artifact, dict) or any(not isinstance(artifact.get(key), str)
                or not HEX.fullmatch(artifact[key]) for key in ("keySha256", "bundleSha256"))
                or not isinstance(artifact.get("members"), list) or not 0 < len(artifact["members"]) <= MAX_BATCH_LOCATIONS
                or artifact["keySha256"] in approved):
            raise SnapshotError("invalid_object_approval_policy")
        approved[artifact["keySha256"]] = artifact
    return {**policy, "byKey": approved}


def load_bundle(folder: Path, key: str, rows: list[dict]) -> tuple[dict, dict, bytes, str]:
    manifest = public_manifest(json.loads(bounded_read(child_file(folder, "manifest.json"), MAX_MANIFEST_BYTES)))
    source = bounded_read(child_file(folder, "locations.tsv"), MAX_MANIFEST_BYTES)
    names = manifest_file_names(manifest)
    if not names or len(names) != len(set(names)) or any(not FILE.fullmatch(name) for name in names):
        raise SnapshotError("invalid_object_artifact")
    files, total = {}, len(source) + len(encoded(manifest))
    for name in sorted(names):
        remaining = MAX_BUNDLE_BYTES - total
        if remaining < 0:
            raise SnapshotError("object_artifact_too_large")
        files[name] = bounded_read(child_file(folder, name), remaining)
        total += len(files[name])
    if total > MAX_BUNDLE_BYTES or not 0 < len(rows) <= MAX_BATCH_LOCATIONS:
        raise SnapshotError("object_artifact_too_large")
    lease = KEY.fullmatch(key).group(1)
    outputs = validate_object_index(manifest, files, source, rows, lease_id=lease)
    if any(output["outputSha256"] != row["output_sha256"] for output, row in zip(outputs, rows)):
        raise SnapshotError("object_publication_checksum_mismatch")
    if any(row["object_index_sha256"] != digest(source) for row in rows):
        raise SnapshotError("object_source_checksum_mismatch")
    # Native structural validation binds pano/lat/lng. Bind the other exported
    # pose fields and country/generation here before replacing private TSV labels.
    for line, row in zip(source.decode("utf-8").splitlines(), rows):
        fields = line.split("\t")
        if (len(fields) != 12 or any(float(fields[column]) != row[field] for column, field in
                ((4, "heading"), (5, "pitch"), (6, "zoom")))
                or fields[8] != (row.get("country") or "") or fields[9] != "gen4"):
            raise SnapshotError("object_source_pose_mismatch")
    identity = {"manifest": manifest, "sourceTsv": {"bytes": len(source), "sha256": digest(source)},
                "files": {name: {"bytes": len(raw), "sha256": digest(raw)} for name, raw in sorted(files.items())}}
    return manifest, files, source, digest(encoded(identity))


def normalized_source(rows: list[dict], *, road_flags: list[bool] | None = None) -> bytes:
    # Preserve only the native boolean; never copy the original road text.
    flags = road_flags if road_flags is not None else [False] * len(rows)
    if len(flags) != len(rows) or any(type(flag) is not bool for flag in flags):
        raise SnapshotError("invalid_object_source")
    items = [{"locationId": row["id"], "lat": row["lat"], "lng": row["lon"],
              "heading": row["heading"], "pitch": row["pitch"], "zoom": row["zoom"],
              "panoId": row["asset_id"], "country": row.get("country") or "", "cameraGeneration": "gen4",
              "roadName": "has road name" if flag else "no road name"}
             for row, flag in zip(rows, flags)]
    return ("\n".join(object_tsv_lines(items)) + "\n").encode()


def build_object_snapshot(inventory: Path, inventory_sha256: str, policy: Path, policy_sha256: str,
                          cache: Path, destination: Path, *, previous: Path | None = None,
                          previous_sha256: str | None = None, environment: str = "production") -> dict:
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        resource = resource_for_environment(environment)
        document = json.loads(pinned_read(Path(inventory), inventory_sha256, MAX_INVENTORY_BYTES))
        if (not isinstance(document, dict) or document.get("version") != 1
                or document.get("resource") != resource or not isinstance(document.get("rows"), list)
                or not 0 < len(document["rows"]) <= MAX_LOCATIONS):
            raise SnapshotError("invalid_community_inventory")
        approvals = load_policy(Path(policy), policy_sha256)
        rows = sorted(document["rows"], key=lambda row: row.get("id", -1))
        public = {row["id"]: row_member(row, approvals["inputModel"]) for row in rows}
        if len(public) != len(rows):
            raise SnapshotError("duplicate_location_id")
        previous_members, previous_document = [], None
        if previous is not None or previous_sha256 is not None:
            if previous is None or previous_sha256 is None:
                raise SnapshotError("previous_snapshot_pin_required")
            previous_document = verify_object_snapshot(previous, previous_sha256, environment=environment)
            previous_members = json.loads(bounded_read(Path(previous) / "members.json", MAX_INVENTORY_BYTES))
            by_id = {row["id"]: row for row in rows}
            if any(member["locationId"] not in by_id for member in previous_members):
                raise SnapshotError("snapshot_history_changed")
            prior_ids = {member["locationId"] for member in previous_members}
            rows = [by_id[member["locationId"]] for member in previous_members] + [row for row in rows if row["id"] not in prior_ids]
        groups = {}
        for row in rows:
            cache_directory(cache, row.get("object_index_key"))
            groups.setdefault(row["object_index_key"], []).append(row)
        bundles, members, total_bytes = [], {}, 0
        for bundle_index, (key, selected) in enumerate(groups.items()):
            selected.sort(key=lambda row: row["id"])
            folder = cache_directory(cache, key)
            manifest, files, original_source, artifact_sha = load_bundle(folder, key, selected)
            key_sha = digest(key.encode())
            approval = approvals["byKey"].get(key_sha)
            expected_members = [public[row["id"]] for row in selected]
            if (not approval or approval["bundleSha256"] != artifact_sha or approval["members"] != expected_members):
                raise SnapshotError("object_artifact_not_independently_approved")
            relative = f"objects/{key_sha}"
            output = destination / relative
            output.mkdir(parents=True, exist_ok=False)
            from .object_features import ROAD_TRUE
            road_flags = [line.split("\t")[10].strip().lower() in ROAD_TRUE
                          for line in original_source.decode("utf-8").splitlines()]
            source = normalized_source(selected, road_flags=road_flags)
            if len(source) > MAX_MANIFEST_BYTES:
                raise SnapshotError("object_artifact_too_large")
            # Removing private labels changes UTF-8 row lengths. Rebuild the
            # lookup pointers from the exported bytes, not the private source.
            positions, offset = [], 0
            for line in source.splitlines(keepends=True):
                positions.append(struct.pack("<Q", offset))
                offset += len(line)
            offsets = b"".join(positions)
            files = {**files, "location-offsets.bin": offsets}
            manifest = {**manifest, "sourceBytes": len(source), "sourceSha256": digest(source),
                        "offsets": {**manifest["offsets"], "bytes": len(offsets), "sha256": digest(offsets)}}
            validate_object_index(manifest, files, source, selected, lease_id=KEY.fullmatch(key).group(1))
            exported = {"locations.tsv": source, "manifest.json": encoded(manifest), **files}
            batch_bytes = sum(map(len, exported.values()))
            if (batch_bytes > MAX_BUNDLE_BYTES or len(source) > MAX_MANIFEST_BYTES
                    or len(exported["manifest.json"]) > MAX_MANIFEST_BYTES):
                raise SnapshotError("object_artifact_too_large")
            total_bytes += batch_bytes
            if total_bytes > MAX_SNAPSHOT_BYTES:
                raise SnapshotError("object_snapshot_too_large")
            entries = {name: write_file(output / name, raw) for name, raw in sorted(exported.items())}
            bundles.append({"bundleIndex": bundle_index, "path": relative, "keySha256": key_sha,
                            "approvedArtifactSha256": artifact_sha, "files": entries})
            for local_index, row in enumerate(selected):
                members[row["id"]] = {**public[row["id"]], "bundleIndex": bundle_index, "localIndex": local_index}
        ordered = [{"sourceIndex": ordinal, **members[row["id"]]} for ordinal, row in enumerate(rows)]
        if ordered[:len(previous_members)] != previous_members:
            raise SnapshotError("snapshot_history_changed")
        # Publication digests identify global IDs, so member equality alone
        # cannot detect replacement of an old batch's object feature contents.
        if previous_document and bundles[:len(previous_document["bundles"])] != previous_document["bundles"]:
            raise SnapshotError("snapshot_history_changed")
        members_raw = encoded(ordered)
        if len(members_raw) > MAX_SNAPSHOT_METADATA_BYTES:
            raise SnapshotError("object_snapshot_metadata_too_large")
        members_file = write_file(destination / "members.json", members_raw)
        manifest = {"version": 1, "scope": "operator-sealed-contributed-objects", "lane": "object",
                    "resource": resource,
                    "locations": len(rows), "outputModel": OBJECT_INDEX_MODEL, "inputModel": approvals["inputModel"],
                    "runtimeIdentity": RUNTIME_IDENTITY, "commonModelSha256": COMMON_MODEL_SHA256,
                    "codebookSha256": CODEBOOK_SHA256, "coverageValidator": VALIDATOR,
                    "approvalPolicyId": approvals["policyId"], "approvalPolicySha256": policy_sha256,
                    "inventorySha256": inventory_sha256, "previousSnapshotSha256": previous_sha256,
                    "roadNameAuthority": "unavailable", "files": {"members.json": members_file}, "bundles": bundles}
        sealed = encoded(manifest)
        if len(sealed) > MAX_SNAPSHOT_METADATA_BYTES:
            raise SnapshotError("object_snapshot_metadata_too_large")
        temporary = destination / "snapshot.json.tmp"
        write_file(temporary, sealed)
        temporary.replace(destination / "snapshot.json")
        return {"locations": len(rows), "bundles": len(bundles), "snapshotSha256": digest(sealed)}
    except Exception as failure:
        code = str(failure) if isinstance(failure, SnapshotError) else "object_snapshot_build_failed"
        write_file(destination / "failure-report.json", encoded({"sealed": False, "error": code}))
        raise


def verify_file(root: Path, name: str, expected: dict, limit: int) -> bytes:
    if (not isinstance(expected, dict) or type(expected.get("bytes")) is not int
            or not 0 <= expected["bytes"] <= limit):
        raise SnapshotError("invalid_snapshot_manifest")
    raw = pinned_read(child_file(root, name), expected.get("sha256"), limit)
    if len(raw) != expected["bytes"]:
        raise SnapshotError("snapshot_file_checksum_mismatch")
    return raw


def verify_object_snapshot(root: Path, expected_sha256: str, *, environment: str | None = None) -> dict:
    root = Path(root)
    document = json.loads(pinned_read(child_file(root, "snapshot.json"), expected_sha256, MAX_SNAPSHOT_METADATA_BYTES))
    if (not isinstance(document, dict) or document.get("version") != 1
            or document.get("scope") != "operator-sealed-contributed-objects" or document.get("lane") != "object"
            or type(document.get("locations")) is not int or not 0 < document["locations"] <= MAX_LOCATIONS
            or document.get("outputModel") != OBJECT_INDEX_MODEL or document.get("runtimeIdentity") != RUNTIME_IDENTITY
            or document.get("commonModelSha256") != COMMON_MODEL_SHA256 or document.get("codebookSha256") != CODEBOOK_SHA256
            or document.get("coverageValidator") != VALIDATOR or document.get("roadNameAuthority") != "unavailable"
            or not isinstance(document.get("files"), dict) or set(document["files"]) != {"members.json"}
            or not isinstance(document.get("bundles"), list) or not 0 < len(document["bundles"]) <= document["locations"]
            or any(not isinstance(document.get(field), str) or not HEX.fullmatch(document[field]) for field in
                   ("inventorySha256", "approvalPolicySha256"))):
        raise SnapshotError("invalid_snapshot_manifest")
    snapshot_resource(document, environment)
    clean_text(document.get("approvalPolicyId"), required=True, maximum=128)
    clean_text(document.get("inputModel"), required=True, maximum=128)
    members = json.loads(verify_file(root, "members.json", document["files"]["members.json"], MAX_SNAPSHOT_METADATA_BYTES))
    if not isinstance(members, list) or len(members) != document["locations"]:
        raise SnapshotError("invalid_snapshot_members")
    seen, grouped = set(), {}
    for ordinal, member in enumerate(members):
        if (not isinstance(member, dict) or type(member.get("sourceIndex")) is not int or member["sourceIndex"] != ordinal
                or type(member.get("locationId")) is not int or member["locationId"] < 1 or member["locationId"] in seen
                or type(member.get("bundleIndex")) is not int or not 0 <= member["bundleIndex"] < len(document["bundles"])
                or type(member.get("localIndex")) is not int or member["localIndex"] < 0 or not isinstance(member.get("pose"), dict)
                or any(not isinstance(member.get(field), str) or not HEX.fullmatch(member[field]) for field in
                       ("outputSha256", "coverageEvidenceSha256"))):
            raise SnapshotError("invalid_snapshot_members")
        seen.add(member["locationId"])
        grouped.setdefault(member["bundleIndex"], []).append(member)
    key_hashes, total = set(), 0
    for index, bundle in enumerate(document["bundles"]):
        if (not isinstance(bundle, dict) or type(bundle.get("bundleIndex")) is not int or bundle["bundleIndex"] != index
                or not isinstance(bundle.get("keySha256"), str) or not HEX.fullmatch(bundle["keySha256"])
                or bundle["keySha256"] in key_hashes or bundle.get("path") != f"objects/{bundle['keySha256']}"
                or not isinstance(bundle.get("approvedArtifactSha256"), str) or not HEX.fullmatch(bundle["approvedArtifactSha256"])
                or not isinstance(bundle.get("files"), dict)):
            raise SnapshotError("invalid_snapshot_manifest")
        key_hashes.add(bundle["keySha256"])
        folder = root / bundle["path"]
        if folder.resolve() != root.resolve() / bundle["path"]:
            raise SnapshotError("snapshot_file_outside_root")
        files = bundle["files"]
        manifest = json.loads(verify_file(folder, "manifest.json", files.get("manifest.json"), MAX_MANIFEST_BYTES))
        if manifest != public_manifest(manifest):
            raise SnapshotError("invalid_object_artifact")
        names = manifest_file_names(manifest)
        if any(not FILE.fullmatch(name) for name in names) or len(names) != len(set(names)):
            raise SnapshotError("invalid_object_artifact")
        if set(files) != {"locations.tsv", "manifest.json", *names}:
            raise SnapshotError("invalid_snapshot_manifest")
        selected = sorted(grouped.get(index, []), key=lambda member: member["localIndex"])
        if not 0 < len(selected) <= MAX_BATCH_LOCATIONS or [member["localIndex"] for member in selected] != list(range(len(selected))):
            raise SnapshotError("invalid_snapshot_members")
        rows = [{"id": member["locationId"], "asset_id": member["pose"].get("panoId"),
                 "capture": member["pose"].get("capture"), "lane": "object", "model": document["inputModel"],
                 "state": "published", "contributor_id": "sealed-contribution", "lat": member["pose"].get("lat"),
                 "lon": member["pose"].get("lng"), "heading": member["pose"].get("heading"),
                 "pitch": member["pose"].get("pitch"), "zoom": member["pose"].get("zoom"),
                 "country": member["pose"].get("country"), "camera_generation": member["pose"].get("cameraGeneration"),
                 "output_sha256": member["outputSha256"], "location_output_sha256": member["outputSha256"],
                 "object_index_sha256": manifest.get("sourceSha256"), "coverage_validator": VALIDATOR,
                 "coverage_evidence_sha256": member["coverageEvidenceSha256"]} for member in selected]
        for row, member in zip(rows, selected):
            if row_member(row, document["inputModel"]) != {key: member[key] for key in
                    ("locationId", "outputSha256", "coverageEvidenceSha256", "pose")}:
                raise SnapshotError("invalid_snapshot_members")
        if [row["id"] for row in rows] != sorted(row["id"] for row in rows):
            raise SnapshotError("invalid_snapshot_members")
        source = verify_file(folder, "locations.tsv", files["locations.tsv"], MAX_MANIFEST_BYTES)
        try:
            source_fields = [line.split("\t") for line in source.decode("utf-8").splitlines()]
            if (len(source_fields) != len(rows) or any(len(fields) != 12
                    or fields[10] not in ("has road name", "no road name") for fields in source_fields)):
                raise SnapshotError("object_source_pose_mismatch")
            road_flags = [fields[10] == "has road name" for fields in source_fields]
        except UnicodeDecodeError:
            raise SnapshotError("object_source_pose_mismatch") from None
        if source != normalized_source(rows, road_flags=road_flags):
            raise SnapshotError("object_source_pose_mismatch")
        payloads, batch_bytes = {}, len(source) + files["manifest.json"]["bytes"]
        for name in names:
            payloads[name] = verify_file(folder, name, files[name], max(0, MAX_BUNDLE_BYTES - batch_bytes))
            batch_bytes += len(payloads[name])
        total += batch_bytes
        if batch_bytes > MAX_BUNDLE_BYTES or total > MAX_SNAPSHOT_BYTES:
            raise SnapshotError("object_snapshot_too_large")
        source_id = manifest.get("sourceId")
        if not isinstance(source_id, str) or not re.fullmatch(r"community-[0-9a-f]{32}", source_id):
            raise SnapshotError("invalid_object_artifact")
        try:
            outputs = validate_object_index(manifest, payloads, source, rows, lease_id=source_id[10:])
        except VisionIndexError as error:
            raise SnapshotError("invalid_object_artifact") from error
        if [output["outputSha256"] for output in outputs] != [member["outputSha256"] for member in selected]:
            raise SnapshotError("object_publication_checksum_mismatch")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--artifact-cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--previous-sha256")
    parser.add_argument("--environment", choices=("production", "staging"), default="production")
    args = parser.parse_args()
    try:
        report = build_object_snapshot(args.inventory, args.inventory_sha256, args.policy, args.policy_sha256,
                                       args.artifact_cache, args.out, previous=args.previous,
                                       previous_sha256=args.previous_sha256, environment=args.environment)
    except FileExistsError:
        print(json.dumps({"sealed": False, "error": "destination_already_exists"}))
        raise SystemExit(1)
    except Exception:
        print(json.dumps({"sealed": False, "error": "object_snapshot_build_failed",
                          "failureReport": "failure-report.json" if (args.out / "failure-report.json").is_file() else None}))
        raise SystemExit(1)
    print(json.dumps({"sealed": True, **report}))


if __name__ == "__main__":
    main()
