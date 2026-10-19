"""Synthetic trust-boundary tests. No real inference, coverage or credit."""
import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from community import native_object_verifier as audit
from community.object_canary import MODELS
from community.object_features import crc8, crc16
from community.object_index import COMMON_MODEL_SHA256, RUNTIME_IDENTITY, CODEBOOK_SHA256
from community.search_snapshot import CONFIRMED_STAGING_RESOURCE, digest, encoded
from community.tests.test_object_features import DOCUMENT, mutate


class NativeObjectVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        for name in ('runtime/models', 'policy', 'assignment', 'candidate', 'jobs'):
            (self.root / name).mkdir(parents=True)
        self.binary = self.root / 'runtime/native.exe'
        self.binary.write_bytes(b'synthetic-never-executed')
        self.models = self.root / 'runtime/models'
        for name in MODELS:
            (self.models / name).write_bytes(b'synthetic-' + name.encode())
        if os.name == 'nt':
            for name in audit.runtime_profile.__globals__['DLLS']:
                (self.binary.parent / name).write_bytes(b'synthetic-library')
        self.database = self.root / 'policy/protected.sqlite'
        self.database.write_bytes(b'synthetic fingerprint; not official coverage')
        os.utime(self.database, (1760000000, 1760000000))
        self.snapshot = self.root / 'policy/protected.json'
        self.snapshot_document = {'schemaVersion': 1, 'database': str(self.database),
            'generatedAt': '2026-10-09T00:00:00Z', 'sourceLocationCount': 4, 'uniqueLocationCount': 1,
            'sourceMaps': [{'id': str(i), 'name': name, 'folder': folder, 'locationCount': 1}
                for i, (name, folder) in enumerate([
                    ('‼️GEONECTIONS JSON‼️', None), ('Past Locations', None),
                    ('synthetic-map', 'Titled Maps ‼️'), ('synthetic-map', 'Titled Maps ‼️ Done✅')])],
            'coordinates': [{'lat': 0, 'lng': 0}]}
        self.snapshot.write_bytes(encoded(self.snapshot_document))
        self.authority = self.root / 'policy/authority.json'
        self.authority.write_bytes(encoded({'contract': 'vision-gen4-inline-object-import-v1',
            'inlineQualityFilterRequired': True, 'runtimeLiveProtectedFilterRequired': True,
            'invariants': {'protectedDatabaseFingerprintSealed': True},
            'quality': {'currentTunnelEvidence': 'none-darkness-never-rejects-v1'},
            'protectedSnapshot': {'path': str(self.snapshot), 'bytes': self.snapshot.stat().st_size,
                'sha256': digest(self.snapshot.read_bytes()), 'generatedAt': self.snapshot_document['generatedAt']},
            'protectedDatabase': {
                'main': {'path': str(self.database), 'exists': True, 'bytes': self.database.stat().st_size,
                    'sha256': digest(self.database.read_bytes()),
                    'modifiedUnixMillis': self.database.stat().st_mtime_ns // 1_000_000},
                'wal': {'path': str(self.database) + '-wal', 'exists': False}}}))
        self.manifest, self.files, self.source = mutate({})
        self.manifest['viewQuality'].update(policy='vision-per-view-quality-v1', viewCount=6,
            implementationIdentity='a' * 64, protectedAuthorityManifestSha256=digest(self.authority.read_bytes()),
            blurAreaFractionExclusive=.5, tileGrid=8, tunnelVisionProbabilityInclusive=.85,
            tunnelEvidencePolicy='none-darkness-never-rejects-v1', blurRejectedViews=0,
            darkTunnelRejectedViews=0, fullyRejectedLocations=0, keptViews=12)
        rows = copy.deepcopy(DOCUMENT['items'])
        for row, fields in zip(rows, self.source.decode().splitlines()):
            columns = fields.split('\t')
            row.update(mapId=columns[0], sourceLocationId=int(columns[1]), roadName=columns[10],
                coverageValidator=audit.VALIDATOR, coverageEvidenceSha256='c' * 64)
        self.assignment = self.root / 'assignment/assignment.json'
        self.trusted = {'version': 1, 'scope': 'trusted-object-assignment',
            'policyId': 'staging.synthetic-object-audit', 'resource': CONFIRMED_STAGING_RESOURCE,
            'profileId': '1' * 64, 'leaseId': DOCUMENT['leaseId'], 'sourceSha256': digest(self.source), 'records': rows}
        self.assignment.write_bytes(encoded(self.trusted))
        self.source_path = self.root / 'assignment/locations.tsv'
        self.source_path.write_bytes(self.source)
        self.policy_path = self.root / 'policy/policy.json'
        self.policy = {'version': 1, 'scope': 'trusted-native-object-audit', 'policyId': self.trusted['policyId'],
            'sourceFiles': audit.source_pins(), 'environment': 'staging', 'resource': CONFIRMED_STAGING_RESOURCE,
            'runtimeProfileSha256': audit.runtime_profile(self.binary, self.models)['sha256'],
            'profiles': ['1' * 64], 'qualityImplementationIdentity': 'a' * 64,
            'protectedAuthority': {'path': str(self.authority), 'bytes': self.authority.stat().st_size,
                                   'sha256': digest(self.authority.read_bytes())},
            'maxLocations': 2, 'timeoutSeconds': 900,
            'auditThresholds': {'lanes': {key: 0 for key in audit.LANE_LIMITS},
                                'semantic': {key: 0 for key in audit.SEMANTIC_LIMITS}}}
        self.candidate = self.root / 'candidate'
        self.write_index(self.candidate, self.manifest, self.files)
        self.calls = []
        self.verifier = self.start()

    def start(self):
        self.policy_path.write_bytes(encoded(self.policy))
        # Fake model bytes cannot pass actual native model identity validation.
        # The separate path-validation test exercises that real guard below.
        with patch.object(audit.NativeObjectVerifier, 'validate_model_paths'):
            return audit.NativeObjectVerifier(self.binary, self.models, self.policy_path,
                                               digest(self.policy_path.read_bytes()))

    def write_index(self, folder, manifest, files):
        folder.mkdir(exist_ok=True)
        document = copy.deepcopy(manifest)
        entries = [document[key] for key in ('offsets', 'metadata', 'globalIds', 'semantic', 'viewQuality')]
        entries += document['classes'] + document['hotConcepts']
        for entry in entries:
            raw = files[entry['file']]
            entry.update(bytes=len(raw), records=len(raw) // entry.get('recordBytes', 32), sha256=digest(raw))
        for name, raw in files.items():
            (folder / name).write_bytes(raw)
        (folder / 'manifest.json').write_bytes(encoded(document))

    def fake_native(self, command, job, timeout):
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 900)
        self.calls.append(command[1])
        job.mkdir()
        (job / 'stdout.log').write_bytes(b'synthetic')
        (job / 'stderr.log').write_bytes(audit.THREAD_MARKER.encode())
        if command[1] == 'runtime-info':
            return encoded({'valid': True, 'indexContractVersion': 4, 'searchContractVersion': 2,
                'commonModelSHA256': COMMON_MODEL_SHA256, 'runtimeIdentity': RUNTIME_IDENTITY,
                'viewQualityImplementationIdentity': 'a' * 64})
        if command[1] == 'index-segment':
            for flag in ('--cpu', '--quality-filter', '--protected-authority-manifest'):
                self.assertIn(flag, command)
            self.assertNotIn('--frozen-views', command)
            self.assertNotIn('--stop-after', command)
            self.assertEqual(command[command.index('--duty-cycle-percent') + 1], '100')
            source = Path(command[command.index('--source-tsv') + 1])
            self.assertEqual(source.read_bytes(), self.source)
            target = Path(command[command.index('--output-dir') + 1])
            self.write_index(target, {**self.manifest, 'sourceTsv': str(source)}, self.files)
            return b''
        self.assertEqual(command[1], 'verify-index')
        self.assertIn('--full', command)
        return encoded({'valid': True, 'full': True, 'indexVersion': 4})

    def run_audit(self, name='one', runner=None):
        with patch.object(self.verifier, 'run', side_effect=runner or self.fake_native):
            return self.verifier.audit(assignment=self.assignment, assignment_sha256=digest(self.assignment.read_bytes()),
                source=self.source_path, candidate=self.candidate,
                candidate_sha256=digest((self.candidate / 'manifest.json').read_bytes()), out=self.root / 'jobs' / name)

    def test_recompute_and_two_full_verifications_are_mandatory(self):
        report = self.run_audit()
        self.assertEqual((report['status'], report['decision']), ('COMPLETE', 'approved'))
        self.assertEqual(self.calls, ['runtime-info', 'index-segment', 'verify-index', 'verify-index'])
        self.assertFalse(report['serverAuthorization'])
        self.assertFalse(report['productionQualified'])
        self.assertEqual(report['acceptedContributions'], 0)
        self.assertEqual(report['inputIdentity'], 'LIVE_RETRIEVAL_NOT_FROZEN')
        self.assertEqual(report['policySha256'], digest(self.policy_path.read_bytes()))
        self.assertEqual(report['runtimeProfileSha256'], self.policy['runtimeProfileSha256'])
        self.assertEqual(report['sourceSha256'], digest(self.source))
        self.assertTrue(report['nativeReferenceRecomputed'])
        raw = (self.root / 'jobs/one/audit-report.json').read_text()
        self.assertNotIn(str(self.root), raw)
        self.assertNotIn('synthetic-pano', raw)
        self.assertNotIn('Synthetic Côte', raw)

    def test_candidate_feature_change_is_rejected_after_independent_inference(self):
        files = dict(self.files)
        name = self.manifest['classes'][0]['file']
        raw = bytearray(files[name])
        score = struct.unpack_from('<f', raw, 4)[0]
        struct.pack_into('<f', raw, 4, score + .0001)
        struct.pack_into('<H', raw, 29, round((score + .0001) * 65535))
        raw[31] = crc8(raw[:31])
        files[name] = bytes(raw)
        self.write_index(self.candidate, self.manifest, files)
        report = self.run_audit()
        self.assertEqual((report['status'], report['decision']), ('COMPLETE', 'rejected'))
        self.assertIn('index-segment', self.calls)

    def test_only_explicit_numerical_tolerance_can_accept_a_score_change(self):
        self.policy['auditThresholds']['lanes']['maximumScoreDifference'] = .0002
        self.policy['auditThresholds']['lanes']['maximumConfidenceDifference'] = .0002
        self.verifier = self.start()
        files = dict(self.files)
        name = self.manifest['classes'][0]['file']
        raw = bytearray(files[name])
        score = struct.unpack_from('<f', raw, 4)[0] + .0001
        struct.pack_into('<f', raw, 4, score)
        struct.pack_into('<H', raw, 29, round(score * 65535))
        raw[31] = crc8(raw[:31]); files[name] = bytes(raw)
        self.write_index(self.candidate, self.manifest, files)
        self.assertEqual(self.run_audit()['decision'], 'approved')

    def test_changed_pq_code_is_not_hidden_by_numerical_tolerance(self):
        files = dict(self.files)
        raw = bytearray(files['semantic-pq128.bin']); raw[0] ^= 1
        struct.pack_into('<H', raw, 142, crc16(raw[:142]))
        files['semantic-pq128.bin'] = bytes(raw)
        self.write_index(self.candidate, self.manifest, files)
        self.assertEqual(self.run_audit()['decision'], 'rejected')

    def test_frozen_diagnostic_is_refused_before_any_native_work(self):
        for value in (None, 'b' * 64):
            with self.subTest(value=value):
                self.write_index(self.candidate, {**self.manifest, 'frozenViewsManifestSha256': value}, self.files)
                result = self.run_audit(str(value))
                self.assertEqual(result['status'], 'FAILED')
                self.assertEqual(result['decision'], 'pending')
                self.assertEqual(result['error'], 'diagnostic_object_artifact')
                self.assertEqual(self.calls, [])

    def test_assignment_tampering_cannot_supply_coverage_or_pose(self):
        for key, value in (('profileId', 'f' * 64), ('policyId', 'other'), ('resource', {})):
            with self.subTest(key=key):
                self.assignment.write_bytes(encoded({**self.trusted, key: value}))
                self.assertEqual(self.run_audit(key)['status'], 'FAILED')
                self.assertEqual(self.calls, [])
        for key, value in (('coverageValidator', 'official-gen4-historical-v1'),
                           ('cameraGeneration', 'gen3'), ('heading', 91)):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.trusted); changed['records'][0][key] = value
                self.assignment.write_bytes(encoded(changed))
                self.assertEqual(self.run_audit(key)['status'], 'FAILED')
                self.assertEqual(self.calls, [])

    def test_runtime_or_policy_change_never_reaches_inference(self):
        (self.models / MODELS[-1]).write_bytes(b'changed')
        result = self.run_audit()
        self.assertEqual((result['status'], result['decision']), ('FAILED', 'pending'))
        self.assertEqual(self.calls, [])

    def test_late_authority_change_preserves_all_failure_evidence(self):
        def late(command, job, timeout):
            value = self.fake_native(command, job, timeout)
            if job.name == 'verify-after':
                self.database.write_bytes(b'changed after compute')
            return value
        result = self.run_audit(runner=late)
        self.assertEqual((result['status'], result['decision']), ('FAILED', 'pending'))
        self.assertTrue((self.root / 'jobs/one/reference/manifest.json').exists())
        self.assertTrue((self.root / 'jobs/one/inference/stderr.log').exists())

    def test_late_candidate_change_cannot_reuse_an_earlier_comparison(self):
        def late(command, job, timeout):
            result = self.fake_native(command, job, timeout)
            if job.name == 'verify-after':
                (self.candidate / 'manifest.json').write_bytes(b'{"changed":true}')
            return result
        result = self.run_audit(runner=late)
        self.assertEqual((result['status'], result['decision']), ('FAILED', 'pending'))

    def test_untransported_tunnel_authority_is_refused(self):
        doc = json.loads(self.authority.read_bytes())
        doc['quality']['currentTunnelEvidence'] = 'sealed-external-map-plus-tunnel-vision-exact-pano-coordinate-v1'
        self.authority.write_bytes(encoded(doc))
        self.policy['protectedAuthority'].update(bytes=self.authority.stat().st_size,
                                                 sha256=digest(self.authority.read_bytes()))
        with self.assertRaisesRegex(audit.ObjectAuditError, 'unsupported_object_audit_authority'):
            self.start()

    def test_malformed_authority_sections_fail_with_a_fixed_setup_error(self):
        original = self.authority.read_bytes()
        for field in ('quality', 'invariants'):
            with self.subTest(field=field):
                doc = json.loads(original); doc[field] = 'invalid'
                self.authority.write_bytes(encoded(doc))
                self.policy['protectedAuthority'].update(bytes=self.authority.stat().st_size,
                                                         sha256=digest(self.authority.read_bytes()))
                with self.assertRaisesRegex(audit.ObjectAuditError, 'unsupported_object_audit_authority'):
                    self.start()

    def test_timeout_or_interrupt_is_pending_and_not_a_rejection(self):
        for i, error in enumerate((subprocess.TimeoutExpired('synthetic', 900), KeyboardInterrupt())):
            with self.subTest(error=type(error).__name__):
                result = self.run_audit(str(i), runner=lambda *_: (_ for _ in ()).throw(error))
                self.assertEqual((result['status'], result['decision']), ('FAILED', 'pending'))
                self.assertEqual(result['error'], 'object_audit_unavailable')

    def test_full_verification_cannot_be_replaced_by_successful_exit(self):
        def incomplete(command, job, timeout):
            value = self.fake_native(command, job, timeout)
            return encoded({'valid': True, 'indexVersion': 4, 'full': False}) if command[1] == 'verify-index' else value
        self.assertEqual(self.run_audit(runner=incomplete)['error'], 'object_audit_native_verification_failed')

    def test_native_runtime_contract_must_match_the_quality_implementation(self):
        def old(command, job, timeout):
            value = self.fake_native(command, job, timeout)
            if command[1] == 'runtime-info':
                info = json.loads(value); info['viewQualityImplementationIdentity'] = 'b' * 64
                return encoded(info)
            return value
        self.assertEqual(self.run_audit(runner=old)['error'], 'object_audit_runtime_contract_mismatch')
        self.assertEqual(self.calls, ['runtime-info'])

    def test_output_is_fresh_and_cannot_overwrite_inputs_or_a_failure(self):
        self.run_audit()
        before = (self.root / 'jobs/one/audit-report.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_audit()
        self.assertEqual((self.root / 'jobs/one/audit-report.json').read_bytes(), before)
        with self.assertRaisesRegex(audit.ObjectAuditError, 'overlaps_input'):
            self.verifier.audit(assignment=self.assignment, assignment_sha256=digest(self.assignment.read_bytes()),
                source=self.source_path, candidate=self.candidate, candidate_sha256='f' * 64, out=self.candidate / 'nested')

    def test_small_batch_and_time_bounds_cannot_be_silently_increased(self):
        for key, value in (('maxLocations', 16), ('timeoutSeconds', 901), ('maxLocations', True)):
            with self.subTest(key=key, value=value):
                original = self.policy[key]; self.policy[key] = value
                with self.assertRaisesRegex(audit.ObjectAuditError, 'budget'):
                    self.start()
                self.policy[key] = original

    def test_protected_assignment_is_refused_before_any_native_execution(self):
        row = self.trusted['records'][0]
        self.snapshot_document['coordinates'] = [{'lat': row['lat'], 'lng': row['lng']}]
        self.snapshot.write_bytes(encoded(self.snapshot_document))
        authority = json.loads(self.authority.read_bytes())
        authority['protectedSnapshot'].update(bytes=self.snapshot.stat().st_size, sha256=digest(self.snapshot.read_bytes()))
        self.authority.write_bytes(encoded(authority))
        self.policy['protectedAuthority'].update(bytes=self.authority.stat().st_size, sha256=digest(self.authority.read_bytes()))
        self.verifier = self.start()
        result = self.run_audit()
        self.assertEqual((result['status'], result['decision'], result['error']),
                         ('FAILED', 'pending', 'object_audit_protected_assignment'))
        self.assertEqual(self.calls, [])

    def test_missing_or_mismatched_snapshot_cannot_supply_authority(self):
        original = self.authority.read_bytes()
        for mode in ('missing', 'database', 'date', 'stale'):
            with self.subTest(mode=mode):
                authority = json.loads(original)
                if mode == 'missing':
                    del authority['protectedSnapshot']
                else:
                    snapshot = copy.deepcopy(self.snapshot_document)
                    if mode == 'database': snapshot['database'] = str(self.root / 'different.sqlite')
                    elif mode == 'stale':
                        snapshot['generatedAt'] = '2024-10-09T00:00:00Z'
                        authority['protectedSnapshot']['generatedAt'] = snapshot['generatedAt']
                    else: snapshot['generatedAt'] = '2026-10-08T00:00:00Z'
                    self.snapshot.write_bytes(encoded(snapshot))
                    authority['protectedSnapshot'].update(bytes=self.snapshot.stat().st_size, sha256=digest(self.snapshot.read_bytes()))
                self.authority.write_bytes(encoded(authority))
                self.policy['protectedAuthority'].update(bytes=self.authority.stat().st_size, sha256=digest(self.authority.read_bytes()))
                with self.assertRaises(ValueError): self.start()

    def test_changed_snapshot_during_native_work_keeps_a_pending_failure(self):
        def changed(command, job, timeout):
            value = self.fake_native(command, job, timeout)
            if command[1] == 'index-segment': self.snapshot.write_bytes(b'changed snapshot')
            return value
        result = self.run_audit(runner=changed)
        self.assertEqual((result['status'], result['decision']), ('FAILED', 'pending'))
        self.assertFalse(result['serverAuthorization'])

    def test_staging_policy_cannot_be_used_with_production_resources(self):
        self.policy['environment'] = 'production'
        with self.assertRaisesRegex(audit.ObjectAuditError, 'resource_mismatch'):
            self.start()

    def test_loose_unknown_or_nonfinite_tolerances_are_refused(self):
        for value in (float('nan'), float('inf'), True, -.1, .1):
            with self.subTest(value=value):
                bad = copy.deepcopy(self.policy['auditThresholds']); bad['lanes']['maximumScoreDifference'] = value
                with self.assertRaisesRegex(audit.ObjectAuditError, 'bounds'):
                    audit.bounds(bad)
        bad = copy.deepcopy(self.policy['auditThresholds']); bad['semantic']['averageCosine'] = .9
        with self.assertRaises(audit.ObjectAuditError):
            audit.bounds(bad)

    def test_model_manifest_cannot_redirect_a_pinned_model_read(self):
        paths = {'pq': {'file': 'owlv2-pq128-codebook.bin', 'sha256': CODEBOOK_SHA256},
            'owlv2': {}, 'yoloe': {}}
        for key, name in (('vision', 'owlv2-vision-proposals.onnx'), ('text', 'owlv2-text-encoder.onnx'),
                          ('tokenizer', 'owlv2-tokenizer.json'), ('vocab', 'owlv2-vocab.json'), ('merges', 'owlv2-merges.txt')):
            paths['owlv2'][key + 'File'] = name
            paths['owlv2'][key + 'SHA256'] = self.verifier.profile['profile']['assets']['models/' + name]
        for key, name in (('model', 'yoloe-26l-hot.onnx'), ('promptEmbeddings', 'yoloe-26l-hot-prompts.npz')):
            paths['yoloe'][key + 'File'] = name
            paths['yoloe'][key + 'SHA256'] = self.verifier.profile['profile']['assets']['models/' + name]
        self.verifier.profile['profile']['assets']['models/owlv2-pq128-codebook.bin'] = CODEBOOK_SHA256
        self.verifier.profile['profile']['assets']['models/rfdetr-medium-576-b4.onnx'] = COMMON_MODEL_SHA256
        (self.models / 'hybrid-object-runtime.json').write_bytes(encoded(paths))
        self.verifier.validate_model_paths()
        paths['owlv2']['visionFile'] = '../unpinned.onnx'
        (self.models / 'hybrid-object-runtime.json').write_bytes(encoded(paths))
        with self.assertRaisesRegex(audit.ObjectAuditError, 'models'):
            self.verifier.validate_model_paths()

    def test_native_environment_excludes_credentials_and_controls_threads(self):
        def owned(command, **options):
            env = options['env']
            self.assertNotIn('VISION_HOST_SECRET', env)
            self.assertNotIn('CLOUDFLARE_API_TOKEN', env)
            self.assertNotIn('PYTHONPATH', env)
            self.assertEqual({env[key] for key in audit.THREAD_ENVIRONMENT_KEYS}, {'1'})
            self.assertEqual(env['TEMP'], str(self.root / 'jobs/process'))
            options['stderr'].write(audit.THREAD_MARKER.encode())
            options['stdout'].write(b'{}')
            return subprocess.CompletedProcess(command, 0)
        with patch.dict(os.environ, {'VISION_HOST_SECRET': 'never inherit', 'CLOUDFLARE_API_TOKEN': 'never inherit'}), \
                patch.object(audit, 'run_owned', side_effect=owned):
            self.assertEqual(self.verifier.run([str(self.binary), 'runtime-info'], self.root / 'jobs/process', 1), b'{}')
        self.assertEqual(json.loads((self.root / 'jobs/process/exit.json').read_bytes())['exitCode'], 0)

    def test_owned_native_timeout_keeps_a_fixed_private_exit_receipt(self):
        with patch.object(audit, 'run_owned', side_effect=subprocess.TimeoutExpired('private-native-path', 1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.verifier.run([str(self.binary), 'runtime-info'], self.root / 'jobs/timeout', 1)
        raw = (self.root / 'jobs/timeout/exit.json').read_text()
        receipt = json.loads(raw)
        self.assertEqual((receipt['status'], receipt['errorType']), ('FAILED', 'TimeoutExpired'))
        self.assertNotIn('private-native-path', raw)


if __name__ == '__main__':
    unittest.main()
