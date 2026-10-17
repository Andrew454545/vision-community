"""Release-pinned canary refreshes do not mutate or weaken historical checks."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from community import pc_canary as canary


class ReleasedCanaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = (canary.FIXTURE / 'canary-112.tsv').read_bytes()
        self.reference, _ = canary.canary_reference()
        (self.root / 'fixture.tsv').write_bytes(self.fixture)
        (self.root / 'reference.i8').write_bytes(self.reference)
        self.document = {'version': 2, 'policyId': 'synthetic-released-canary-test',
            'runtimeProfileSha256': 'a' * 64,
            'fixtureSha256': hashlib.sha256(self.fixture).hexdigest(),
            'referenceSha256': hashlib.sha256(self.reference).hexdigest(),
            'fullCalibration': {'approved': True, 'locations': 1024, 'repetitions': 3, 'evidenceSha256': 'd' * 64},
            'thresholds': {'minimumViewCosine': .9999, 'maximumViewRelativeL2': .02},
            'dataset': {'fixture': {'path': 'fixture.tsv', 'bytes': len(self.fixture), 'sha256': canary.sha(self.root/'fixture.tsv')},
                        'reference': {'path': 'reference.i8', 'bytes': len(self.reference), 'sha256': canary.sha(self.root/'reference.i8')},
                        'parentReferenceSha256': 'f' * 64}}

    def load(self):
        path = self.root / 'release-policy.json'
        path.write_text(json.dumps(self.document), encoding='utf-8')
        return canary.CanaryPolicy.load(path, canary.sha(path))

    def test_loaded_dataset_keeps_its_independent_pins_and_historical_reference_unchanged(self):
        historical = canary.canary_reference()
        policy = self.load()
        values = policy.pinned_inputs()
        self.assertEqual(values, {'fixtureBytes': self.fixture, 'referenceBytes': self.reference})
        reference, identity = canary.canary_reference(policy)
        self.assertEqual(reference, self.reference)
        self.assertEqual(identity['parentReferenceSha256'], 'f' * 64)
        self.assertEqual(canary.canary_reference(), historical)

    def test_unloaded_operator_definition_cannot_select_local_dataset_paths(self):
        policy = canary.CanaryPolicy(self.document)
        with self.assertRaisesRegex(ValueError, 'pinned_policy_load'):
            policy.pinned_inputs()

    def test_paths_sizes_and_top_level_hashes_must_match_trusted_dataset(self):
        for name in ('fixture', 'reference'):
            for key, bad in (('path', '../outside'), ('path', 'C:/outside'), ('path', '/outside'),
                             ('path', 'sub\\outside'), ('bytes', True), ('bytes', 1024**2), ('sha256', '0'*64)):
                changed = copy.deepcopy(self.document)
                changed['dataset'][name][key] = bad
                with self.subTest(name=name, key=key, bad=bad), self.assertRaisesRegex(ValueError, 'invalid_canary_dataset'):
                    canary.CanaryPolicy(changed)
        for version in (True, '2', 4):
            with self.assertRaisesRegex(ValueError, 'invalid_canary_policy'):
                canary.CanaryPolicy({**self.document, 'version': version})

    def test_changed_source_bytes_and_wrong_reference_length_are_rejected(self):
        policy = self.load()
        path = self.root / 'fixture.tsv'
        path.write_bytes(b'X' + self.fixture[1:])
        with self.assertRaisesRegex(ValueError, 'checksum_mismatch'):
            policy.pinned_inputs()
        path.write_bytes(self.fixture)
        (self.root / 'reference.i8').write_bytes(self.reference[:-1])
        with self.assertRaisesRegex(ValueError, 'size_mismatch'):
            policy.pinned_inputs()

    def test_repeated_panorama_or_invalid_record_cannot_inflate_readiness(self):
        bad = self.fixture.splitlines(keepends=True)[0] * 112
        (self.root / 'fixture.tsv').write_bytes(bad)
        self.document['fixtureSha256'] = canary.sha(self.root/'fixture.tsv')
        self.document['dataset']['fixture'].update(bytes=len(bad), sha256=self.document['fixtureSha256'])
        with self.assertRaisesRegex(ValueError, 'dataset_geometry'):
            self.load().pinned_inputs()
        (self.root / 'fixture.tsv').write_bytes(self.fixture)
        self.document['fixtureSha256'] = canary.sha(self.root/'fixture.tsv')
        self.document['dataset']['fixture'].update(bytes=len(self.fixture), sha256=self.document['fixtureSha256'])
        bad = b'\0' * len(self.reference)
        (self.root/'reference.i8').write_bytes(bad)
        self.document['referenceSha256'] = canary.sha(self.root/'reference.i8')
        self.document['dataset']['reference']['sha256'] = self.document['referenceSha256']
        with self.assertRaisesRegex(ValueError, 'invalid_view_scale'):
            self.load().pinned_inputs()

    def run_check(self, policy, change=None):
        def indexer(source, **kwargs):
            self.assertEqual(source.parent, self.root/'attempt')
            self.assertEqual(source.read_bytes(), self.fixture)
            kwargs['index_dir'].mkdir()
            (kwargs['index_dir']/'shard-000000.i8').write_bytes(self.reference)
            if change is not None:
                change(source)
        profile = {'sha256':'a'*64, 'profile':{'synthetic':True}}
        with patch.object(canary, 'runtime_profile', return_value=profile), \
             patch.object(canary, 'require_complete_index'):
            return canary.run_canary(self.root/'attempt', binary=Path('synthetic'), model_dir=Path('synthetic'),
                policy=policy, indexer=indexer)

    def test_private_pinned_copy_qualifies_locally_without_server_authorization(self):
        result = self.run_check(self.load())
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertTrue(result['qualified'])
        self.assertEqual(result['decision'], 'LOCAL_CANARY_PASSED')
        self.assertFalse(result['serverAuthorization'])
        self.assertEqual(result['inputIdentity'], 'SOURCE_PIXELS_NOT_FROZEN')
        self.assertEqual(result['reference'], 'RELEASE_PINNED_REFERENCE_LIVE_SOURCE_PIXELS')
        self.assertEqual(result['submission']['canary']['fixtureSha256'], self.document['fixtureSha256'])
        self.assertEqual(len(result['submission']['canary']['records']),112)

    def test_release_source_changed_during_indexing_cannot_leave_approval_or_packet(self):
        def change(_source):
            (self.root/'fixture.tsv').write_bytes(b'X'+self.fixture[1:])
        result = self.run_check(self.load(), change)
        self.assertEqual(result['status'],'FAILED')
        self.assertFalse(result['qualified'])
        self.assertNotIn('submission',result)
        self.assertIn('checksum_mismatch',result['error'])

    def test_private_copy_changed_during_indexing_cannot_leave_approval_or_packet(self):
        result = self.run_check(self.load(), lambda source: source.write_bytes(b'X'+self.fixture[1:]))
        self.assertEqual(result['status'],'FAILED')
        self.assertFalse(result['qualified'])
        self.assertNotIn('submission',result)
        self.assertEqual(result['error'],'canary_dataset_changed_during_check')

    def test_reparse_point_is_rejected_before_any_dataset_bytes_are_read(self):
        policy = self.load()
        original = Path.lstat
        def reparse(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path.name != 'fixture.tsv':
                return value
            class Linked:
                st_mode = value.st_mode
                st_file_attributes = 0x400
            return Linked()
        with patch.object(Path,'lstat',reparse):
            with self.assertRaisesRegex(ValueError,'linked_canary_dataset'):
                policy.pinned_inputs()

    def release_manifest(self):
        policy = self.load()
        files = [{'asset': 'mma-vision-test', 'path': 'bin/mma-vision.exe',
                  'bytes': 1, 'sha256': '0'*64, 'executable': True}]
        for name in ('release-policy.json', 'fixture.tsv', 'reference.i8'):
            path = self.root/name
            files.append({'asset': 'pc-check-'+name, 'path': name,
                          'bytes': path.stat().st_size, 'sha256': canary.sha(path)})
        return policy, {'files': files, 'pcCanaryPolicy': {
            'path': 'release-policy.json', 'sha256': canary.sha(self.root/'release-policy.json')}}

    def test_release_manifest_pins_all_three_assets_and_keeps_old_releases_compatible(self):
        policy, manifest = self.release_manifest()
        loaded = canary.released_canary_policy(manifest, self.root)
        self.assertEqual(loaded.document, policy.document)
        self.assertEqual(loaded.pinned_inputs(), policy.pinned_inputs())
        self.assertIsNone(canary.released_canary_policy({'files': []}, self.root/'absent'))

    def test_unpinned_or_duplicate_release_assets_cannot_supply_pc_check_inputs(self):
        _, manifest = self.release_manifest()
        for name in ('release-policy.json', 'fixture.tsv', 'reference.i8'):
            entry = next(v for v in manifest['files'] if v['path'] == name)
            for mode in ('missing', 'duplicate', 'hash', 'size', 'executable'):
                changed = copy.deepcopy(manifest)
                if mode == 'missing':
                    changed['files'] = [v for v in changed['files'] if v['path'] != name]
                elif mode == 'duplicate':
                    changed['files'].append(copy.deepcopy(entry))
                else:
                    target = next(v for v in changed['files'] if v['path'] == name)
                    target[{'hash':'sha256','size':'bytes','executable':'executable'}[mode]] = {
                        'hash':'0'*64,'size':entry['bytes']+1,'executable':True}[mode]
                with self.subTest(name=name, mode=mode), self.assertRaises(ValueError):
                    canary.released_canary_policy(changed, self.root)

    def test_release_selector_must_be_a_safe_independently_pinned_policy(self):
        _, manifest = self.release_manifest()
        for bad in (None, {'path':'../release-policy.json','sha256':'0'*64},
                    {'path':'release-policy.json','sha256':'not-a-pin'},
                    {'path':'release-policy.json','sha256':'0'*64,'url':'https://untrusted.test'}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError,'invalid_release_canary_policy'):
                canary.released_canary_policy({**manifest,'pcCanaryPolicy':bad},self.root)

    def test_linked_policy_parent_is_rejected_before_policy_read(self):
        _, manifest = self.release_manifest()
        original = Path.lstat
        def reparse(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path != self.root:
                return value
            class Linked:
                st_mode = value.st_mode
                st_file_attributes = 0x400
            return Linked()
        with patch.object(Path,'lstat',reparse), patch.object(canary.CanaryPolicy,'load') as read:
            with self.assertRaisesRegex(ValueError,'linked_canary_policy'):
                canary.released_canary_policy(manifest,self.root)
            read.assert_not_called()

    def test_manifest_cannot_refresh_with_a_legacy_implicit_dataset(self):
        self.document['version'] = 1
        self.document.pop('dataset')
        _, manifest = self.release_manifest()
        with self.assertRaisesRegex(ValueError,'release_canary_dataset_required'):
            canary.released_canary_policy(manifest,self.root)

    def test_guided_pc_check_uses_release_policy_and_still_asks_server_for_approval(self):
        from community.desktop import DesktopApp
        policy, manifest = self.release_manifest()
        calls = []
        def check(*args, **kwargs):
            calls.append(kwargs)
            return {'status':'COMPLETE','runtimeProfile':{'sha256':'a'*64},'submission':{'pinnedFixture':True}}
        def request(method, url, body):
            calls.append((method,url,body))
            return 200, {'qualified':True,'profileId':'a'*64,'expiresAt':time.time()+3600}, None
        app = DesktopApp(self.root/'desktop',canary=check,profile_matches=lambda *a,**k:True)
        app.client = SimpleNamespace(request=request,profile_id=None)
        with patch.object(app,'capabilities'), patch('community.desktop.load_manifest',return_value=manifest), \
             patch('community.desktop.released_canary_policy',return_value=policy) as selector:
            app.qualify()
        from community.bootstrap import runtime_platform
        selector.assert_called_once_with(manifest,app.root/'runtime',platform_name=runtime_platform())
        self.assertIs(calls[0]['policy'],policy)
        self.assertEqual(calls[1],('POST','/api/scene-qualifications',{'pinnedFixture':True}))
        self.assertTrue(app.snapshot()['qualified'])

    def test_legacy_windows_policy_never_selects_mac_assets_or_approval(self):
        _,manifest=self.release_manifest()
        with patch.object(canary,'files_for_platform') as select:
            self.assertIsNone(canary.released_canary_policy(manifest,self.root,platform_name='darwin-arm64'))
            select.assert_not_called()

    def test_platform_map_uses_mac_files_and_retains_independent_policy_pins(self):
        _,manifest=self.release_manifest()
        entry=manifest.pop('pcCanaryPolicy')
        manifest['pcCanaryPolicies']={'darwin-arm64':entry,'windows-x86_64':{'path':'unread-windows.json','sha256':'0'*64}}
        manifest['files'][0].update(asset='mma-vision-mac-test',path='bin/mma-vision',platforms=['darwin-arm64'])
        loaded=canary.released_canary_policy(manifest,self.root,platform_name='darwin-arm64')
        self.assertEqual(loaded.document,self.document)
        manifest['pcCanaryPolicies']['darwin-arm64']['sha256']='0'*64
        with self.assertRaises(ValueError):canary.released_canary_policy(manifest,self.root,platform_name='darwin-arm64')

    def test_ambiguous_empty_or_unknown_platform_policy_maps_are_rejected(self):
        _,manifest=self.release_manifest();entry=manifest.pop('pcCanaryPolicy')
        for value in ({},[],{'unknown':entry},{'darwin-arm64':None}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                canary.released_canary_policy({**manifest,'pcCanaryPolicies':value},self.root,platform_name='darwin-arm64')
        with self.assertRaises(ValueError):
            canary.released_canary_policy({**manifest,'pcCanaryPolicies':{'darwin-arm64':entry},'pcCanaryPolicy':entry},self.root)

    def test_absent_platform_policy_is_diagnostic_without_fallback(self):
        _,manifest=self.release_manifest();entry=manifest.pop('pcCanaryPolicy')
        with patch.object(canary,'files_for_platform') as select:
            self.assertIsNone(canary.released_canary_policy({**manifest,'pcCanaryPolicies':{'windows-x86_64':entry}},
                self.root,platform_name='darwin-arm64'))
            select.assert_not_called()

    def test_broken_release_policy_stops_before_native_execution_and_submission(self):
        from community.desktop import DesktopApp, DesktopError
        app = DesktopApp(self.root/'desktop')
        app.client = SimpleNamespace(request=None)
        with patch.object(app,'capabilities'), patch.object(app,'canary') as execute, \
             patch('community.desktop.released_canary_policy',side_effect=ValueError('invalid_release_canary_policy')):
            with self.assertRaisesRegex(DesktopError,'pc_check_files_invalid'):
                app.qualify()
        execute.assert_not_called()
        self.assertFalse(app.snapshot()['qualified'])


if __name__ == '__main__':
    unittest.main()
