"""Restart-safe client handoff only; no model, imagery, account or live requests."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from community.contribute import CommunityClient, ContributeError
from community.delivery import DurableCommunityClient


class ObjectPendingDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.account, self.lease = 'a' * 32, 'b' * 32
        self.outputs = [{'locationId': 1, 'model': 'synthetic-object'}]
        self.index = {'manifest': {'synthetic': True}, 'sourceTsv': '', 'files': {'synthetic.bin': ''}}
        self.client = self.open()

    def open(self):
        client = DurableCommunityClient('https://community.example.test')
        client.enable_outbox(self.root, self.account)
        return client

    def pending(self):
        return {'submissionId': self.lease, 'accepted': 0, 'unitsEarned': 0, 'pendingAudit': True,
                'pending': 1, 'auditProtocol': 'object-saved-audit-v1', 'auditState': 'queued'}

    def seed(self):
        with patch.object(CommunityClient, 'request', return_value=(200, self.pending(), None)):
            self.assertTrue(self.client.submit_object(self.lease, self.outputs, self.index)['pendingAudit'])

    def test_pending_bundle_survives_restart_and_uses_object_audit_without_reupload_or_inference(self):
        self.seed()
        before = self.client.outbox.pending_delivery(self.lease)
        self.assertEqual(before['state'], 'pending')
        restarted, calls = self.open(), []
        def request(_client, method, path, body):
            calls.append((method, path, body))
            return 200, {'submissionId': self.lease, 'accepted': 1, 'unitsEarned': 10, 'pendingAudit': False}, None
        with patch.object(CommunityClient, 'request', new=request):
            self.assertEqual(restarted.resume_submissions(), {'accepted': 1, 'unitsEarned': 10})
            self.assertEqual(restarted.resume_submissions(), {'accepted': 0, 'unitsEarned': 0})
        self.assertEqual(calls, [('POST', '/api/object-audits', {'submissionId': self.lease})])
        self.assertEqual(restarted.pending, 0)

    def test_unknown_pending_protocol_or_overclaim_preserves_ready_output(self):
        for changes in ({'auditProtocol': None}, {'submissionId': 'c' * 32}, {'accepted': 1}, {'unitsEarned': 10}):
            with patch.object(CommunityClient, 'request', return_value=(200, {**self.pending(), **changes}, None)):
                with self.assertRaisesRegex(ContributeError, 'invalid_submission_result'):
                    self.client.submit_object(self.lease, self.outputs, self.index)
            saved = self.client.outbox.pending_delivery(self.lease)
            self.assertEqual(saved['state'], 'ready')
            self.assertEqual(self.client.outbox.decode_delivery(saved)['objectIndex'], self.index)

    def test_pending_and_network_failure_keep_one_saved_bundle_for_later_retry(self):
        self.seed()
        with patch.object(CommunityClient, 'request', return_value=(200, self.pending(), None)):
            self.assertEqual(self.open().resume_submissions(), {'accepted': 0, 'unitsEarned': 0})
        with patch.object(CommunityClient, 'request', return_value=(503, {'error': 'object_settlement_unavailable'}, None)):
            with self.assertRaises(ContributeError):
                self.open().resume_submissions()
        self.assertEqual(self.client.pending, 1)
        self.assertEqual(self.client.outbox.pending_delivery(self.lease)['state'], 'pending')

    def test_cancelled_service_reply_closes_auditing_without_claiming_accepted_work(self):
        self.seed()
        reply = {'submissionId': self.lease, 'accepted': 0, 'unitsEarned': 0, 'pendingAudit': False,
                 'rejected': True, 'cancelled': True}
        with patch.object(CommunityClient, 'request', return_value=(200, reply, None)):
            with self.assertRaisesRegex(ContributeError, 'object_submission_rejected'):
                self.open().resume_submissions()
        self.assertEqual(self.client.pending, 0)
