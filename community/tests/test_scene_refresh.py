import copy
import json
from pathlib import Path
import tempfile
import unittest

from community import scene_refresh as refresh
from community.tests import test_scene_publication_snapshot as fixtures
from community.search_snapshot import cache_file, digest, encoded


class SceneRefreshTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PublicationSnapshotTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture
        self.root = self.f.root / 'refresh'
        self.root.mkdir()
        sealed = self.f.seal('seed')
        authority = self.f.root / 'authority.json'
        template = self.f.root / 'template'
        (template / 'policy').mkdir(parents=True)
        policy = encoded({'version': 1, 'syntheticFixture': True})
        files = {'policy/policy.json': policy, 'policy/canary-reference.i8': self.f.blob,
                 'manifest.json': encoded({'version': 1, 'policySha256': digest(policy),
                    'runtimeSha256': 'd' * 64, 'snapshotSha256': sealed['snapshotSha256']})}
        for name, raw in files.items():
            (template / name).write_bytes(raw)
        self.settings = {'version': 1, 'environment': 'staging', 'resource': self.f.authority['resource'],
            'authority': {'path': str(authority), 'sha256': digest(authority.read_bytes())},
            'runtimeSha256': 'd' * 64, 'searchPolicyId': 'synthetic-runtime', 'reserveNativeStarts': 4,
            'template': {'root': str(template), 'files': {name: digest(raw) for name, raw in files.items()}},
            'seed': {'snapshot': str(self.f.root / 'seed/snapshot'), 'snapshotSha256': sealed['snapshotSha256'],
                     'bundle': {'version': 1, 'sha256': 'a' * 64, 'key': 'native-host/bundles/' + 'a' * 64 + '.zip', 'bytes': 50}}}
        test = self

        class Adapter:
            def __init__(self):
                self.calls = []
                self.head = self.head_for(test.settings['seed'])
                self.budget = {'configured': True, 'requestsRemaining': 48, 'startsRemaining': 12}
                self.lose_activation_reply = False
                self.fail_upload_once = False
                self.mutate_capture_number = None
                self.captures = 0

            def head_for(self, current):
                return {'policyId': test.settings['searchPolicyId'], 'runtimeSha256': test.settings['runtimeSha256'],
                    'snapshotSha256': current['snapshotSha256'], 'bundleSha256': current['bundle']['sha256']}

            def call(self, operation, **values):
                self.calls.append(operation)
                if operation == 'capture':
                    self.captures += 1
                    value = {'inventory': copy.deepcopy(test.f.inventory), 'control': copy.deepcopy(test.f.control)}
                    if self.captures == self.mutate_capture_number:
                        value['inventory']['rows'][-1]['heading'] += 1
                    return value
                if operation == 'artifact':
                    Path(values['destination']).write_bytes(cache_file(test.f.cache, values['key']).read_bytes())
                    return {}
                if operation == 'head':
                    return {'httpStatus': 200, 'body': copy.deepcopy(self.head)}
                if operation == 'status':
                    return {'httpStatus': 200, 'body': {'computeBudget': dict(self.budget)}}
                if operation == 'upload':
                    if self.fail_upload_once:
                        self.fail_upload_once = False
                        raise refresh.AdapterUnavailable('synthetic upload outage')
                    assert refresh.bundle_descriptor(values['archive']) == values['descriptor']
                    return {'uploaded': True}
                if operation == 'activate':
                    request = values['request']
                    if self.head['bundleSha256'] != request['expectedBundleSha256']:
                        return {'httpStatus': 409, 'body': {'error': 'operator_bundle_changed'}}
                    self.head = {**request['search'], 'bundleSha256': request['bundle']['sha256']}
                    if self.lose_activation_reply:
                        self.lose_activation_reply = False
                        raise refresh.AdapterUnavailable('synthetic lost response')
                    return {'httpStatus': 200, 'body': {**self.head, 'refreshed': True}}
                raise AssertionError(operation)
        self.adapter = Adapter()

    def append(self):
        row = copy.deepcopy(self.f.inventory['rows'][0])
        row.update(id=2, asset_id='synthetic-second', lat=3)
        lease = 'e' * 32
        key = 'four-view-v4/' + lease + '.i8'
        blob = (b'\0\x3c' + b'\x08' * 768) * 4
        cache_file(self.f.cache, key).write_bytes(blob)
        row.update(output_sha256=digest(blob), location_output_sha256=digest(blob), four_view_sha256=digest(blob), four_view_key=key)
        self.f.inventory['rows'].append(row)
        record = json.loads(self.f.control['candidates'][0]['records_json'])[0]
        record.update(locationId=2, assetId='synthetic-second', lat=3, outputSha256=digest(blob))
        records = json.dumps([record], separators=(',', ':'))
        submission = digest(records.encode() + b'\n' + blob)
        candidate = {**self.f.control['candidates'][0], 'lease_id': lease, 'records_json': records,
                     'submission_sha256': submission, 'artifact_key': 'scene-quarantine/' + lease + '/' + submission + '.i8'}
        self.f.control['candidates'].append(candidate)
        self.f.control['ledger'].append({**self.f.control['ledger'][0], 'reference': 'lease:' + lease})

    def run_once(self, name='run'):
        return refresh.SceneRefresher(self.root, self.settings, self.adapter).once(self.root / name)

    def test_unchanged_real_membership_never_spends_native_work_or_changes_pointer(self):
        result = self.run_once()
        self.assertEqual(result['status'], 'CURRENT_NO_CHANGE')
        self.assertNotIn('activate', self.adapter.calls)
        self.assertNotIn('upload', self.adapter.calls)
        self.assertNotIn('status', self.adapter.calls)

    def test_new_earned_native_publication_is_appended_and_activated_once(self):
        self.append()
        control = copy.deepcopy(self.f.control)
        result = self.run_once()
        self.assertEqual(result['status'], 'NATIVE_AUDITED_SCENE_REFRESHED')
        self.assertEqual(result['locations'], 2)
        state = json.loads((self.root / 'state.private.json').read_bytes())
        self.assertIsNone(state['pending'])
        self.assertEqual(state['current']['snapshotSha256'], self.adapter.head['snapshotSha256'])
        self.assertEqual(self.adapter.calls.count('activate'), 1)
        self.assertEqual(self.f.control, control)
        self.assertEqual(self.run_once('repeat')['status'], 'CURRENT_NO_CHANGE')
        self.assertEqual(self.adapter.calls.count('activate'), 1)

    def test_lost_activation_reply_recovers_without_reactivation_or_duplicate_work(self):
        self.append(); self.adapter.lose_activation_reply = True
        self.assertEqual(self.run_once()['status'], 'DEFERRED_ADAPTER_UNAVAILABLE')
        self.assertEqual(self.adapter.calls.count('activate'), 1)
        self.assertEqual(self.run_once('restarted')['status'], 'NATIVE_AUDITED_SCENE_REFRESHED')
        self.assertEqual(self.adapter.calls.count('activate'), 1)
        self.assertTrue((self.root / 'run/failure-report.json').is_file())

    def test_upload_outage_preserves_a_prepared_operation_across_restart(self):
        self.append(); self.adapter.fail_upload_once = True
        self.assertEqual(self.run_once()['status'], 'DEFERRED_ADAPTER_UNAVAILABLE')
        pending = json.loads((self.root / 'state.private.json').read_bytes())['pending']
        self.assertTrue(Path(pending['archive']).is_file())
        self.assertEqual(self.run_once('resume')['status'], 'NATIVE_AUDITED_SCENE_REFRESHED')
        self.assertEqual(self.adapter.calls.count('activate'), 1)

    def test_lost_reply_recovers_even_if_later_work_has_arrived(self):
        self.append(); self.adapter.lose_activation_reply = True
        self.assertEqual(self.run_once()['status'], 'DEFERRED_ADAPTER_UNAVAILABLE')
        self.adapter.mutate_capture_number = self.adapter.captures + 1
        self.assertEqual(self.run_once('acknowledgement')['status'], 'NATIVE_AUDITED_SCENE_REFRESHED')
        self.assertEqual(self.adapter.calls.count('activate'), 1)
        self.assertIsNone(json.loads((self.root / 'state.private.json').read_bytes())['pending'])

    def test_corrupt_seed_descriptor_fails_before_using_any_remote_binding(self):
        self.settings['seed']['bundle']['bytes'] = True
        with self.assertRaisesRegex(refresh.RefreshError, 'invalid_refresh_state'):
            self.run_once()
        self.assertEqual(self.adapter.calls, [])

    def test_small_remaining_native_allowance_is_reserved_for_contributor_work(self):
        self.append(); self.adapter.budget['startsRemaining'] = 4
        self.assertEqual(self.run_once()['status'], 'DEFERRED_NATIVE_ALLOWANCE')
        self.assertNotIn('upload', self.adapter.calls)
        self.assertNotIn('activate', self.adapter.calls)
        self.adapter.budget['startsRemaining'] = 12
        self.assertEqual(self.run_once('next-day')['status'], 'NATIVE_AUDITED_SCENE_REFRESHED')

    def test_pointer_replacement_by_another_operator_cannot_be_overwritten(self):
        self.append(); self.adapter.head['bundleSha256'] = 'f' * 64
        with self.assertRaisesRegex(refresh.RefreshError, 'refresh_active_pointer_changed'):
            self.run_once()
        self.assertNotIn('upload', self.adapter.calls)
        self.assertNotIn('activate', self.adapter.calls)

    def test_membership_change_before_upload_retries_without_activation(self):
        self.append(); self.adapter.mutate_capture_number = 2
        self.assertEqual(self.run_once()['status'], 'SOURCE_CHANGED_RETRY')
        self.assertNotIn('upload', self.adapter.calls)
        self.assertNotIn('activate', self.adapter.calls)
        self.assertIsNone(json.loads((self.root / 'state.private.json').read_bytes())['pending'])

    def test_membership_change_after_upload_still_cannot_activate_stale_work(self):
        self.append(); self.adapter.mutate_capture_number = 3
        self.assertEqual(self.run_once()['status'], 'SOURCE_CHANGED_RETRY')
        self.assertIn('upload', self.adapter.calls)
        self.assertNotIn('activate', self.adapter.calls)

    def test_changed_prepared_archive_is_refused_after_restart(self):
        self.append(); self.adapter.budget['startsRemaining'] = 4
        self.run_once()
        pending = json.loads((self.root / 'state.private.json').read_bytes())['pending']
        Path(pending['archive']).write_bytes(b'changed-private-fixture')
        with self.assertRaisesRegex(refresh.RefreshError, 'refresh_prepared_bytes_changed'):
            self.run_once('restart')
        self.assertNotIn('activate', self.adapter.calls)

    def test_tampered_native_bytes_cannot_become_searchable(self):
        self.append()
        cache_file(self.f.cache, 'four-view-v4/' + 'e'*32 + '.i8').write_bytes(b'\0' * 3080)
        with self.assertRaises(Exception):
            self.run_once()
        self.assertNotIn('activate', self.adapter.calls)
        self.assertTrue((self.root / 'run/failure-report.json').is_file())

    def test_zip_metadata_is_deterministic_and_template_pins_are_required(self):
        seed = self.settings['seed']
        first = refresh.pack_bundle(self.settings['template'], seed['snapshot'], seed['snapshotSha256'], self.root / 'first.zip')
        second = refresh.pack_bundle(self.settings['template'], seed['snapshot'], seed['snapshotSha256'], self.root / 'second.zip')
        self.assertEqual(first, second)
        (Path(self.settings['template']['root']) / 'policy/policy.json').write_bytes(b'changed')
        with self.assertRaises(Exception):
            refresh.pack_bundle(self.settings['template'], seed['snapshot'], seed['snapshotSha256'], self.root / 'changed.zip')

    def test_only_confirmed_staging_resources_are_implemented(self):
        self.settings['environment'] = 'production'
        with self.assertRaisesRegex(refresh.RefreshError, 'unconfirmed_refresh_resources'):
            self.run_once()

    def test_canonical_export_order_cannot_cause_refresh_churn(self):
        self.append()
        value = {'inventory': self.f.inventory, 'control': self.f.control}
        first = refresh.canonical_capture(copy.deepcopy(value), self.settings['resource'])
        value['inventory']['rows'].reverse(); value['control']['candidates'].reverse(); value['control']['ledger'].reverse()
        second = refresh.canonical_capture(value, self.settings['resource'])
        self.assertEqual(refresh.capture_pin(first), refresh.capture_pin(second))
