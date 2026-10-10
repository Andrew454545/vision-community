import copy
import json
from pathlib import Path
import tempfile
import unittest

from community.scene_publication_snapshot import PublicationSnapshotError, seal_publications
from community.search_snapshot import (CONFIRMED_STAGING_RESOURCE, SnapshotError, cache_file,
                                       digest, encoded, verify_snapshot)


class PublicationSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.lease = 'b' * 32
        self.owner = 'private-fixture-owner'
        self.profile = 'c' * 64
        self.key = 'four-view-v4/' + self.lease + '.i8'
        self.blob = (b'\0\x3c' + b'\x07' * 768) * 4
        cache_file(self.cache, self.key).write_bytes(self.blob)
        row = {'id': 1, 'asset_id': 'synthetic-pano', 'capture': '2026-09', 'lane': 'scene',
               'model': 'input-model', 'state': 'published', 'contributor_id': self.owner,
               'lat': 1, 'lon': 2, 'heading': 90, 'pitch': 0, 'zoom': 0, 'country': 'Italy',
               'camera_generation': 'gen4', 'output_sha256': digest(self.blob),
               'location_output_sha256': digest(self.blob), 'four_view_sha256': digest(self.blob),
               'four_view_key': self.key}
        record = {'locationId': 1, 'assetId': 'synthetic-pano', 'capture': '2026-09', 'inputModel': 'input-model',
                  'lat': 1, 'lng': 2, 'heading': 90, 'pitch': 0, 'zoom': 0, 'country': 'Italy',
                  'cameraGeneration': 'gen4', 'outputSha256': digest(self.blob)}
        records = json.dumps([record], separators=(',', ':'))
        submission = digest(records.encode() + b'\n' + self.blob)
        base = {'version': 1, 'resource': CONFIRMED_STAGING_RESOURCE}
        self.inventory = {**base, 'rows': [row]}
        self.control = {**base, 'candidates': [{'lease_id': self.lease, 'account_id': self.owner,
            'qualification_id': 'qualified', 'policy_id': 'staging.native-fixture', 'created_at': 100,
            'state': 'published', 'records_json': records, 'submission_sha256': submission,
            'artifact_key': 'scene-quarantine/' + self.lease + '/' + submission + '.i8'}],
            'qualifications': [{'id': 'qualified', 'account_id': self.owner, 'policy_id': 'staging.native-fixture',
                                'profile_id': self.profile, 'created_at': 90, 'expires_at': 101}],
            'accounts': [{'id': self.owner, 'deleted_at': None}],
            'ledger': [{'reference': 'lease:' + self.lease, 'account_id': self.owner,
                        'reason': 'verified_work', 'units': 1}]}
        self.authority = {**base, 'scope': 'native-audited-community-scene-publications',
                          'productionApproved': False, 'inputModel': 'input-model',
                          'snapshotPolicyId': 'staging.snapshot-fixture',
                          'policies': [{'policyId': 'staging.native-fixture', 'profileIds': [self.profile],
                                        'runtimeSha256': 'd' * 64}]}

    def seal(self, name='result', **options):
        args = []
        for name_part in ('inventory', 'control', 'authority'):
            path = self.root / (name_part + '.json')
            raw = encoded(getattr(self, name_part))
            path.write_bytes(raw)
            args.extend([path, digest(raw)])
        return seal_publications(*args, self.cache, self.root / name, environment='staging', **options)

    def fails(self, code):
        with self.assertRaisesRegex((PublicationSnapshotError, SnapshotError), code):
            self.seal()
        self.assertFalse((self.root / 'result/snapshot/snapshot.json').exists())
        failure = (self.root / 'result/failure-report.json').read_text()
        self.assertNotIn(self.owner, failure)
        self.assertEqual(json.loads(failure), {'sealed': False, 'error': code})

    def test_seals_audited_earned_work_without_handwritten_output_approvals(self):
        result = self.seal()
        snapshot = self.root / 'result/snapshot'
        self.assertEqual(verify_snapshot(snapshot, result['snapshotSha256'], environment='staging')['locations'], 1)
        self.assertEqual((snapshot / 'scene-records.i8').read_bytes(), self.blob)
        self.assertFalse(result['activated'])
        self.assertFalse(result['networkUsed'])
        self.assertEqual(result['newCreditGranted'], 0)
        for path in snapshot.iterdir():
            self.assertNotIn(self.owner.encode(), path.read_bytes())
        self.assertNotIn(self.owner, (self.root / 'result/receipt.json').read_text())
        repeat = self.seal('repeat')
        self.assertEqual(repeat['snapshotSha256'], result['snapshotSha256'])

    def test_current_inventory_cannot_change_audited_pose_or_output(self):
        self.inventory['rows'][0]['heading'] = 91
        self.fails('publication_audit_membership_mismatch')

    def test_changed_native_bytes_cannot_be_hidden_by_inventory_hashes(self):
        cache_file(self.cache, self.key).write_bytes(b'\0' * len(self.blob))
        self.fails('publication_audit_bytes_mismatch')

    def test_pending_or_rejected_native_work_cannot_be_sealed(self):
        self.control['candidates'][0]['state'] = 'pending'
        self.fails('publication_audit_not_authoritative')

    def test_wrong_runtime_profile_cannot_use_an_approved_policy_name(self):
        self.control['qualifications'][0]['profile_id'] = 'e' * 64
        self.fails('publication_audit_not_authoritative')

    def test_qualification_must_cover_the_original_submission_time(self):
        self.control['qualifications'][0]['expires_at'] = 100
        self.fails('publication_audit_not_authoritative')

    def test_deleted_owners_never_reappear_from_an_old_audit(self):
        self.control['accounts'][0]['deleted_at'] = 102
        self.fails('publication_audit_not_authoritative')

    def test_credit_must_be_once_only_earned_for_this_exact_lease_and_owner(self):
        original = copy.deepcopy(self.control)
        for index, patch in enumerate([{'reason': 'fixture_funding'}, {'account_id': 'another'},
                                       {'reference': 'another'}, {'units': 2}, {'units': True}]):
            self.control = copy.deepcopy(original)
            self.control['ledger'][0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(PublicationSnapshotError):
                self.seal('bad-credit-' + str(index))

    def test_duplicate_credits_are_not_resolved_by_selecting_one(self):
        self.control['ledger'].append(dict(self.control['ledger'][0]))
        self.fails('ambiguous_publication_control')

    def test_mixed_or_unconfirmed_resources_cannot_be_sealed(self):
        self.control['resource'] = {**CONFIRMED_STAGING_RESOURCE, 'databaseId': 'wrong'}
        self.fails('invalid_publication_control_resource')

    def test_missing_audit_is_not_replaced_by_the_contributor_checksum(self):
        self.inventory['rows'][0]['id'] = 2
        self.fails('unrelated_publication_audit')

    def test_unpublished_inventory_still_fails_the_existing_snapshot_guards(self):
        self.inventory['rows'][0]['state'] = 'pending'
        self.fails('not_a_contributed_scene_publication')

    def test_previous_snapshot_history_and_existing_directories_are_preserved(self):
        first = self.seal()
        prior = self.root / 'result/snapshot'
        self.assertEqual(self.seal('next', previous=prior, previous_sha256=first['snapshotSha256'])['locations'], 1)
        original = (self.root / 'result/receipt.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.seal()
        self.assertEqual((self.root / 'result/receipt.json').read_bytes(), original)

    def test_pins_and_strict_control_json_are_required(self):
        self.seal()
        path = self.root / 'control.json'
        raw = path.read_bytes()
        path.write_bytes(raw + b' ')
        with self.assertRaisesRegex(SnapshotError, 'input_checksum_mismatch'):
            seal_publications(self.root / 'inventory.json', digest((self.root / 'inventory.json').read_bytes()),
                              path, digest(raw), self.root / 'authority.json', digest((self.root / 'authority.json').read_bytes()),
                              self.cache, self.root / 'bad-pin', environment='staging')
