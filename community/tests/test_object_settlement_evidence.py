"""Actual saved jobs/files/HTTP; explicitly synthetic native inference and coverage."""
import http.client
import json
import threading
import unittest
from unittest.mock import patch
from community import object_audit_jobs as jobs
from community.tests import test_protected_origin as origin_fixtures
from community.tests import test_object_audit_jobs as job_fixtures


class ObjectSettlementEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.origin = origin_fixtures.ProtectedOriginTests()
        self.origin.setUp()
        self.addCleanup(self.origin.doCleanups)
        self.service, self.job, _ = self.origin.saved_job()
        self.native = self.origin.fixture

    def test_full_revalidation_returns_only_correlated_batch_evidence_without_inference(self):
        calls = list(self.native.calls)
        with patch.object(self.native.verifier, 'verify_inputs', wraps=self.native.verifier.verify_inputs) as full:
            value = self.service.settlement_evidence(self.job)
            self.assertGreaterEqual(full.call_count, 1)
        self.assertEqual(self.native.calls, calls)
        self.assertEqual(value['audit']['state'], 'approved')
        self.assertEqual(value['qualificationScope'], 'batch-only')
        self.assertEqual(value['expiresAt'], value['issuedAt'] + 30)
        for name in ('policySha256','runtimeProfileSha256','qualityImplementationIdentity',
                     'protectedAuthoritySha256','protectedOriginHandoffSha256'):
            self.assertRegex(value[name], '^[a-f0-9]{64}$')
        self.assertEqual(value['policySha256'], self.native.verifier.policy_sha256)
        self.assertEqual(value['resource'], self.native.policy['resource'])
        self.assertFalse(value['audit']['serverAuthorization'])
        self.assertFalse(value['audit']['productionQualified'])
        self.assertEqual(value['audit']['acceptedContributions'], 0)
        self.assertEqual(value['audit']['searchCreditsCreated'], 0)
        self.assertNotIn(str(self.origin.root), json.dumps(value))

    def test_changed_source_or_runtime_cannot_bless_the_preserved_approved_report(self):
        report = self.origin.root / 'spool' / ('attempts-' + self.job) / 'attempt-1/audit-report.json'
        raw = report.read_bytes()
        (self.origin.arrow / '0.arrow').write_bytes(b'synthetic changed source')
        with self.assertRaises((ValueError, jobs.JobError)):
            self.service.settlement_evidence(self.job)
        self.assertEqual(report.read_bytes(), raw)
        with self.service.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?', (self.job,)).fetchone()[0], 'approved')

    def test_cancelled_job_and_job_without_origin_are_not_settlement_evidence(self):
        self.service.control(self.job, 'cancel')
        with self.assertRaises(jobs.JobError):
            self.service.settlement_evidence(self.job)
        fixture = job_fixtures.ObjectAuditJobTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        job = fixture.submit()['jobId']
        fixture.run_next()
        self.assertEqual(fixture.service.get(job)['state'], 'approved')
        with self.assertRaises(jobs.JobError):
            fixture.service.settlement_evidence(job)

    def test_private_http_endpoint_authenticates_and_returns_strict_full_evidence(self):
        secret = 'synthetic-private-transport-not-a-live-secret'
        server = jobs.make_server(self.service, secret)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def request(body, authorization):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                try:
                    connection.request('POST', '/object-audits/' + self.job + '/settlement-evidence', body,
                        {'Content-Type': 'application/json', 'Authorization': authorization})
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()
            self.assertEqual(request('{}', 'Bearer wrong')[0], 401)
            self.assertEqual(request('{"profileId":"caller"}', 'Bearer ' + secret)[0], 400)
            status, value = request('{}', 'Bearer ' + secret)
            self.assertEqual(status, 200)
            self.assertEqual(value['audit']['jobId'], self.job)
            self.assertEqual(value['qualificationScope'], 'batch-only')
        finally:
            shutdown = threading.Thread(target=server.shutdown, daemon=True)
            shutdown.start()
            shutdown.join(5)
            server.server_close()
            thread.join(5)
            self.assertFalse(shutdown.is_alive(), 'HTTP fixture shutdown deadline exceeded')
