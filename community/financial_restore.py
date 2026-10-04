"""Offline comparison with a separately trusted, current financial snapshot.

Never repairs balances, contacts a provider or opens the restored service.
Operators must stop/drain all writers and establish source completeness first.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from .native_scene_search import plain_path, strict_json
from .search_snapshot import HEX, digest, encoded, file_digest, pinned_read, resource_for_environment, write_file
from .storage_restore import MAX_DATABASE, closed_database

MAX_ACCOUNTS = 100_000
MAX_ROWS = 1_000_000
MAX_SNAPSHOT = 32 * 1024**2
SAFE_INTEGER = 2**53 - 1
ACCOUNT = re.compile(r"[0-9a-f]{32}\Z")
SCOPE = "closed-community-financial-snapshot"


class FinancialRestoreError(ValueError):
    pass


def integer(value, *, signed=False):
    return type(value) is int and (-SAFE_INTEGER if signed else 0) <= value <= SAFE_INTEGER


def new_destination(path):
    path = Path(path).absolute()
    plain_path(path.parent, directory=True)
    path.mkdir(mode=0o700, exist_ok=False)
    return plain_path(path, directory=True).resolve(strict=True)


@contextmanager
def pinned_database(source, pin, destination):
    source = plain_path(source).resolve(strict=True)
    if not isinstance(pin, str) or not HEX.fullmatch(pin):
        raise FinancialRestoreError("invalid_checksum_pin")
    closed_database(source)
    target = destination / "input.sqlite"
    total = 0
    with source.open("rb") as handle, target.open("xb") as output:
        for raw in iter(lambda: handle.read(1024**2), b""):
            total += len(raw)
            if total > MAX_DATABASE:
                raise FinancialRestoreError("database_too_large")
            output.write(raw)
    if file_digest(target) != pin:
        raise FinancialRestoreError("database_checksum_mismatch")
    closed_database(source)
    sql = sqlite3.connect(target.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        sql.row_factory = sqlite3.Row
        sql.execute("PRAGMA trusted_schema=OFF")
        if any(row[0] != "ok" for row in sql.execute("PRAGMA integrity_check")) or list(sql.execute("PRAGMA foreign_key_check")):
            raise FinancialRestoreError("database_integrity_failure")
        yield sql
        closed_database(source)
        if file_digest(source) != pin:
            raise FinancialRestoreError("input_changed_during_check")
    finally:
        sql.close()


def financial_state(sql):
    required = {
        "accounts": {"id", "units", "deleted_at"},
        "ledger": {"id", "account_id", "units", "reason", "reference"},
        "searches": {"id", "account_id", "idempotency_key", "query", "result_json"},
    }
    for table, columns in required.items():
        if not columns <= {row[1] for row in sql.execute(f"PRAGMA table_info({table})")}:
            raise FinancialRestoreError("unsupported_financial_schema")
    for table, limit in (("accounts", MAX_ACCOUNTS), ("ledger", MAX_ROWS), ("searches", MAX_ROWS)):
        if sql.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > limit:
            raise FinancialRestoreError("financial_row_limit_exceeded")
    accounts = {}
    for row in sql.execute("SELECT id,units,deleted_at FROM accounts ORDER BY id"):
        if (not isinstance(row["id"], str) or not ACCOUNT.fullmatch(row["id"]) or row["id"] in accounts
                or not integer(row["units"]) or row["deleted_at"] is not None and not integer(row["deleted_at"])):
            raise FinancialRestoreError("invalid_financial_account")
        accounts[row["id"]] = {"accountId": row["id"], "units": row["units"], "deletedAt": row["deleted_at"],
                               "ledgerCount": 0, "searchCount": 0, "ledger": hashlib.sha256(),
                               "searches": hashlib.sha256(), "total": 0}
    references, search_debits = set(), {}
    previous_id = 0
    for row in sql.execute("SELECT id,account_id,units,reason,reference FROM ledger ORDER BY id"):
        account = accounts.get(row["account_id"])
        if (account is None or not integer(row["id"]) or row["id"] <= previous_id or not integer(row["units"], signed=True)
                or not isinstance(row["reason"], str) or not row["reason"] or len(row["reason"]) > 200
                or not isinstance(row["reference"], str) or not row["reference"] or len(row["reference"]) > 1000
                or row["reference"] in references):
            raise FinancialRestoreError("invalid_financial_ledger")
        references.add(row["reference"])
        previous_id = row["id"]
        if row["reason"] == "verified_work" and (row["units"] <= 0 or not row["reference"].startswith("lease:")):
            raise FinancialRestoreError("invalid_financial_work_award")
        if row["reason"] == "search" and account["deletedAt"] is None:
            if row["units"] >= 0 or not row["reference"].startswith("search:"):
                raise FinancialRestoreError("invalid_financial_search_debit")
            search_debits[row["reference"][7:]] = row["account_id"]
        account["total"] += row["units"]
        if not integer(account["total"], signed=True):
            raise FinancialRestoreError("financial_accounting_overflow")
        account["ledgerCount"] += 1
        account["ledger"].update(encoded(dict(row)))
    keys, ids = set(), set()
    for row in sql.execute("SELECT id,account_id,idempotency_key,query,result_json FROM searches ORDER BY id"):
        account = accounts.get(row["account_id"])
        key = (row["account_id"], row["idempotency_key"])
        if (account is None or account["deletedAt"] is not None
                or any(not isinstance(row[name], str) or not row[name] for name in ("id", "idempotency_key", "query", "result_json"))
                or len(row["id"]) > 200 or len(row["idempotency_key"]) > 100
                or len(row["query"]) > 10000 or len(row["result_json"]) > 4 * 1024**2
                or key in keys or row["id"] in ids):
            raise FinancialRestoreError("invalid_financial_search")
        keys.add(key)
        ids.add(row["id"])
        if search_debits.pop(row["id"], None) != row["account_id"]:
            raise FinancialRestoreError("financial_search_debit_mismatch")
        saved = strict_json(row["result_json"].encode("utf-8"))
        if not isinstance(saved, dict) or saved.get("searchId") != row["id"]:
            raise FinancialRestoreError("invalid_financial_search_result")
        account["searchCount"] += 1
        account["searches"].update(encoded(dict(row)))
    if search_debits:
        raise FinancialRestoreError("financial_search_debit_mismatch")
    result = []
    for account in accounts.values():
        if account["total"] != account["units"] or account["deletedAt"] is not None and account["units"] != 0:
            raise FinancialRestoreError("financial_balance_ledger_mismatch")
        # A privacy repair may add a balancing deletion entry to the old copy.
        # Deleted accounts must remain zero/search-free; their historical ledger
        # equivalence is deliberately outside this financial comparison.
        deleted = account["deletedAt"] is not None
        result.append({key: account[key] for key in ("accountId", "units", "deletedAt")}
                      | {"ledgerCount": None if deleted else account["ledgerCount"],
                         "ledgerSha256": None if deleted else account["ledger"].hexdigest(),
                         "searchCount": account["searchCount"], "searchesSha256": account["searches"].hexdigest()})
    return result


def validate_snapshot(document, environment, not_before, now):
    if (not integer(not_before) or not integer(now) or not_before > now
            or not isinstance(document, dict) or set(document) != {"version", "scope", "resource", "exportedAt", "databaseSha256", "accounts"}
            or document["version"] != 1 or type(document["version"]) is not int or document["scope"] != SCOPE
            or document["resource"] != resource_for_environment(environment)
            or not integer(document["exportedAt"]) or not not_before <= document["exportedAt"] <= now
            or not isinstance(document["databaseSha256"], str) or not HEX.fullmatch(document["databaseSha256"])
            or not isinstance(document["accounts"], list) or len(document["accounts"]) > MAX_ACCOUNTS):
        raise FinancialRestoreError("invalid_or_stale_financial_snapshot")
    previous = ""
    for row in document["accounts"]:
        if (not isinstance(row, dict) or set(row) != {"accountId", "units", "deletedAt", "ledgerCount", "ledgerSha256", "searchCount", "searchesSha256"}
                or not isinstance(row["accountId"], str) or not ACCOUNT.fullmatch(row["accountId"])
                or row["accountId"] <= previous or not integer(row["units"]) or not integer(row["searchCount"])
                or row["searchCount"] > MAX_ROWS or not isinstance(row["searchesSha256"], str) or not HEX.fullmatch(row["searchesSha256"])):
            raise FinancialRestoreError("invalid_financial_snapshot_account")
        previous = row["accountId"]
        if row["deletedAt"] is None:
            if (not integer(row["ledgerCount"]) or row["ledgerCount"] > MAX_ROWS
                    or not isinstance(row["ledgerSha256"], str) or not HEX.fullmatch(row["ledgerSha256"])):
                raise FinancialRestoreError("invalid_financial_snapshot_account")
        elif (not integer(row["deletedAt"]) or row["deletedAt"] > document["exportedAt"] or row["units"] != 0
              or row["searchCount"] != 0 or row["ledgerCount"] is not None or row["ledgerSha256"] is not None
              or row["searchesSha256"] != digest(b"")):
            raise FinancialRestoreError("invalid_financial_snapshot_account")


def fail(destination, error):
    write_file(destination / "failure-report.json", encoded({"version": 1, "complete": False, "liveReady": False,
        "error": str(error) if isinstance(error, FinancialRestoreError) else "financial_check_failed"}))


def export_financial_snapshot(database, database_sha256, destination, *, exported_at=None, environment="production"):
    destination = new_destination(destination)
    try:
        resource = resource_for_environment(environment)
        with pinned_database(database, database_sha256, destination) as sql:
            document = {"version": 1, "scope": SCOPE, "resource": resource,
                        "exportedAt": int(time.time()) if exported_at is None else exported_at,
                        "databaseSha256": database_sha256, "accounts": financial_state(sql)}
        validate_snapshot(document, environment, document["exportedAt"], int(time.time()))
        raw = encoded(document)
        if len(raw) > MAX_SNAPSHOT:
            raise FinancialRestoreError("financial_snapshot_too_large")
        write_file(destination / "financial-snapshot.private.json", raw)
        report = {"version": 1, "complete": True, "liveReady": False, "scope": "offline-financial-snapshot-export",
                  "resource": resource, "snapshotSha256": digest(raw), "sourceDatabaseSha256": database_sha256,
                  "accounts": len(document["accounts"])}
        write_file(destination / "export-report.json", encoded(report))
        return report
    except (Exception, KeyboardInterrupt) as error:
        fail(destination, error)
        raise


def check_financial_restore(repaired_dir, report_sha256, snapshot, snapshot_sha256, destination,
                            *, not_before, environment="production", now=None):
    destination = new_destination(destination)
    try:
        now = int(time.time()) if now is None else now
        snapshot = plain_path(snapshot).resolve(strict=True)
        raw = pinned_read(snapshot, snapshot_sha256, MAX_SNAPSHOT)
        trusted = strict_json(raw)
        validate_snapshot(trusted, environment, not_before, now)
        root = plain_path(repaired_dir, directory=True).resolve(strict=True)
        if root == destination or root in destination.parents or snapshot.parent == destination:
            raise FinancialRestoreError("output_overlaps_input")
        report_path = plain_path(root / "restore-report.json")
        report_raw = pinned_read(report_path, report_sha256, 1024**2)
        report = strict_json(report_raw)
        if (not isinstance(report, dict) or report.get("version") != 1
                or report.get("scope") != "offline-privacy-repaired-community-copy"
                or report.get("liveReady") is not False or report.get("resource") != trusted["resource"]):
            raise FinancialRestoreError("invalid_repaired_copy_report")
        with pinned_database(root / "restored.sqlite", report.get("databaseSha256"), destination) as sql:
            actual = financial_state(sql)
        if actual != trusted["accounts"]:
            raise FinancialRestoreError("restored_financial_state_differs")
        if pinned_read(snapshot, snapshot_sha256, MAX_SNAPSHOT) != raw or pinned_read(report_path, report_sha256, 1024**2) != report_raw:
            raise FinancialRestoreError("input_changed_during_check")
        result = {"version": 1, "complete": True, "scope": "offline-financial-restore-comparison", "liveReady": False,
                  "creditRecoveryVerified": False, "financialStateMatchesTrustedCutoff": True,
                  "resource": trusted["resource"], "snapshotSha256": snapshot_sha256, "restoreReportSha256": report_sha256,
                  "databaseSha256": report["databaseSha256"], "trustedExportedAt": trusted["exportedAt"],
                  "writerStopAt": not_before, "accounts": len(actual), "deletedAccountHistoryCompared": False}
        write_file(destination / "financial-report.json", encoded(result))
        return result
    except (Exception, KeyboardInterrupt) as error:
        fail(destination, error)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    export = sub.add_parser("export", help="Hash financial state from a separately trusted closed current database.")
    export.add_argument("--database", type=Path, required=True)
    export.add_argument("--database-sha256", required=True)
    check = sub.add_parser("check", help="Compare a pinned privacy repair with the trusted current snapshot.")
    check.add_argument("--repaired-dir", type=Path, required=True)
    check.add_argument("--report-sha256", required=True)
    check.add_argument("--snapshot", type=Path, required=True)
    check.add_argument("--snapshot-sha256", required=True)
    check.add_argument("--writers-stopped-at", type=int, required=True)
    for command in (export, check):
        command.add_argument("--out", type=Path, required=True)
        command.add_argument("--environment", choices=("production", "staging"), default="production")
    args = parser.parse_args()
    try:
        if args.operation == "export":
            result = export_financial_snapshot(args.database, args.database_sha256, args.out, environment=args.environment)
        else:
            result = check_financial_restore(args.repaired_dir, args.report_sha256, args.snapshot, args.snapshot_sha256,
                                            args.out, not_before=args.writers_stopped_at, environment=args.environment)
        print(json.dumps(result, indent=2))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({"complete": False, "liveReady": False,
                          "error": str(error) if isinstance(error, FinancialRestoreError) else "financial_check_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
