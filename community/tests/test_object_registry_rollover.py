"""Real SQLite/files rollover with explicitly synthetic native inference."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from community import object_audit_jobs as jobs
from community.object_audit_registry import extend_registry
from community.search_snapshot import digest, encoded
from community.tests import test_object_audit_jobs as job_fixtures


class ObjectRegistryRolloverTests(unittest.TestCase):
    def setUp(self):
        self.h = job_fixtures.ObjectAuditJobTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def extend(self, numbers, label):
        h = self.h
        document = json.loads(h.registry.read_bytes())
        entries = []
        for number in numbers:
            path = h.root/'assignment'/f'additional-{number}.json'
            lease = f'{number:032x}'
            path.write_bytes(encoded({**h.native.trusted, 'leaseId': lease}))
            entries.append({'leaseId': lease, 'profileId': h.body['profileId'],
                'assignment': h.pin(path), 'source': h.pin(h.native.source_path)})
        added = h.root/'assignment'/f'additions-{label}.json'
        added.write_bytes(encoded({key: value for key, value in {
            **document, 'version': 1, 'assignments': entries}.items() if key != 'previousRegistry'}))
        target = h.root/'assignment'/f'registry-{label}.json'
        extend_registry(h.registry, digest(h.registry.read_bytes()), added, digest(added.read_bytes()), target)
        return target

    def switch(self, target):
        self.h.service.close()
        self.h.registry = target
        self.h.service = self.h.open()

    def body(self, entry):
        body = copy.deepcopy(self.h.body)
        body.update(leaseId=entry['leaseId'], assignmentSha256=entry['assignment']['sha256'])
        body['objectIndex']['manifest']['sourceId'] = 'community-'+entry['leaseId']
        return encoded(body)

    def test_two_rollovers_preserve_failed_evidence_saved_approval_nonce_and_old_deletion(self):
        h = self.h
        old_registry, old_bytes = h.registry, h.registry.read_bytes()
        first = h.submit()['jobId']
        h.run_next(runner=lambda *_: (_ for _ in ()).throw(OSError('synthetic native failure')))
        report = h.attempt(first)/'audit-report.json'
        original_failure = report.read_bytes()
        h.now = h.service.get(first)['retryAt']
        nonce = {'requestId': 'a'*64, 'expectedAttempts': 1}
        h.service.control(first, 'retry', nonce)
        self.switch(self.extend([2], 'first'))
        self.assertEqual(h.service.control(first, 'retry', nonce)['state'], 'queued')
        h.run_next()
        approved = h.service.get(first)
        self.assertEqual((approved['state'], approved['attempts']), ('approved', 2))
        approval = (h.attempt(first, 2)/'audit-report.json').read_bytes()
        self.switch(self.extend([3], 'second'))
        self.assertEqual(h.service.get(first), approved)
        self.assertEqual(h.submit(), approved)
        self.assertEqual(report.read_bytes(), original_failure)
        self.assertEqual((h.attempt(first, 2)/'audit-report.json').read_bytes(), approval)
        self.assertEqual(old_registry.read_bytes(), old_bytes)
        with h.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM registry_extensions').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM retry_intents').fetchone()[0], 1)
        entries = json.loads(h.registry.read_bytes())['assignments']
        next_job = h.service.submit(self.body(entries[-1]))
        self.assertEqual(next_job['state'], 'queued')
        calls = list(h.native.calls)
        h.service.erase_assignment(h.body['leaseId'])
        h.service.erase_next()
        h.restart()
        self.assertEqual(h.service.get(first)['state'], 'erased')
        self.assertEqual(h.native.calls, calls)
        with self.assertRaisesRegex(jobs.JobError, 'object_assignment_revoked'):
            h.submit()

    def test_update_failure_is_atomic_and_backwards_or_forked_extensions_are_refused(self):
        h = self.h
        first = h.submit()
        original_registry = h.registry
        original_identity = (digest(original_registry.read_bytes()), h.native.verifier.policy_sha256)
        target = self.extend([2], 'next')
        fork = self.extend([3], 'fork')
        with h.service.connect() as db:
            db.execute("CREATE TRIGGER fail_transition BEFORE UPDATE ON identity BEGIN SELECT RAISE(ABORT,'synthetic late failure'); END")
        h.service.close()
        h.registry = target
        with self.assertRaises(sqlite3.IntegrityError):
            h.open()
        with h.service.connect() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM identity').fetchone()), original_identity)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM registry_extensions').fetchone()[0], 0)
            db.execute('DROP TRIGGER fail_transition')
        h.service = h.open()
        self.assertEqual(h.submit(), first)
        h.service.close()
        for invalid in (original_registry, fork):
            h.registry = invalid
            with self.assertRaisesRegex(jobs.JobError, 'object_job_service_identity_changed'):
                h.open()
        h.registry = target
        h.service = h.open()
        self.assertEqual(h.submit(), first)

    def test_extension_cannot_change_the_runtime_policy_even_with_same_policy_name(self):
        h = self.h
        target = self.extend([2], 'changed-policy')
        original_registry, original_policy = h.registry, copy.deepcopy(h.native.policy)
        h.service.close()
        h.native.policy['auditThresholds']['lanes']['maximumScoreDifference'] = .0001
        h.native.verifier = h.native.start()
        h.registry = target
        with self.assertRaisesRegex(jobs.JobError, 'object_job_service_identity_changed'):
            h.open()
        h.native.policy = original_policy
        h.native.verifier = h.native.start()
        h.registry = original_registry
        h.service = h.open()

    def test_registry_changed_during_validation_cannot_commit_an_identity_transition(self):
        h = self.h
        original_registry = h.registry
        original_pin = digest(original_registry.read_bytes())
        target = self.extend([2], 'late-change')
        valid = target.read_bytes()
        original = h.native.verifier.assignment
        def changed(*args, **kwargs):
            value = original(*args, **kwargs)
            target.write_bytes(valid+b' ')
            return value
        h.service.close()
        h.registry = target
        with patch.object(h.native.verifier, 'assignment', side_effect=changed):
            with self.assertRaises(ValueError):
                h.open()
        self.assertEqual(target.read_bytes(), valid+b' ')
        with h.service.connect() as db:
            self.assertEqual(db.execute('SELECT registry FROM identity').fetchone()[0], original_pin)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM registry_extensions').fetchone()[0], 0)
        h.registry = original_registry
        h.service = h.open()

    def test_more_than_64_jobs_keep_history_and_current_recovery_covers_old_and_new_leases(self):
        h = self.h
        first_registry = h.registry
        self.switch(self.extend(range(2, 66), '65-assignments'))
        entries = json.loads(h.registry.read_bytes())['assignments']
        for entry in entries:
            job = h.service.submit(self.body(entry))
            h.service.control(job['jobId'], 'cancel')
        with h.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 65)
        self.assertFalse(h.native.calls)
        self.switch(self.extend([66, 67], '67-assignments'))
        entries = json.loads(h.registry.read_bytes())['assignments']
        new_job = h.service.submit(self.body(entries[-2]))
        self.assertEqual(new_job['state'], 'queued')
        for name, error in (('MAX_INPUT_BYTES', 'object_job_capacity_reached'), ('MAX_QUEUED', 'object_job_queue_full')):
            with patch.object(jobs, name, 0):
                with self.assertRaisesRegex(jobs.JobError, error):
                    h.service.submit(self.body(entries[-1]))
        authority = {'version': 1, 'scope': 'private-object-erasure-recovery-v1',
            'resource': h.native.policy['resource'], 'policySha256': h.native.verifier.policy_sha256,
            'registrySha256': digest(h.registry.read_bytes()), 'deletionLedgerSha256': '9'*64,
            'capturedAt': h.now, 'expiresAt': h.now+600, 'revocations': [
                {'leaseId': entry['leaseId'], 'assignmentSha256': entry['assignment']['sha256'], 'deletedAt': 950}
                for entry in (entries[0], entries[-2], entries[-1])]}
        path = h.root/'assignment/current-deletions.json'
        path.write_bytes(encoded({**authority, 'registrySha256': digest(first_registry.read_bytes())}))
        with self.assertRaisesRegex(ValueError, 'invalid_object_recovery_authority'):
            h.service.apply_recovery_authority(path, digest(path.read_bytes()))
        path.write_bytes(encoded(authority))
        result = h.service.apply_recovery_authority(path, digest(path.read_bytes()))
        self.assertEqual(result['revokedAssignments'], 3)
        h.restart()
        self.assertEqual(h.service.get(new_job['jobId'])['state'], 'erasing')
        with self.assertRaisesRegex(jobs.JobError, 'object_assignment_revoked'):
            h.service.submit(self.body(entries[-1]))
        with h.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 66)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assignment_revocations').fetchone()[0], 3)
        self.assertFalse(h.native.calls)


if __name__ == '__main__':
    unittest.main()
