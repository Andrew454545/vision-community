"""Actual private files/SQLite/HTTP; explicit synthetic inference, no live work."""
import http.client
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from community import native_object_verifier as audit
from community import object_audit_jobs as jobs
from community.object_canary import MODELS
from community.search_snapshot import digest, encoded
from community.tests import test_object_audit_jobs as jobfixtures
from community.tests import test_protected_origin as originfixtures


class ObjectReceiptGuardTests(unittest.TestCase):
    def fixture(self):
        fixture = jobfixtures.ObjectAuditJobTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        job = fixture.submit()['jobId']
        self.assertTrue(fixture.run_next())
        complete = fixture.service.get(job)
        self.assertEqual((complete['state'], complete['attempts']), ('approved', 1))
        return fixture, job, complete

    def refused(self, fixture, job, *, restart=False):
        calls = list(fixture.native.calls)
        if restart:
            fixture.restart()
        for operation in (lambda: fixture.service.get(job), fixture.submit):
            with self.assertRaisesRegex(jobs.JobError, 'object_job_receipt_unavailable') as failure:
                operation()
            self.assertEqual(failure.exception.status, 503)
        self.assertFalse(fixture.run_next())
        self.assertEqual(fixture.native.calls, calls)
        with fixture.service.connect() as db:
            row = db.execute('SELECT state,attempts,receipt FROM jobs WHERE id=?', (job,)).fetchone()
            self.assertEqual((row['state'], row['attempts']), ('approved', 1))
            self.assertRegex(row['receipt'], '[a-f0-9]{64}')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts WHERE job=?', (job,)).fetchone()[0], 1)

    def test_changed_policy_authority_runtime_model_database_and_snapshot_hide_saved_approval(self):
        for name in ('policy', 'authority', 'binary', 'model', 'database', 'snapshot', 'new-wal', 'new-dependency'):
            with self.subTest(name=name):
                fixture, job, _ = self.fixture()
                native = fixture.native
                paths = {'policy': native.policy_path, 'authority': native.authority, 'binary': native.binary,
                         'model': native.models / MODELS[-1], 'database': native.database,
                         'snapshot': native.snapshot, 'new-wal': native.database.with_name(native.database.name + '-wal'),
                         'new-dependency': native.binary.parent / 'added-library.dll'}
                receipt = fixture.attempt(job) / 'audit-report.json'
                original = receipt.read_bytes()
                paths[name].write_bytes(b'changed-after-completed-audit')
                self.refused(fixture, job)
                self.assertEqual(receipt.read_bytes(), original)

    def test_changed_registry_assignment_and_trusted_source_hide_saved_approval(self):
        for name in ('registry', 'assignment', 'source'):
            with self.subTest(name=name):
                fixture, job, _ = self.fixture()
                path = {'registry': fixture.registry, 'assignment': fixture.native.assignment,
                        'source': fixture.native.source_path}[name]
                receipt = fixture.attempt(job) / 'audit-report.json'
                original = receipt.read_bytes()
                path.write_bytes(path.read_bytes() + b' ')
                self.refused(fixture, job)
                self.assertEqual(receipt.read_bytes(), original)

    def test_changed_candidate_and_report_cannot_replay_stored_approval_after_restart(self):
        for name in ('source', 'manifest', 'lane', 'report-decision', 'report-pin'):
            with self.subTest(name=name):
                fixture, job, complete = self.fixture()
                directory = fixture.work / job
                receipt = fixture.attempt(job) / 'audit-report.json'
                original = receipt.read_bytes()
                if name.startswith('report-'):
                    doc = json.loads(original)
                    doc['decision' if name == 'report-decision' else 'sourceSha256'] = (
                        'rejected' if name == 'report-decision' else 'f' * 64)
                    receipt.write_bytes(encoded(doc))
                else:
                    path = {'source': directory / 'locations.tsv', 'manifest': directory / 'candidate/manifest.json',
                            'lane': directory / 'candidate' / fixture.native.manifest['classes'][0]['file']}[name]
                    path.write_bytes(path.read_bytes() + b'changed')
                preserved = receipt.read_bytes()
                self.refused(fixture, job, restart=True)
                self.assertEqual(receipt.read_bytes(), preserved)
                with fixture.service.connect() as db:
                    self.assertEqual(db.execute('SELECT receipt FROM jobs WHERE id=?', (job,)).fetchone()[0],
                                     complete['receiptSha256'])

    def test_report_whitespace_change_is_not_the_stored_receipt(self):
        fixture, job, _ = self.fixture()
        path = fixture.attempt(job) / 'audit-report.json'
        path.write_bytes(path.read_bytes() + b'\n')
        self.refused(fixture, job)

    def test_damaged_candidate_recovery_preserves_report_and_marks_attempt_unconfirmed(self):
        fixture, job, _ = self.fixture()
        receipt = fixture.attempt(job) / 'audit-report.json'
        preserved = receipt.read_bytes()
        path = fixture.work / job / 'candidate' / fixture.native.manifest['classes'][0]['file']
        path.write_bytes(path.read_bytes() + b'changed')
        with fixture.service.connect() as db:
            db.execute("UPDATE jobs SET state='running',receipt=NULL WHERE id=?", (job,))
            db.execute("UPDATE attempts SET state='running',receipt=NULL WHERE job=?", (job,))
        calls = list(fixture.native.calls)
        fixture.restart()
        self.assertEqual(fixture.service.get(job)['state'], 'failed')
        self.assertFalse(fixture.run_next())
        self.assertEqual(fixture.native.calls, calls)
        self.assertEqual(receipt.read_bytes(), preserved)
        with fixture.service.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM attempts WHERE job=?', (job,)).fetchone()[0], 'unconfirmed')

    def test_erasure_still_works_when_models_and_saved_receipt_are_unavailable(self):
        fixture, job, _ = self.fixture()
        (fixture.native.models / MODELS[-1]).unlink()
        receipt = fixture.attempt(job) / 'audit-report.json'
        receipt.write_bytes(receipt.read_bytes() + b'\n')
        with self.assertRaisesRegex(jobs.JobError, 'object_job_receipt_unavailable'):
            fixture.service.get(job)
        self.assertEqual(fixture.service.control(job, 'erase')['state'], 'erasing')
        self.assertTrue(fixture.run_next())
        self.assertEqual(fixture.service.get(job)['state'], 'erased')
        self.assertFalse((fixture.work / job).exists())
        self.assertFalse(fixture.attempt(job).exists())

    def test_same_size_model_edit_and_restored_modification_time_are_detected(self):
        fixture, job, _ = self.fixture()
        path = fixture.native.models / MODELS[-1]
        before, original = path.stat(), path.read_bytes()
        changed = bytes([original[0] ^ 1]) + original[1:]
        path.write_bytes(changed)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual((path.stat().st_size, path.stat().st_mtime_ns), (before.st_size, before.st_mtime_ns))
        self.refused(fixture, job)

    def test_replacing_model_with_identical_bytes_does_not_reuse_old_file_identity(self):
        fixture, job, _ = self.fixture()
        path = fixture.native.models / MODELS[-1]
        before = path.stat()
        replacement = path.with_suffix('.replacement')
        replacement.write_bytes(path.read_bytes())
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        os.replace(replacement, path)
        self.refused(fixture, job)

    def test_status_does_not_rehash_models_or_repeat_inference(self):
        fixture, job, complete = self.fixture()
        calls = list(fixture.native.calls)
        with patch.object(audit, 'runtime_profile', side_effect=AssertionError('model rehash on status')):
            for _ in range(3):
                self.assertEqual(fixture.service.get(job), complete)
                self.assertEqual(fixture.submit(), complete)
            fixture.restart()
            self.assertEqual(fixture.service.get(job), complete)
        self.assertEqual(fixture.native.calls, calls)
        self.assertEqual((complete['acceptedContributions'], complete['searchCreditsCreated']), (0, 0))
        self.assertFalse(complete['serverAuthorization'])
        self.assertFalse(complete['productionQualified'])

    def test_late_candidate_edit_between_validation_and_reply_is_detected(self):
        fixture, job, _ = self.fixture()
        validate = fixture.native.verifier.validate_index
        path = fixture.work / job / 'candidate' / fixture.native.manifest['classes'][0]['file']
        original = path.read_bytes()
        before = path.stat()
        def late(*args):
            result = validate(*args)
            path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            return result
        with patch.object(fixture.native.verifier, 'validate_index', side_effect=late):
            with self.assertRaisesRegex(jobs.JobError, 'object_job_receipt_unavailable'):
                fixture.service.get(job)

    def test_late_model_edit_cannot_be_blessed_by_full_verification(self):
        fixture, job, _ = self.fixture()
        profile = audit.runtime_profile
        path = fixture.native.models / MODELS[-1]
        original, before = path.read_bytes(), path.stat()
        def late(*args):
            result = profile(*args)
            path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            return result
        with patch.object(audit, 'runtime_profile', side_effect=late):
            with self.assertRaisesRegex(audit.ObjectAuditError, 'object_audit_inputs_changed'):
                fixture.native.verifier.verify_inputs()
        self.refused(fixture, job)

    def test_full_startup_reverification_requires_the_original_model_bytes(self):
        fixture, job, _ = self.fixture()
        (fixture.native.models / MODELS[-1]).write_bytes(b'changed-before-new-process')
        with patch.object(audit.NativeObjectVerifier, 'validate_model_paths'):
            with self.assertRaisesRegex(audit.ObjectAuditError, 'object_audit_runtime_mismatch'):
                audit.NativeObjectVerifier(fixture.native.binary, fixture.native.models,
                    fixture.native.policy_path, digest(fixture.native.policy_path.read_bytes()))
        self.refused(fixture, job)

    def test_real_http_refuses_changed_report_and_still_allows_revocation(self):
        fixture, job, _ = self.fixture()
        receipt = fixture.attempt(job) / 'audit-report.json'
        receipt.write_bytes(receipt.read_bytes() + b'\n')
        original = receipt.read_bytes()
        secret = 'synthetic-transport-secret-never-used-for-live'
        server = jobs.make_server(fixture.service, secret)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(method, path, body=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                connection.request(method, path, body=body, headers={'Authorization': 'Bearer ' + secret,
                    'Content-Type': 'application/json'})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()
        try:
            for method, path, body in (('GET', '/object-audits/' + job, None),
                                       ('POST', '/object-audits', encoded(fixture.body))):
                self.assertEqual(request(method, path, body), (503, {'error': 'object_job_receipt_unavailable'}))
            self.assertEqual(request('POST', '/object-audits/' + job + '/cancel', b'{}')[1]['state'], 'cancelled')
            self.assertEqual(receipt.read_bytes(), original)
            self.assertEqual(request('GET', '/object-audits/' + job)[1]['state'], 'cancelled')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)

    def test_fresh_process_reuses_one_attempt_and_refuses_a_changed_saved_receipt(self):
        fixture, job, complete = self.fixture()
        fixture.service.close()
        output = fixture.root / 'fresh-process.log'
        with output.open('xb') as stream:
            process = subprocess.Popen([sys.executable, '-B', '-c', jobfixtures.CHILD,
                str(fixture.root), 'receipt-guard', '1000'], cwd=jobfixtures.REPO,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), stdout=stream, stderr=stream,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                marker = fixture.root / 'child-receipt-guard.port'
                deadline = time.monotonic() + 20
                while not marker.exists():
                    self.assertIsNone(process.poll(), 'fresh private host exited before its durable marker')
                    self.assertLess(time.monotonic(), deadline, 'fresh private host startup deadline')
                    time.sleep(.05)
                port = int(marker.read_text())
                def request(method, path, body=None):
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
                    try:
                        connection.request(method, path, body=body, headers={'Content-Type': 'application/json',
                            'Authorization': 'Bearer synthetic-transport-secret-never-used-for-live'})
                        response = connection.getresponse()
                        return response.status, json.loads(response.read())
                    finally:
                        connection.close()
                self.assertEqual(request('GET', '/object-audits/' + job), (200, complete))
                receipt = fixture.attempt(job) / 'audit-report.json'
                receipt.write_bytes(receipt.read_bytes() + b'\n')
                preserved = receipt.read_bytes()
                self.assertEqual(request('GET', '/object-audits/' + job),
                                 (503, {'error': 'object_job_receipt_unavailable'}))
                self.assertEqual(request('POST', '/object-audits', encoded(fixture.body)),
                                 (503, {'error': 'object_job_receipt_unavailable'}))
                self.assertEqual(receipt.read_bytes(), preserved)
                self.assertFalse((fixture.root / 'child-native-calls.txt').exists())
                self.assertEqual(request('POST', '/object-audits/' + job + '/cancel', b'{}')[1]['state'], 'cancelled')
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)

    def test_revocation_remains_available_after_origin_change_or_expiry(self):
        for mode in ('changed', 'expired'):
            with self.subTest(mode=mode):
                fixture = originfixtures.ProtectedOriginTests(methodName='runTest')
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                service, job, _ = fixture.saved_job()
                receipt = fixture.root / 'spool' / ('attempts-' + job) / 'attempt-1/audit-report.json'
                preserved = receipt.read_bytes()
                if mode == 'changed':
                    (fixture.arrow / '0.arrow').write_bytes(b'changed-before-revocation')
                now = time.time()
                with patch.object(originfixtures.origin.time, 'time', return_value=now + (3602 if mode == 'expired' else 0)):
                    with self.assertRaisesRegex(jobs.JobError, 'object_job_origin_unavailable'):
                        service.get(job)
                    self.assertEqual(service.control(job, 'cancel')['state'], 'cancelled')
                    self.assertEqual(receipt.read_bytes(), preserved)
                    self.assertEqual(service.control(job, 'erase')['state'], 'erasing')
                    self.assertTrue(service.run_next())
                    self.assertEqual(service.get(job)['state'], 'erased')
                self.assertFalse(receipt.exists())

    def test_damaged_recovered_candidate_retry_has_a_fixed_http_error_without_another_attempt(self):
        fixture, job, _ = self.fixture()
        path = fixture.work / job / 'candidate' / fixture.native.manifest['classes'][0]['file']
        path.write_bytes(path.read_bytes() + b'changed')
        with fixture.service.connect() as db:
            db.execute("UPDATE jobs SET state='running',receipt=NULL WHERE id=?", (job,))
            db.execute("UPDATE attempts SET state='running',receipt=NULL WHERE job=?", (job,))
        fixture.restart()
        fixture.now = fixture.service.get(job)['retryAt']
        calls = list(fixture.native.calls)
        server = jobs.make_server(fixture.service, 'synthetic-transport-secret-never-used-for-live')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            connection.request('POST', '/object-audits/' + job + '/retry', body=b'{}', headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer synthetic-transport-secret-never-used-for-live'})
            response = connection.getresponse()
            self.assertEqual((response.status, json.loads(response.read())),
                             (503, {'error': 'object_verifier_unavailable'}))
            self.assertEqual((fixture.service.get(job)['state'], fixture.service.get(job)['attempts']), ('failed', 1))
            self.assertEqual(fixture.native.calls, calls)
            self.assertFalse(fixture.run_next())
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(5)


if __name__ == '__main__':
    unittest.main()
