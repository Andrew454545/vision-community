import json
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from community.contribute import CommunityClient, ContributeError
from community.desktop import DesktopApp, DesktopClient
from community.submission_outbox import SubmissionOutbox, MAX_PENDING_SUBMISSIONS


class OutboxTest(unittest.TestCase):
    url = "https://community.example"
    account = "a" * 32
    lease = "b" * 32
    outputs = [{"locationId": 1, "embedding": "saved-output-data"}]

    def client(self, root):
        client = DesktopClient(self.url)
        client.enable_outbox(root, self.account)
        return client

    def test_restart_recovers_delivery_after_lost_submit_response_without_reprocessing(self):
        with tempfile.TemporaryDirectory() as root:
            first = self.client(root)
            first.token = "PRIVATE_BEARER_TOKEN"
            with patch.object(CommunityClient, "request", side_effect=ContributeError("network_error")):
                with self.assertRaises(ContributeError):
                    first.submit(self.lease, self.outputs)
            self.assertTrue(first.submission_is_saved(self.lease))
            restarted = self.client(root)
            calls = []

            def network(client, method, path, body=None):
                calls.append((method, path, body))
                if path == "/api/submissions":
                    return 200, {"accepted": 0, "unitsEarned": 0, "pendingAudit": True, "submissionId": self.lease}, None
                if path == "/api/scene-audits":
                    return 200, {"accepted": 1, "unitsEarned": 1, "pendingAudit": False}, None
                self.fail("Recovery requested a lease or ran unrelated work")

            with patch.object(CommunityClient, "request", new=network):
                self.assertEqual(restarted.resume_submissions(), {"accepted": 1, "unitsEarned": 1})
                self.assertEqual(restarted.resume_submissions(), {"accepted": 0, "unitsEarned": 0})
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][2]["outputs"], self.outputs)
            self.assertEqual(restarted.pending, 0)
            self.assertNotIn(b"PRIVATE_BEARER_TOKEN", (Path(root) / "submissions.sqlite").read_bytes())

    def test_pending_audit_survives_restart_and_an_outage(self):
        with tempfile.TemporaryDirectory() as root:
            first = self.client(root)
            first.outbox.remember(self.lease, self.outputs)
            first.outbox.result(self.lease, {"pendingAudit": True})
            restarted = self.client(root)
            with patch.object(CommunityClient, "request", side_effect=ContributeError("network_error")):
                with self.assertRaises(ContributeError):
                    restarted.resume_submissions()
            self.assertEqual(restarted.pending, 1)
            with patch.object(CommunityClient, "request", return_value=(200, {"accepted": 1, "unitsEarned": 1}, None)) as request:
                restarted.resume_submissions()
                self.assertEqual(request.call_args.args[1], "/api/scene-audits")
            self.assertEqual(restarted.pending, 0)

    def test_outbox_cannot_be_replayed_to_a_different_account_or_service(self):
        with tempfile.TemporaryDirectory() as root:
            first = self.client(root)
            first.outbox.remember(self.lease, self.outputs)
            for origin, account in [(self.url, "c" * 32), ("https://other.example", self.account)]:
                other = SubmissionOutbox(Path(root) / "submissions.sqlite", origin, account)
                self.assertEqual(other.pending(), [])
            self.assertEqual(first.outbox.count(), 1)

    def test_months_of_receipts_do_not_require_scanning_history_to_recover(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            path = Path(root) / 'submissions.sqlite'
            with closing(sqlite3.connect(path)) as connection:
                connection.executemany('''INSERT INTO deliveries
                    (origin,account_id,lease_id,payload_json,payload_sha256,state,result_json,updated_at)
                    VALUES (?, ?, ?, NULL, ?, 'accepted', ?, ?)''',
                    [(self.url, self.account, f'{n:032x}', 'c' * 64, '{"accepted":16}', n) for n in range(10000)])
                connection.commit()
            for n in (10001, 10002):
                client.outbox.remember(f'{n:032x}', self.outputs)
            client.outbox.result(f'{10002:032x}', {'pendingAudit': True})
            self.assertEqual([row['lease_id'] for row in client.outbox.pending()], [f'{10001:032x}', f'{10002:032x}'])
            self.assertEqual(client.pending, 2)
            self.assertTrue(client.submission_is_saved(f'{5:032x}'))
            with closing(sqlite3.connect(path)) as connection:
                queries = (
                    ("SELECT lease_id,state,payload_json FROM deliveries WHERE origin=? AND account_id=? AND state IN ('ready','pending') ORDER BY updated_at,rowid LIMIT 16", 'deliveries_pending'),
                    ("SELECT COUNT(*) FROM deliveries WHERE origin=? AND account_id=? AND state IN ('ready','pending')", 'deliveries_pending'),
                    ("SELECT COUNT(*) FROM deliveries WHERE origin=? AND account_id=? AND state='lease_lost'", 'deliveries_lost'),
                )
                for query, index in queries:
                    plan = ' '.join(row[3] for row in connection.execute('EXPLAIN QUERY PLAN ' + query, (self.url, self.account)))
                    self.assertIn(index, plan)
                    self.assertNotIn('TEMP B-TREE', plan)
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0], 10002)

    def test_older_journal_migration_preserves_pending_payloads(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'submissions.sqlite'
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('''CREATE TABLE deliveries (origin TEXT,account_id TEXT,lease_id TEXT,
                    payload_json TEXT,payload_sha256 TEXT,state TEXT,result_json TEXT,
                    PRIMARY KEY(origin,account_id,lease_id))''')
                connection.execute('INSERT INTO deliveries VALUES (?,?,?,?,?,?,?)',
                    (self.url, self.account, self.lease, json.dumps(self.outputs), 'c' * 64, 'ready', None))
                connection.commit()
            migrated = self.client(root)
            self.assertEqual(json.loads(migrated.outbox.pending()[0]['payload_json']), self.outputs)
            self.assertEqual(migrated.pending, 1)

    def test_altered_local_payload_and_empty_response_preserve_saved_work(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            client.outbox.remember(self.lease, self.outputs)
            with self.assertRaisesRegex(ValueError, "submission_payload_changed"):
                client.outbox.remember(self.lease, [{"locationId": 2}])
            with self.assertRaisesRegex(ValueError, "invalid_submission_result"):
                client.outbox.result(self.lease, {})
            self.assertEqual(json.loads(client.outbox.pending()[0]["payload_json"]), self.outputs)

    def test_rejected_audit_stops_processing_and_keeps_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            client.outbox.remember(self.lease, self.outputs)
            client.outbox.result(self.lease, {"pendingAudit": True})
            with patch.object(CommunityClient, "request", return_value=(200, {"rejected": True}, None)):
                with self.assertRaisesRegex(ContributeError, "scene_submission_rejected"):
                    client.resume_submissions()
            with closing(sqlite3.connect(Path(root) / "submissions.sqlite")) as connection:
                state, payload = connection.execute("SELECT state,payload_json FROM deliveries").fetchone()
            self.assertEqual(state, "rejected")
            self.assertEqual(json.loads(payload), self.outputs)

    def test_pending_backlog_is_bounded_and_retries_are_fair(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            for index in range(MAX_PENDING_SUBMISSIONS):
                client.outbox.remember(f"{index:032x}", self.outputs)
            with patch.object(CommunityClient, "lease") as lease:
                with self.assertRaisesRegex(ContributeError, "scene_audit_backlog"):
                    client.lease("scene", 16, "slow")
                lease.assert_not_called()
            first = client.outbox.pending(1)[0]["lease_id"]
            client.outbox.result(first, {"pendingAudit": True})
            self.assertNotEqual(client.outbox.pending(1)[0]["lease_id"], first)

    def test_confirmed_lost_lease_preserves_payload_and_is_not_retried_after_restart(self):
        for code, status in (("expired_lease", 409), ("lease_lost", 409), ("unknown_lease", 404)):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as root:
                client = self.client(root)
                client.outbox.remember(self.lease, self.outputs)
                with patch.object(CommunityClient, "request", side_effect=ContributeError(code, status)) as request:
                    self.assertEqual(client.resume_submissions(), {"accepted": 0, "unitsEarned": 0, "leaseLost": 1})
                    request.assert_called_once()
                restarted = self.client(root)
                with patch.object(CommunityClient, "request") as request:
                    self.assertEqual(restarted.resume_submissions(), {"accepted": 0, "unitsEarned": 0})
                    request.assert_not_called()
                self.assertEqual(restarted.pending, 0)
                self.assertEqual(restarted.undelivered, 1)
                self.assertTrue(restarted.submission_is_saved(self.lease))
                with closing(sqlite3.connect(Path(root) / "submissions.sqlite")) as connection:
                    state, payload, result = connection.execute("SELECT state,payload_json,result_json FROM deliveries").fetchone()
                self.assertEqual(state, "lease_lost")
                self.assertEqual(json.loads(payload), self.outputs)
                self.assertEqual(json.loads(result), {"accepted": 0, "unitsEarned": 0, "leaseLost": True, "code": code})

    def test_only_definitive_submission_ownership_errors_can_close_delivery(self):
        failures = (("network_error", 503), ("http_error", 404), ("unauthorized", 401),
                    ("verification_failed", 422), ("expired_lease", 503), ("lease_lost", 500),
                    ("unknown_lease", 409), ("expired_lease", 401))
        for code, status in failures:
            with self.subTest(code=code, status=status), tempfile.TemporaryDirectory() as root:
                client = self.client(root)
                client.outbox.remember(self.lease, self.outputs)
                with patch.object(CommunityClient, "request", side_effect=ContributeError(code, status)):
                    with self.assertRaises(ContributeError):
                        client.resume_submissions()
                self.assertEqual(client.pending, 1)
                self.assertEqual(client.undelivered, 0)
                self.assertEqual(client.outbox.pending()[0]["state"], "ready")

    def test_pending_audit_is_not_abandoned_on_ownership_error(self):
        for code, status in (("unknown_lease", 404), ("expired_lease", 409)):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as root:
                client = self.client(root)
                client.outbox.remember(self.lease, self.outputs)
                client.outbox.result(self.lease, {"pendingAudit": True})
                with patch.object(CommunityClient, "request", side_effect=ContributeError(code, status)):
                    with self.assertRaises(ContributeError):
                        client.resume_submissions()
                self.assertEqual(client.pending, 1)
                self.assertEqual(client.undelivered, 0)
                self.assertEqual(client.outbox.pending()[0]["state"], "pending")

    def test_staging_then_failed_audit_keeps_pending_delivery(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            client.outbox.remember(self.lease, self.outputs)
            responses = [(200, {"pendingAudit": True, "submissionId": self.lease}, None),
                         ContributeError("expired_lease", 409)]
            with patch.object(CommunityClient, "request", side_effect=responses):
                with self.assertRaises(ContributeError):
                    client.resume_submissions()
            self.assertEqual(client.pending, 1)
            self.assertEqual(client.undelivered, 0)
            self.assertEqual(client.outbox.pending()[0]["state"], "pending")

    def test_terminal_delivery_cannot_be_changed_by_late_result_or_other_account(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            client.outbox.remember(self.lease, self.outputs)
            other = SubmissionOutbox(Path(root) / "submissions.sqlite", self.url, "c" * 32)
            self.assertFalse(other.lose_lease(self.lease, "expired_lease"))
            self.assertTrue(client.outbox.lose_lease(self.lease, "expired_lease"))
            self.assertFalse(client.outbox.lose_lease(self.lease, "lease_lost"))
            client.outbox.result(self.lease, {"accepted": 1, "unitsEarned": 1})
            self.assertEqual(client.undelivered, 1)
            with closing(sqlite3.connect(Path(root) / "submissions.sqlite")) as connection:
                state, payload, result = connection.execute("SELECT state,payload_json,result_json FROM deliveries").fetchone()
            self.assertEqual(state, "lease_lost")
            self.assertEqual(json.loads(payload), self.outputs)
            self.assertEqual(json.loads(result)["code"], "expired_lease")
            client.outbox.remember(self.lease, self.outputs)
            self.assertEqual(client.pending, 0)

    def test_pending_or_invalid_loss_marker_cannot_close_delivery(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            client.outbox.remember(self.lease, self.outputs)
            with self.assertRaises(ValueError):
                client.outbox.lose_lease(self.lease, "network_error")
            client.outbox.result(self.lease, {"pendingAudit": True})
            self.assertFalse(client.outbox.lose_lease(self.lease, "expired_lease"))
            self.assertEqual(client.pending, 1)

    def test_real_http_expiry_does_not_block_another_saved_batch_or_claim_more_work(self):
        calls = []
        expired, accepted = self.lease, "c" * 32
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, body))
                if self.path == "/api/submissions" and body["leaseId"] == expired:
                    status, data = 409, {"error": "expired_lease"}
                elif self.path == "/api/submissions" and body["leaseId"] == accepted:
                    status, data = 200, {"accepted": 1, "unitsEarned": 1, "replayed": True}
                else:
                    status, data = 500, {"error": "unexpected_request"}
                raw = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with tempfile.TemporaryDirectory() as root:
                    url = f"http://127.0.0.1:{server.server_port}"
                    client = DesktopClient(url)
                    client.enable_outbox(root, self.account)
                    client.outbox.remember(expired, self.outputs)
                    client.outbox.remember(accepted, self.outputs)
                    self.assertEqual(client.resume_submissions(), {"accepted": 1, "unitsEarned": 1, "leaseLost": 1})
                    self.assertEqual(client.pending, 0)
                    restarted = DesktopClient(url)
                    restarted.enable_outbox(root, self.account)
                    self.assertEqual(restarted.undelivered, 1)
                    self.assertEqual(restarted.resume_submissions(), {"accepted": 0, "unitsEarned": 0})
                    self.assertEqual([body["leaseId"] for _, body in calls], [expired, accepted])
                    self.assertTrue(all(path == "/api/submissions" for path, _ in calls))
            finally:
                server.shutdown()
                thread.join(timeout=5)

    def test_expiry_releases_backlog_slot_without_discarding_other_pending_work(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client(root)
            for index in range(MAX_PENDING_SUBMISSIONS):
                client.outbox.remember(f"{index:032x}", self.outputs)
            expired = client.outbox.pending(1)[0]["lease_id"]
            def response(_client, method, path, body=None):
                if path == "/api/submissions" and body["leaseId"] == expired:
                    raise ContributeError("expired_lease", 409)
                return 200, {"pendingAudit": True}, None
            with patch.object(CommunityClient, "request", new=response):
                self.assertEqual(client.resume_submissions()["leaseLost"], 1)
            self.assertEqual(client.pending, MAX_PENDING_SUBMISSIONS - 1)
            self.assertEqual(client.undelivered, 1)
            with patch.object(CommunityClient, "lease", return_value={"leaseId": "d" * 32}) as lease:
                self.assertEqual(client.lease("scene", 16, "slow")["leaseId"], "d" * 32)
                lease.assert_called_once()

    def test_guided_app_recovers_undelivered_count_without_account_credentials_in_report(self):
        with tempfile.TemporaryDirectory() as root:
            app = DesktopApp(Path(root), url=self.url)
            client = self.client(Path(root) / "indexes")
            client.outbox.remember(self.lease, self.outputs)
            app.client = client
            with patch.object(CommunityClient, "request", side_effect=ContributeError("expired_lease", 409)):
                app.resume_submissions()
            self.assertEqual(app.snapshot()["undelivered"], 1)
            self.assertEqual(app.snapshot()["completed"], 0)
            self.assertEqual(app.snapshot()["units"], 0)
            restarted = DesktopApp(Path(root), url=self.url)
            def response(_client, method, path, body=None):
                if path == "/api/capabilities":
                    return 200, {"version": 1, "sceneContributions": {"model": "vision-four-view-v4",
                        "ready": True, "deviceQualificationRequired": True, "canaryLocations": 112}}, None
                if path == "/api/recovery":
                    return 200, {"accountId": self.account, "token": "PRIVATE_TOKEN"}, None
                if path == "/api/me":
                    return 200, {"accountId": self.account, "units": 0}, None
                self.fail("Unexpected request")
            with patch.object(CommunityClient, "request", new=response):
                restarted.connect("PRIVATE_ACCOUNT_CODE")
            self.assertEqual(restarted.snapshot()["undelivered"], 1)
            self.assertEqual(restarted.snapshot()["pending"], 0)
            self.assertNotIn("PRIVATE", json.dumps(restarted.snapshot()))


if __name__ == "__main__":
    unittest.main()
