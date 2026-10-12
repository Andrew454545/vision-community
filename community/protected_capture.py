"""Inspect pinned native protection captures across OSes without import authority.

Original source paths are opaque provenance. Never open, remap or fabricate them.
Live source verification remains in protected_origin.verify_origin.
"""
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
import re
import time

from .object_canary import regular
from .native_scene_search import strict_json
from .protected_origin import MAX_JSON, MAX_SOURCE, MAX_AGE_MS, SELECTORS, millis
from .protected_reference import ProtectedReference
from .search_snapshot import pinned_read

HEX = re.compile(r'[a-f0-9]{64}\Z')
MAP = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
DEVICE = re.compile(r'(con|prn|aux|nul|com[0-9]|lpt[0-9])', re.I)
DECIMAL = re.compile(r'(0|[1-9][0-9]{0,39})\Z')


def require(value):
    if not value:
        raise ValueError('invalid_protected_capture')


def source_path(value):
    """Canonical absolute source syntax; no current-OS filesystem operations."""
    require(isinstance(value, str) and 0 < len(value) <= 32768 and '\x00' not in value)
    path = PurePosixPath(value) if value.startswith('/') else PureWindowsPath(value)
    require(path.is_absolute() and str(path) == value and '..' not in path.parts
            and not any(DEVICE.fullmatch(part.split('.')[0]) for part in path.parts[1:]))
    if isinstance(path, PureWindowsPath):
        require(re.fullmatch(r'[A-Za-z]:', path.drive) and not any(':' in part for part in path.parts[1:])
                and all(not part.endswith((' ', '.')) for part in path.parts[1:]))
    else:
        require(not value.startswith('//') and '\\' not in value)
    return path


def fingerprint(member, expected_path):
    require(isinstance(member, dict) and source_path(member.get('path')) == expected_path
            and member['path'] == str(expected_path) and type(member.get('exists')) is bool)
    if not member['exists']:
        require(set(member) == {'path', 'exists'})
        return None
    require(set(member) == {'path', 'exists', 'bytes', 'sha256', 'modifiedUnixMillis', 'identity'}
            and type(member['bytes']) is int and 0 <= member['bytes'] <= MAX_SOURCE
            and isinstance(member['sha256'], str) and HEX.fullmatch(member['sha256'])
            and type(member['modifiedUnixMillis']) is int and member['modifiedUnixMillis'] >= 0)
    identity = member['identity']
    require(isinstance(identity, list) and len(identity) == 5 and identity[2] == member['bytes']
            and type(identity[2]) is int
            and all(isinstance(identity[i], str) and DECIMAL.fullmatch(identity[i]) for i in (0, 1, 3, 4))
            and int(identity[3]) // 1_000_000 == member['modifiedUnixMillis'])
    return identity[0], identity[1]


@dataclass(frozen=True)
class CapturedProtection:
    reference: ProtectedReference
    document: dict
    evidence: dict


def inspect_capture(path, expected_sha256, exporter_sha256, *, now=None):
    """Validate recorded bytes/provenance only, including expired captures.

    Independently pinned owner delivery establishes the expected hashes. This
    cannot demonstrate that unavailable original source files are still current.
    Expiry is reported honestly, never reset to the time of download/inspection.
    """
    require(isinstance(expected_sha256, str) and HEX.fullmatch(expected_sha256)
            and isinstance(exporter_sha256, str) and HEX.fullmatch(exporter_sha256))
    path = regular(path)
    raw = pinned_read(path, expected_sha256, MAX_JSON)
    doc = strict_json(raw)
    require(isinstance(doc, dict) and type(doc.get('version')) is int and doc['version'] == 1
            and doc.get('contract') == 'vision-origin-protected-mma-handoff-v1'
            and doc.get('status') == 'ORIGIN_PROTECTED_STATE_CAPTURED_NOT_PORTABLE_IMPORT_AUTHORITY'
            and doc.get('selectors') == SELECTORS
            and all(doc.get(k) is False for k in ('objectImportApproved', 'portableImportApproved',
                'productionQualified', 'databaseBytesCopied', 'sourceBytesCopied', 'networkUsed'))
            and doc.get('freshness') == {'policy': 'live-origin-files-required-no-offline-relabelling-v1',
                                       'maxAgeMillis': MAX_AGE_MS})
    started, completed = millis(doc.get('startedAt')), millis(doc.get('completedAt'))
    current = time.time() if now is None else now
    require(type(current) in (int, float) and current >= 0 and current < float('inf')
            and started >= 0 and started <= completed <= current * 1000 + 1000)
    artifacts = doc.get('sourceArtifacts')
    require(isinstance(artifacts, list) and 10 <= len(artifacts) <= 20002)
    main = source_path(artifacts[0].get('path') if isinstance(artifacts[0], dict) else None)
    snapshots = []
    for key, name in (('snapshot', 'protected-snapshot.private.json'), ('selectionProbe', 'selection-probe.private.json')):
        member = doc.get(key)
        require(isinstance(member, dict) and member.get('file') == name
                and type(member.get('bytes')) is int and 0 < member['bytes'] <= MAX_JSON)
        content = pinned_read(regular(path.parent / name), member.get('sha256'), MAX_JSON)
        require(len(content) == member['bytes'])
        value = strict_json(content)
        snapshots.append((value, ProtectedReference(value, database=str(main))))
    source, reference = snapshots[0]
    probe = snapshots[1][0]
    require(all(source[key] == probe[key] for key in ('sourceMaps', 'coordinates', 'sourceLocationCount', 'uniqueLocationCount'))
            and doc.get('sourceMapCount') == len(source['sourceMaps'])
            and type(doc['sourceMapCount']) is int
            and doc.get('sourceLocationCount') == source['sourceLocationCount']
            and type(doc['sourceLocationCount']) is int
            and doc.get('uniqueLocationCount') == source['uniqueLocationCount']
            and type(doc['uniqueLocationCount']) is int
            and doc['snapshot'].get('generatedAt') == source['generatedAt'])
    generated = millis(source['generatedAt'])
    require(started - 1000 <= generated <= completed + 1000
            and started - 1000 <= millis(probe['generatedAt']) <= completed + 1000)
    expected, seen = [main, source_path(str(main) + '-wal')], set()
    for row in source['sourceMaps']:
        key = row['id']
        require(MAP.fullmatch(key) and not DEVICE.fullmatch(key) and key.lower() not in seen)
        seen.add(key.lower())
        expected += [main.parent / 'arrow' / (key + suffix) for suffix in ('.arrow', '_delta.arrow')]
    require(len(artifacts) == len(expected))
    identities = []
    for member, expected_path in zip(artifacts, expected):
        value = fingerprint(member, expected_path)
        if value is not None:
            identities.append(value)
            require(member['modifiedUnixMillis'] <= generated + 1000)
    require(artifacts[0]['exists'] and len(set(identities)) == len(identities)
            and all(artifacts[i]['exists'] or artifacts[i + 1]['exists'] for i in range(2, len(artifacts), 2)))
    exporter = doc.get('exporter')
    require(isinstance(exporter, dict) and fingerprint(exporter, source_path(exporter.get('path'))) is not None
            and exporter['sha256'] == exporter_sha256 and exporter['bytes'] > 0
            and (exporter['identity'][0], exporter['identity'][1]) not in identities)
    # Re-pin local payloads after all parsing. No original source path is opened.
    pinned_read(path, expected_sha256, MAX_JSON)
    for key in ('snapshot', 'selectionProbe'):
        member = doc[key]
        pinned_read(regular(path.parent / member['file']), member['sha256'], MAX_JSON)
    return CapturedProtection(reference, doc, {
        'manifestSha256': expected_sha256, 'snapshotSha256': doc['snapshot']['sha256'],
        'selectionProbeSha256': doc['selectionProbe']['sha256'], 'exporterSha256': exporter_sha256,
        'sourceMaps': doc['sourceMapCount'], 'sourceLocations': doc['sourceLocationCount'],
        'uniqueLocations': doc['uniqueLocationCount'], 'sourceArtifactMembers': len(artifacts),
        'startedAt': doc['startedAt'], 'completedAt': doc['completedAt'],
        'originProofExpiresUnixMillis': int(started + MAX_AGE_MS),
        'originProofExpired': current * 1000 >= started + MAX_AGE_MS,
        'capturePinsValidated': True, 'verifiedOnOriginalSourceMachine': False,
        'sourceContentHashesVerified': False, 'portableImportApproved': False,
        'objectImportApproved': False, 'productionQualified': False,
    })
