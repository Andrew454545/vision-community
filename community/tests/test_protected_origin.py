"""Synthetic local trust-boundary checks, including native Node producer interop."""
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from community import protected_origin as origin
from community import native_object_verifier as audit
from community import object_audit_jobs as jobs
from community.process_owner import run_owned
from community.search_snapshot import digest, encoded
from community.tests import test_native_object_verifier as fixtures

NODE_FIXTURE = r'''
import { prepareProtectedHandoff } from './prepare-protected-mma-handoff.mjs';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
const [database, exporter, exporterSha256, outputDir, raw] = process.argv.slice(1);
const snapshot = JSON.parse(raw);
const result = await prepareProtectedHandoff({database, exporter, exporterSha256, outputDir}, {
 runExporter: async (_binary, args) => writeFile(args.at(-1), JSON.stringify({
  ...snapshot, generatedAt: new Date().toISOString()
 }) + '\n', {flag:'wx'})
});
console.log(JSON.stringify(result));
'''


class ProtectedOriginTests(unittest.TestCase):
    def setUp(self):
        self.fixture = f = fixtures.NativeObjectVerifierTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.root = f.root
        self.receipts = self.root / 'origin'
        self.arrow = f.database.parent / 'arrow'
        self.arrow.mkdir()
        for row in f.snapshot_document['sourceMaps']:
            (self.arrow / (row['id'] + '.arrow')).write_bytes(b'synthetic-arrow-' + row['id'].encode())
        self.exporter = f.database.parent / 'exporter'
        self.exporter.write_bytes(b'synthetic-never-executed-exporter')
        self.install_origin()

    def install_origin(self, node=False):
        f = self.fixture
        if node:
            node_path, native = os.environ.get('VISION_TEST_NODE'), os.environ.get('VISION_TEST_NATIVE_SOURCE')
            if not node_path or not native:
                self.skipTest('Explicit Node/native source paths needed for native producer interoperability')
            # Existing synthetic receipt is kept, never overwritten by the native producer.
            self.receipts = self.root / 'node-origin'
            stdout_path, stderr_path = self.root / 'node.stdout.log', self.root / 'node.stderr.log'
            with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
                result = run_owned([node_path, '--input-type=module', '-e', NODE_FIXTURE,
                    str(f.database), str(self.exporter), digest(self.exporter.read_bytes()),
                    str(self.receipts), json.dumps(f.snapshot_document, ensure_ascii=False)],
                    cwd=Path(native) / 'automation/runtime-source/scripts',
                    env=dict(os.environ), stdout=stdout, stderr=stderr, timeout=30)
            self.assertEqual(result.returncode, 0, stderr_path.read_text(errors='replace'))
            self.assertFalse(json.loads(stdout_path.read_bytes())['objectImportApproved'])
            self.document = json.loads((self.receipts / 'handoff.private.json').read_bytes())
        else:
            self.receipts.mkdir()
            now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            snapshot = {**f.snapshot_document, 'generatedAt': now}
            raw = encoded(snapshot)
            for filename in ('protected-snapshot.private.json', 'selection-probe.private.json'):
                (self.receipts / filename).write_bytes(raw)
            paths = [f.database, Path(str(f.database) + '-wal')]
            for row in snapshot['sourceMaps']:
                paths += [self.arrow / (row['id'] + suffix) for suffix in ('.arrow', '_delta.arrow')]
            self.document = {'version': 1, 'contract': 'vision-origin-protected-mma-handoff-v1',
                'status': 'ORIGIN_PROTECTED_STATE_CAPTURED_NOT_PORTABLE_IMPORT_AUTHORITY',
                'startedAt': now, 'completedAt': now, 'selectors': origin.SELECTORS,
                'snapshot': {'file': 'protected-snapshot.private.json', 'bytes': len(raw),
                    'sha256': digest(raw), 'generatedAt': now},
                'selectionProbe': {'file': 'selection-probe.private.json', 'bytes': len(raw), 'sha256': digest(raw)},
                'sourceMapCount': 4, 'sourceLocationCount': 4, 'uniqueLocationCount': 1,
                'sourceArtifacts': [origin.fingerprint(str(p), time.monotonic() + 30, optional=i != 0)
                                    for i, p in enumerate(paths)],
                'exporter': origin.fingerprint(str(self.exporter), time.monotonic() + 30),
                'freshness': {'policy': 'live-origin-files-required-no-offline-relabelling-v1', 'maxAgeMillis': origin.MAX_AGE_MS},
                **{k: False for k in ('objectImportApproved', 'portableImportApproved', 'productionQualified',
                    'databaseBytesCopied', 'sourceBytesCopied', 'networkUsed')}}
            (self.receipts / 'handoff.private.json').write_bytes(encoded(self.document))
        doc = json.loads(f.authority.read_bytes())
        member = self.receipts / 'handoff.private.json'
        doc['protectedOriginHandoff'] = {'path': str(member), 'bytes': member.stat().st_size, 'sha256': digest(member.read_bytes())}
        doc['invariants']['protectedSourceArtifactsSealed'] = True
        doc['protectedSnapshot'] = {'path': str(self.receipts / 'protected-snapshot.private.json'),
            **{k: self.document['snapshot'][k] for k in ('bytes', 'sha256', 'generatedAt')}}
        f.authority.write_bytes(encoded(doc))
        f.policy['protectedAuthority'].update(bytes=f.authority.stat().st_size, sha256=digest(f.authority.read_bytes()))
        f.policy['protectedOriginHandoffSha256'] = digest(member.read_bytes())
        f.manifest['viewQuality']['protectedAuthorityManifestSha256'] = digest(f.authority.read_bytes())
        f.write_index(f.candidate, f.manifest, f.files)
        f.verifier = f.start()

    def test_current_origin_can_complete_component_audit_without_import_permission(self):
        report = self.fixture.run_audit()
        self.assertEqual(report['decision'], 'approved')
        self.assertFalse(report['protectedOrigin']['objectImportApproved'])
        self.assertFalse(report['protectedOrigin']['portableImportApproved'])
        self.assertFalse(report['serverAuthorization'])
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertTrue(report['protectedOrigin']['sourceContentHashesVerified'])

    def test_intermediate_guard_does_not_rehash_large_source_files_or_replace_full_proof(self):
        def refused_hash(*args, **kwargs):
            self.fail('Intermediate status check must not rehash source contents')
        with patch.object(origin, 'hashlib', SimpleNamespace(sha256=refused_hash)):
            self.fixture.verifier.verify_origin_guard()
        self.assertTrue(self.fixture.verifier.origin_evidence['sourceContentHashesVerified'])

    def test_actual_node_producer_is_accepted_by_python_on_original_machine(self):
        self.install_origin(node=True)
        self.assertEqual(self.fixture.run_audit()['decision'], 'approved')
        (self.arrow / '0.arrow').write_bytes(b'changed-native-source')
        with self.assertRaises(ValueError):
            self.fixture.verifier.verify_inputs()

    def test_changed_arrow_stops_before_inference(self):
        (self.arrow / '0.arrow').write_bytes(b'changed')
        report = self.fixture.run_audit()
        self.assertEqual((report['status'], report['decision']), ('FAILED', 'pending'))
        self.assertEqual(self.fixture.calls, [])

    def test_unchanged_size_and_mtime_cannot_hide_arrow_replacement(self):
        p = self.arrow / '0.arrow'
        state = p.stat()
        p.write_bytes(b'x' * state.st_size)
        os.utime(p, ns=(state.st_atime_ns, state.st_mtime_ns))
        with self.assertRaises(ValueError):
            self.fixture.verifier.verify_inputs()

    def test_previously_absent_delta_cannot_appear(self):
        (self.arrow / '0_delta.arrow').write_bytes(b'new')
        with self.assertRaises(ValueError):
            self.fixture.verifier.verify_inputs()

    def test_exporter_is_also_checked(self):
        self.exporter.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.fixture.verifier.verify_inputs()

    def test_wal_appearance_is_also_checked(self):
        Path(str(self.fixture.database) + '-wal').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.fixture.verifier.verify_inputs()

    def test_source_change_during_native_stage_keeps_failure_and_stops_next_stage(self):
        f = self.fixture
        def changed(command, job, timeout):
            result = f.fake_native(command, job, timeout)
            if command[1] == 'index-segment':
                (self.arrow / '0.arrow').write_bytes(b'changed-during-inference')
            return result
        report = f.run_audit(runner=changed)
        self.assertEqual((report['status'], report['decision']), ('FAILED', 'pending'))
        self.assertEqual(f.calls, ['runtime-info', 'index-segment'])
        self.assertEqual(json.loads((f.root / 'jobs/one/audit-report.json').read_bytes()), report)

    def test_expiry_is_measured_from_original_start_even_on_recovered_verifier(self):
        with patch.object(origin.time, 'time', return_value=time.time() + 3602):
            with self.assertRaises(ValueError):
                self.fixture.verifier.verify_inputs()

    def test_missing_or_changed_independent_pin_is_not_legacy_fallback(self):
        f = self.fixture
        for value in (None, 'a' * 64):
            with self.subTest(value=value):
                if value is None:
                    f.policy.pop('protectedOriginHandoffSha256')
                else:
                    f.policy['protectedOriginHandoffSha256'] = value
                with self.assertRaisesRegex(ValueError, 'invalid_object_audit_origin_authority'):
                    f.start()

    def test_guard_fields_cannot_be_stripped_when_policy_requires_them(self):
        f = self.fixture
        doc = json.loads(f.authority.read_bytes())
        del doc['protectedOriginHandoff']
        del doc['invariants']['protectedSourceArtifactsSealed']
        f.authority.write_bytes(encoded(doc))
        f.policy['protectedAuthority'].update(bytes=f.authority.stat().st_size, sha256=digest(f.authority.read_bytes()))
        with self.assertRaisesRegex(ValueError, 'invalid_object_audit_origin_authority'):
            f.start()

    def test_missing_origin_files_fail_without_using_only_coordinate_snapshot(self):
        (self.arrow / '1.arrow').unlink()
        with self.assertRaises(ValueError):
            self.fixture.verifier.verify_inputs()

    def test_snapshot_pin_and_relative_member_are_bound(self):
        f = self.fixture
        p = self.receipts / 'protected-snapshot.private.json'
        p.write_bytes(p.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            f.verifier.verify_inputs()

    def test_receipt_changes_cannot_be_relabelled_fresh(self):
        p = self.receipts / 'handoff.private.json'
        doc = json.loads(p.read_bytes())
        doc['startedAt'] = '2027-01-01T00:00:00Z'
        p.write_bytes(encoded(doc))
        with self.assertRaises(ValueError):
            self.fixture.verifier.verify_inputs()

    def saved_job(self):
        f = self.fixture
        def pin(p):
            return {'path': str(p), 'bytes': p.stat().st_size, 'sha256': digest(p.read_bytes())}
        registry = self.root / 'assignment/registry.json'
        registry.write_bytes(encoded({'version': 1, 'scope': 'private-object-audit-registry',
            'policyId': f.policy['policyId'], 'resource': f.policy['resource'],
            'assignments': [{'leaseId': f.trusted['leaseId'], 'profileId': f.trusted['profileId'],
                'assignment': pin(f.assignment), 'source': pin(f.source_path)}]}))
        service = jobs.ObjectAuditJobs(f.verifier, registry, digest(registry.read_bytes()), self.root / 'spool')
        self.addCleanup(service.close)
        body = encoded({'version': 1, 'leaseId': f.trusted['leaseId'], 'profileId': f.trusted['profileId'],
            'policyId': f.policy['policyId'], 'assignmentSha256': digest(f.assignment.read_bytes()),
            'submissionSha256': '2' * 64, 'objectIndex': {
                'manifest': json.loads((f.candidate / 'manifest.json').read_bytes()),
                'sourceTsv': base64.b64encode(f.source).decode(),
                'files': {name: base64.b64encode(raw).decode() for name, raw in f.files.items()}}})
        job = service.submit(body)['jobId']
        with patch.object(f.verifier, 'run', side_effect=f.fake_native):
            self.assertTrue(service.run_next())
        self.assertEqual(service.get(job)['decision'], 'approved')
        return service, job, body

    def test_saved_approval_and_duplicate_reply_fail_closed_after_origin_change(self):
        service, job, body = self.saved_job()
        receipt = self.root / 'spool' / ('attempts-' + job) / 'attempt-1/audit-report.json'
        original = receipt.read_bytes()
        (self.arrow / '0.arrow').write_bytes(b'changed-after-settlement')
        for operation in (lambda: service.get(job), lambda: service.submit(body)):
            with self.assertRaisesRegex(jobs.JobError, 'object_job_origin_unavailable') as failure:
                operation()
            self.assertEqual(failure.exception.status, 503)
        self.assertEqual(receipt.read_bytes(), original)

    def test_saved_approval_expires_without_rewriting_historical_decision(self):
        service, job, _ = self.saved_job()
        with patch.object(origin.time, 'time', return_value=time.time() + 3602):
            with self.assertRaisesRegex(jobs.JobError, 'object_job_origin_unavailable'):
                service.get(job)
        with service.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?', (job,)).fetchone()[0], 'approved')

    def test_recovered_receipt_must_bind_the_same_origin_evidence(self):
        service, job, _ = self.saved_job()
        receipt = self.root / 'spool' / ('attempts-' + job) / 'attempt-1/audit-report.json'
        doc = json.loads(receipt.read_bytes())
        del doc['protectedOrigin']
        receipt.write_bytes(encoded(doc))
        with service.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()
            with self.assertRaisesRegex(jobs.JobError, 'object_job_receipt_unavailable'):
                service.receipt(row)
