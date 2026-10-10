import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from calibration import mac_object_reference as reference


class MacObjectReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_real_manifest_is_pinned_and_contains_only_the_twelve_mac_object_assets(self):
        document, entries = reference.selected_assets(reference.bootstrap.manifest_path())
        self.assertEqual(len(entries), 12)
        self.assertEqual(sum(bool(item.get('executable')) for item in entries), 1)
        self.assertFalse(any('siglip' in item['asset'] or 'windows' in item['asset'] for item in entries))
        altered = self.root / 'manifest.json'
        altered.write_text(json.dumps(document) + ' ', encoding='utf-8')
        with self.assertRaisesRegex(reference.check.CheckError, 'manifest_pin_changed'):
            reference.selected_assets(altered)

    def test_inventory_detects_replaced_model_and_does_not_trust_a_declared_checksum(self):
        path = self.root / 'model.onnx'
        path.write_bytes(b'original')
        entries = [{'path': path.name, 'bytes': path.stat().st_size, 'sha256': reference.check.file_sha256(path)}]
        self.assertEqual(reference.inventory(self.root, entries)[path.name]['sha256'], entries[0]['sha256'])
        path.write_bytes(b'replaced')
        with self.assertRaisesRegex(reference.check.CheckError, 'runtime_pin_changed'):
            reference.inventory(self.root, entries)

    def exercise(self, fail=False, tamper=False):
        names = ['object-runtime/vision-object', *('models/object-hybrid-v1/' + name for name in reference.check.MODELS)]
        entries = [{'path': name, 'bytes': 4, 'sha256': hashlib.sha256(b'test').hexdigest()} for name in names]
        calls = []
        def install(document, root, **options):
            for entry in entries:
                target = root / entry['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'test')
        def run(argv, *, env, cwd, stdout, stderr, timeout):
            calls.append(argv)
            self.assertEqual(timeout, 900)
            self.assertNotIn('GITHUB_TOKEN', env)
            if argv[1] == 'fetch-views':
                views = Path(argv[argv.index('--output-dir') + 1])
                views.mkdir()
                for i in range(6):
                    (views / (str(i) + '.png')).write_bytes(b'\x89PNG\r\n\x1a\n' + b'\0' * 4 + b'IHDR' + (640).to_bytes(4, 'big') * 2)
            else:
                if fail and argv[1] == 'detect-hybrid-images':
                    return SimpleNamespace(returncode=7)
                query = argv[argv.index('--query') + 1] if '--query' in argv else None
                rows = []
                for i, value in enumerate(argv):
                    if value != '--image':
                        continue
                    row = {'path': argv[i + 1], 'width': 640, 'height': 640}
                    if query is None:
                        row['detections'] = [{'classId': 3, 'className': 'car', 'confidence': .4, 'rankingScore': .4,
                            'supportCount': 1, 'x1': .1, 'y1': .2, 'x2': .3, 'y2': .4}]
                    else:
                        row.update(query=query, semanticScore=.2, semanticBox=[.1, .2, .3, .4], hot=[])
                    rows.append(row)
                Path(argv[argv.index('--output') + 1]).write_text(json.dumps(rows), encoding='utf-8')
                if tamper:
                    (Path(cwd) / 'runtime/models/object-hybrid-v1/object-model.json').write_bytes(b'bad!')
            return SimpleNamespace(returncode=0)
        with patch.object(reference.sys, 'platform', 'darwin'), \
                patch.object(reference.bootstrap, 'runtime_platform', return_value='darwin-arm64'), \
                patch.object(reference, 'selected_assets', return_value=({}, entries)):
            report = reference.collect(self.root / 'attempt', runner=run, installer=install)
        return report, calls

    def test_complete_portable_values_remain_unqualified_and_pool_request_is_not_attestation(self):
        report, calls = self.exercise()
        self.assertEqual(report['status'], 'COMPLETE_UNQUALIFIED')
        self.assertEqual(len(calls), 13)
        self.assertEqual(len(report['repeatComparisons']), 6)
        self.assertEqual(len(report['comparisons']), 3)
        self.assertTrue(report['withinProfileExact'])
        self.assertFalse(report['productionQualified'])
        self.assertFalse(report['referenceIsAndrewInstalledGold'])
        self.assertFalse(report['sharedCpuThreadBudgetVerified'])
        self.assertEqual(report['actualProviderPlacement'], 'NOT_ATTESTED')
        files = list((self.root / 'attempt/export').iterdir())
        self.assertEqual(len(files), 13)
        self.assertNotIn(str(self.root), ''.join(path.read_text() for path in files))
        self.assertTrue(all(path.suffix == '.json' for path in files))
        for command in report['commands'][1:]:
            pin = command['portable']
            target = self.root / 'attempt/export' / pin['path']
            self.assertEqual(reference.check.file_sha256(target), pin['sha256'])
            self.assertEqual(target.stat().st_size, pin['bytes'])
        for argv in calls[1:]:
            self.assertEqual('--cpu' in argv, 'coreml-requested' not in str(argv))

    def test_native_failure_preserves_finished_common_values_and_no_complete_claim(self):
        report, calls = self.exercise(fail=True)
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(report['commands'][-1]['exitCode'], 7)
        self.assertEqual(report['failure']['code'], 'native_command_failed')
        self.assertEqual(len(report['repeatComparisons']), 1)
        self.assertEqual(len(list((self.root / 'attempt/export').iterdir())), 3)
        self.assertFalse(report['productionQualified'])

    def test_changed_model_at_recheck_cannot_become_complete(self):
        report, calls = self.exercise(tamper=True)
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(report['failure']['code'], 'runtime_pin_changed')
        self.assertFalse(report['productionQualified'])

    def test_retry_cannot_overwrite_failure(self):
        out = self.root / 'attempt'
        out.mkdir()
        (out / 'prior').write_text('original')
        with self.assertRaises(FileExistsError):
            reference.collect(out)
        self.assertEqual((out / 'prior').read_text(), 'original')

    def test_non_mac_fails_before_downloading_or_running(self):
        with patch.object(reference.sys, 'platform', 'win32'), \
                patch.object(reference.bootstrap, 'install_runtime') as installer, \
                patch.object(reference.check, 'run_owned') as native:
            report = reference.collect(self.root / 'attempt')
        installer.assert_not_called()
        native.assert_not_called()
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(report['failure']['code'], 'requires_apple_silicon_mac')
