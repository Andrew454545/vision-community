"""Read-only private adapter from operator-pinned saved runs to sample evidence.

No listener, path lookup from a request, model execution, receipt fabrication,
upload or account write. The caller must locate the owned artifact manifest
through trusted account/job state and retain original runs and failures.
"""
from __future__ import annotations

import re
import time

from .native_scene_search import strict_json
from .object_canary import fingerprint, pinned, regular
from .object_index_qualification import ObjectIndexQualifier, MAX_SECONDS
from .object_qualification import ObjectQualificationError, checksum, require
from .search_snapshot import digest, pinned_read

ID = re.compile(r'[a-f0-9]{32}\Z')
MAX_MANIFEST = 16384


class SavedObjectQualificationEvidence:
    def __init__(self, comparator, artifacts, artifacts_sha256):
        require(isinstance(comparator, ObjectIndexQualifier), 'invalid_object_sample_comparator')
        self.comparator = comparator
        self.artifacts, self.artifacts_sha256 = regular(artifacts), artifacts_sha256

    def evidence(self, request, *, now=None):
        try:
            return self._evidence(request, now)
        except ObjectQualificationError:
            raise
        except Exception:
            raise ObjectQualificationError('object_qualification_evidence_unavailable') from None

    def _evidence(self, request, now):
        started = time.monotonic()
        current = int(time.time()) if now is None else now
        require(type(current) is int and current >= 0, 'invalid_object_qualification_request')
        keys = {'version', 'accountId', 'requestId', 'challenge', 'profileId', 'artifactSetSha256', 'policyId', 'policySha256'}
        engine = self.comparator
        require(isinstance(request, dict) and set(request) == keys and type(request['version']) is int
            and request['version'] == 1 and all(isinstance(request[k], str) and ID.fullmatch(request[k])
                for k in ('accountId', 'requestId', 'challenge'))
            and checksum(request['profileId']) and request['profileId'] in engine.scores.policy['profiles']
            and request['artifactSetSha256'] == self.artifacts_sha256
            and request['policyId'] == engine.policy['policyId'] and request['policySha256'] == engine.policy_sha256,
            'invalid_object_qualification_request')
        raw = pinned_read(regular(self.artifacts), self.artifacts_sha256, MAX_MANIFEST)
        doc = strict_json(raw)
        require(isinstance(doc, dict) and set(doc) == {'version', 'scope', 'accountId', 'requestId', 'profileId',
            'scoreRequest', 'indexManifest', 'executionReceipt'} and type(doc['version']) is int and doc['version'] == 1
            and doc['scope'] == 'trusted-owned-object-sample-artifacts-v1'
            and all(doc[k] == request[k] for k in ('accountId', 'requestId', 'profileId')),
            'object_qualification_artifact_owner_mismatch')
        root = self.artifacts.parent
        score_path = pinned(root, doc['scoreRequest'], 8 * 1024**2)
        index_path = pinned(root, doc['indexManifest'], 1024 * 1024)
        execution_path = pinned(root, doc['executionReceipt'], MAX_MANIFEST)
        scores = pinned_read(score_path, doc['scoreRequest']['sha256'], 8 * 1024**2)
        execution_raw = pinned_read(execution_path, doc['executionReceipt']['sha256'], MAX_MANIFEST)
        execution = strict_json(execution_raw)
        profile = engine.scores.policy['profiles'][request['profileId']]
        settings_sha256 = fingerprint({'execution': profile['execution'], 'threads': profile['threads']})
        require(isinstance(execution, dict) and set(execution) == {'version', 'scope', 'accountId', 'requestId', 'detector', 'index'}
            and type(execution['version']) is int and execution['version'] == 1
            and execution['scope'] == 'trusted-owned-object-sample-runs-v1'
            and execution['accountId'] == request['accountId'] and execution['requestId'] == request['requestId'],
            'object_qualification_saved_runs_mismatch')
        for lane, field, expected in (('detector', 'scoreSubmissionSha256', digest(scores)),
                                      ('index', 'candidateManifestSha256', doc['indexManifest']['sha256'])):
            entry = execution[lane]
            require(isinstance(entry, dict) and set(entry) == {'profileId', 'settingsSha256', field}
                and entry['profileId'] == request['profileId'] and entry['settingsSha256'] == settings_sha256
                and entry[field] == expected, 'object_qualification_saved_runs_mismatch')
        # Recompute the full numerical result. Never read an existing pass flag
        # from the saved manifest or turn the execution receipt into audit proof.
        report = engine.qualify(scores, index_path, doc['indexManifest']['sha256'], now=current)
        require(report['profileId'] == request['profileId'], 'object_qualification_saved_runs_mismatch')
        require(pinned_read(regular(self.artifacts), self.artifacts_sha256, MAX_MANIFEST) == raw
            and pinned_read(pinned(root, doc['scoreRequest'], 8 * 1024**2), doc['scoreRequest']['sha256'], 8 * 1024**2) == scores
            and pinned_read(pinned(root, doc['executionReceipt'], MAX_MANIFEST), doc['executionReceipt']['sha256'], MAX_MANIFEST) == execution_raw
            and pinned(root, doc['indexManifest'], 1024 * 1024) == index_path,
            'object_qualification_saved_runs_changed')
        elapsed = time.monotonic() - started
        require(elapsed < MAX_SECONDS, 'object_qualification_evidence_timeout')
        issued = current + int(elapsed)
        require(issued < report['expiresAt'], 'object_qualification_evidence_expired')
        return {'version': 1, 'scope': 'trusted-saved-object-sample-evidence-v1',
            'accountId': request['accountId'], 'requestId': request['requestId'], 'challenge': request['challenge'],
            'artifactSetSha256': self.artifacts_sha256,
            'artifacts': {'detectorProfileId': request['profileId'], 'indexProfileId': request['profileId'],
                'detectorSettingsSha256': settings_sha256, 'indexSettingsSha256': settings_sha256,
                'executionReceiptSha256': doc['executionReceipt']['sha256']},
            'report': report, 'issuedAt': issued, 'expiresAt': issued + 30}
