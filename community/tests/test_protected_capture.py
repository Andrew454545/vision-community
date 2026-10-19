"""Cross-OS recorded capture inspection, with explicitly synthetic provenance."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import tempfile
import unittest
from unittest.mock import patch

from community import protected_capture as capture
from community.protected_origin import SELECTORS
from community.search_snapshot import digest, encoded


class ProtectedCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'handoff.private.json'
        self.now = 1000
        self.timestamp = datetime.fromtimestamp(self.now, timezone.utc).isoformat()
        self.database = '/private/synthetic/MMA/Main'
        self.maps = [{'id': str(i), 'name': name, 'folder': folder, 'locationCount': 1}
            for i, (name, folder) in enumerate([
                (SELECTORS['rootMaps'][0], None), (SELECTORS['rootMaps'][1], None),
                ('synthetic first', SELECTORS['folders'][0]), ('synthetic second', SELECTORS['folders'][1])])]
        self.snapshot = {'schemaVersion': 1, 'database': self.database, 'generatedAt': self.timestamp,
            'sourceMaps': self.maps, 'sourceLocationCount': 4, 'uniqueLocationCount': 1,
            'coordinates': [{'lat': 10.0, 'lng': 20.0}]}
        self.doc = {'version': 1, 'contract': 'vision-origin-protected-mma-handoff-v1',
            'status': 'ORIGIN_PROTECTED_STATE_CAPTURED_NOT_PORTABLE_IMPORT_AUTHORITY',
            'startedAt': self.timestamp, 'completedAt': self.timestamp, 'selectors': SELECTORS,
            'sourceMapCount': 4, 'sourceLocationCount': 4, 'uniqueLocationCount': 1,
            'freshness': {'policy': 'live-origin-files-required-no-offline-relabelling-v1', 'maxAgeMillis': 3600000},
            **{key: False for key in ('objectImportApproved', 'portableImportApproved', 'productionQualified',
                                    'databaseBytesCopied', 'sourceBytesCopied', 'networkUsed')}}
        self.install_paths()
        self.write_snapshot()
        self.save()

    def member(self, path, number, exists=True):
        value = {'path': str(path), 'exists': exists}
        if exists:
            value.update(bytes=10, sha256='a'*64, modifiedUnixMillis=900000,
                         identity=['1', str(number), 10, '900000000000', '900000000001'])
        return value

    def install_paths(self, windows=False):
        main = (PureWindowsPath(r'C:\synthetic\MMA\Main') if windows else PurePosixPath(self.database))
        self.database = str(main)
        self.snapshot['database'] = self.database
        values = [self.member(main, 1), self.member(str(main)+'-wal', 2, False)]
        for i, row in enumerate(self.maps):
            values += [self.member(main.parent/'arrow'/(row['id']+'.arrow'), 3+i),
                       self.member(main.parent/'arrow'/(row['id']+'_delta.arrow'), 100+i, False)]
        self.doc['sourceArtifacts'] = values
        self.doc['exporter'] = self.member(main.parent/'native-exporter', 99)

    def write_snapshot(self, probe=None):
        for key, name, value in [('snapshot', 'protected-snapshot.private.json', self.snapshot),
                                 ('selectionProbe', 'selection-probe.private.json', self.snapshot if probe is None else probe)]:
            raw = encoded(value)
            (self.root/name).write_bytes(raw)
            self.doc[key] = {'file': name, 'bytes': len(raw), 'sha256': digest(raw)}
            if key == 'snapshot':
                self.doc[key]['generatedAt'] = value['generatedAt']

    def save(self):
        raw = encoded(self.doc)
        self.path.write_bytes(raw)
        self.pin = digest(raw)

    def inspect(self, **kwargs):
        return capture.inspect_capture(self.path, self.pin, 'a'*64, now=kwargs.pop('now', self.now), **kwargs)

    def test_mac_capture_can_be_inspected_on_windows_without_source_access_or_approval(self):
        original = {p.name: p.read_bytes() for p in self.root.iterdir()}
        result = self.inspect()
        self.assertTrue(result.reference.contains(10, 20))
        self.assertFalse(result.reference.contains(-10, -20))
        self.assertEqual(result.evidence['sourceArtifactMembers'], 10)
        self.assertFalse(result.evidence['originProofExpired'])
        self.assertTrue(result.evidence['capturePinsValidated'])
        for key in ('verifiedOnOriginalSourceMachine', 'sourceContentHashesVerified', 'portableImportApproved',
                    'objectImportApproved', 'productionQualified'):
            self.assertIs(result.evidence[key], False)
        safe = json.dumps(result.evidence)
        self.assertNotIn(self.database, safe)
        self.assertNotIn(self.maps[2]['name'], safe)
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_windows_capture_paths_are_also_opaque_and_never_remapped(self):
        self.install_paths(windows=True)
        self.write_snapshot()
        self.save()
        self.assertTrue(self.inspect().evidence['capturePinsValidated'])

    def test_expiry_is_preserved_and_never_reset_by_later_inspection(self):
        fresh = self.inspect(now=4599)
        stale = self.inspect(now=4600)
        self.assertFalse(fresh.evidence['originProofExpired'])
        self.assertTrue(stale.evidence['originProofExpired'])
        self.assertEqual(fresh.evidence['originProofExpiresUnixMillis'], stale.evidence['originProofExpiresUnixMillis'])
        self.assertFalse(stale.evidence['portableImportApproved'])
        for invalid in (float('nan'), float('inf'), True, -1, 990):
            with self.subTest(now=invalid), self.assertRaises(ValueError):
                self.inspect(now=invalid)

    def test_independent_manifest_exporter_and_payload_pins_are_mandatory(self):
        with self.assertRaises(ValueError):
            capture.inspect_capture(self.path, 'f'*64, 'a'*64, now=self.now)
        with self.assertRaises(ValueError):
            capture.inspect_capture(self.path, self.pin, 'f'*64, now=self.now)
        for name in ('protected-snapshot.private.json', 'selection-probe.private.json'):
            path = self.root/name
            raw = path.read_bytes()
            path.write_bytes(raw+b' ')
            with self.assertRaises(ValueError):
                self.inspect()
            path.write_bytes(raw)

    def test_snapshot_probe_coordinates_and_selection_must_agree(self):
        for key, value in [('coordinates', [{'lat': 10, 'lng': 21}]),
                           ('sourceMaps', list(reversed(self.maps)))]:
            self.write_snapshot({**self.snapshot, key: value})
            self.save()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.inspect()

    def test_no_omitted_reordered_or_aliased_source_artifacts(self):
        original = copy.deepcopy(self.doc)
        mutations = [lambda d: d['sourceArtifacts'].pop(),
            lambda d: d['sourceArtifacts'].reverse(),
            lambda d: d['sourceArtifacts'][2].update(identity=d['sourceArtifacts'][0]['identity']),
            lambda d: d['sourceArtifacts'][2].update(path=d['sourceArtifacts'][0]['path']),
            lambda d: d['sourceArtifacts'].__setitem__(2, {'path': d['sourceArtifacts'][2]['path'], 'exists': False}),
            lambda d: d['exporter'].update(identity=d['sourceArtifacts'][0]['identity']),
            lambda d: d['sourceArtifacts'][0].update(bytes=True),
            lambda d: d['sourceArtifacts'][0].update(modifiedUnixMillis=1002000),
            lambda d: d['sourceArtifacts'][1].update(bytes=0),
            lambda d: d['sourceArtifacts'][0]['identity'].__setitem__(1, '01')]
        for index, mutation in enumerate(mutations):
            self.doc = copy.deepcopy(original)
            mutation(self.doc)
            self.save()
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.inspect()

    def test_relabelled_authority_future_generation_and_extended_freshness_are_refused(self):
        original = copy.deepcopy(self.doc)
        mutations = [lambda d: d.update(portableImportApproved=True),
            lambda d: d.update(objectImportApproved=True), lambda d: d.update(databaseBytesCopied=True),
            lambda d: d['freshness'].update(maxAgeMillis=86400000),
            lambda d: d.update(sourceMapCount=True), lambda d: d.update(sourceLocationCount=5),
            lambda d: d['snapshot'].update(generatedAt='1970-01-01T00:20:00+00:00'),
            lambda d: d['snapshot'].update(file='../protected-snapshot.private.json')]
        for index, mutation in enumerate(mutations):
            self.doc = copy.deepcopy(original)
            mutation(self.doc)
            self.save()
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.inspect()

    def test_cross_os_paths_refuse_traversal_aliases_device_names_and_unc(self):
        for invalid in ('relative/Main', '/private/../Main', '//private/Main', '/private//Main',
                        '/private/./Main', '/private/nul', r'C:Main', r'C:\private\..\Main',
                        r'C:\private\Main:stream', r'\\server\private\Main', 'C:\\private\\Main.',
                        '/private\\Main'):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                capture.source_path(invalid)

    def test_a_payload_changed_during_inspection_cannot_pass_final_repin(self):
        original = capture.ProtectedReference
        calls = []
        def changed(value, **kwargs):
            result = original(value, **kwargs)
            calls.append(True)
            if len(calls) == 2:
                path = self.root/'protected-snapshot.private.json'
                path.write_bytes(path.read_bytes()+b' ')
            return result
        with patch.object(capture, 'ProtectedReference', side_effect=changed), self.assertRaises(ValueError):
            self.inspect()
        self.assertEqual(len(calls), 2)

    def test_duplicate_keys_are_not_reinterpreted_as_new_capture_authority(self):
        raw = self.path.read_bytes().replace(b'"version":1', b'"version":1,"version":1')
        self.assertNotEqual(raw, self.path.read_bytes())
        self.path.write_bytes(raw)
        self.pin = digest(raw)
        with self.assertRaises(ValueError):
            self.inspect()


if __name__ == '__main__':
    unittest.main()
