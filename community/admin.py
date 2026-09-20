"""Read-only integrity audit, consistent SQLite backup, and catalog shard import."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def audit(database: Path) -> dict:
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        issues = []
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            issues.append(f"sqlite_integrity:{integrity}")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            issues.append("foreign_key_violation")
        if connection.execute(
            """SELECT 1 FROM accounts a WHERE a.units !=
                 COALESCE((SELECT SUM(l.units) FROM ledger l WHERE l.account_id=a.id), 0)
               LIMIT 1"""
        ).fetchone():
            issues.append("credit_ledger_mismatch")
        if connection.execute(
            """SELECT 1 FROM locations l LEFT JOIN published_index i ON i.location_id=l.id
               WHERE (l.state='published' AND (i.location_id IS NULL OR
                       l.output_sha256!=i.output_sha256 OR l.contributor_id IS NULL))
                  OR (l.state!='published' AND i.location_id IS NOT NULL)
               LIMIT 1"""
        ).fetchone():
            issues.append("published_index_mismatch")
        if connection.execute(
            """SELECT 1 FROM locations l LEFT JOIN leases e ON e.id=l.active_lease
               WHERE (l.state='leased' AND (e.id IS NULL OR e.state!='active' OR
                      e.expires_at!=l.lease_until OR NOT EXISTS
                      (SELECT 1 FROM lease_items i WHERE i.lease_id=e.id AND i.location_id=l.id)))
                  OR (l.state!='leased' AND (l.active_lease IS NOT NULL OR l.lease_until IS NOT NULL))
               LIMIT 1"""
        ).fetchone():
            issues.append("lease_state_mismatch")
        counts = {
            name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in ("accounts", "locations", "published_index", "leases", "ledger", "searches")
        }
        return {"ok": not issues, "issues": issues, "counts": counts}
    finally:
        connection.close()


def backup(database: Path, destination: Path) -> dict:
    if not database.is_file():
        raise FileNotFoundError(database)
    if destination.exists():
        raise FileExistsError(destination)
    if database.resolve() == destination.resolve():
        raise ValueError("backup destination must differ from source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
        # A fresh backup may inherit WAL mode without WAL sidecars. Convert it
        # to a self-contained file before checking or moving it elsewhere.
        target.execute("PRAGMA journal_mode=DELETE")
    finally:
        target.close()
        source.close()
    report = audit(destination)
    if not report["ok"]:
        destination.unlink()
        raise RuntimeError(f"backup failed integrity audit: {report['issues']}")
    return report


def restore(archive: Path, database: Path, *, artifacts: Path | None = None) -> dict:
    """Restore a SQLite backup into a new database path, then audit it."""
    report = backup(archive, database)
    if artifacts is not None:
        source_artifacts = archive.with_name(archive.stem + "-artifacts")
        if source_artifacts.is_dir():
            import shutil

            if artifacts.exists():
                raise FileExistsError(artifacts)
            shutil.copytree(source_artifacts, artifacts)
    return report


def import_shard(database: Path, tsv: Path, *, lane: str = "scene", artifacts: Path | None = None, limit: int | None = None) -> dict:
    from .service import CommunityService

    service = CommunityService(database, artifacts=artifacts or database.parent / "artifacts")
    return service.import_shard(tsv, lane=lane, limit=limit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "backup", "restore", "import-shard"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--to", type=Path)
    parser.add_argument("--from-backup", dest="from_backup", type=Path)
    parser.add_argument("--tsv", type=Path)
    parser.add_argument("--lane", default="scene")
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "backup" and args.to is None:
        parser.error("backup requires --to")
    if args.command == "restore" and args.from_backup is None:
        parser.error("restore requires --from-backup")
    if args.command == "import-shard" and args.tsv is None:
        parser.error("import-shard requires --tsv")
    if args.command == "check" and args.to is not None:
        parser.error("--to is only valid for backup")
    try:
        if args.command == "check":
            report = audit(args.db)
        elif args.command == "backup":
            report = backup(args.db, args.to)
        elif args.command == "import-shard":
            report = import_shard(args.db, args.tsv, lane=args.lane, artifacts=args.artifacts, limit=args.limit)
        else:
            report = restore(args.from_backup, args.db)
    except (FileNotFoundError, FileExistsError, RuntimeError, sqlite3.DatabaseError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(report, sort_keys=True))
    if isinstance(report, dict) and report.get("ok") is False:
        parser.exit(1)


if __name__ == "__main__":
    main()
