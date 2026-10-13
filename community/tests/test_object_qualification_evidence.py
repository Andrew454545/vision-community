"""Private saved artifact adapter; one real comparator on synthetic inputs."""
import copy
import unittest
from unittest.mock import patch

from community import object_qualification_evidence as evidence
from community.object_canary import fingerprint
from community.object_qualification import ObjectQualificationError
from community.search_snapshot import digest, encoded
from community.tests import test_object_index_qualification as index_fixture

NOW = 2000000000


class SavedObjectQualificationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index_fixture.ObjectIndexQualificationTests.setUpClass()
        cls.addClassCleanup(index_fixture.ObjectIndexQualificationTests.doClassCleanups)
        cls.sample = case = index_fixture.ObjectIndexQualificationTests()
        case.setUp()
        cls.engine = case.engine()
        cls.root = case.root
        cls.candidate, cls.candidate_sha = case.write_index(cls.root / 'adapter-candidate', case.actual, case.actual_files)
        cls.scores = cls.root / 'adapter-scores.json'
        cls.scores.write_bytes(case.score_request)
        cls.execution_path = cls.root / 'adapter-execution.json'
        settings = fingerprint({'execution': 'cpu', 'threads': 1})
        cls.template = {'version': 1, 'scope': 'trusted-owned-object-sample-runs-v1',
            'accountId': 'a' * 32, 'requestId': 'b' * 32,
            'detector': {'profileId': case.profile_id, 'settingsSha256': settings, 'scoreSubmissionSha256': digest(case.score_request)},
            'index': {'profileId': case.profile_id, 'settingsSha256': settings, 'candidateManifestSha256': cls.candidate_sha}}

    def setUp(self):
        self.execution = copy.deepcopy(self.template)
        self.manifest_path = self.root / (self._testMethodName + '-artifacts.json')

    def adapter(self):
        self.execution_path.write_bytes(encoded(self.execution))
        doc = {'version': 1, 'scope': 'trusted-owned-object-sample-artifacts-v1', 'accountId': 'a' * 32,
            'requestId': 'b' * 32, 'profileId': self.sample.profile_id,
            'scoreRequest': self.sample.helper.pin(self.scores),
            'indexManifest': {**self.sample.helper.pin(self.candidate), 'path': 'adapter-candidate/manifest.json'},
            'executionReceipt': self.sample.helper.pin(self.execution_path)}
        raw = encoded(doc)
        self.manifest_path.write_bytes(raw)
        self.request = {'version': 1, 'accountId': 'a' * 32, 'requestId': 'b' * 32, 'challenge': 'c' * 32,
            'profileId': self.sample.profile_id, 'artifactSetSha256': digest(raw), 'policyId': self.engine.policy['policyId'],
            'policySha256': self.engine.policy_sha256}
        return evidence.SavedObjectQualificationEvidence(self.engine, self.manifest_path, digest(raw))

    def test_saved_same_profile_artifacts_reach_the_actual_100_location_comparator(self):
        result = self.adapter().evidence(self.request, now=NOW)
        self.assertEqual(result['scope'], 'trusted-saved-object-sample-evidence-v1')
        self.assertEqual(result['challenge'], 'c' * 32)
        self.assertEqual(result['report']['locations'], 100)
        self.assertTrue(result['report']['sampleCompatible'])
        self.assertFalse(result['report']['qualified'])
        self.assertEqual(result['expiresAt'], result['issuedAt'] + 30)
        self.assertNotIn(str(self.root), encoded(result).decode())

    def test_another_account_request_policy_or_client_path_cannot_choose_saved_artifacts(self):
        adapter = self.adapter()
        for change in ({'accountId': 'd' * 32}, {'requestId': 'd' * 32}, {'policySha256': 'd' * 64},
                       {'artifactSetSha256': 'd' * 64}, {'path': '/private/client-chosen'}, {'approved': True}):
            with self.assertRaises(ObjectQualificationError):
                adapter.evidence({**self.request, **change}, now=NOW)

    def test_different_index_runtime_settings_or_output_pins_never_reach_comparison(self):
        for change in ({'profileId': 'd' * 64}, {'settingsSha256': 'd' * 64}, {'candidateManifestSha256': 'd' * 64}):
            self.execution = copy.deepcopy(self.template)
            self.execution['index'].update(change)
            adapter = self.adapter()
            with patch.object(self.engine, 'qualify', side_effect=AssertionError('must not compare mismatched runs')):
                with self.assertRaisesRegex(ObjectQualificationError, 'saved_runs_mismatch'):
                    adapter.evidence(self.request, now=NOW)

    def test_changed_saved_receipt_is_service_failure_without_a_device_rejection(self):
        adapter = self.adapter()
        self.execution_path.write_bytes(b'{}')
        with self.assertRaisesRegex(ObjectQualificationError, 'evidence_unavailable') as context:
            adapter.evidence(self.request, now=NOW)
        self.assertNotIn(str(self.root), str(context.exception))
