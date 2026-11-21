"""Fresh private protection evidence for qualification-based Object uploads.

Reuse independently pinned original-source inputs and owned assignments. This
does not run inference, renew an expired capture, assert Scene membership,
qualify an account, publish work, or grant portable database authority.
"""
from __future__ import annotations

import re
import time

from .native_scene_search import strict_json
from .object_audit_jobs import ObjectAuditJobs
from .object_canary import regular
from .object_qualification import checksum, integer
from .protected_origin import millis, MAX_AGE_MS
from .search_snapshot import digest, pinned_read

ID = re.compile(r'[0-9a-f]{32}\Z')
POLICY_KEYS = {'version', 'scope', 'policyId', 'qualificationPolicySha256', 'protectedPolicySha256',
    'qualityImplementationIdentity', 'protectedAuthoritySha256', 'protectedOriginHandoffSha256',
    'sceneInputModel', 'resource', 'validFrom', 'validUntil'}
REQUEST_KEYS = {'version', 'accountId', 'leaseId', 'profileId', 'qualificationId', 'challenge',
    'assignmentSha256', 'sourceSha256', 'snapshotSha256', 'policyId', 'policySha256', 'qualificationPolicySha256'}


class ObjectEligibilityError(ValueError):
    pass


def require(value):
    if not value:
        raise ObjectEligibilityError('object_protection_unavailable')


class LiveObjectProtection:
    def __init__(self, jobs, policy, policy_sha256, *, guard):
        require(isinstance(jobs, ObjectAuditJobs) and callable(guard) and checksum(policy_sha256))
        self.jobs, self.guard = jobs, guard
        self.path, self.sha256 = regular(policy), policy_sha256
        self._policy()

    def _policy(self):
        doc = strict_json(pinned_read(regular(self.path), self.sha256, 4096))
        verifier = self.jobs.verifier
        require(isinstance(doc, dict) and set(doc) == POLICY_KEYS and type(doc['version']) is int
            and doc['version'] == 1 and doc['scope'] == 'qualified-object-eligibility-v1'
            and doc['policyId'] == verifier.document['policyId']
            and all(checksum(doc[k]) for k in POLICY_KEYS if k.endswith('Sha256') or k == 'qualityImplementationIdentity')
            and doc['protectedPolicySha256'] == verifier.policy_sha256
            and doc['qualityImplementationIdentity'] == verifier.document['qualityImplementationIdentity']
            and doc['protectedAuthoritySha256'] == verifier.document['protectedAuthority']['sha256']
            and doc['protectedOriginHandoffSha256'] == verifier.document.get('protectedOriginHandoffSha256')
            and verifier.origin_path is not None and doc['resource'] == verifier.document['resource']
            and isinstance(doc['sceneInputModel'], str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', doc['sceneInputModel'])
            and integer(doc['validFrom'], 0, 8640000000000)
            and integer(doc['validUntil'], doc['validFrom'] + 1, doc['validFrom'] + 30 * 86400))
        return doc

    def _current(self, lease):
        jobs = self.jobs
        require(not jobs.stop.is_set() and not any((jobs.work / name).exists() for name in ('PAUSE', 'STOP')))
        self.guard()  # The configured owner supplies the actual activation/credential guard.
        jobs.verifier.verify_inputs_guard()
        require(jobs.verifier.origin_evidence is not None
            and jobs.verifier.origin_evidence['verifiedOnOriginalSourceMachine'] is True
            and jobs.verifier.origin_evidence['sourceContentHashesVerified'] is True)
        with jobs.connect() as database:
            require(database.execute('SELECT 1 FROM assignment_revocations WHERE lease=?', (lease,)).fetchone() is None)
        return jobs.entry({'lease': lease})

    def evidence(self, request):
        try:
            started = time.monotonic()
            require(isinstance(request, dict) and set(request) == REQUEST_KEYS and type(request['version']) is int
                and request['version'] == 1 and all(isinstance(request[k], str) and ID.fullmatch(request[k])
                    for k in ('accountId', 'leaseId', 'qualificationId', 'challenge'))
                and all(checksum(request[k]) for k in REQUEST_KEYS if k.endswith('Sha256') or k == 'profileId'))
            # No new job or native work is created. The lock keeps owner-side
            # revocation and this finite read mutually exclusive.
            with self.jobs.lock:
                doc = self._policy()
                now = int(time.time())
                require(doc['validFrom'] <= now < doc['validUntil'] and request['policyId'] == doc['policyId']
                    and request['policySha256'] == self.sha256
                    and request['qualificationPolicySha256'] == doc['qualificationPolicySha256'])
                entry = self._current(request['leaseId'])
                require(entry['profileId'] == request['profileId'] and entry['assignment']['sha256'] == request['assignmentSha256']
                    and entry['source']['sha256'] == request['sourceSha256'])
                source = self.jobs.source(entry)
                assignment = self.jobs.verifier.assignment(entry['assignment']['path'],entry['assignment']['sha256'],source)
                rows = assignment['records']
                require(1 <= len(rows) <= 4)
                origin_path = self.jobs.verifier.origin_path
                origin = strict_json(pinned_read(regular(origin_path),doc['protectedOriginHandoffSha256'],32 * 1024**2))
                expires = int((millis(origin['startedAt']) + MAX_AGE_MS) // 1000)
                require(self._current(request['leaseId']) == entry and self._policy() == doc
                    and digest(self.jobs.source(entry)) == digest(source) and time.monotonic() - started < 20)
                issued = int(time.time())
                require(issued < min(expires,doc['validUntil']))
                return {'version': 1, 'scope': 'trusted-live-object-protection-v1',
                    **{k: request[k] for k in REQUEST_KEYS if k != 'version'},
                    'protectedPolicySha256': doc['protectedPolicySha256'],
                    'qualityImplementationIdentity': doc['qualityImplementationIdentity'],
                    'protectedAuthoritySha256': doc['protectedAuthoritySha256'],
                    'protectedOriginHandoffSha256': doc['protectedOriginHandoffSha256'],
                    'resource': doc['resource'], 'records': [{'locationId': row['locationId'],
                        'coverageEvidenceSha256': row['coverageEvidenceSha256']} for row in rows],
                    'protectedEligible': True, 'verifiedOnOriginalSourceMachine': True,
                    'sceneMembershipVerified': False, 'coverageVerified': False, 'qualificationVerified': False,
                    'serverAuthorization': False, 'productionQualified': False,
                    'acceptedContributions': 0, 'searchCreditsCreated': 0,
                    'issuedAt': issued, 'expiresAt': min(issued + 30,expires,doc['validUntil'])}
        except Exception:
            # Original files/attempts stay with the owner; never expose private
            # paths or translate missing live evidence into a device rejection.
            raise ObjectEligibilityError('object_protection_unavailable') from None
