"""Independently pinned current deletion authority for a restored private spool.

This is an operator input, never an HTTP request or evidence from the old backup.
It revokes work only; it cannot approve an audit, authorize upload or grant credit.
"""
from __future__ import annotations

from pathlib import Path
import re

from .native_scene_search import strict_json
from .object_canary import regular
from .search_snapshot import pinned_read

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
    require(isinstance(authority, dict) and set(authority) == {
        'version', 'scope', 'resource', 'policySha256', 'registrySha256',
        'deletionLedgerSha256', 'capturedAt', 'expiresAt', 'revocations'}
        and type(authority['version']) is int and authority['version'] == 1
        and authority['scope'] == 'private-object-erasure-recovery-v1'
        and authority['resource'] == verifier.document['resource']
        and authority['policySha256'] == verifier.policy_sha256
        and authority['registrySha256'] == registry_sha256
        and isinstance(authority['deletionLedgerSha256'], str)
        and HEX.fullmatch(authority['deletionLedgerSha256']))
    captured, expires = authority['capturedAt'], authority['expiresAt']
    require(type(captured) is int and type(expires) is int
            and 0 <= captured <= now < expires <= captured + MAX_AGE_SECONDS)
    revocations = authority['revocations']
    require(isinstance(revocations, list) and len(revocations) <= len(entries) <= 64)
    seen = set()
    for entry in revocations:
        require(isinstance(entry, dict) and set(entry) == {'leaseId', 'assignmentSha256', 'deletedAt'}
                and isinstance(entry['leaseId'], str) and entry['leaseId'] in entries
                and entry['leaseId'] not in seen
                and entry['assignmentSha256'] == entries[entry['leaseId']]['assignment']['sha256']
                and type(entry['deletedAt']) is int and 0 <= entry['deletedAt'] <= captured)
        seen.add(entry['leaseId'])
    return authority
