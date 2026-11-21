"""Trusted fixed-input Object score comparison, without inference or admission.

The operator pins the reference fixture, policy, runtime profiles and numerical
bounds. Client-reported comparison summaries are never an approval source.
No listener, account, upload, publication, credit or background job exists here.
"""
from __future__ import annotations

import math
import re
import time

from .native_scene_search import strict_json
from .native_scene_verifier import source_pins
from .object_canary import ObjectFixture, MODELS, MAX_SUBMISSION_BYTES, compare_rows, fingerprint, regular
from .search_snapshot import digest, encoded, pinned_read, resource_for_environment

MAX_REQUEST = MAX_SUBMISSION_BYTES
MAX_SECONDS = 20
MAX_AGE = 30 * 86400
HEX = re.compile(r'[a-f0-9]{64}\Z')
PIPELINE = {'object_canary.py', 'object_index.py', 'object_features.py', 'vision_index.py', 'process_owner.py'}
CEILINGS = {'maximumScoreDifference': .001, 'maximumBoxDifference': 2 / 65535}


class ObjectQualificationError(ValueError):
    pass


def require(value, code='object_qualification_unavailable'):
    if not value:
        raise ObjectQualificationError(code)


def checksum(value):
    return isinstance(value, str) and HEX.fullmatch(value) is not None


def integer(value, low, high):
    return type(value) is int and low <= value <= high


class ObjectQualifier:
    """A numerical decision only. Publication needs separate current authority."""
    def __init__(self, fixture, fixture_sha256, policy, policy_sha256):
        self.policy_path, self.policy_sha256 = regular(policy), policy_sha256
        require(checksum(policy_sha256))
        self.policy = p = strict_json(pinned_read(self.policy_path, policy_sha256, 1024 * 1024))
        require(isinstance(p, dict) and set(p) == {'version', 'scope', 'policyId', 'environment', 'resource',
            'sourceFiles', 'fixtureSha256', 'profiles', 'minimumLocations', 'thresholds',
            'validFrom', 'validUntil', 'qualificationSeconds'} and type(p['version']) is int and p['version'] == 1
            and p['scope'] == 'trusted-fixed-input-object-qualification-v1'
            and isinstance(p['policyId'], str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', p['policyId'])
            and p['environment'] in ('staging', 'production')
            and p['resource'] == resource_for_environment(p['environment'])
            and (not p['policyId'].startswith('staging.') or p['environment'] == 'staging')
            and p['sourceFiles'] == source_pins() and p['fixtureSha256'] == fixture_sha256
            and integer(p['minimumLocations'], 100, 112)
            and integer(p['validFrom'], 0, 8640000000000)
            and integer(p['validUntil'], p['validFrom'] + 1, p['validFrom'] + MAX_AGE)
            and integer(p['qualificationSeconds'], 1, MAX_AGE), 'invalid_object_qualification_policy')
        thresholds = p['thresholds']
        require(isinstance(thresholds, dict) and set(thresholds) == set(CEILINGS)
            and all(type(thresholds[k]) in (int, float) and math.isfinite(thresholds[k])
                and 0 <= thresholds[k] <= high for k, high in CEILINGS.items()), 'invalid_object_qualification_bounds')
        self.fixture = ObjectFixture(fixture, fixture_sha256)
        require(len(self.fixture.document['cases']) >= p['minimumLocations'], 'object_qualification_sample_too_small')
        profiles = p['profiles']
        require(isinstance(profiles, dict) and 1 <= len(profiles) <= 16, 'invalid_object_qualification_profiles')
        for pin, profile in profiles.items():
            require(checksum(pin) and isinstance(profile, dict) and set(profile) == {
                'version', 'platform', 'execution', 'assets', 'threads', 'pipeline'}
                and type(profile['version']) is int and profile['version'] == 1
                and profile['platform'] in ('win32', 'darwin') and profile['execution'] == 'cpu'
                and type(profile['threads']) is int and profile['threads'] == 1
                and isinstance(profile['assets'], dict) and 12 <= len(profile['assets']) <= 256
                and isinstance(profile['pipeline'], dict) and set(profile['pipeline']) == PIPELINE
                and all(checksum(v) for v in [*profile['assets'].values(), *profile['pipeline'].values()])
                and all(name == 'binary' or re.fullmatch(r'(?:models|bin)/[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', name)
                    for name in profile['assets'])
                and {name: profile['assets'].get('models/' + name) for name in MODELS} == self.fixture.document['modelSha256']
                and checksum(profile['assets'].get('binary')) and fingerprint(profile) == pin,
                'invalid_object_qualification_profiles')

    def verify(self):
        require(strict_json(pinned_read(regular(self.policy_path), self.policy_sha256, 1024 * 1024)) == self.policy
            and source_pins() == self.policy['sourceFiles'], 'object_qualification_policy_changed')
        return self.fixture.verify()

    def qualify(self, raw, *, now=None, timeout_seconds=MAX_SECONDS):
        try:
            return self._qualify(raw, now=now, timeout_seconds=timeout_seconds)
        except ObjectQualificationError:
            raise
        except Exception:
            # Broken operator inputs are not a device rejection; private paths,
            # operating-system errors and raw submitted JSON never leave here.
            raise ObjectQualificationError('object_qualification_unavailable') from None

    def _qualify(self, raw, *, now, timeout_seconds):
        require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_REQUEST, 'invalid_object_qualification_request')
        require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
            and 0 < timeout_seconds <= MAX_SECONDS, 'invalid_object_qualification_budget')
        started = time.monotonic()
        current = int(time.time()) if now is None else now
        require(integer(current, 0, 8640000000000), 'invalid_object_qualification_time')
        p = self.policy
        require(p['validFrom'] <= current < p['validUntil'], 'object_qualification_policy_expired')
        try:
            body = strict_json(raw)
        except (ValueError, UnicodeError):
            raise ObjectQualificationError('invalid_object_qualification_request') from None
        require(isinstance(body, dict) and set(body) == {'profileId', 'canary'}
            and checksum(body['profileId']) and body['profileId'] in p['profiles'], 'object_profile_not_qualified')
        canary = body['canary']
        require(isinstance(canary, dict) and set(canary) == {'version', 'fixtureSha256', 'outputs'}
            and type(canary['version']) is int and canary['version'] == 1
            and canary['fixtureSha256'] == self.fixture.sha256 and isinstance(canary['outputs'], list)
            and len(canary['outputs']) == len(self.fixture.document['cases']), 'invalid_object_qualification_request')
        inventory = self.verify()
        counts = {'structuralDifferences': 0, 'numericValuesCompared': 0,
            'maximumScoreDifference': 0.0, 'maximumBoxDifference': 0.0}
        for output, (case, _images, reference) in zip(canary['outputs'], inventory):
            require(time.monotonic() - started < timeout_seconds, 'object_qualification_timeout')
            require(isinstance(output, dict) and set(output) == {'case', 'common', 'hybrid'}
                and output['case'] == case['id'] and isinstance(output['hybrid'], dict)
                and set(output['hybrid']) == set(case['queries']), 'invalid_object_qualification_request')
            try:
                comparisons = [compare_rows(output['common'], reference['common'])]
                comparisons += [compare_rows(output['hybrid'][q], reference['hybrid'][q], query=q) for q in case['queries']]
            except (ValueError, TypeError, KeyError):
                raise ObjectQualificationError('invalid_object_qualification_request') from None
            for comparison in comparisons:
                for name in ('structuralDifferences', 'numericValuesCompared'):
                    counts[name] += comparison[name]
                for name in CEILINGS:
                    counts[name] = max(counts[name], comparison[name])
        require(self.verify() == inventory, 'object_qualification_fixture_changed')
        elapsed = time.monotonic() - started
        require(elapsed < timeout_seconds, 'object_qualification_timeout')
        issued = current + int(elapsed)
        require(issued < p['validUntil'], 'object_qualification_policy_expired')
        approved = counts['structuralDifferences'] == 0 and counts['numericValuesCompared'] > 0 \
            and all(counts[k] <= limit for k, limit in p['thresholds'].items())
        # Detector parity alone is not complete index/PQ/quality parity, and
        # must not be mistaken for account qualification by a future caller.
        return {'version': 1, 'scoreCompatible': approved, 'qualified': False,
            'qualificationScope': 'fixed-input-detector-score-parity-only',
            'policyId': p['policyId'], 'policySha256': self.policy_sha256, 'profileId': body['profileId'],
            'fixtureSha256': self.fixture.sha256, 'submissionSha256': digest(raw),
            'locations': len(inventory), 'views': 6 * len(inventory), 'comparison': counts,
            'issuedAt': issued, 'expiresAt': min(issued + p['qualificationSeconds'], p['validUntil']),
            'serverAuthorization': False, 'productionQualified': False,
            'acceptedContributions': 0, 'searchCreditsCreated': 0}
