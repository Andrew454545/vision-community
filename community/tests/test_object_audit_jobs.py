"""Real SQLite/files/HTTP recovery; native inference is an explicit synthetic runner."""
import base64
import copy
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from community import object_audit_jobs as jobs
from community.search_snapshot import digest, encoded
from community.tests import test_native_object_verifier as fixtures

REPO = Path(__file__).resolve().parents[2]
CHILD = r'''
import base64,json,sys,time
from pathlib import Path
from unittest.mock import patch
from community.native_object_verifier import NativeObjectVerifier
from community.object_audit_jobs import ObjectAuditJobs,make_server
from community.search_snapshot import digest
from community.tests.test_native_object_verifier import NativeObjectVerifierTests
root,mode,clock=Path(sys.argv[1]),sys.argv[2],int(sys.argv[3])
test=NativeObjectVerifierTests()
test.calls=[]
test.source=(root/'assignment/locations.tsv').read_bytes()
test.manifest=json.loads((root/'candidate/manifest.json').read_bytes())
test.files={p.name:p.read_bytes() for p in (root/'candidate').glob('*.bin')}
policy=root/'policy/policy.json'
with patch.object(NativeObjectVerifier,'validate_model_paths'):
    verifier=NativeObjectVerifier(root/'runtime/native.exe',root/'runtime/models',policy,digest(policy.read_bytes()))
def runner(command,folder,timeout):
    with (root/'child-native-calls.txt').open('a') as stream:stream.write(command[1]+'\n')
    if mode=='interrupt' and command[1]=='index-segment':
        (root/'child-blocked').write_bytes(b'synthetic native runner paused')
        while True:time.sleep(.1)
    return test.fake_native(command,folder,timeout)
verifier.run=runner
registry=root/'assignment/registry.json'
clock_file=root/('child-'+mode+'.clock')
clock_file.write_text(str(clock))
jobs=ObjectAuditJobs(verifier,registry,digest(registry.read_bytes()),root/'spool',clock=lambda:int(clock_file.read_text()))
server=make_server(jobs,'synthetic-transport-secret-never-used-for-live')
jobs.start()
(root/('child-'+mode+'.port')).write_text(str(server.server_port))
server.serve_forever()
'''


class ObjectAuditJobTests(unittest.TestCase):
    def setUp(self):
        self.native = fixtures.NativeObjectVerifierTests()
        self.native.setUp()
        self.addCleanup(self.native.doCleanups)
        self.root = self.native.root
        self.now = 1000
        self.registry = self.root / 'assignment/registry.json'
        self.registry.write_bytes(encoded({'version': 1, 'scope': 'private-object-audit-registry',
            'policyId': self.native.policy['policyId'], 'resource': self.native.policy['resource'],
            'assignments': [{'leaseId': self.native.trusted['leaseId'], 'profileId': self.native.trusted['profileId'],
                'assignment': self.pin(self.native.assignment), 'source': self.pin(self.native.source_path)}]}))
        self.work = self.root / 'spool'
        self.service = self.open()
        self.addCleanup(lambda: self.service.close())
        self.body = {'version': 1, 'leaseId': self.native.trusted['leaseId'],
            'profileId': self.native.trusted['profileId'], 'policyId': self.native.policy['policyId'],
            'assignmentSha256': digest(self.native.assignment.read_bytes()), 'submissionSha256': '2' * 64,
            'objectIndex': {'manifest': json.loads((self.native.candidate / 'manifest.json').read_bytes()),
                'sourceTsv': base64.b64encode(self.native.source).decode(),
                'files': {name: base64.b64encode(raw).decode() for name, raw in self.native.files.items()}}}

    def pin(self, path):
        return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path.read_bytes())}

    def open(self):
        return jobs.ObjectAuditJobs(self.native.verifier, self.registry, digest(self.registry.read_bytes()),
                                    self.work, clock=lambda: self.now)

    def restart(self):
        self.service.close()
        self.service = self.open()

    def submit(self):
        return self.service.submit(encoded(self.body))

    def run_next(self, runner=None):
        with patch.object(self.native.verifier, 'run', side_effect=runner or self.native.fake_native):
            return self.service.run_next()

    def attempt(self, job, number=1):
        return self.work / ('attempts-' + job) / f'attempt-{number}'

    def mark_running(self, job):
        with self.service.connect() as db:
            db.execute("UPDATE jobs SET state='running',attempts=1 WHERE id=?", (job,))
            db.execute("INSERT INTO attempts VALUES (?,1,'running',1000,NULL,NULL)", (job,))

    def test_lost_reply_and_restart_reuse_one_job_and_native_attempt(self):
        first = self.submit()
        self.assertEqual(first['state'], 'queued')
        self.assertFalse(first['serverAuthorization'])
        self.restart()
        self.assertEqual(self.submit(), first)
        self.assertTrue(self.run_next())
        complete = self.service.get(first['jobId'])
        self.assertEqual((complete['state'], complete['attempts']), ('approved', 1))
        self.assertEqual(self.native.calls, ['runtime-info', 'index-segment', 'verify-index', 'verify-index'])
        self.restart()
        self.assertEqual(self.submit(), complete)
        self.assertFalse(self.run_next())
        self.assertEqual(complete['searchCreditsCreated'], 0)
        self.assertEqual(complete['acceptedContributions'], 0)
        self.assertFalse(complete['productionQualified'])

    def test_concurrent_duplicate_starts_store_only_one_candidate(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(lambda _: self.submit(), range(4)))
        self.assertEqual(len({value['jobId'] for value in replies}), 1)
        with self.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)

    def test_different_bytes_for_same_assignment_conflict_even_with_same_submission_label(self):
        self.submit()
        self.body['objectIndex']['manifest']['sourceTsv'] = 'another-name.tsv'
        with self.assertRaisesRegex(jobs.JobError, 'object_job_conflict'):
            self.submit()

    def test_caller_cannot_choose_assignment_policy_profile_or_paths(self):
        original = copy.deepcopy(self.body)
        for field, value in [('leaseId', 'f' * 32), ('profileId', 'f' * 64), ('policyId', 'caller'),
                             ('assignmentSha256', 'f' * 64), ('binary', 'C:/caller.exe')]:
            self.body = {**original, field: value}
            with self.assertRaises(jobs.JobError):
                self.submit()
        self.body = original
        self.body['objectIndex']['files']['../outside.bin'] = ''
        with self.assertRaises(jobs.JobError):
            self.submit()
        self.assertFalse((self.root / 'outside.bin').exists())

    def test_same_spool_cannot_be_owned_by_two_services(self):
        with self.assertRaisesRegex(jobs.JobError, 'object_job_service_already_running'):
            self.open()

    def test_shutdown_refuses_new_writes_before_releasing_spool_ownership(self):
        job = self.submit()['jobId']
        self.service.close()
        for operation in (self.submit, lambda:self.service.control(job,'cancel'), lambda:self.service.get(job)):
            with self.assertRaisesRegex(jobs.JobError,'object_verifier_unavailable'):
                operation()
        self.service = self.open()
        self.assertEqual(self.service.get(job)['state'],'queued')

    def test_source_must_match_independently_pinned_assignment_exactly(self):
        self.body['objectIndex']['sourceTsv'] = base64.b64encode(self.native.source.replace(b'\n', b'\r\n')).decode()
        with self.assertRaisesRegex(jobs.JobError, 'object_job_source_mismatch'):
            self.submit()

    def test_candidate_change_before_audit_never_approves(self):
        first = self.submit()
        manifest = self.work / first['jobId'] / 'candidate/manifest.json'
        manifest.write_bytes(b'{}')
        self.run_next()
        self.assertEqual(self.service.get(first['jobId'])['state'], 'failed')
        self.assertEqual(self.native.calls, [])

    def test_completed_durable_receipt_is_recovered_without_recomputing(self):
        job = self.submit()['jobId']
        self.mark_running(job)
        with patch.object(self.native.verifier, 'run', side_effect=self.native.fake_native):
            result = self.native.verifier.audit(assignment=self.native.assignment,
                assignment_sha256=digest(self.native.assignment.read_bytes()), source=self.work / job / 'locations.tsv',
                candidate=self.work / job / 'candidate',
                candidate_sha256=digest((self.work / job / 'candidate/manifest.json').read_bytes()), out=self.attempt(job))
        self.assertEqual(result['decision'], 'approved')
        report = self.attempt(job) / 'audit-report.json'
        preserved = report.read_bytes()
        self.restart()
        self.assertEqual(self.service.get(job)['state'], 'approved')
        self.assertEqual(report.read_bytes(), preserved)
        self.assertFalse(self.run_next())

    def test_incomplete_attempt_survives_restart_and_explicit_retry_uses_new_folder(self):
        job = self.submit()['jobId']
        self.mark_running(job)
        self.attempt(job).mkdir()
        old = self.attempt(job) / 'audit-report.json'
        old.write_bytes(b'{"status":"INCOMPLETE","decision":"pending"}\n')
        original = old.read_bytes()
        self.restart()
        self.assertEqual(self.service.get(job)['state'], 'failed')
        with self.service.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM attempts').fetchone()[0], 'unconfirmed')
        self.assertFalse(self.run_next())
        with self.assertRaisesRegex(jobs.JobError, 'object_job_retry_limited'):
            self.service.control(job, 'retry')
        self.now += 60
        self.service.control(job, 'retry')
        self.run_next()
        self.assertEqual((self.service.get(job)['state'], self.service.get(job)['attempts']), ('approved', 2))
        self.assertEqual(old.read_bytes(), original)
        self.assertTrue((self.attempt(job, 2) / 'audit-report.json').is_file())

    def test_failed_attempts_have_durable_backoff_and_finite_budget(self):
        job = self.submit()['jobId']
        for attempt in range(1, 4):
            self.run_next(runner=lambda *_: (_ for _ in ()).throw(OSError('private path and secret')))
            value = self.service.get(job)
            self.assertEqual((value['state'], value['decision'], value['attempts']), ('failed', 'pending', attempt))
            self.assertNotIn('private path', encoded(value).decode())
            self.now = value['retryAt']
            if attempt < 3:
                self.service.control(job, 'retry')
        self.restart()
        with self.assertRaisesRegex(jobs.JobError, 'object_job_retry_limited'):
            self.service.control(job, 'retry')
        self.assertEqual(len(list((self.work / ('attempts-' + job)).iterdir())), 3)

    def test_queued_cancel_prevents_native_work_and_replay_stays_cancelled(self):
        job = self.submit()['jobId']
        self.service.control(job, 'cancel')
        self.restart()
        self.assertFalse(self.run_next())
        self.assertEqual(self.submit()['state'], 'cancelled')
        self.assertEqual(self.native.calls, [])

    def test_cancel_during_native_work_wins_over_late_approval(self):
        job = self.submit()['jobId']
        entered, resume = threading.Event(), threading.Event()
        def runner(*args):
            if not entered.is_set():
                entered.set()
                self.assertTrue(resume.wait(5))
            return self.native.fake_native(*args)
        with patch.object(self.native.verifier, 'run', side_effect=runner), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.service.run_next)
            self.assertTrue(entered.wait(5))
            self.service.control(job, 'cancel')
            resume.set()
            self.assertTrue(pending.result(10))
        value = self.service.get(job)
        self.assertEqual((value['state'], value['decision']), ('cancelled', 'pending'))
        self.assertTrue((self.attempt(job) / 'audit-report.json').is_file())

    def test_queued_erasure_is_durable_and_cannot_be_resurrected_by_any_replay(self):
        job = self.submit()['jobId']
        source = self.native.source_path.read_bytes()
        ack = self.service.control(job, 'erase')
        self.assertEqual((ack['state'], ack['decision'], ack['receiptSha256']), ('erasing', 'pending', None))
        self.assertTrue((self.work / job).is_dir())
        self.restart()
        self.assertEqual(self.service.get(job)['state'], 'erasing')
        self.assertTrue(self.run_next())
        self.assertEqual(self.native.calls, [])
        self.assertFalse((self.work / job).exists())
        self.assertFalse((self.work / ('attempts-' + job)).exists())
        self.assertEqual(self.native.source_path.read_bytes(), source)
        self.restart()
        for action in ('cancel', 'retry', 'erase'):
            self.assertEqual(self.service.control(job, action)['state'], 'erased')
        self.assertEqual(self.submit()['state'], 'erased')
        self.assertFalse(self.run_next())
        self.assertFalse((self.work / job).exists())
        with self.service.connect() as db:
            self.assertEqual(tuple(db.execute('SELECT requested,completed FROM erasures').fetchone()), (1000, 1000))
            self.assertEqual(db.execute('SELECT input_bytes FROM jobs').fetchone()[0], 0)
        self.body['submissionSha256'] = '3' * 64
        with self.assertRaisesRegex(jobs.JobError, 'object_job_conflict'):
            self.submit()

    def test_approved_payload_and_native_private_reports_require_explicit_erasure(self):
        job = self.submit()['jobId']
        self.run_next()
        report = self.attempt(job) / 'audit-report.json'
        original = report.read_bytes()
        self.service.control(job, 'cancel')
        self.assertEqual(report.read_bytes(), original)
        self.service.control(job, 'erase')
        self.assertIsNone(self.service.get(job)['receiptSha256'])
        self.run_next()
        self.assertFalse(report.exists())
        self.assertEqual(self.service.get(job)['state'], 'erased')
        self.assertTrue(self.native.assignment.is_file())
        self.assertTrue(self.registry.is_file())

    def test_erasure_during_native_work_revokes_approval_but_waits_for_owned_writer(self):
        job = self.submit()['jobId']
        entered, resume = threading.Event(), threading.Event()
        def runner(*args):
            if not entered.is_set():
                entered.set()
                self.assertTrue(resume.wait(10))
            return self.native.fake_native(*args)
        with patch.object(self.native.verifier, 'run', side_effect=runner), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.service.run_next)
            self.assertTrue(entered.wait(5))
            try:
                self.assertEqual(self.service.control(job, 'erase')['state'], 'erasing')
                self.assertFalse(self.service.run_next())
                self.assertTrue((self.work / job / 'candidate/manifest.json').is_file())
                with self.assertRaisesRegex(jobs.JobError, 'object_job_worker_busy'):
                    self.service.erase_next()
            finally:
                resume.set()
            self.assertTrue(pending.result(15))
        self.assertEqual(self.service.get(job)['state'], 'erasing')
        self.assertEqual(self.service.get(job)['decision'], 'pending')
        self.assertIsNone(self.service.get(job)['receiptSha256'])
        self.run_next()
        self.assertEqual(self.service.get(job)['state'], 'erased')
        self.assertFalse((self.work / ('attempts-' + job)).exists())

    def test_erasure_after_partial_folder_cleanup_resumes_without_reauditing(self):
        job = self.submit()['jobId']
        self.run_next()
        self.service.control(job, 'erase')
        erase = self.service.erase_tree
        def interrupted(name):
            if name.startswith('attempts-'):
                raise OSError('synthetic denied attempt cleanup')
            erase(name)
        with patch.object(self.service, 'erase_tree', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.run_next()
        self.assertFalse((self.work / job).exists())
        self.assertTrue((self.work / ('attempts-' + job)).is_dir())
        self.assertEqual(self.service.get(job)['state'], 'erasing')
        calls = list(self.native.calls)
        self.restart()
        self.assertTrue(self.run_next())
        self.assertEqual(self.native.calls, calls)
        self.assertEqual(self.service.get(job)['state'], 'erased')

    def test_missing_files_do_not_lose_the_uncommitted_erasure_intent(self):
        job = self.submit()['jobId']
        self.service.control(job, 'erase')
        erase = self.service.erase_tree
        def late_failure(name):
            erase(name)
            if name.startswith('attempts-'):
                raise OSError('synthetic interruption before completion commit')
        with patch.object(self.service, 'erase_tree', side_effect=late_failure):
            with self.assertRaises(OSError):
                self.run_next()
        self.assertFalse((self.work / job).exists())
        self.assertFalse((self.work / ('attempts-' + job)).exists())
        self.restart()
        self.assertTrue(self.run_next())
        self.assertEqual(self.service.get(job)['state'], 'erased')

    def test_erasure_inventory_limit_preserves_pending_intent_and_payload(self):
        job = self.submit()['jobId']
        self.service.control(job, 'erase')
        with patch.object(jobs, 'MAX_ERASE_ENTRIES', 1):
            with self.assertRaisesRegex(jobs.JobError, 'object_erasure_inventory_limit'):
                self.run_next()
        self.assertTrue((self.work / job / 'candidate/manifest.json').is_file())
        self.assertEqual(self.service.get(job)['state'], 'erasing')
        self.assertEqual(self.service.control(job, 'retry')['state'], 'erasing')
        self.run_next()
        self.assertEqual(self.service.get(job)['state'], 'erased')

    def test_erasure_refuses_escaping_names_and_linked_payload_without_touching_target(self):
        job = self.submit()['jobId']
        outside = self.root / 'private-outside'
        outside.mkdir()
        retained = outside / 'must-remain.txt'
        retained.write_bytes(b'untouched operator authority')
        for name in ('../private-outside', str(outside), job + '/../private-outside'):
            with self.assertRaises(jobs.JobError):
                self.service.erase_tree(name)
        link = self.work / job / 'external'
        if os.name == 'nt':
            result = subprocess.run(['cmd.exe','/c','mklink','/J',str(link),str(outside)],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW,timeout=10)
            if result.returncode:
                self.skipTest('Windows denied fixture directory-junction creation')
            self.addCleanup(lambda: link.rmdir() if os.path.lexists(link) else None)
        else:
            link.symlink_to(outside, target_is_directory=True)
            self.addCleanup(lambda: link.unlink() if os.path.lexists(link) else None)
        self.service.control(job, 'erase')
        with self.assertRaises(ValueError):
            self.run_next()
        self.assertEqual(retained.read_bytes(), b'untouched operator authority')
        self.assertTrue((self.work / job / 'candidate/manifest.json').is_file())
        self.assertEqual(self.service.get(job)['state'], 'erasing')

    def test_restart_with_revoked_running_attempt_never_reads_or_approves_its_receipt(self):
        job = self.submit()['jobId']
        self.mark_running(job)
        self.attempt(job).mkdir()
        (self.attempt(job) / 'private.log').write_bytes(b'private synthetic candidate log')
        self.service.control(job, 'erase')
        with patch.object(self.service, 'receipt', side_effect=AssertionError('revoked receipt consulted')):
            self.service.recover()
        self.restart()
        self.run_next()
        self.assertEqual(self.service.get(job)['state'], 'erased')
        self.assertEqual(self.native.calls, [])
        with self.service.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM attempts').fetchone()[0], 'cancelled')

    def test_upgrading_existing_private_spool_preserves_jobs_and_completed_attempts(self):
        job = self.submit()['jobId']
        self.run_next()
        before = self.service.get(job)
        self.service.close()
        with self.service.connect() as db:
            db.execute('DROP TABLE erasures')
        self.service = self.open()
        self.assertEqual(self.service.get(job), before)
        self.assertFalse(self.run_next())
        self.service.control(job, 'erase')
        self.run_next()
        self.assertEqual(self.service.get(job)['state'], 'erased')

    def test_transient_settlement_failure_recovers_receipt_without_another_native_attempt(self):
        job = self.submit()['jobId']
        with patch.object(self.service, 'finish', side_effect=sqlite3.OperationalError('synthetic temporary failure')):
            with self.assertRaises(sqlite3.OperationalError):
                self.run_next()
        self.assertEqual(self.service.get(job)['state'], 'running')
        self.assertFalse(self.run_next())
        self.assertEqual((self.service.get(job)['state'],self.service.get(job)['attempts']),('approved',1))
        self.assertEqual(self.native.calls,['runtime-info','index-segment','verify-index','verify-index'])

    def test_cancelled_inflight_job_still_blocks_a_second_native_process(self):
        self.service.close()
        second_lease = '9' * 32
        second_assignment = self.root / 'assignment/second.json'
        second_assignment.write_bytes(encoded({**self.native.trusted,'leaseId':second_lease}))
        registry = json.loads(self.registry.read_bytes())
        registry['assignments'].append({**registry['assignments'][0],'leaseId':second_lease,
                                       'assignment':self.pin(second_assignment)})
        self.registry.write_bytes(encoded(registry))
        self.work = self.root / 'spool-two'
        self.service = self.open()
        first = self.submit()['jobId']
        self.body['leaseId'] = second_lease
        self.body['assignmentSha256'] = digest(second_assignment.read_bytes())
        self.body['objectIndex']['manifest']['sourceId'] = 'community-' + second_lease
        # Equal creation seconds deliberately use opaque IDs as a tie-breaker.
        # Give this fixture distinct times so it actually cancels the active job.
        self.now += 1
        second = self.submit()['jobId']
        entered, resume = threading.Event(), threading.Event()
        def runner(*args):
            if not entered.is_set():
                entered.set()
                self.assertTrue(resume.wait(5))
            return self.native.fake_native(*args)
        with patch.object(self.native.verifier,'run',side_effect=runner), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.service.run_next)
            self.assertTrue(entered.wait(5))
            try:
                self.service.control(first,'cancel')
                self.assertFalse(self.service.run_next())
                with self.assertRaisesRegex(jobs.JobError,'object_job_worker_busy'):
                    self.service.recover()
                self.assertEqual((self.service.get(second)['state'],self.service.get(second)['attempts']),('queued',0))
            finally:
                resume.set()
            self.assertTrue(pending.result(10))
        self.assertEqual(self.service.get(first)['state'],'cancelled')
        self.assertEqual(self.native.calls,['runtime-info','index-segment','verify-index','verify-index'])

    def test_changed_registry_before_native_start_stays_pending(self):
        job = self.submit()['jobId']
        self.registry.write_bytes(self.registry.read_bytes()+b' ')
        self.run_next()
        self.assertEqual((self.service.get(job)['state'],self.service.get(job)['decision']),('failed','pending'))
        self.assertEqual(self.native.calls,[])

    def test_completed_receipt_for_another_assignment_cannot_settle_this_job(self):
        job = self.submit()['jobId']
        original = self.native.verifier.audit
        def wrong_receipt(**kwargs):
            value = original(**kwargs)
            path = kwargs['out'] / 'audit-report.json'
            path.write_bytes(encoded({**value,'assignmentSha256':'f'*64}))
            return value
        with patch.object(self.native.verifier,'audit',side_effect=wrong_receipt):
            self.run_next()
        self.assertEqual((self.service.get(job)['state'],self.service.get(job)['decision']),('failed','pending'))
        self.assertFalse(self.run_next())

    def test_spool_registry_identity_cannot_be_rebound_after_restart(self):
        self.submit()
        self.service.close()
        self.registry.write_bytes(self.registry.read_bytes() + b' ')
        with self.assertRaisesRegex(jobs.JobError, 'object_job_service_identity_changed'):
            self.open()

    def test_disk_and_queue_limits_prevent_staging(self):
        with patch.object(jobs.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 0})()):
            with self.assertRaisesRegex(jobs.JobError, 'object_job_disk_budget'):
                self.submit()
        with patch.object(jobs, 'MAX_QUEUED', 0):
            with self.assertRaisesRegex(jobs.JobError, 'object_job_capacity_reached'):
                self.submit()
        with self.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0)

    def test_real_http_acknowledges_pending_and_recovers_lost_reply(self):
        secret = 'synthetic-transport-secret-never-used-for-live'
        server = jobs.make_server(self.service, secret)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(method, path, body=None, auth=secret):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                connection.request(method, path, body=body,
                    headers={'Authorization': 'Bearer ' + auth, 'Content-Type': 'application/json'})
                result = connection.getresponse()
                return result.status, json.loads(result.read())
            finally:
                connection.close()
        try:
            self.assertEqual(request('POST', '/object-audits', b'not json', auth='wrong')[0], 401)
            self.assertEqual(request('POST', '/unknown', b'{}')[0], 404)
            status, first = request('POST', '/object-audits', encoded(self.body))
            self.assertEqual((status, first['state']), (200, 'queued'))
            self.assertEqual(self.native.calls, [])
            # Ignore the first acknowledgement as if the connection was lost.
            self.assertEqual(request('POST', '/object-audits', encoded(self.body)), (200, first))
            self.run_next()
            status, result = request('GET', '/object-audits/' + first['jobId'])
            self.assertEqual((status, result['state']), (200, 'approved'))
            self.assertEqual(request('POST', '/object-audits/' + first['jobId'] + '/cancel', b'{}')[1]['state'], 'cancelled')
            self.assertEqual(request('POST', '/object-audits/' + first['jobId'] + '/erase', b'{}', auth='wrong')[0], 401)
            self.assertEqual(request('POST', '/object-audits/' + first['jobId'] + '/erase', b'{}')[1]['state'], 'erasing')
            self.run_next()
            self.assertEqual(request('GET', '/object-audits/' + first['jobId'])[1]['state'], 'erased')
        finally:
            server.shutdown(); server.server_close(); thread.join(5)

    def test_abrupt_process_exit_and_fresh_http_host_preserve_attempt_and_complete_retry(self):
        self.service.close()
        children = []
        def wait_for(condition):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if condition():
                    return
                if children and children[-1].poll() is not None:
                    self.fail('owned fixture child exited before its durable marker')
                time.sleep(.05)
            self.fail('owned fixture child did not reach its bounded marker')
        def child(mode, clock):
            output = (self.root / ('child-' + mode + '.log')).open('wb')
            self.addCleanup(output.close)
            process = subprocess.Popen([sys.executable,'-B','-c',CHILD,str(self.root),mode,str(clock)],cwd=REPO,
                env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),stdout=output,stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            children.append(process)
            marker = self.root / ('child-' + mode + '.port')
            wait_for(marker.is_file)
            return process, int(marker.read_text())
        def request(port, method, path, body=None):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            try:
                connection.request(method,path,body=body,headers={'Content-Type':'application/json',
                    'Authorization':'Bearer synthetic-transport-secret-never-used-for-live'})
                response = connection.getresponse()
                raw = response.read()
                self.assertEqual(response.status,200,raw)
                return json.loads(raw)
            finally:
                connection.close()
        try:
            first, port = child('interrupt', 1000)
            started = request(port,'POST','/object-audits',encoded(self.body))
            job = started['jobId']
            wait_for((self.root / 'child-blocked').is_file)
            first.kill(); first.wait(timeout=5)
            report = self.attempt(job) / 'audit-report.json'
            preserved = report.read_bytes()
            self.assertEqual(json.loads(preserved)['status'],'INCOMPLETE')
            second, port = child('complete', 1060)
            self.assertEqual(request(port,'GET','/object-audits/'+job)['state'],'failed')
            replayed = request(port,'POST','/object-audits',encoded(self.body))
            self.assertEqual((replayed['jobId'],replayed['attempts']),(job,1))
            (self.root/'child-complete.clock').write_text(str(replayed['retryAt']))
            request(port,'POST','/object-audits/'+job+'/retry',b'{}')
            wait_for(lambda: request(port,'GET','/object-audits/'+job)['state']=='approved')
            result = request(port,'GET','/object-audits/'+job)
            self.assertEqual((result['attempts'],result['acceptedContributions'],result['searchCreditsCreated']),(2,0,0))
            self.assertEqual(report.read_bytes(),preserved)
            self.assertEqual((self.root/'child-native-calls.txt').read_text().splitlines(),
                ['runtime-info','index-segment','runtime-info','index-segment','verify-index','verify-index'])
            self.assertTrue((self.attempt(job,2)/'audit-report.json').is_file())
        finally:
            for process in children:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
