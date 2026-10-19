"""Real saved jobs and files; native model output is explicitly synthetic."""
import http.client
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch

from community import object_audit_jobs as jobs
from community.search_snapshot import digest, encoded
from community.tests import test_object_audit_jobs as fixtures


class ObjectAuditRetentionTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.ObjectAuditJobTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.job = self.h.submit()['jobId']

    def approve(self):
        self.h.run_next()
        receipt = self.h.service.get(self.job)
        self.assertEqual(receipt['state'], 'approved')
        body = {k: receipt[k] for k in ('version', 'leaseId', 'assignmentSha256', 'submissionSha256',
                                       'candidateManifestSha256', 'receiptSha256', 'attempts')}
        body['acceptanceSha256'] = 'e' * 64  # Synthetic hosted acknowledgement, no credit is created here.
        return body

    def states(self, folder):
        return {p.relative_to(folder).as_posix(): digest(p.read_bytes()) for p in folder.rglob('*') if p.is_file()}

    def test_approval_without_hosted_ack_retains_all_evidence(self):
        body = self.approve()
        before = self.states(self.h.attempt(self.job))
        self.assertFalse(self.h.run_next())
        self.assertEqual(self.states(self.h.attempt(self.job)), before)
        self.assertTrue((self.h.work / self.job).exists())
        for key, value in [('attempts', 2), ('receiptSha256', '0' * 64), ('leaseId', '0' * 32),
                           ('assignmentSha256', '0' * 64), ('submissionSha256', '0' * 64),
                           ('candidateManifestSha256', '0' * 64)]:
            with self.assertRaises(jobs.JobError):
                self.h.service.retire(self.job, {**body, key: value})
        self.assertEqual(self.h.service.get(self.job)['state'], 'approved')

    def test_retirement_preserves_failure_and_receipt_then_releases_input_storage(self):
        def fail(*_):
            raise OSError('synthetic failed native attempt')
        self.h.run_next(fail)
        failed = self.states(self.h.attempt(self.job))
        self.h.now = self.h.service.get(self.job)['retryAt']
        self.h.service.control(self.job, 'retry')
        body = self.approve()
        native_calls = len(self.h.native.calls)
        successful = self.h.attempt(self.job, 2)
        (successful / 'cache' / 'large-synthetic-cache').write_bytes(b'cache')
        before = self.states(successful)
        self.assertEqual(self.h.service.retire(self.job, body)['state'], 'retiring')
        self.h.restart()
        self.assertTrue(self.h.run_next())
        retired = self.h.service.get(self.job)
        self.assertEqual((retired['state'], retired['decision'], retired['receiptSha256']),
                         ('retired', 'pending', body['receiptSha256']))
        self.assertFalse((self.h.work / self.job).exists())
        self.assertEqual(self.states(self.h.attempt(self.job)), failed)
        self.assertEqual(self.states(successful), {k: v for k, v in before.items()
                         if not k.startswith(('cache/', 'reference/'))})
        self.assertEqual(self.h.submit(), retired)
        self.assertEqual(self.h.service.retire(self.job, body), retired)
        for action in ('cancel', 'retry'):
            self.assertEqual(self.h.service.control(self.job, action), retired)
        self.assertFalse(self.h.run_next())
        self.assertEqual(len(self.h.native.calls), native_calls)
        with self.h.service.connect() as db:
            self.assertEqual(db.execute('SELECT input_bytes FROM jobs').fetchone()[0], 0)
            self.assertIsNotNone(db.execute('SELECT completed FROM retirements').fetchone()[0])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 2)
        with self.assertRaises(jobs.JobError):
            self.h.service.retire(self.job, {**body, 'acceptanceSha256': 'f' * 64})
        with self.assertRaises(jobs.JobError):
            self.h.service.settlement_evidence(self.job)

    def test_interrupted_bulk_cleanup_recovers_without_model_or_report_rewrite(self):
        body = self.approve()
        report = (self.h.attempt(self.job) / 'audit-report.json').read_bytes()
        self.h.service.retire(self.job, body)
        remove = self.h.service.remove_tree
        def interrupted(path):
            if path.name == 'reference':
                raise OSError('synthetic filesystem failure after candidate cleanup')
            remove(path)
        with patch.object(self.h.service, 'remove_tree', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.h.run_next()
        self.assertFalse((self.h.work / self.job).exists())
        self.assertEqual(self.h.service.get(self.job)['state'], 'retiring')
        self.h.restart()
        self.assertTrue(self.h.run_next())
        self.assertEqual(self.h.service.get(self.job)['state'], 'retired')
        self.assertEqual((self.h.attempt(self.job) / 'audit-report.json').read_bytes(), report)
        self.assertEqual(len(self.h.native.calls), 4)

    def test_lost_completion_transaction_retries_the_same_intent(self):
        body = self.approve()
        self.h.service.retire(self.job, body)
        with self.h.service.connect() as db:
            db.execute("CREATE TRIGGER synthetic_failure BEFORE UPDATE ON jobs WHEN NEW.state='retired' "
                       "BEGIN SELECT RAISE(ABORT,'synthetic lost completion'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.h.run_next()
        self.assertEqual(self.h.service.get(self.job)['state'], 'retiring')
        with self.h.service.connect() as db:
            db.execute('DROP TRIGGER synthetic_failure')
        self.h.restart()
        self.assertTrue(self.h.run_next())
        self.assertEqual(self.h.service.retire(self.job, body)['state'], 'retired')
        self.assertEqual(len(self.h.native.calls), 4)

    def test_privacy_erasure_wins_over_pending_and_completed_retirement(self):
        body = self.approve()
        self.h.service.retire(self.job, body)
        self.h.service.erase_assignment(body['leaseId'])
        self.assertTrue(self.h.run_next())
        self.assertEqual(self.h.service.retire(self.job, body)['state'], 'erased')
        self.assertFalse((self.h.work / ('attempts-' + self.job)).exists())
        with self.h.service.connect() as db:
            self.assertIsNotNone(db.execute('SELECT completed FROM retirements').fetchone()[0])
        self.assertFalse(self.h.run_next())

    def test_changed_receipt_or_unfinished_job_cannot_be_retired(self):
        dummy = {**self.h.body, 'candidateManifestSha256': 'a' * 64, 'receiptSha256': 'b' * 64,
                 'attempts': 1, 'acceptanceSha256': 'e' * 64}
        dummy.pop('objectIndex');dummy.pop('profileId');dummy.pop('policyId')
        with self.assertRaises(jobs.JobError):
            self.h.service.retire(self.job, dummy)
        body = self.approve()
        (self.h.attempt(self.job) / 'audit-report.json').write_bytes(b'changed preserved report')
        with self.assertRaises(ValueError):
            self.h.service.retire(self.job, body)
        with self.h.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM retirements').fetchone()[0], 0)
        self.assertTrue((self.h.work / self.job).exists())

    def test_real_http_retirement_requires_authentication_and_exact_bounded_body(self):
        body = self.approve()
        secret = 'synthetic-only-retirement-transport-secret'
        server = jobs.make_server(self.h.service, secret)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        def request(raw, auth=secret):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                connection.request('POST', f'/object-audits/{self.job}/retire', body=raw,
                    headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + auth})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()
        try:
            self.assertEqual(request(b'', 'wrong')[0], 401)
            self.assertEqual(request(b'{}')[0], 400)
            self.assertEqual(request(encoded({**body, 'path': 'caller-selected'}))[0], 400)
            code, ack = request(encoded(body))
            self.assertEqual((code, ack['state']), (200, 'retiring'))
            self.h.run_next()
            self.assertEqual(request(encoded(body))[1]['state'], 'retired')
        finally:
            server.shutdown();server.server_close();thread.join(5)
