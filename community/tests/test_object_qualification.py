"""Synthetic fixed samples and models; no genuine device approval or inference."""
import copy
import json
import time
import unittest
from unittest.mock import patch

from community import object_canary as canary
from community import object_qualification as qualification
from community.native_scene_verifier import source_pins
from community.search_snapshot import CONFIRMED_STAGING_RESOURCE, digest, encoded
from community.tests import test_object_canary as fixture_module

NOW = 2000000000


class ObjectQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = helper = fixture_module.ObjectCanaryTests()
        helper.setUp()
        cls.addClassCleanup(helper.doCleanups)
        template = copy.deepcopy(helper.document['cases'][0])
        cases = []
        for i in range(100):
            row = copy.deepcopy(template)
            row['id'] = 'synthetic-' + str(i)
            for j, image in enumerate(row['images']):
                target = helper.root / f'case-{i}-face-{j}.png'
                target.write_bytes((helper.root / image['path']).read_bytes())
                image['path'] = target.name
            target = helper.root / f'case-{i}-gold.json'
            target.write_bytes(encoded(helper.gold))
            row['reference'] = helper.pin(target)
            cases.append(row)
        helper.document['cases'] = cases
        cls.fixture_sha256 = helper.save()
        profile = canary.runtime_profile(helper.binary, helper.models)
        cls.profile = profile
        cls.template = {'version': 1, 'scope': 'trusted-fixed-input-object-qualification-v1',
            'policyId': 'staging.synthetic-object-scores', 'environment': 'staging',
            'resource': CONFIRMED_STAGING_RESOURCE, 'sourceFiles': source_pins(),
            'fixtureSha256': cls.fixture_sha256, 'profiles': {profile['sha256']: profile['profile']},
            'minimumLocations': 100, 'thresholds': dict(qualification.CEILINGS),
            'validFrom': NOW - 10, 'validUntil': NOW + 86400, 'qualificationSeconds': 3600}

    def setUp(self):
        self.policy = copy.deepcopy(self.template)
        self.policy_path = self.fixture.root / (self._testMethodName + '.json')
        self.body = {'profileId': self.profile['sha256'], 'canary': {'version': 1,
            'fixtureSha256': self.fixture_sha256, 'outputs': [
                {'case': row['id'], **copy.deepcopy(self.fixture.gold)} for row in self.fixture.document['cases']]}}

    def engine(self):
        raw = encoded(self.policy)
        self.policy_path.write_bytes(raw)
        return qualification.ObjectQualifier(self.fixture.fixture, self.fixture_sha256, self.policy_path, digest(raw))

    def result(self, body=None):
        return self.engine().qualify(encoded(self.body if body is None else body), now=NOW)

    def test_complete_100_location_values_compare_without_admission_or_human_labels(self):
        raw = encoded(self.body)
        result = self.engine().qualify(raw, now=NOW)
        self.assertTrue(result['scoreCompatible'])
        self.assertFalse(result['qualified'])
        self.assertNotIn('approved', result)
        self.assertEqual(result['locations'], 100)
        self.assertEqual(result['views'], 600)
        self.assertEqual(result['comparison']['numericValuesCompared'], 9600)
        self.assertEqual(result['comparison']['structuralDifferences'], 0)
        self.assertEqual(result['submissionSha256'], digest(raw))
        self.assertFalse(result['serverAuthorization'])
        self.assertFalse(result['productionQualified'])
        self.assertEqual(result['acceptedContributions'], 0)
        self.assertEqual(result['searchCreditsCreated'], 0)
        self.assertNotIn(str(self.fixture.root), json.dumps(result))
        self.assertEqual(result['expiresAt'], result['issuedAt'] + 3600)

    def test_score_difference_is_measured_from_values_not_client_summary(self):
        self.body['canary']['outputs'][-1]['hybrid']['car'][5]['semanticScore'] += .0009
        result = self.result()
        self.assertTrue(result['scoreCompatible'])
        self.assertAlmostEqual(result['comparison']['maximumScoreDifference'], .0009)
        self.body['canary']['outputs'][-1]['hybrid']['car'][5]['semanticScore'] += .0002
        result = self.result()
        self.assertFalse(result['scoreCompatible'])
        self.assertGreater(result['comparison']['maximumScoreDifference'], .001)
        self.body['canary']['comparison'] = {'exact': True}
        with self.assertRaises(qualification.ObjectQualificationError):
            self.result()

    def test_box_and_discrete_differences_cannot_be_hidden_by_average_scores(self):
        for mutate in (
            lambda output: output['common'][0]['detections'][0].update(x1=.101),
            lambda output: output['common'][0]['detections'].clear(),
            lambda output: output['common'][0]['detections'][0].update(classId=1, className='person'),
            lambda output: output['common'][0]['detections'][0].update(supportCount=2),
            lambda output: output['hybrid']['car'][0]['hot'].clear(),
        ):
            body = copy.deepcopy(self.body)
            mutate(body['canary']['outputs'][50])
            self.assertFalse(self.result(body)['scoreCompatible'])

    def test_missing_extra_or_reordered_samples_and_queries_are_refused(self):
        for mutate in (
            lambda value: value['canary']['outputs'].pop(),
            lambda value: value['canary']['outputs'].append(copy.deepcopy(value['canary']['outputs'][0])),
            lambda value: value['canary']['outputs'].reverse(),
            lambda value: value['canary']['outputs'][0]['hybrid'].update(untrusted=[]),
            lambda value: value['canary']['outputs'][0]['hybrid']['car'][0].update(query='unknown'),
            lambda value: value['canary']['outputs'][0]['common'][0].update(path='/private/client/path'),
        ):
            body = copy.deepcopy(self.body)
            mutate(body)
            with self.assertRaises(qualification.ObjectQualificationError):
                self.result(body)

    def test_unpinned_runtime_fixture_and_client_approval_flags_are_refused(self):
        for mutate in (
            lambda value: value.update(profileId='0' * 64),
            lambda value: value['canary'].update(fixtureSha256='0' * 64),
            lambda value: value.update(approved=True),
            lambda value: value['canary'].update(version=True),
        ):
            body = copy.deepcopy(self.body)
            mutate(body)
            with self.assertRaises(qualification.ObjectQualificationError):
                self.result(body)

    def test_invalid_numbers_are_not_ordinary_parity_failures(self):
        engine = self.engine()
        raw = encoded(self.body)
        for bad in (raw.replace(b'"confidence":0.6', b'"confidence":true', 1),
                    raw.replace(b'"confidence":0.6', b'"confidence":1e999', 1),
                    raw.replace(b'"confidence":0.6', b'"confidence":-1', 1)):
            with self.assertRaisesRegex(qualification.ObjectQualificationError, 'invalid_object_qualification_request'):
                engine.qualify(bad, now=NOW)

    def test_duplicate_json_and_request_size_are_bounded(self):
        engine = self.engine()
        for raw in (b'{"profileId":"a","profileId":"b"}', b'{"x":NaN}', b'', b' ' * (qualification.MAX_REQUEST + 1)):
            with self.assertRaises(qualification.ObjectQualificationError):
                engine.qualify(raw, now=NOW)

    def test_operator_tolerances_cannot_exceed_conservative_existing_limits(self):
        for name, maximum in qualification.CEILINGS.items():
            for invalid in (True, -1, maximum * 1.01):
                self.policy['thresholds'] = dict(qualification.CEILINGS)
                self.policy['thresholds'][name] = invalid
                with self.assertRaisesRegex(qualification.ObjectQualificationError, 'bounds'):
                    self.engine()

    def test_tiny_exploratory_cohort_cannot_be_relabelled_qualification(self):
        self.policy['minimumLocations'] = 3
        with self.assertRaisesRegex(qualification.ObjectQualificationError, 'policy'):
            self.engine()
        self.policy['minimumLocations'] = 112
        with self.assertRaisesRegex(qualification.ObjectQualificationError, 'sample_too_small'):
            self.engine()

    def test_resource_expiry_and_source_pins_are_operator_authority(self):
        for field, value in [('resource', {**CONFIRMED_STAGING_RESOURCE, 'bucket': 'other'}),
            ('environment', 'production'), ('validUntil', NOW + qualification.MAX_AGE + 1),
            ('qualificationSeconds', 0), ('sourceFiles', {})]:
            self.policy = copy.deepcopy(self.template)
            self.policy[field] = value
            with self.assertRaises(qualification.ObjectQualificationError):
                self.engine()
        self.policy = copy.deepcopy(self.template)
        engine = self.engine()
        for current in (NOW - 11, NOW + 86400, True):
            with self.assertRaises(qualification.ObjectQualificationError):
                engine.qualify(encoded(self.body), now=current)

    def test_model_thread_and_pipeline_profiles_must_match_their_hashes(self):
        for mutate in (
            lambda p: p.update(threads=2),
            lambda p: p['assets'].update(binary='0' * 64),
            lambda p: p['assets'].update({'models/' + canary.MODELS[0]: '0' * 64}),
            lambda p: p['pipeline'].update({'object_canary.py': '0' * 64}),
            lambda p: p.update(platform='linux'),
        ):
            self.policy = copy.deepcopy(self.template)
            mutate(self.policy['profiles'][self.profile['sha256']])
            with self.assertRaisesRegex(qualification.ObjectQualificationError, 'profiles'):
                self.engine()
        changed = copy.deepcopy(self.profile['profile'])
        changed['assets']['models/' + canary.MODELS[0]] = '0' * 64
        self.policy = copy.deepcopy(self.template)
        self.policy['profiles'] = {canary.fingerprint(changed): changed}
        with self.assertRaisesRegex(qualification.ObjectQualificationError, 'profiles'):
            self.engine()

    def test_independently_pinned_mac_and_windows_package_bytes_may_differ(self):
        # Metadata only, not actual Mac execution or authentic native results.
        mac = copy.deepcopy(self.profile['profile'])
        mac['platform'] = 'darwin'
        mac['assets'] = {k: v for k, v in mac['assets'].items() if not k.startswith('bin/')}
        mac['assets'].update(binary='8' * 64, **{'bin/libonnxruntime.dylib': '9' * 64})
        mac['pipeline']['object_canary.py'] = '7' * 64
        mac_pin = canary.fingerprint(mac)
        self.policy['profiles'][mac_pin] = mac
        engine = self.engine()
        for profile in (self.profile['sha256'], mac_pin):
            self.body['profileId'] = profile
            decision = engine.qualify(encoded(self.body), now=NOW)
            self.assertTrue(decision['scoreCompatible'])
            self.assertFalse(decision['qualified'])

    def test_read_guards_and_finite_comparison_deadline_do_not_create_decisions(self):
        engine = self.engine()
        with patch.object(qualification.time, 'monotonic', side_effect=[0, 21]):
            with self.assertRaisesRegex(qualification.ObjectQualificationError, 'timeout'):
                engine.qualify(encoded(self.body), now=NOW)
        self.policy_path.write_bytes(b'changed policy')
        with self.assertRaises(ValueError):
            engine.qualify(encoded(self.body), now=NOW)

    def test_fixed_input_inventory_is_bracketed_after_numeric_comparison(self):
        engine = self.engine()
        original = engine.verify
        checks = []
        def verify():
            checks.append(True)
            if len(checks) == 2:
                raise qualification.ObjectQualificationError('object_qualification_fixture_changed')
            return original()
        with patch.object(engine, 'verify', side_effect=verify):
            with self.assertRaisesRegex(qualification.ObjectQualificationError, 'fixture_changed'):
                engine.qualify(encoded(self.body), now=NOW)
        self.assertEqual(len(checks), 2)


if __name__ == '__main__':
    unittest.main()
