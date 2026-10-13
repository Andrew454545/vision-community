"""Trusted fixed-input Object detector and complete v4 index comparison.

Read-only, offline and finite. A numerical sample result is not reusable
account admission, current coverage/protected authority or a contribution.
"""
from __future__ import annotations

import math
import time

from calibration import compare_object_indexes as comparison
from .native_object_verifier import bounds, within
from .native_scene_search import strict_json
from .native_scene_verifier import source_pins
from .object_canary import pinned, regular, relative
from .object_index import COMMON_MODEL_SHA256, CODEBOOK_SHA256
from .object_qualification import (ObjectQualifier, ObjectQualificationError, checksum,
                                   integer, require, MAX_SECONDS as SCORE_SECONDS)
from .search_snapshot import digest, pinned_read

MAX_SECONDS = 60
MAX_DOCUMENT = 1024 * 1024


class ObjectIndexQualifier:
    """Combine actual scores and indexed features; never consume a pass flag.

The operator's separate index policy pins the score policy and a reference
bundle. The latter binds each detector case to the exact native frozen-input
row and six PNGs. Candidate paths are local saved artifacts, not JSON paths
followed from an uploader. Neither an endpoint nor a publication writer exists.
"""
    def __init__(self, scores, reference, reference_sha256, policy, policy_sha256):
        try:
            started = time.monotonic()
            self._initialize(scores, reference, reference_sha256, policy, policy_sha256)
            require(time.monotonic() - started < MAX_SECONDS, 'object_index_qualification_timeout')
        except ObjectQualificationError:
            raise
        except Exception:
            raise ObjectQualificationError('object_index_qualification_unavailable') from None

    def _initialize(self, scores, reference, reference_sha256, policy, policy_sha256):
        require(isinstance(scores, ObjectQualifier), 'invalid_object_index_score_comparator')
        self.scores = scores
        self.policy_path, self.policy_sha256 = regular(policy), policy_sha256
        self.reference_path, self.reference_sha256 = regular(reference), reference_sha256
        p = self.policy = strict_json(pinned_read(self.policy_path, policy_sha256, MAX_DOCUMENT))
        require(isinstance(p, dict) and set(p) == {'version', 'scope', 'policyId',
            'scorePolicySha256', 'referenceBundleSha256', 'sourceFiles', 'thresholds', 'minimumKeptLocations'}
            and type(p['version']) is int and p['version'] == 1
            and p['scope'] == 'trusted-fixed-input-object-index-qualification-v1'
            and p['policyId'] == scores.policy['policyId'] + '.index-v1'
            and len(p['policyId']) <= 128
            and p['scorePolicySha256'] == scores.policy_sha256
            and p['referenceBundleSha256'] == reference_sha256
            and p['sourceFiles'] == source_pins()
            and integer(p['minimumKeptLocations'], scores.policy['minimumLocations'], 112),
            'invalid_object_index_qualification_policy')
        # Reuse the existing conservative numerical limits. PQ codes, selected
        # faces, hit identities/support and quality masks must still agree.
        bounds(p['thresholds'])
        self.reference = strict_json(pinned_read(self.reference_path, reference_sha256, MAX_DOCUMENT))
        self._reference()

    def _reference(self):
        require(strict_json(pinned_read(regular(self.reference_path), self.reference_sha256, MAX_DOCUMENT))
            == self.reference, 'object_index_reference_changed')
        r, fixture = self.reference, self.scores.fixture
        cases = fixture.document['cases']
        require(isinstance(r, dict) and set(r) == {'version', 'scope', 'detectorFixtureSha256',
            'reference', 'cases', 'source', 'frozenViews', 'index'}
            and type(r['version']) is int and r['version'] == 1
            and r['scope'] == 'trusted-fixed-input-object-index-sample-v1'
            and r['detectorFixtureSha256'] == fixture.sha256
            and r['reference'] == fixture.document['reference']
            and r['cases'] == [case['id'] for case in cases], 'invalid_object_index_reference')
        root = self.reference_path.parent
        source_path = pinned(root, r['source'], MAX_DOCUMENT)
        source = pinned_read(source_path, r['source']['sha256'], MAX_DOCUMENT)
        # Preserve row bytes including their LF, exactly as the native frozen
        # contract hashes them. A different TSV/order is a different sample.
        lines = source.splitlines(keepends=True)
        require(len(lines) == len(cases) and all(line.endswith(b'\n') for line in lines),
            'object_index_sample_rows_mismatch')
        require(all(len(line.decode('utf-8').rstrip('\r\n').split('\t')) == 12
            and line.decode('utf-8').rstrip('\r\n').split('\t')[9] == 'gen4' for line in lines),
            'object_index_sample_not_gen4')
        frozen_path = pinned(root, r['frozenViews'], MAX_DOCUMENT)
        frozen = strict_json(pinned_read(frozen_path, r['frozenViews']['sha256'], MAX_DOCUMENT))
        require(isinstance(frozen, dict) and set(frozen) == {'contract', 'sourceBytes', 'sourceSha256',
            'totalLocations', 'locations'} and frozen['contract'] == 'vision-object-frozen-rgb-v1'
            and type(frozen['sourceBytes']) is int and frozen['sourceBytes'] == len(source)
            and frozen['sourceSha256'] == digest(source)
            and type(frozen['totalLocations']) is int and frozen['totalLocations'] == len(cases)
            and isinstance(frozen['locations'], list) and len(frozen['locations']) == len(cases),
            'object_index_frozen_inputs_mismatch')
        for ordinal, (case, row, line) in enumerate(zip(cases, frozen['locations'], lines)):
            require(isinstance(row, dict) and set(row) == {'index', 'lineSha256', 'faces'}
                and type(row['index']) is int and row['index'] == ordinal
                and row['lineSha256'] == digest(line) and isinstance(row['faces'], list)
                and len(row['faces']) == 6, 'object_index_frozen_inputs_mismatch')
            for face, (image, entry) in enumerate(zip(case['images'], row['faces'])):
                require(isinstance(entry, dict) and set(entry) == {'offset', 'file', 'bytes', 'sha256', 'rgbSha256'}
                    and type(entry['offset']) is int and entry['offset'] == face
                    and type(entry['bytes']) is int and entry['bytes'] == image['bytes']
                    and entry['sha256'] == image['sha256'] and checksum(entry['rgbSha256'])
                    and relative(entry['file']), 'object_index_frozen_inputs_mismatch')
                # Share the actual pinned fixture files, rather than following
                # a second unbounded set of image paths or trusting a hash list.
                require(regular(frozen_path.parent / entry['file']) == regular(fixture.path.parent / image['path']),
                    'object_index_frozen_inputs_mismatch')
        index_path = pinned(root, r['index'], MAX_DOCUMENT)
        gold, files, _ = comparison.load_index(index_path, r['index']['sha256'], source)
        require(gold.get('frozenViewsManifestSha256') == r['frozenViews']['sha256']
            and gold['totalLocations'] == len(cases) and gold.get('viewQuality')
            and fixture.document['modelSha256']['rfdetr-medium-576-b4.onnx'] == COMMON_MODEL_SHA256
            and fixture.document['modelSha256']['owlv2-pq128-codebook.bin'] == CODEBOOK_SHA256,
            'object_index_reference_identity_mismatch')
        require(all(gold.get(key, 0) == 0 for key in ('fetchErrors', 'inferenceErrors', 'permanentlyInvalidLocations')),
            'object_index_reference_incomplete')
        require(sum(bool(files['view-quality.bin'][i + 1]) for i in range(0, len(files['view-quality.bin']), 8))
            >= self.policy['minimumKeptLocations'], 'object_index_reference_insufficient_quality')
        return source_path, source, index_path, gold, files

    def qualify(self, score_request, candidate, candidate_sha256, *, now=None, timeout_seconds=MAX_SECONDS):
        try:
            return self._qualify(score_request, candidate, candidate_sha256, now, timeout_seconds)
        except ObjectQualificationError:
            raise
        except Exception:
            # Malformed/missing operator assets are service failures, not a
            # failed device score. Never expose private paths or submitted data.
            raise ObjectQualificationError('object_index_qualification_unavailable') from None

    def _qualify(self, score_request, candidate, candidate_sha256, now, timeout_seconds):
        require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
            and 0 < timeout_seconds <= MAX_SECONDS, 'invalid_object_index_qualification_budget')
        started = time.monotonic()
        current = int(time.time()) if now is None else now
        score = self.scores.qualify(score_request, now=current, timeout_seconds=min(SCORE_SECONDS, timeout_seconds))
        require(strict_json(pinned_read(regular(self.policy_path), self.policy_sha256, MAX_DOCUMENT)) == self.policy
            and source_pins() == self.policy['sourceFiles'], 'object_index_qualification_policy_changed')
        source_path, source, gold_path, gold, files = before = self._reference()
        candidate = regular(candidate)
        require(candidate.parent != gold_path.parent and checksum(candidate_sha256), 'invalid_object_index_candidate')
        actual, actual_files, _ = comparison.load_index(candidate, candidate_sha256, source)
        require(actual.get('frozenViewsManifestSha256') == self.reference['frozenViews']['sha256']
            and actual.get('viewQuality'), 'object_index_candidate_sample_mismatch')
        require(time.monotonic() - started < timeout_seconds, 'object_index_qualification_timeout')
        measured = comparison.compare(gold_path, self.reference['index']['sha256'], candidate, candidate_sha256, source_path)
        compatible = within(measured, self.policy['thresholds']) and all(
            value == 0 for counters in measured['nativeCounters'].values() for value in counters.values())
        # Recheck the operator bundle, native row/face map, quality and feature
        # inventory after comparison, in addition to the comparator's own pins.
        require(self._reference() == before and self.scores.verify()
            and strict_json(pinned_read(regular(self.policy_path), self.policy_sha256, MAX_DOCUMENT)) == self.policy
            and source_pins() == self.policy['sourceFiles'], 'object_index_qualification_inputs_changed')
        require(comparison.load_index(candidate, candidate_sha256, source)[:2] == (actual, actual_files),
            'object_index_qualification_inputs_changed')
        elapsed = time.monotonic() - started
        require(elapsed < timeout_seconds, 'object_index_qualification_timeout')
        issued = current + int(elapsed)
        require(issued < score['expiresAt'], 'object_index_qualification_policy_expired')
        return {'version': 1, 'qualificationScope': 'fixed-input-object-score-and-index-parity-only',
            'sampleCompatible': score['scoreCompatible'] and compatible,
            'scoreCompatible': score['scoreCompatible'], 'indexCompatible': compatible, 'qualified': False,
            'policyId': self.policy['policyId'], 'policySha256': self.policy_sha256,
            'scorePolicySha256': self.scores.policy_sha256, 'profileId': score['profileId'],
            'fixtureSha256': self.scores.fixture.sha256, 'referenceBundleSha256': self.reference_sha256,
            'scoreSubmissionSha256': score['submissionSha256'], 'candidateManifestSha256': candidate_sha256,
            'frozenViewsManifestSha256': self.reference['frozenViews']['sha256'],
            'locations': score['locations'], 'views': score['views'],
            'detectorComparison': score['comparison'], 'indexComparison': measured,
            'issuedAt': issued, 'expiresAt': score['expiresAt'],
            'identicalInputBindingVerified': True, 'inferenceProvenanceVerified': False,
            'currentEligibilityVerified': False, 'serverAuthorization': False, 'productionQualified': False,
            'acceptedContributions': 0, 'searchCreditsCreated': 0}
