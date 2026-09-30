import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from community.contribute import CommunityClient, ContributeError
from community.desktop import DesktopClient
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


if __name__ == "__main__":
    unittest.main()
