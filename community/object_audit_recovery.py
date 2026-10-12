"""Independently pinned current revocation authority for a restored spool.

Operator input only: never an HTTP request or evidence from the old backup.
V1 covers account deletion; V2 also covers active-owner submission cancellation.
Neither format can approve an audit, authorize upload or grant credit.
"""
from __future__ import annotations

from pathlib import Path
import re

from .native_scene_search import strict_json
from .object_canary import regular
from .search_snapshot import pinned_read
from .object_audit_registry import MAX_ASSIGNMENTS

MAX_AUTHORITY = 1024 * 1024
MAX_AGE_SECONDS = 600
HEX = re.compile(r'[0-9a-f]{64}\Z')


def recovery_revocations(path, sha256, *, registry_sha256, verifier, entries, now):
    def require(value):
        if not value:
            raise ValueError('invalid_object_recovery_authority')

    require(isinstance(path, (str, Path)) and Path(path).is_absolute()
            and isinstance(sha256, str) and HEX.fullmatch(sha256))
    authority = strict_json(pinned_read(regular(path), sha256, MAX_AUTHORITY))
    require(isinstance(authority, dict) and type(authority.get('version')) is int
            and authority['version'] in (1, 2))
    version = authority['version']
    fields = {'version', 'scope', 'resource', 'policySha256', 'registrySha256',
              'deletionLedgerSha256', 'capturedAt', 'expiresAt', 'revocations'}
    if version == 2:
        fields |= {'cancellationLedgerSha256', 'cancellations'}
    require(set(authority) == fields
            and authority['scope'] == f'private-object-erasure-recovery-v{version}'
            and authority['resource'] == verifier.document['resource']
            and authority['policySha256'] == verifier.policy_sha256
            and authority['registrySha256'] == registry_sha256
            and isinstance(authority['deletionLedgerSha256'], str)
            and HEX.fullmatch(authority['deletionLedgerSha256']))
    captured, expires = authority['capturedAt'], authority['expiresAt']
    require(type(captured) is int and type(expires) is int
            and 0 <= captured <= now < expires <= captured + MAX_AGE_SECONDS)
    revocations = authority['revocations']
    require(isinstance(revocations, list) and len(revocations) <= len(entries) <= MAX_ASSIGNMENTS)
    seen = set()
    for entry in revocations:
        require(isinstance(entry, dict) and set(entry) == {'leaseId', 'assignmentSha256', 'deletedAt'}
                and isinstance(entry['leaseId'], str) and entry['leaseId'] in entries
                and entry['leaseId'] not in seen
                and entry['assignmentSha256'] == entries[entry['leaseId']]['assignment']['sha256']
                and type(entry['deletedAt']) is int and 0 <= entry['deletedAt'] <= captured)
        seen.add(entry['leaseId'])
    if version == 2:
        require(isinstance(authority['cancellationLedgerSha256'], str)
                and HEX.fullmatch(authority['cancellationLedgerSha256'])
                and isinstance(authority['cancellations'], list)
                and len(authority['cancellations']) <= len(entries))
        cancelled, requests = set(), set()
        for entry in authority['cancellations']:
            require(isinstance(entry, dict) and set(entry) == {
                'leaseId', 'assignmentSha256', 'requestId', 'cancelledAt'}
                and isinstance(entry['leaseId'], str) and entry['leaseId'] in entries
                and entry['leaseId'] not in cancelled
                and entry['assignmentSha256'] == entries[entry['leaseId']]['assignment']['sha256']
                and isinstance(entry['requestId'], str) and HEX.fullmatch(entry['requestId'])
                and entry['requestId'] not in requests
                and type(entry['cancelledAt']) is int and 0 <= entry['cancelledAt'] <= captured)
            cancelled.add(entry['leaseId']); requests.add(entry['requestId'])
    return authority
