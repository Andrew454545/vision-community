"""Offline integrity check for published indexes and queue catalog backups.

Uses a pinned, privacy-repaired database copy and a private downloaded cache.
Never contacts a provider, changes accounts, approves inference or reopens service.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .four_view import BYTES_PER_LOCATION
from .native_scene_search import plain_path, strict_json
from .object_index import manifest_file_names
from .object_snapshot import (cache_directory, child_file, load_bundle,
                              row_member, MAX_BUNDLE_BYTES)
from .search_snapshot import (HEX, MAX_ARTIFACT_BYTES, MAX_LOCATIONS, bounded_read,
                              cache_file, digest, encoded, file_digest, pinned_read,
                              resource_for_environment, valid_record, write_file)

MAX_DATABASE = 512 * 1024**2
MAX_CATALOG = 128 * 1024**2
MAX_FILES = 200_000
MAX_TOTAL_BYTES = 16 * 1024**3
CATALOG_KEY = re.compile(r"catalog/[A-Za-z0-9_/-]+\.tsv\Z")


class StorageRestoreError(ValueError):
    pass


def closed_database(path: Path) -> None:
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise StorageRestoreError("backup_not_closed")


def bounded_hash(path: Path, maximum: int) -> str:
    plain_path(path)
    hashed, total = hashlib.sha256(), 0
    with path.open("rb") as source:
        for raw in iter(lambda: source.read(1024**2), b""):
            total += len(raw)
            if total > maximum:
                raise StorageRestoreError("artifact_too_large")
            hashed.update(raw)
    return hashed.hexdigest()


def catalog_cache_file(cache: Path, key: str) -> Path:
    # Keys are labels, not relative filesystem paths.
    if (not isinstance(key, str) or not CATALOG_KEY.fullmatch(key)
            or any(part in ("", ".", "..") for part in key.split("/"))):
        raise StorageRestoreError("invalid_catalog_key")
    return Path(cache) / (digest(key.encode()) + ".tsv")


def check_storage_restore(repaired_dir: Path, report_sha256: str, cache: Path,
                          destination: Path, *, environment: str = "production") -> dict:
    destination = Path(destination).absolute()
    plain_path(destination.parent, directory=True)
    destination.mkdir(exist_ok=False, mode=0o700)  # Preserve completed and failed attempts.
    sql = None
    try:
        # Windows 8.3 aliases and full names refer to the same ordinary folder.
        # Reject links/reparse points BEFORE canonicalizing, then use one name
        # consistently for containment checks and opaque inventory labels.
        destination = plain_path(destination, directory=True).resolve(strict=True)
        root = plain_path(repaired_dir, directory=True).resolve(strict=True)
        cache = plain_path(cache, directory=True).resolve(strict=True)
        if any(folder == destination or folder in destination.parents for folder in (root, cache)):
            raise StorageRestoreError("output_overlaps_input")
        resource = resource_for_environment(environment)
        report_path = plain_path(root / "restore-report.json")
        report = strict_json(pinned_read(report_path, report_sha256, 1024**2))
        if (not isinstance(report, dict) or report.get("version") != 1
                or report.get("scope") != "offline-privacy-repaired-community-copy"
                or report.get("liveReady") is not False or report.get("resource") != resource
                or not isinstance(report.get("databaseSha256"), str)
                or not HEX.fullmatch(report["databaseSha256"])):
            raise StorageRestoreError("invalid_repaired_copy_report")
        database = plain_path(root / "restored.sqlite")
        closed_database(database)
        if database.stat().st_size > MAX_DATABASE:
            raise StorageRestoreError("database_too_large")
        copy = destination / "input.sqlite"
        with database.open("rb") as source, copy.open("xb") as target:
            copied = 0
            for raw in iter(lambda: source.read(1024**2), b""):
                copied += len(raw)
                if copied > MAX_DATABASE:
                    raise StorageRestoreError("database_too_large")
                target.write(raw)
        closed_database(database)
        if copy.stat().st_size > MAX_DATABASE or file_digest(copy) != report["databaseSha256"]:
            raise StorageRestoreError("database_checksum_mismatch")
        # Query the private pinned copy; a new WAL on the source cannot supply
        # unhashed rows. Immutable read mode never modifies either database.
        sql = sqlite3.connect(copy.as_uri() + "?mode=ro&immutable=1", uri=True)
        sql.row_factory = sqlite3.Row
        sql.execute("PRAGMA trusted_schema=OFF")
        if any(row[0] != "ok" for row in sql.execute("PRAGMA integrity_check")):
            raise StorageRestoreError("database_integrity_failure")
        if list(sql.execute("PRAGMA foreign_key_check")):
            raise StorageRestoreError("database_integrity_failure")
        if sql.execute("SELECT 1 FROM accounts WHERE deleted_at IS NOT NULL AND (units!=0 OR recovery_hash IS NOT NULL) LIMIT 1").fetchone():
            raise StorageRestoreError("invalid_deleted_account")
        if sql.execute("SELECT 1 FROM searches s JOIN accounts a ON a.id=s.account_id WHERE a.deleted_at IS NOT NULL LIMIT 1").fetchone():
            raise StorageRestoreError("invalid_deleted_account")
        count = sql.execute("SELECT COUNT(*) FROM published_index").fetchone()[0]
        if count > MAX_LOCATIONS:
            raise StorageRestoreError("publication_limit_exceeded")
        if sql.execute("""SELECT 1 FROM locations l LEFT JOIN published_index i ON i.location_id=l.id
          WHERE l.state='published' AND i.location_id IS NULL LIMIT 1""").fetchone():
            raise StorageRestoreError("published_location_missing_index")
        rows = [dict(row) for row in sql.execute("""SELECT l.*,
          l.output_sha256 AS location_output_sha256,i.output_sha256 AS published_output_sha256,i.four_view_sha256,i.four_view_key,
          i.object_index_sha256,i.object_index_key,c.validator AS coverage_validator,
          c.evidence_sha256 AS coverage_evidence_sha256
          FROM published_index i LEFT JOIN locations l ON l.id=i.location_id
          LEFT JOIN object_coverage c ON c.location_id=l.id ORDER BY l.id""")]
        scene, objects = {}, {}
        for row in rows:
            row["output_sha256"] = row.pop("published_output_sha256")
            if (type(row.get("id")) is not int or row["id"] < 1 or row.get("state") != "published"
                    or not isinstance(row.get("contributor_id"), str) or not row["contributor_id"].strip()
                    or not isinstance(row.get("output_sha256"), str) or not HEX.fullmatch(row["output_sha256"])
                    or row.get("location_output_sha256") != row["output_sha256"]):
                raise StorageRestoreError("invalid_contributed_publication")
            if row["lane"] == "scene":
                if row.get("four_view_sha256") != row["output_sha256"]:
                    raise StorageRestoreError("scene_publication_checksum_mismatch")
                cache_file(cache, row.get("four_view_key"))  # Validate before grouping.
                scene.setdefault(row["four_view_key"], []).append(row)
            elif row["lane"] == "object":
                # Integrity checks retain the same trusted Gen4/pose requirements
                # as snapshot export. They do not replace native inference audit.
                row_member(row, row["model"])
                cache_directory(cache, row.get("object_index_key"))
                objects.setdefault(row["object_index_key"], []).append(row)
            else:
                raise StorageRestoreError("invalid_contributed_publication")
        checked, total_bytes = {}, 0

        def remember(path: Path, maximum: int) -> None:
            nonlocal total_bytes
            path = plain_path(path)
            size = path.stat().st_size
            if size > maximum:
                raise StorageRestoreError("artifact_too_large")
            if path not in checked:
                total_bytes += size
                if len(checked) >= MAX_FILES or total_bytes > MAX_TOTAL_BYTES:
                    raise StorageRestoreError("storage_check_limit_exceeded")
                checked[path] = {"bytes": size, "sha256": bounded_hash(path, maximum)}

        for key, members in sorted(scene.items()):
            path = plain_path(cache_file(cache, key))
            remember(path, MAX_ARTIFACT_BYTES)
            raw = bounded_read(path, MAX_ARTIFACT_BYTES)
            if not raw or len(raw) % BYTES_PER_LOCATION:
                raise StorageRestoreError("invalid_scene_artifact")
            actual = Counter()
            for start in range(0, len(raw), BYTES_PER_LOCATION):
                record = raw[start:start + BYTES_PER_LOCATION]
                if not valid_record(record):
                    raise StorageRestoreError("invalid_scene_artifact")
                actual[digest(record)] += 1
            if actual != Counter(row["output_sha256"] for row in members):
                raise StorageRestoreError("scene_artifact_membership_mismatch")
        for key, members in sorted(objects.items()):
            folder = plain_path(cache_directory(cache, key), directory=True)
            remember(child_file(folder, "manifest.json"), 1024**2)
            remember(child_file(folder, "locations.tsv"), 1024**2)
            manifest = strict_json(bounded_read(child_file(folder, "manifest.json"), 1024**2))
            for name in manifest_file_names(manifest):
                remember(child_file(folder, name), MAX_BUNDLE_BYTES)
            load_bundle(folder, key, members)
        catalogs = list(sql.execute("SELECT r2_key,bytes,sha256 FROM pose_catalog ORDER BY lane,shard_id"))
        if len(catalogs) > MAX_FILES:
            raise StorageRestoreError("storage_check_limit_exceeded")
        for row in catalogs:
            if (type(row["bytes"]) is not int or not 0 < row["bytes"] <= MAX_CATALOG
                    or not isinstance(row["sha256"], str) or not HEX.fullmatch(row["sha256"])):
                raise StorageRestoreError("invalid_catalog_inventory")
            path = catalog_cache_file(cache, row["r2_key"])
            remember(path, MAX_CATALOG)
            if checked[path]["bytes"] != row["bytes"] or checked[path]["sha256"] != row["sha256"]:
                raise StorageRestoreError("catalog_checksum_mismatch")
        # Recheck every input after all validation; no successful report can be
        # sealed after a cache or database changes during the check.
        for path, expected in checked.items():
            plain_path(path)
            if path.stat().st_size != expected["bytes"] or bounded_hash(path, expected["bytes"]) != expected["sha256"]:
                raise StorageRestoreError("artifact_changed_during_check")
        closed_database(database)
        if bounded_hash(database, MAX_DATABASE) != report["databaseSha256"] or bounded_hash(copy, MAX_DATABASE) != report["databaseSha256"]:
            raise StorageRestoreError("database_changed_during_check")
        if bounded_hash(report_path, 1024**2) != report_sha256:
            raise StorageRestoreError("report_changed_during_check")
        sql.close()
        sql = None
        # Only opaque cache labels, file hashes and aggregate counts escape the
        # checker. Credentials, contributor IDs, keys and paths stay in inputs.
        inventory = [{"cacheLabel": path.relative_to(cache).as_posix(), **expected}
                     for path, expected in sorted(checked.items())]
        receipt = write_file(destination / "checked-files.private.json", encoded(inventory))
        result = {"version": 1, "scope": "offline-community-storage-integrity", "resource": resource,
                  "complete": True, "liveReady": False, "inferenceApproved": False,
                  "creditRecoveryVerified": False, "restoreReportSha256": report_sha256,
                  "databaseSha256": report["databaseSha256"], "publishedLocations": len(rows),
                  "sceneLocations": sum(map(len, scene.values())), "sceneArtifacts": len(scene),
                  "objectLocations": sum(map(len, objects.values())), "objectBundles": len(objects),
                  "catalogShards": len(catalogs), "checkedFiles": len(checked), "checkedBytes": total_bytes,
                  "checkedInventorySha256": receipt["sha256"]}
        write_file(destination / "storage-report.json", encoded(result))  # Completion last.
        return result
    except (Exception, KeyboardInterrupt) as error:
        if sql is not None:
            sql.close()
        code = (str(error) if isinstance(error, StorageRestoreError) else
                "interrupted" if isinstance(error, KeyboardInterrupt) else "storage_restore_check_failed")
        write_file(destination / "failure-report.json", encoded({"complete": False, "liveReady": False, "error": code}))
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Community storage restore check; does not contact Cloudflare")
    parser.add_argument("--repaired-dir", type=Path, required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--artifact-cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--environment", choices=("production", "staging"), default="production")
    args = parser.parse_args()
    try:
        result = check_storage_restore(args.repaired_dir, args.report_sha256, args.artifact_cache,
                                       args.out, environment=args.environment)
    except (Exception, KeyboardInterrupt) as error:
        code = (str(error) if isinstance(error, StorageRestoreError) else
                "interrupted" if isinstance(error, KeyboardInterrupt) else "storage_restore_check_failed")
        print(json.dumps({"complete": False, "liveReady": False, "error": code}))
        raise SystemExit(1)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
