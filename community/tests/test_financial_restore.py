from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from community.financial_restore import (FinancialRestoreError, check_financial_restore,
                                         export_financial_snapshot, validate_snapshot)
from community.search_snapshot import CONFIRMED_STAGING_RESOURCE, digest, encoded

ROOT = Path(__file__).resolve().parents[2]


class FinancialRestoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = self.root / "current.sqlite"
        self.repaired = self.root / "repaired"
        self.repaired.mkdir()
        self.database = self.repaired / "restored.sqlite"
        self.active, self.deleted = "a" * 32, "b" * 32
        self.search_id = "c" * 32
        with closing(sqlite3.connect(self.current)) as sql, sql:
            sql.executescript((ROOT / "deploy/cloudflare/schema.sql").read_text())
            sql.executemany("INSERT INTO accounts (id,token_hash,units,deleted_at) VALUES (?,?,?,?)",
                            [(self.active, "private-session-one", 20000, None),
                             (self.deleted, "private-revoked-session", 0, 1000)])
            sql.executemany("INSERT INTO ledger VALUES (?,?,?,?,?)", [
                (1, self.active, 120000, "verified_work", "lease:private-earned-reference"),
                (2, self.active, -100000, "search", "search:" + self.search_id),
                (3, self.deleted, 100, "verified_work", "lease:private-deleted-reference"),
                (4, self.deleted, -100, "account_deleted", "account-delete:" + self.deleted)])
            sql.execute("INSERT INTO searches VALUES (?,?,?,?,?)", (self.search_id, self.active,
                "private-repeat-key", "sha256:" + "d" * 64,
                json.dumps({"searchId": self.search_id, "privateResult": "saved exact ranked response"})))
        shutil.copyfile(self.current, self.database)
        self.seal_report()
        self.export()

    def export(self, name="current-export"):
        report = export_financial_snapshot(self.current, digest(self.current.read_bytes()), self.root / name,
                                          exported_at=2000, environment="staging")
        self.snapshot = self.root / name / "financial-snapshot.private.json"
        self.snapshot_pin = report["snapshotSha256"]
        return report

    def seal_report(self):
        report = {"version": 1, "scope": "offline-privacy-repaired-community-copy", "liveReady": False,
                  "resource": dict(CONFIRMED_STAGING_RESOURCE), "databaseSha256": digest(self.database.read_bytes())}
        # An actual Node-produced report need not use this module's encoding.
        raw = (json.dumps(report, indent=2) + "\n").encode()
        (self.repaired / "restore-report.json").write_bytes(raw)
        self.report_pin = digest(raw)

    def mutate(self, statement, parameters=()):
        with closing(sqlite3.connect(self.database)) as sql, sql:
            sql.execute(statement, parameters)
        self.seal_report()

    def check(self, name="checked", **overrides):
        options = {"not_before": 1900, "now": 2100, "environment": "staging"} | overrides
        return check_financial_restore(self.repaired, self.report_pin, self.snapshot, self.snapshot_pin,
                                       self.root / name, **options)

    def assert_failed(self, code):
        with self.assertRaisesRegex(FinancialRestoreError, code):
            self.check()
        folder = self.root / "checked"
        self.assertFalse((folder / "financial-report.json").exists())
        raw = (folder / "failure-report.json").read_bytes()
        self.assertFalse(json.loads(raw)["complete"])
        for private in (self.active, self.deleted, self.search_id, "private-session-one",
                        "private-repeat-key", "saved exact ranked response", str(self.root)):
            self.assertNotIn(private.encode(), raw)

    def test_exact_balance_earnings_and_paid_search_history_match_without_live_approval(self):
        before = self.database.read_bytes(), self.current.read_bytes(), self.snapshot.read_bytes()
        result = self.check()
        self.assertTrue(result["complete"])
        self.assertTrue(result["financialStateMatchesTrustedCutoff"])
        self.assertFalse(result["liveReady"])
        self.assertFalse(result["creditRecoveryVerified"])
        self.assertFalse(result["deletedAccountHistoryCompared"])
        self.assertEqual(result["accounts"], 2)
        self.assertEqual(before, (self.database.read_bytes(), self.current.read_bytes(), self.snapshot.read_bytes()))
        for private in (self.active, "private-repeat-key", "saved exact ranked response", "private-session-one"):
            self.assertNotIn(private.encode(), (self.root / "checked/financial-report.json").read_bytes())
            self.assertNotIn(private.encode(), (self.root / "current-export/export-report.json").read_bytes())
        with self.assertRaises(FileExistsError):
            self.check()

    def test_new_earned_credit_after_backup_cannot_be_lost(self):
        with closing(sqlite3.connect(self.current)) as sql, sql:
            sql.execute("INSERT INTO ledger (account_id,units,reason,reference) VALUES (?,16,'verified_work','lease:new-work')", (self.active,))
            sql.execute("UPDATE accounts SET units=units+16 WHERE id=?", (self.active,))
        self.export("after-backup-export")
        self.assert_failed("restored_financial_state_differs")

    def test_same_balance_with_changed_history_still_fails(self):
        self.mutate("INSERT INTO ledger (account_id,units,reason,reference) VALUES (?,16,'verified_work','lease:new-work')", (self.active,))
        self.mutate("INSERT INTO ledger (account_id,units,reason,reference) VALUES (?,-16,'correction','private-correction')", (self.active,))
        self.assert_failed("restored_financial_state_differs")

    def test_balance_not_backed_by_ledger_fails(self):
        self.mutate("UPDATE accounts SET units=units+1 WHERE id=?", (self.active,))
        self.assert_failed("financial_balance_ledger_mismatch")

    def test_missing_saved_result_cannot_allow_repeated_paid_search(self):
        self.mutate("DELETE FROM searches")
        self.assert_failed("financial_search_debit_mismatch")

    def test_missing_debit_cannot_make_saved_result_free(self):
        self.mutate("DELETE FROM ledger WHERE reason='search'")
        self.mutate("UPDATE accounts SET units=120000 WHERE id=?", (self.active,))
        self.assert_failed("financial_search_debit_mismatch")

    def test_changed_replay_key_or_ranked_result_fails_with_same_balance(self):
        original = self.database.read_bytes()
        for field, value in (("idempotency_key", "other-repeat-key"),
                             ("result_json", json.dumps({"searchId": self.search_id, "privateResult": "different ranking"})),
                             ("query", "sha256:" + "e" * 64)):
            with self.subTest(field=field):
                self.database.write_bytes(original)
                self.mutate(f"UPDATE searches SET {field}=?", (value,))
                with self.assertRaisesRegex(FinancialRestoreError, "restored_financial_state_differs"):
                    self.check(field)

    def test_deleted_balance_closure_can_differ_but_revocation_and_zero_balance_must_match(self):
        self.mutate("UPDATE ledger SET units=60 WHERE id=3")
        self.mutate("UPDATE ledger SET units=-60,reason='account_restore_deleted' WHERE id=4")
        self.assertTrue(self.check("deleted-balanced")["complete"])
        self.mutate("UPDATE accounts SET deleted_at=NULL WHERE id=?", (self.deleted,))
        self.assert_failed("restored_financial_state_differs")

    def test_new_account_after_backup_cannot_be_omitted(self):
        with closing(sqlite3.connect(self.current)) as sql, sql:
            sql.execute("INSERT INTO accounts (id,token_hash) VALUES (?,?)", ("f" * 32, "private-new-session"))
        self.export("new-account-export")
        self.assert_failed("restored_financial_state_differs")

    def test_resource_cutoff_and_pin_changes_fail_and_preserve_outputs(self):
        for name, kwargs in (("wrong-environment", {"environment": "production"}),
                             ("stale", {"not_before": 2001}), ("future", {"now": 1999}),
                             ("bool-cutoff", {"not_before": True})):
            with self.subTest(name=name), self.assertRaisesRegex(FinancialRestoreError, "invalid_or_stale_financial_snapshot"):
                self.check(name, **kwargs)
            self.assertFalse((self.root / name / "financial-report.json").exists())
        self.snapshot.write_bytes(self.snapshot.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            self.check("changed-pin")
        self.assertFalse((self.root / "changed-pin/financial-report.json").exists())

    def test_snapshot_rejects_duplicate_accounts_and_other_bucket(self):
        document = json.loads(self.snapshot.read_bytes())
        document["accounts"].append(document["accounts"][0])
        with self.assertRaisesRegex(FinancialRestoreError, "invalid_financial_snapshot_account"):
            validate_snapshot(document, "staging", 1900, 2100)
        document = json.loads(self.snapshot.read_bytes())
        document["resource"]["bucket"] = "geonections-images"
        with self.assertRaisesRegex(FinancialRestoreError, "invalid_or_stale_financial_snapshot"):
            validate_snapshot(document, "staging", 1900, 2100)

    def test_invalid_current_source_does_not_export_approval(self):
        with closing(sqlite3.connect(self.current)) as sql, sql:
            sql.execute("DELETE FROM searches")
        with self.assertRaisesRegex(FinancialRestoreError, "financial_search_debit_mismatch"):
            self.export("broken-source")
        self.assertFalse((self.root / "broken-source/export-report.json").exists())
        self.assertTrue((self.root / "broken-source/failure-report.json").exists())

    def test_open_database_missing_pin_and_row_limits_stop(self):
        sidecar = Path(str(self.current) + "-wal")
        sidecar.write_bytes(b"private unpinned changes")
        with self.assertRaises(ValueError):
            self.export("open-source")
        sidecar.unlink()
        with patch("community.financial_restore.MAX_ACCOUNTS", 1), self.assertRaisesRegex(FinancialRestoreError, "financial_row_limit_exceeded"):
            self.export("limited-source")
        self.report_pin = "0" * 64
        with self.assertRaises(ValueError):
            self.check("bad-report-pin")
        self.assertFalse((self.root / "bad-report-pin/financial-report.json").exists())

    def test_source_change_during_check_is_detected(self):
        from community.financial_restore import financial_state
        def concurrent_change(sql):
            actual = financial_state(sql)
            self.database.write_bytes(self.database.read_bytes() + b"private changed bytes")
            return actual
        with patch("community.financial_restore.financial_state", side_effect=concurrent_change):
            self.assert_failed("input_changed_during_check")

    def test_cli_protects_private_text_and_does_not_make_success_on_wrong_pin(self):
        result = subprocess.run([sys.executable, "-B", "-m", "community.financial_restore", "check",
            "--repaired-dir", str(self.repaired), "--report-sha256", "0" * 64,
            "--snapshot", str(self.snapshot), "--snapshot-sha256", self.snapshot_pin,
            "--writers-stopped-at", "1900", "--environment", "staging", "--out", str(self.root / "cli-failed")],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["complete"])
        for private in (str(self.root), "private-session-one", self.active, "private-repeat-key"):
            self.assertNotIn(private, result.stdout + result.stderr)
        self.assertFalse((self.root / "cli-failed/financial-report.json").exists())

    def test_invalid_work_award_and_incomplete_json_search_are_rejected(self):
        self.mutate("UPDATE ledger SET reason='verified_work' WHERE id=2")
        self.assert_failed("invalid_financial_work_award")
        self.mutate("UPDATE ledger SET reason='search' WHERE id=2")
        self.mutate("UPDATE searches SET result_json='{}'")
        with self.assertRaisesRegex(FinancialRestoreError, "invalid_financial_search_result"):
            self.check("incomplete-response")

    def test_interruption_preserves_redacted_failure_and_no_completion(self):
        with patch("community.financial_restore.financial_state", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.check()
        self.assertFalse((self.root / "checked/financial-report.json").exists())
        raw = (self.root / "checked/failure-report.json").read_bytes()
        self.assertEqual(json.loads(raw)["error"], "financial_check_failed")
        self.assertNotIn(self.active.encode(), raw)


if __name__ == "__main__":
    unittest.main()
