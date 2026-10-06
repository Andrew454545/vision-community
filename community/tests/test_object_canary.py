import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from community import object_canary as check


class ObjectCanaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.binary = self.root / ('vision-object.exe' if os.name == 'nt' else 'vision-object')
        self.binary.write_bytes(b'synthetic native binary; never executed')
        for name in check.DLLS:
            (self.root / name).write_bytes(b'synthetic DLL')
        self.models = self.root / 'models'
        self.models.mkdir()
        for name in check.MODELS:
            (self.models / name).write_bytes(b'synthetic model ' + name.encode())
        self.fixture = self.root / 'fixture.json'
        images = []
        for i in range(6):
            path = self.root / f'face-{i}.png'
            # Validation fixture only; no actual image decoding/inference.
            path.write_bytes(b'\x89PNG\r\n\x1a\n\0\0\0\rIHDR' + struct.pack('>II', 640, 640) + bytes([i]))
            images.append(self.pin(path))
        detection = {'classId': 3, 'className': 'car', 'confidence': .6, 'rankingScore': .6,
                     'supportCount': 1, 'x1': .1, 'y1': .2, 'x2': .8, 'y2': .9}
        hot = {'conceptId': 1, 'concept': 'clock', 'confidence': .4,
               'x1': .1, 'y1': .2, 'x2': .8, 'y2': .9}
        self.gold = {'common': [{'width': 640, 'height': 640, 'detections': [copy.deepcopy(detection)]}
                                for _ in range(6)],
                     'hybrid': {'car': [{'width': 640, 'height': 640, 'query': 'car', 'semanticScore': .3,
                                        'semanticBox': [.1, .2, .8, .9], 'hot': [copy.deepcopy(hot)]}
                                       for _ in range(6)]}}
        path = self.root / 'gold.json'
        path.write_text(json.dumps(self.gold), encoding='utf-8')
        self.document = {'version': 1, 'reference': {'sourceRevision': 'a' * 40,
                         'runtimeProfileSha256': 'b' * 64, 'evidenceSha256': 'c' * 64, 'execution': 'cpu'},
                         'modelSha256': {name: check.file_sha256(self.models / name) for name in check.MODELS},
                         'cases': [{'id': 'synthetic-one', 'images': images, 'queries': ['car'],
                                    'reference': self.pin(path)}]}

    def pin(self, path):
        return {'path': path.name, 'bytes': path.stat().st_size, 'sha256': check.file_sha256(path)}

    def save(self):
        self.fixture.write_text(json.dumps(self.document), encoding='utf-8')
        return check.file_sha256(self.fixture)

    def runner(self, argv, env, cwd):
        self.commands.append(argv)
        self.assertEqual({env[key] for key in check.THREAD_ENVIRONMENT_KEYS}, {'1'})
        self.assertNotIn('OBJECT_TEST_SECRET', env)
        self.assertNotIn('HTTP_PROXY', env)
        self.assertIn('--cpu', argv)
        self.assertEqual(Path(argv[0]), self.binary)
        images = [argv[i + 1] for i, value in enumerate(argv) if value == '--image']
        self.assertEqual(len(images), 6)
        rows = copy.deepcopy(self.gold['common'] if argv[1] == 'detect-images' else self.gold['hybrid']['car'])
        for row, image in zip(rows, images):
            row['path'] = image
        if self.change:
            self.change(argv, rows)
        Path(argv[argv.index('--output') + 1]).write_text(json.dumps(rows), encoding='utf-8')

    def run_check(self, change=None):
        self.commands, self.change = [], change
        with patch.dict(os.environ, {'OBJECT_TEST_SECRET': 'private', 'HTTP_PROXY': 'secret proxy'}):
            return check.run_canary(self.root / 'attempt', binary=self.binary, model_dir=self.models,
                                    fixture=self.fixture, fixture_sha256=self.save(), runner=self.runner)

    def test_all_three_lanes_complete_without_account_approval_or_machine_paths(self):
        report = self.run_check()
        self.assertEqual(report['status'], 'COMPLETE')
        self.assertTrue(report['exactReferenceMatch'])
        self.assertEqual([command[1] for command in self.commands], ['detect-images', 'detect-hybrid-images'])
        for key in ('qualified', 'serverAuthorization', 'productionPathVerified', 'coverageAdmissionVerified', 'rawDataUploaded'):
            self.assertFalse(report[key])
        self.assertNotIn('submission', report)
        self.assertNotIn(str(self.root), json.dumps(report))
        portable = (self.root / 'attempt/synthetic-one-hybrid-0-portable.json').read_text()
        self.assertNotIn('path', json.loads(portable)[0])
        self.assertEqual(json.loads((self.root / 'attempt/object-check-report.json').read_text()), report)

    def test_score_and_box_changes_are_measured_and_never_approved(self):
        def change(argv, rows):
            if argv[1] == 'detect-hybrid-images':
                rows[0]['semanticScore'] += .02
                rows[1]['hot'][0]['x1'] += .03
        report = self.run_check(change)
        self.assertEqual(report['status'], 'COMPLETE')
        self.assertFalse(report['exactReferenceMatch'])
        hybrid = report['comparisons'][1]
        self.assertAlmostEqual(hybrid['maximumScoreDifference'], .02)
        self.assertAlmostEqual(hybrid['maximumBoxDifference'], .03)
        self.assertEqual(hybrid['structuralDifferences'], 0)
        self.assertFalse(report['qualified'])

    def test_missing_or_changed_identity_detections_are_not_reported_as_parity(self):
        actual = copy.deepcopy(self.gold['common'])
        actual[0]['detections'] = []
        actual[1]['detections'][0].update(classId=1, className='person')
        result = check.compare_rows(actual, self.gold['common'])
        self.assertFalse(result['exact'])
        self.assertEqual(result['structuralDifferences'], 2)
        self.assertEqual(result['maximumAbsoluteDifference'], 0)
        actual[2]['detections'][0]['confidence'] = float('nan')
        with self.assertRaisesRegex(check.CheckError, 'invalid_detection_number'):
            check.compare_rows(actual, self.gold['common'])

    def test_wrong_view_path_or_query_cannot_be_stripped_to_match_reference(self):
        for change in (lambda rows: rows[0].update(path='another private image'),
                       lambda rows: rows[0].update(query='another query')):
            rows = [{**row, 'path': str(self.root / f'face-{i}.png')}
                    for i, row in enumerate(self.gold['hybrid']['car'])]
            change(rows)
            with self.assertRaises(check.CheckError):
                check.canonical_rows(rows, images=[self.root / f'face-{i}.png' for i in range(6)], query='car')

    def test_bad_fixture_pins_paths_counts_and_model_set_fail_before_native_work(self):
        valid = copy.deepcopy(self.document)
        for change in (lambda d: d['cases'][0]['images'][0].update(path='../outside.png'),
                       lambda d: d['cases'][0]['images'][0].update(bytes=True),
                       lambda d: d['cases'][0]['images'][0].update(sha256='0' * 64),
                       lambda d: d['cases'][0]['images'].pop(),
                       lambda d: d['cases'].append(copy.deepcopy(d['cases'][0])),
                       lambda d: d['modelSha256'].pop(check.MODELS[-1]),
                       lambda d: d['cases'][0]['queries'].append('car')):
            self.document = copy.deepcopy(valid)
            change(self.document)
            with self.assertRaises(check.CheckError):
                check.ObjectFixture(self.fixture, self.save())
        self.document = valid
        digest = self.save()
        with self.assertRaisesRegex(check.CheckError, 'checksum_mismatch'):
            check.ObjectFixture(self.fixture, '0' * 64)
        (self.root / 'face-0.png').write_bytes(b'changed')
        with self.assertRaisesRegex(check.CheckError, 'asset_changed'):
            check.ObjectFixture(self.fixture, digest)

    def test_different_model_or_mid_run_runtime_change_retains_failure_without_approval(self):
        self.document['modelSha256'][check.MODELS[0]] = '0' * 64
        report = self.run_check()
        self.assertEqual(report['status'], 'FAILED')
        self.assertEqual(report['error'], 'object_check_models_differ_from_reference')
        self.assertEqual(self.commands, [])
        # Separate attempt, preserving the first failure instead of overwriting it.
        report_path = self.root / 'attempt/object-check-report.json'
        before = report_path.read_bytes()
        self.document['modelSha256'][check.MODELS[0]] = check.file_sha256(self.models / check.MODELS[0])
        self.fixture.write_text(json.dumps(self.document), encoding='utf-8')
        self.change = lambda argv, rows: self.binary.write_bytes(b'changed after inference')
        report = check.run_canary(self.root / 'second', binary=self.binary, model_dir=self.models,
                                 fixture=self.fixture, fixture_sha256=check.file_sha256(self.fixture), runner=self.runner)
        self.assertEqual(report['status'], 'FAILED')
        self.assertEqual(report['error'], 'object_runtime_changed_during_check')
        self.assertEqual(before, report_path.read_bytes())
        self.assertNotIn('submission', report)

    def test_fixture_changed_after_commands_cannot_leave_a_complete_report(self):
        def change(argv, rows):
            if argv[1] == 'detect-hybrid-images':
                (self.root / 'face-0.png').write_bytes(b'changed during inference')
        report = self.run_check(change)
        self.assertEqual(report['status'], 'FAILED')
        self.assertEqual(report['error'], 'check_asset_changed')

    def test_unknown_exception_is_redacted_and_retry_cannot_overwrite_evidence(self):
        def failure(argv, rows):
            raise RuntimeError('private token or machine path')
        report = self.run_check(failure)
        self.assertEqual(report['error'], 'object_check_failed')
        self.assertNotIn('private token', json.dumps(report))
        before = (self.root / 'attempt/object-check-report.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_check()
        self.assertEqual(before, (self.root / 'attempt/object-check-report.json').read_bytes())

    def test_duplicate_and_overflow_json_numbers_are_rejected(self):
        path = self.root / 'bad.json'
        for raw in ('{"score":1,"score":2}', '{"score":NaN}'):
            path.write_text(raw, encoding='utf-8')
            with self.assertRaises(check.CheckError):
                check.read_json(path)
        rows = copy.deepcopy(self.gold['common'])
        rows[0]['detections'][0]['confidence'] = 1e309
        with self.assertRaises(check.CheckError):
            check.canonical_rows(rows)

    def test_native_runner_requires_shared_pool_and_retains_child_failure_receipt(self):
        def native(argv, **kwargs):
            kwargs['stderr'].write(b'old runtime silently uses unbounded pools\n')
            return type('Process', (), {'returncode': 0})()
        with patch.object(check, 'run_owned', side_effect=native):
            with self.assertRaisesRegex(check.CheckError, 'shared_pool_unconfirmed'):
                check.native_runner(['synthetic'], {}, self.root)
        receipt = json.loads(next(self.root.glob('native-*.exit.json')).read_text())
        self.assertEqual(receipt['status'], 'FAILED')
        self.assertEqual(receipt['timeoutSeconds'], 900)

    def test_windows_dependency_profile_uses_one_canonical_case_per_file(self):
        with patch.object(check.sys, 'platform', 'win32'):
            profile = check.runtime_profile(self.binary, self.models)['profile']
        dependencies = [key for key in profile['assets'] if key.startswith('bin/')]
        self.assertEqual(len(dependencies), len(check.DLLS))
        self.assertTrue(all(key == key.lower() for key in dependencies))

    def test_abrupt_process_exit_keeps_incomplete_receipt_and_finished_lane(self):
        code = '''import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from community import object_canary as check
fixture,binary,models,work=map(Path,sys.argv[2:6])
def native(argv,env,cwd):
    if argv[1]=='detect-hybrid-images':os._exit(73)
    rows=json.loads((fixture.parent/'gold.json').read_bytes())['common']
    images=[argv[i+1] for i,value in enumerate(argv) if value=='--image']
    for row,image in zip(rows,images):row['path']=image
    Path(argv[argv.index('--output')+1]).write_text(json.dumps(rows),encoding='utf-8')
check.run_canary(work,binary=binary,model_dir=models,fixture=fixture,fixture_sha256=sys.argv[6],runner=native)
'''
        digest = self.save()
        child = subprocess.run([sys.executable, '-I', '-B', '-c', code,
                                str(Path(check.__file__).resolve().parents[1]), str(self.fixture),
                                str(self.binary), str(self.models), str(self.root / 'crash'), digest],
                               capture_output=True, timeout=15)
        self.assertEqual(child.returncode, 73, child.stderr.decode(errors='replace'))
        report = json.loads((self.root / 'crash/object-check-report.json').read_text())
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(report['stage'], 'hybrid-0')
        self.assertEqual(report['comparisons'][0]['lane'], 'common')
        self.assertFalse(report['qualified'])
        self.assertFalse(report['serverAuthorization'])
        self.assertNotIn('submission', report)


if __name__ == '__main__':
    unittest.main()
