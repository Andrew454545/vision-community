"""Synthetic 100-location fixed-input index sample; no model or cloud work."""
import copy
import struct
import unittest
import zlib
from unittest.mock import patch

from calibration import compare_object_indexes as comparison
from community import object_canary as canary
from community import object_index_qualification as qualification
from community.native_object_verifier import LANE_LIMITS, SEMANTIC_LIMITS
from community.native_scene_verifier import source_pins
from community.object_features import crc8, crc16
from community.object_index import COMMON_MODEL_SHA256, CODEBOOK_SHA256, global_id_record
from community.object_qualification import ObjectQualifier, ObjectQualificationError, CEILINGS
from community.search_snapshot import CONFIRMED_STAGING_RESOURCE, digest, encoded
from community.tests import test_object_canary as fixture_module
from community.tests.test_object_features import mutate

NOW = 2000000000


class ObjectIndexQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = h = fixture_module.ObjectCanaryTests()
        h.setUp()
        cls.addClassCleanup(h.doCleanups)
        cls.root = h.root
        template = copy.deepcopy(h.document['cases'][0])
        cases = []
        for i in range(100):
            case = copy.deepcopy(template)
            case['id'] = 'synthetic-' + str(i)
            for j, image in enumerate(case['images']):
                target = cls.root / f'case-{i}-face-{j}.png'
                target.write_bytes((cls.root / image['path']).read_bytes())
                image['path'] = target.name
            target = cls.root / f'case-{i}-detector.json'
            target.write_bytes(encoded(h.gold))
            case['reference'] = h.pin(target)
            cases.append(case)
        h.document['cases'] = cases
        # Declared synthetic asset identities, not real downloaded models or a
        # measured runtime. The index contract requires these canonical pins.
        h.document['modelSha256'].update({'rfdetr-medium-576-b4.onnx': COMMON_MODEL_SHA256,
            'owlv2-pq128-codebook.bin': CODEBOOK_SHA256})
        cls.fixture_sha = h.save()
        profile = canary.runtime_profile(h.binary, h.models)['profile']
        profile['assets'].update({'models/' + k: v for k, v in h.document['modelSha256'].items()})
        cls.profile_id = canary.fingerprint(profile)
        cls.score_policy = {'version': 1, 'scope': 'trusted-fixed-input-object-qualification-v1',
            'policyId': 'staging.synthetic-object-sample', 'environment': 'staging',
            'resource': CONFIRMED_STAGING_RESOURCE, 'sourceFiles': source_pins(),
            'fixtureSha256': cls.fixture_sha, 'profiles': {cls.profile_id: profile},
            'minimumLocations': 100, 'thresholds': dict(CEILINGS),
            'validFrom': NOW - 10, 'validUntil': NOW + 86400, 'qualificationSeconds': 3600}
        cls.score_path = cls.root / 'scores-policy.json'
        cls.score_path.write_bytes(encoded(cls.score_policy))
        cls.score_sha = digest(encoded(cls.score_policy))
        cls.scores = ObjectQualifier(h.fixture, cls.fixture_sha, cls.score_path, cls.score_sha)
        cls.score_request = encoded({'profileId': cls.profile_id, 'canary': {'version': 1,
            'fixtureSha256': cls.fixture_sha, 'outputs': [{'case': case['id'], **h.gold} for case in cases]}})
        manifest, files, source = mutate({})
        base_lines = source.decode().splitlines()
        lines = []
        for i in range(100):
            fields = base_lines[i % 2].split('\t')
            fields[7], fields[11] = 'synthetic-pano-' + str(i), str(i)
            lines.append('\t'.join(fields) + '\n')
        cls.source = ''.join(lines).encode()
        cls.source_path = cls.root / 'sample.tsv'
        cls.source_path.write_bytes(cls.source)
        cls.frozen_path = cls.root / 'frozen-views.json'
        cls.frozen = {'contract': 'vision-object-frozen-rgb-v1', 'sourceBytes': len(cls.source),
            'sourceSha256': digest(cls.source), 'totalLocations': 100, 'locations': [
                {'index': i, 'lineSha256': digest(line.encode()), 'faces': [
                    {'offset': j, 'file': image['path'], 'bytes': image['bytes'],
                     'sha256': image['sha256'], 'rgbSha256': '1' * 64}
                    for j, image in enumerate(case['images'])]}
                for i, (line, case) in enumerate(zip(lines, cases))]}
        cls.frozen_path.write_bytes(encoded(cls.frozen))
        cls.frozen_sha = digest(encoded(cls.frozen))
        expanded = {name: raw * 50 for name, raw in files.items()}
        offsets, offset = [], 0
        for line in lines:
            offsets.append(struct.pack('<Q', offset))
            offset += len(line.encode())
        expanded['location-offsets.bin'] = b''.join(offsets)
        expanded['global-location-ids.bin'] = b''.join(global_id_record(i) for i in range(100))
        for entry in manifest['classes'] + manifest['hotConcepts']:
            raw = files[entry['file']]
            records = []
            for repeat in range(50):
                for offset in range(0, len(raw), 32):
                    record = bytearray(raw[offset:offset + 32])
                    struct.pack_into('<I', record, 0, struct.unpack_from('<I', record)[0] + repeat * 2)
                    record[31] = crc8(record[:31])
                    records.append(record)
            expanded[entry['file']] = b''.join(records)
        manifest.update(totalLocations=100, indexedLocations=100, globalStart=0, minimumGlobalLocation=0,
            maximumGlobalLocation=99, sourceBytes=len(cls.source), sourceSha256=digest(cls.source),
            frozenViewsManifestSha256=cls.frozen_sha, fetchErrors=0, inferenceErrors=0)
        manifest['viewQuality'].update(policy='vision-per-view-quality-v1', viewCount=6,
            implementationIdentity='a' * 64, blurAreaFractionExclusive=.5, tileGrid=8,
            tunnelVisionProbabilityInclusive=.85, tunnelEvidencePolicy='none-darkness-never-rejects-v1',
            keptViews=600, blurRejectedViews=0, darkTunnelRejectedViews=0,
            fullyRejectedLocations=0, permanentlyInvalidLocations=0)
        manifest['viewQuality'].pop('protectedAuthorityManifestSha256', None)
        cls.manifest, cls.files = manifest, expanded
        cls.gold_path, cls.gold_sha = cls.write_index(cls.root / 'gold', manifest, expanded)
        cls.bundle = {'version': 1, 'scope': 'trusted-fixed-input-object-index-sample-v1',
            'detectorFixtureSha256': cls.fixture_sha, 'reference': h.document['reference'],
            'cases': [case['id'] for case in cases], 'source': h.pin(cls.source_path),
            'frozenViews': h.pin(cls.frozen_path), 'index': {**h.pin(cls.gold_path), 'path': 'gold/manifest.json'}}

    @staticmethod
    def write_index(folder, manifest, files):
        folder.mkdir(exist_ok=True)
        document = copy.deepcopy(manifest)
        entries = [document[key] for key in ('offsets', 'metadata', 'globalIds', 'semantic', 'viewQuality')]
        entries += document['classes'] + document['hotConcepts']
        for entry in entries:
            raw = files[entry['file']]
            entry.update(bytes=len(raw), records=len(raw) // entry.get('recordBytes', 32), sha256=digest(raw))
        for name, raw in files.items():
            (folder / name).write_bytes(raw)
        path = folder / 'manifest.json'
        raw = encoded(document)
        path.write_bytes(raw)
        return path, digest(raw)

    def setUp(self):
        self.reference = copy.deepcopy(self.bundle)
        self.policy = {'version': 1, 'scope': 'trusted-fixed-input-object-index-qualification-v1',
            'policyId': self.score_policy['policyId'] + '.index-v1', 'scorePolicySha256': self.score_sha,
            'referenceBundleSha256': '', 'sourceFiles': source_pins(),
            'thresholds': {'lanes': dict(LANE_LIMITS), 'semantic': dict(SEMANTIC_LIMITS)},
            'minimumKeptLocations': 100}
        self.actual, self.actual_files = copy.deepcopy(self.manifest), dict(self.files)
        self.candidate_dir = self.root / self._testMethodName
        self.bundle_path = self.root / (self._testMethodName + '-reference.json')
        self.policy_path = self.root / (self._testMethodName + '-policy.json')

    def engine(self):
        raw = encoded(self.reference)
        self.bundle_path.write_bytes(raw)
        self.policy['referenceBundleSha256'] = digest(raw)
        policy = encoded(self.policy)
        self.policy_path.write_bytes(policy)
        return qualification.ObjectIndexQualifier(self.scores, self.bundle_path, digest(raw), self.policy_path, digest(policy))

    def result(self, request=None):
        candidate, pin = self.write_index(self.candidate_dir, self.actual, self.actual_files)
        return self.engine().qualify(self.score_request if request is None else request, candidate, pin, now=NOW)

    def change_semantic(self, offset, raw):
        value = bytearray(self.actual_files['semantic-pq128.bin'])
        value[offset:offset + len(raw)] = raw
        start = (offset // 144) * 144
        struct.pack_into('<H', value, start + 142, crc16(value[start:start + 142]))
        self.actual_files['semantic-pq128.bin'] = bytes(value)

    def test_complete_same_sample_compares_features_without_account_admission(self):
        result = self.result()
        self.assertTrue(result['sampleCompatible'])
        self.assertTrue(result['indexCompatible'])
        self.assertEqual(result['locations'], 100)
        self.assertEqual(result['views'], 600)
        self.assertEqual(result['detectorComparison']['numericValuesCompared'], 9600)
        self.assertEqual(result['indexComparison']['semantic']['recordsCompared'], 1600)
        self.assertTrue(result['indexComparison']['exactFeatureMatch'])
        self.assertTrue(result['identicalInputBindingVerified'])
        self.assertEqual(result['profileId'], self.profile_id)
        for key in ('qualified', 'serverAuthorization', 'productionQualified', 'currentEligibilityVerified',
                    'inferenceProvenanceVerified'):
            self.assertFalse(result[key])
        self.assertNotIn('approved', result)
        self.assertNotIn(str(self.root), encoded(result).decode())
        self.assertNotIn('synthetic-pano', encoded(result).decode())
        self.assertEqual(result['acceptedContributions'], 0)
        self.assertEqual(result['searchCreditsCreated'], 0)

    def test_pq_code_drift_is_rejected_even_when_detector_scores_match(self):
        original = self.actual_files['semantic-pq128.bin'][0]
        self.change_semantic(0, bytes([original ^ 1]))
        result = self.result()
        self.assertTrue(result['scoreCompatible'])
        self.assertFalse(result['sampleCompatible'])
        self.assertFalse(result['indexCompatible'])
        self.assertEqual(result['indexComparison']['semantic']['differentCodeBytes'], 1)

    def test_packed_box_and_float16_calibration_use_existing_numerical_bounds(self):
        original = struct.unpack_from('<H', self.actual_files['semantic-pq128.bin'], 128)[0]
        self.change_semantic(128, struct.pack('<H', original + 1))
        shift = struct.unpack_from('<e', self.actual_files['semantic-pq128.bin'], 136)[0]
        self.change_semantic(136, struct.pack('<e', shift + .005))
        self.assertTrue(self.result()['sampleCompatible'])
        self.change_semantic(136, struct.pack('<e', shift + .02))
        self.assertFalse(self.result()['indexCompatible'])

    def test_detector_failure_cannot_be_hidden_by_identical_saved_index(self):
        request = comparison.strict_json(self.score_request)
        request['canary']['outputs'][-1]['hybrid']['car'][0]['semanticScore'] += .01
        result = self.result(encoded(request))
        self.assertTrue(result['indexCompatible'])
        self.assertFalse(result['scoreCompatible'])
        self.assertFalse(result['sampleCompatible'])

    def test_missing_hit_or_changed_support_cannot_be_averaged_away(self):
        entry = next(e for e in self.actual['hotConcepts'] if e['records'])
        self.actual_files[entry['file']] = self.actual_files[entry['file']][32:]
        result = self.result()
        self.assertFalse(result['indexCompatible'])
        self.assertEqual(sum(r['missingRecords'] for r in result['indexComparison']['lanes']['hotConcepts']), 1)

    def test_quality_mask_drift_and_selected_face_drift_are_visible(self):
        # The unused face 5 can be rejected without changing feature validity.
        raw = bytearray(self.actual_files['view-quality.bin'])
        raw[1], raw[2] = 31, 32
        struct.pack_into('<I', raw, 4, zlib.crc32(raw[:4]))
        self.actual_files['view-quality.bin'] = bytes(raw)
        self.actual['viewQuality'].update(keptViews=599, blurRejectedViews=1)
        semantic = bytearray(self.actual_files['semantic-pq128.bin'])
        for offset in range(0, 16 * 144, 144):
            if semantic[offset + 140] == 5:
                semantic[offset + 140] = 0
                struct.pack_into('<H', semantic, offset + 142, crc16(semantic[offset:offset + 142]))
        self.actual_files['semantic-pq128.bin'] = bytes(semantic)
        result = self.result()
        self.assertFalse(result['indexCompatible'])
        self.assertEqual(result['indexComparison']['viewQualityDifferences'], 1)

    def test_inference_errors_are_not_compatible_work(self):
        self.actual['inferenceErrors'] = 1
        self.assertFalse(self.result()['indexCompatible'])

    def test_different_frozen_input_marker_is_not_same_sample(self):
        for value in ('0' * 64, None):
            self.actual['frozenViewsManifestSha256'] = value
            with self.assertRaises(ObjectQualificationError):
                self.result()

    def test_trusted_case_mapping_and_source_reference_must_match_detector_fixture(self):
        for key, value in (('cases', list(reversed(self.reference['cases']))),
                           ('detectorFixtureSha256', '0' * 64), ('reference', {})):
            self.reference = copy.deepcopy(self.bundle)
            self.reference[key] = value
            with self.assertRaisesRegex(ObjectQualificationError, 'invalid_object_index_reference'):
                self.engine()

    def test_native_row_face_map_is_checked_against_real_pinned_fixture_paths(self):
        saved = self.frozen_path.read_bytes()
        self.addCleanup(self.frozen_path.write_bytes, saved)
        for change in (lambda f: f['locations'][0].update(lineSha256='0' * 64),
                       lambda f: f['locations'][0]['faces'][0].update(sha256='0' * 64),
                       lambda f: f['locations'][0]['faces'].reverse(),
                       lambda f: f['locations'][0]['faces'][0].update(file='../outside.png')):
            frozen = copy.deepcopy(self.frozen)
            change(frozen)
            self.frozen_path.write_bytes(encoded(frozen))
            self.reference['frozenViews'] = self.helper.pin(self.frozen_path)
            with self.assertRaisesRegex(ObjectQualificationError, 'frozen_inputs_mismatch'):
                self.engine()

    def test_no_client_approval_summary_is_consumed(self):
        request = comparison.strict_json(self.score_request)
        request['approved'] = True
        with self.assertRaises(ObjectQualificationError):
            self.result(encoded(request))

    def test_widened_index_bounds_and_unpinned_source_are_refused(self):
        for change in (lambda p: p['thresholds']['lanes'].update(maximumScoreDifference=.002),
                       lambda p: p['thresholds']['semantic'].update(maximumBoxDifference=True),
                       lambda p: p.update(sourceFiles={}), lambda p: p.update(minimumKeptLocations=99)):
            original = copy.deepcopy(self.policy)
            change(self.policy)
            with self.assertRaises(ObjectQualificationError):
                self.engine()
            self.policy = original

    def test_policy_expiry_missing_files_and_bad_crc_cannot_create_result(self):
        engine = self.engine()
        candidate, pin = self.write_index(self.candidate_dir, self.actual, self.actual_files)
        with self.assertRaises(ObjectQualificationError):
            engine.qualify(self.score_request, candidate, pin, now=NOW + 86400)
        raw = bytearray(self.actual_files['semantic-pq128.bin'])
        raw[142] ^= 1
        self.actual_files['semantic-pq128.bin'] = bytes(raw)
        candidate, pin = self.write_index(self.candidate_dir, self.actual, self.actual_files)
        with self.assertRaises(ObjectQualificationError):
            engine.qualify(self.score_request, candidate, pin, now=NOW)
        (self.candidate_dir / 'semantic-pq128.bin').unlink()
        with self.assertRaisesRegex(ObjectQualificationError, 'unavailable') as context:
            engine.qualify(self.score_request, candidate, pin, now=NOW)
        self.assertNotIn(str(self.root), str(context.exception))

    def test_reference_cannot_be_accidentally_compared_with_itself(self):
        with self.assertRaisesRegex(ObjectQualificationError, 'invalid_object_index_candidate'):
            self.engine().qualify(self.score_request, self.gold_path, self.gold_sha, now=NOW)

    def test_candidate_change_during_comparison_is_refused(self):
        engine = self.engine()
        candidate, pin = self.write_index(self.candidate_dir, self.actual, self.actual_files)
        original = comparison.compare_semantic
        def changed(*args):
            value = self.candidate_dir / 'semantic-pq128.bin'
            value.write_bytes(b'changed')
            return original(*args)
        with patch.object(comparison, 'compare_semantic', side_effect=changed):
            with self.assertRaises(ObjectQualificationError):
                engine.qualify(self.score_request, candidate, pin, now=NOW)

    def test_reference_policy_change_after_measurement_is_refused(self):
        engine = self.engine()
        candidate, pin = self.write_index(self.candidate_dir, self.actual, self.actual_files)
        original = comparison.compare
        def changed(*args):
            value = original(*args)
            self.policy_path.write_bytes(b'{}')
            return value
        with patch.object(comparison, 'compare', side_effect=changed):
            with self.assertRaises(ObjectQualificationError):
                engine.qualify(self.score_request, candidate, pin, now=NOW)

    def test_finite_budget_refuses_overrun_and_invalid_limits(self):
        engine = self.engine()
        candidate, pin = self.write_index(self.candidate_dir, self.actual, self.actual_files)
        for limit in (True, 0, 61, float('nan')):
            with self.assertRaises(ObjectQualificationError):
                engine.qualify(self.score_request, candidate, pin, now=NOW, timeout_seconds=limit)
        with self.assertRaisesRegex(ObjectQualificationError, 'timeout'):
            engine.qualify(self.score_request, candidate, pin, now=NOW, timeout_seconds=.000001)
