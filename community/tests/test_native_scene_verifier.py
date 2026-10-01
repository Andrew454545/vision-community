import base64
import copy
import http.client
import json
import platform
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from community import native_scene_search as native
from community import native_scene_verifier as audit
from community.search_snapshot import digest, encoded


class NativeSceneVerifierTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.runtime = self.root/'runtime'
        (self.runtime/'models').mkdir(parents=True)
        (self.runtime/'native.exe').write_bytes(b'synthetic-never-executed')
        (self.runtime/'countries.txt').write_bytes(b'Italy\nUSA\n')
        for name in native.MODEL_FILES:
            (self.runtime/'models'/name).write_bytes(b'synthetic-model-' + name.encode())
        config = {'version': 1, 'contractVersion': 2, 'nativeLayout': 4,
                  'adapterSha256': native.file_digest(Path(native.__file__)), 'pythonVersion': platform.python_version(),
                  'sourceFiles': {name: {'bytes': (Path(native.__file__).parent/name).stat().st_size,
                           'sha256': native.file_digest(Path(native.__file__).parent/name)} for name in native.SOURCE_FILES},
                  'policyId': 'synthetic-service', 'executable': 'native.exe', 'queryModes': ['textOnly'],
                  'files': {p.relative_to(self.runtime).as_posix(): {'bytes': p.stat().st_size, 'sha256': native.file_digest(p)}
                            for p in self.runtime.rglob('*') if p.is_file()}}
        self.runtime_file = self.runtime/'runtime.json'
        self.runtime_file.write_bytes(encoded(config))
        self.policy_root = self.root/'private-policy'
        self.policy_root.mkdir()
        self.record = (b'\x00\x3c' + bytes([1])*768)*4
        self.reference = self.policy_root/'canary-reference.i8'
        self.reference.write_bytes(self.record*112)
        self.profile = '1'*64
        self.definition = {'version': 1, 'policyId': 'synthetic-audit-only', 'runtimeProfileSha256': self.profile,
            'fixtureSha256': '2'*64, 'referenceSha256': digest(self.reference.read_bytes()),
            'fullCalibration': {'approved': True, 'locations': 1024, 'repetitions': 3, 'evidenceSha256': '3'*64},
            'thresholds': {'minimumViewCosine': .999999, 'maximumViewRelativeL2': .000001}}
        self.policy = {'version': 1, 'scope': 'trusted-native-scene-audit', 'policyId': 'synthetic-audit-only',
            'runtimeSha256': digest(self.runtime_file.read_bytes()), 'sourceFiles': audit.source_pins(),
            'profiles': [self.definition], 'auditThresholds': self.definition['thresholds']}
        self.policy_file = self.policy_root/'policy.json'
        self.policy_file.write_bytes(encoded(self.policy))
        self.work = self.root/'work'
        self.work.mkdir()
        self.verifier = self.start()

    def start(self, **changes):
        return audit.NativeSceneVerifier(self.runtime_file, digest(self.runtime_file.read_bytes()),
            self.policy_file, digest(self.policy_file.read_bytes()), changes.get('work', self.work),
            timeout=changes.get('timeout', 50))

    def request(self, blob=None):
        blob = blob or self.record
        records = [{'locationId': 1, 'assetId': 'synthetic-pano', 'capture': 'synthetic-only',
                    'inputModel': 'synthetic-input', 'lat': 1e-7, 'lng': 20, 'heading': 270,
                    'pitch': 0, 'zoom': 1, 'country': 'Italy', 'cameraGeneration': 'gen4', 'outputSha256': digest(blob)}]
        raw = json.dumps(records, ensure_ascii=False, separators=(',', ':')).encode()
        return {'policyId': 'synthetic-audit-only', 'profileId': self.profile,
                'submissionSha256': digest(raw+b'\n'+blob), 'records': records,
                'indexBase64': base64.b64encode(blob).decode()}, raw

    def fake_native(self, command, job, timeout):
        self.assertEqual(command[1], 'index-four-views')
        self.assertEqual(timeout, 50)
        source = job/'locations.tsv'
        self.assertEqual(source.read_text().splitlines()[0].split('\t')[8:10], ['Italy', 'gen4'])
        expected = {'version': 4, 'totalLocations': 1, 'completed': True,
                    'sourceBytes': source.stat().st_size, 'sourcePrefixHash': native.fnv_file(source),
                    'modelIdentity': native.model_identity(self.runtime/'models')}
        (job/'checkpoint.json').write_bytes(encoded({**expected, 'nextLocationIndex': 1,
            'fetchErrors': 0, 'inferenceErrors': 0, 'incompleteLocations': 0}))
        index = job/'index'
        index.mkdir()
        (index/'manifest.json').write_bytes(encoded({**expected, 'indexedLocations': 1,
            'viewsPerLocation': 4, 'bytesPerLocation': 3080}))
        (index/'shard-000000.mask').write_bytes(b'\x0f')
        (index/'shard-000000.i8').write_bytes(self.record)

    def test_qualification_uses_pinned_reference_and_exact_canary_bytes(self):
        canary = {'fixtureSha256': '2'*64, 'referenceSha256': self.definition['referenceSha256'],
                  'locations': 112, 'outputSha256': digest(self.reference.read_bytes()),
                  'records': [base64.b64encode(self.record).decode()]*112}
        raw = json.dumps(canary, ensure_ascii=False, separators=(',', ':')).encode()
        body = {'policyId': 'synthetic-audit-only', 'profileId': self.profile,
                'canarySha256': digest(raw), 'canary': canary}
        result = self.verifier.qualify(body, raw)
        self.assertTrue(result['approved'])
        self.assertEqual(result['canarySha256'], digest(raw))
        for change in ({'profileId': 'f'*64}, {'canarySha256': 'f'*64}, {'policyId': 'wrong'}):
            with self.subTest(change=change), self.assertRaises(audit.VerificationError):
                self.verifier.qualify({**body, **change}, raw)

    def test_native_recomputation_is_required_and_does_not_inherit_candidate_values(self):
        body, raw = self.request()
        with patch.object(native, 'run_native', side_effect=self.fake_native) as run:
            result = self.verifier.audit(body, raw)
        self.assertEqual(result['decision'], 'approved')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_structurally_valid_invented_vectors_are_rejected_by_native_comparison(self):
        wrong = (b'\x00\x3c' + bytes([2])*768)*4
        body, raw = self.request(wrong)
        with patch.object(native, 'run_native', side_effect=self.fake_native):
            self.assertEqual(self.verifier.audit(body, raw)['decision'], 'rejected')

    def test_metadata_and_payload_tampering_duplicate_ids_and_tsv_injection_never_infer(self):
        for kind in ('payload', 'metadata', 'profile', 'duplicate', 'newline'):
            body, raw = self.request()
            if kind == 'payload': body['indexBase64'] = base64.b64encode(self.record[:-1]+b'\x02').decode()
            elif kind == 'metadata': body['records'][0]['lat'] = 20
            elif kind == 'profile': body['profileId'] = 'f'*64
            elif kind == 'duplicate': body['records'].append(body['records'][0])
            elif kind == 'newline': body['records'][0]['assetId'] += '\nprivate-command'
            # Transport-derived metadata is independent of the old fingerprint.
            raw = json.dumps(body['records'], separators=(',', ':')).encode()
            with self.subTest(kind=kind), patch.object(native, 'run_native') as run:
                self.assertEqual(self.verifier.audit(body, raw)['decision'], 'rejected')
                run.assert_not_called()

    def test_zero_norm_candidate_is_rejected_without_native_work(self):
        body, raw = self.request((b'\x00\x3c' + bytes(768))*4)
        with patch.object(native, 'run_native') as run:
            self.assertEqual(self.verifier.audit(body, raw)['decision'], 'rejected')
            run.assert_not_called()

    def test_busy_service_is_retryable_and_never_approves(self):
        body, raw = self.request()
        self.verifier.busy.acquire()
        try:
            with self.assertRaisesRegex(audit.VerificationError, 'scene_auditor_busy'):
                self.verifier.audit(body, raw)
        finally:
            self.verifier.busy.release()

    def test_native_failure_removes_temporaries_keeps_fixed_report_and_recovers(self):
        body, raw = self.request()
        with patch.object(native, 'run_native', side_effect=native.NativeSearchError('native_search_timeout')):
            with self.assertRaises(native.NativeSearchError): self.verifier.audit(body, raw)
        self.assertEqual([p.name for p in self.work.iterdir()], ['first-audit-failure.json'])
        self.assertEqual(json.loads((self.work/'first-audit-failure.json').read_bytes()),
                         {'ready': False, 'error': 'native_audit_unavailable'})
        with patch.object(native, 'run_native', side_effect=self.fake_native):
            self.assertEqual(self.verifier.audit(body, raw)['decision'], 'approved')

    def test_incomplete_mask_source_or_model_cannot_be_approved(self):
        body, raw = self.request()
        for kind in ('mask', 'source', 'model', 'fetch'):
            def broken(command, job, timeout):
                self.fake_native(command, job, timeout)
                if kind == 'mask': (job/'index/shard-000000.mask').write_bytes(b'\x07')
                else:
                    path = job/'checkpoint.json'
                    checkpoint = json.loads(path.read_bytes())
                    checkpoint[{'source': 'sourcePrefixHash', 'model': 'modelIdentity', 'fetch': 'fetchErrors'}[kind]] = 'changed'
                    path.write_bytes(encoded(checkpoint))
            with self.subTest(kind=kind), patch.object(native, 'run_native', side_effect=broken):
                with self.assertRaises(audit.VerificationError): self.verifier.audit(body, raw)

    def test_changed_operator_inputs_never_qualify_or_infer(self):
        body, raw = self.request()
        self.reference.write_bytes(self.reference.read_bytes()[:-1]+b'\x02')
        with patch.object(native, 'run_native') as run, self.assertRaises(audit.VerificationError):
            self.verifier.audit(body, raw)
        run.assert_not_called()

    def test_missing_full_calibration_or_unpinned_helper_cannot_start(self):
        for kind in ('calibration', 'source', 'threshold', 'expiry'):
            document = copy.deepcopy(self.policy)
            if kind == 'calibration': document['profiles'][0]['fullCalibration']['approved'] = False
            elif kind == 'source': document['sourceFiles']['community/native_scene_verifier.py']['sha256'] = 'f'*64
            elif kind == 'threshold': document['auditThresholds']['minimumViewCosine'] = float('inf')
            else: document['profiles'][0]['expiresInSeconds'] = 31*86400
            self.policy_file.write_text(json.dumps(document))
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.start()

    def test_runtime_tampering_and_overlapping_work_are_service_failures(self):
        with self.assertRaisesRegex(audit.VerificationError, 'audit_work_overlaps_input'):
            self.start(work=self.policy_root)
        (self.runtime/'models/text_model.onnx').write_bytes(b'changed')
        with self.assertRaises(native.NativeSearchError): self.start()

    def test_http_authentication_bounds_duplicate_json_and_private_failures(self):
        secret = 'synthetic-private-test-secret-not-real'
        server = audit.make_server(self.verifier, secret)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for body, auth, expected in ((b'{}', '', 401), (b'{"records":[],"records":[]}', 'Bearer '+secret, 503),
                                     (b'[]', 'Bearer '+secret, 400)):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
            connection.request('POST', '/audit', body, {'Content-Type': 'application/json', 'Authorization': auth})
            response = connection.getresponse()
            self.assertEqual(response.status, expected)
            self.assertNotIn(secret.encode(), response.read())
            connection.close()

    def test_fingerprints_preserve_javascript_scientific_spelling_and_unicode(self):
        raw = b'{"other":{},"records":[{"lat":1e-7,"name":"\xe9\x9b\xaa"}],"last":1}'
        native.strict_json(raw)
        self.assertEqual(audit.field_bytes(raw, 'records'), b'[{"lat":1e-7,"name":"\xe9\x9b\xaa"}]')


if __name__ == '__main__':
    unittest.main()
