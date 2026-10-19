"""Bounded operator-pinned registries with append-only assignment extension."""
import argparse
import os
from pathlib import Path
import re

from .native_scene_search import strict_json
from .object_canary import regular
from .search_snapshot import pinned_read, encoded, digest

LEGACY_ASSIGNMENTS = 64
MAX_ASSIGNMENTS = 4096
MAX_REGISTRY_BYTES = 8 * 1024 * 1024
MAX_MEMBER_BYTES = 1024 * 1024
HEX = re.compile(r'[0-9a-f]{64}\Z')
ID = re.compile(r'[0-9a-f]{32}\Z')


def require(value, code='invalid_object_job_registry'):
    if not value:
        raise ValueError(code)


def pin(value, maximum):
    require(isinstance(value, dict) and set(value) == {'path', 'sha256', 'bytes'}
            and isinstance(value['path'], str) and Path(value['path']).is_absolute()
            and isinstance(value['sha256'], str) and HEX.fullmatch(value['sha256'])
            and type(value['bytes']) is int and 0 < value['bytes'] <= maximum)
    return value


def read_registry(path, sha256):
    doc = strict_json(pinned_read(regular(path), sha256, MAX_REGISTRY_BYTES))
    require(isinstance(doc, dict) and type(doc.get('version')) is int and doc['version'] in (1, 2))
    fields = {'version', 'scope', 'policyId', 'resource', 'assignments'}
    if doc['version'] == 2:
        fields.add('previousRegistry')
        pin(doc.get('previousRegistry'), MAX_REGISTRY_BYTES)
    require(set(doc) == fields and doc['scope'] == 'private-object-audit-registry')
    entries = doc['assignments']
    require(isinstance(entries, list) and 1 <= len(entries) <= (
        LEGACY_ASSIGNMENTS if doc['version'] == 1 else MAX_ASSIGNMENTS))
    seen = set()
    for entry in entries:
        require(isinstance(entry, dict) and set(entry) == {'leaseId', 'profileId', 'assignment', 'source'}
                and isinstance(entry['leaseId'], str) and ID.fullmatch(entry['leaseId'])
                and entry['leaseId'] not in seen
                and isinstance(entry['profileId'], str) and HEX.fullmatch(entry['profileId']))
        seen.add(entry['leaseId'])
        for key in ('assignment', 'source'):
            pin(entry[key], MAX_MEMBER_BYTES)
    return doc


def previous_registry(document):
    if document['version'] == 1:
        return None
    previous = document['previousRegistry']
    old = read_registry(previous['path'], previous['sha256'])
    raw = pinned_read(regular(previous['path']), previous['sha256'], MAX_REGISTRY_BYTES)
    require(len(raw) == previous['bytes'], 'object_registry_previous_changed')
    # Keep every old path, hash, byte count, profile, assignment and order. No
    # approved extension may silently replace or retire an old lease identity.
    require(old['policyId'] == document['policyId'] and old['resource'] == document['resource']
            and len(document['assignments']) > len(old['assignments'])
            and document['assignments'][:len(old['assignments'])] == old['assignments'],
            'object_registry_extension_reinterprets_history')
    return old


def extend_registry(previous, previous_sha256, additions, additions_sha256, out):
    previous, additions = regular(previous), regular(additions)
    old, added = read_registry(previous, previous_sha256), read_registry(additions, additions_sha256)
    previous_registry(old)
    require(added['version'] == 1 and added['policyId'] == old['policyId']
            and added['resource'] == old['resource'], 'object_registry_extension_identity_changed')
    entries = old['assignments'] + added['assignments']
    require(len(entries) <= MAX_ASSIGNMENTS and len({entry['leaseId'] for entry in entries}) == len(entries),
            'object_registry_extension_duplicate_or_capacity')
    previous_raw = pinned_read(previous, previous_sha256, MAX_REGISTRY_BYTES)
    document = {**old, 'version': 2, 'previousRegistry': {
        'path': str(previous), 'sha256': previous_sha256, 'bytes': len(previous_raw)}, 'assignments': entries}
    raw = encoded(document)
    require(len(raw) <= MAX_REGISTRY_BYTES, 'object_registry_extension_duplicate_or_capacity')
    target = Path(out).absolute()
    regular(target.parent, directory=True)
    pinned_read(additions, additions_sha256, MAX_REGISTRY_BYTES)
    pinned_read(previous, previous_sha256, MAX_REGISTRY_BYTES)
    with target.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {'version': 2, 'scope': 'private-object-registry-extension', 'registrySha256': digest(raw),
            'registryBytes': len(raw), 'previousAssignments': len(old['assignments']),
            'addedAssignments': len(added['assignments']), 'assignments': len(entries),
            'nativeAssignmentsValidated': False, 'productionQualified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('previous', 'additions', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('previous-sha256', 'additions-sha256'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    try:
        report = extend_registry(args.previous, args.previous_sha256, args.additions, args.additions_sha256, args.out)
    except (OSError, ValueError, KeyError, TypeError):
        print(encoded({'complete': False, 'error': 'object_registry_extension_failed', 'productionQualified': False}).decode())
        return 1
    print(encoded(report).decode())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
