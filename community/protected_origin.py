"""Live origin checks for a separately pinned native protected-map handoff.

This receipt never grants portable import permission. Its actual source files
must still exist unchanged on the machine that produced it, within one hour.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import time

from .native_scene_search import strict_json
from .object_canary import regular
from .protected_reference import ProtectedReference
from .search_snapshot import pinned_read

MAX_JSON = 32 * 1024 * 1024
MAX_SOURCE = 64 * 1024**3
MAX_AGE_MS = 3_600_000
HEX = re.compile(r'[a-f0-9]{64}\Z')
SELECTORS = {'rootMaps': ['‼️GEONECTIONS JSON‼️', 'Past Locations'],
             'folders': ['Titled Maps ‼️', 'Titled Maps ‼️ Done✅']}


class ProtectedOriginError(ValueError):
    pass


def require(value):
    if not value:
        raise ProtectedOriginError('protected_origin_handoff_invalid_or_changed')


def millis(value):
    require(isinstance(value, str))
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.tzinfo is not None)
        return parsed.timestamp() * 1000
    except (ValueError, OverflowError):
        raise ProtectedOriginError('protected_origin_handoff_invalid_or_changed') from None


def absolute(value):
    require(isinstance(value, str) and Path(value).is_absolute()
            and str(Path(value)) == value)
    return Path(value)


def identity(state, stream):
    change = state.st_ctime_ns
    device = state.st_dev
    if os.name == 'nt':
        # Node/libuv records Windows ChangeTime, while Python 3.12 st_ctime
        # records creation time. Read the same native field through our handle.
        import ctypes
        from ctypes import wintypes
        import msvcrt
        class Basic(ctypes.Structure):
            _fields_ = [(name, ctypes.c_longlong) for name in
                        ('creation', 'access', 'write', 'change')] + [('attributes', wintypes.DWORD)]
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                    ctypes.c_void_p, wintypes.DWORD]
        api.GetFileInformationByHandleEx.restype = wintypes.BOOL
        data = Basic()
        require(api.GetFileInformationByHandleEx(msvcrt.get_osfhandle(stream.fileno()),
                                                0, ctypes.byref(data), ctypes.sizeof(data)))
        change = data.change * 100 - 11_644_473_600_000_000_000
        device &= 0xffffffff  # libuv's DWORD volume serial, not Python's 64-bit serial
    return [str(device), str(state.st_ino), state.st_size, str(state.st_mtime_ns), str(change)]


def fingerprint(path, deadline, *, optional=False, metadata=None):
    path = absolute(path)
    regular(path.parent, directory=True)
    if optional and not path.exists():
        require(not path.is_symlink())
        return {'path': str(path), 'exists': False}
    regular(path)
    before = path.stat()
    require(before.st_size <= MAX_SOURCE)
    digest, size = hashlib.sha256() if metadata is None else None, 0
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        # Windows path stat and handle fstat expose different st_ctime fields.
        # Compare their shared identity fields here; native ChangeTime is checked
        # before/after the read through this handle and against the Node receipt.
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns))
        initial = identity(opened, stream)
        if metadata is not None:
            # Between full checks, the pinned source identity (including native
            # ChangeTime) must match. Status must not reread gigabytes of Arrow.
            require(metadata.get('exists') is True and metadata.get('identity') == initial
                    and metadata.get('bytes') == before.st_size
                    and isinstance(metadata.get('sha256'), str) and HEX.fullmatch(metadata['sha256']))
            size, measured_sha = before.st_size, metadata['sha256']
        else:
            while True:
                require(time.monotonic() <= deadline)
                block = stream.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                require(size <= MAX_SOURCE)
                digest.update(block)
            measured_sha = digest.hexdigest()
        final = os.fstat(stream.fileno())
        require(identity(final, stream) == initial)
    after = regular(path).stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            and size == before.st_size)
    return {'path': str(path), 'exists': True, 'bytes': size, 'sha256': measured_sha,
            'modifiedUnixMillis': before.st_mtime_ns // 1_000_000, 'identity': initial}


def verify_origin(path, expected_sha256, snapshot, database, *, full=True):
    """Return hash-only evidence; no private paths or coordinates in reports."""
    path = regular(absolute(str(path)))
    doc = strict_json(pinned_read(path, expected_sha256, MAX_JSON))
    require(isinstance(doc, dict) and type(doc.get('version')) is int and doc['version'] == 1
            and doc.get('contract') == 'vision-origin-protected-mma-handoff-v1'
            and doc.get('status') == 'ORIGIN_PROTECTED_STATE_CAPTURED_NOT_PORTABLE_IMPORT_AUTHORITY'
            and doc.get('selectors') == SELECTORS
            and all(doc.get(k) is False for k in ('objectImportApproved', 'portableImportApproved',
                'productionQualified', 'databaseBytesCopied', 'sourceBytesCopied', 'networkUsed'))
            and doc.get('freshness') == {'policy': 'live-origin-files-required-no-offline-relabelling-v1',
                                       'maxAgeMillis': MAX_AGE_MS})
    started, completed, now = millis(doc.get('startedAt')), millis(doc.get('completedAt')), time.time() * 1000
    require(started <= completed <= now + 1000 and now - started <= MAX_AGE_MS)
    members = []
    for key, filename in (('snapshot', 'protected-snapshot.private.json'),
                          ('selectionProbe', 'selection-probe.private.json')):
        member = doc.get(key)
        require(isinstance(member, dict) and member.get('file') == filename
                and type(member.get('bytes')) is int and 0 < member['bytes'] <= MAX_JSON)
        raw = pinned_read(regular(path.parent / filename), member.get('sha256'), MAX_JSON)
        require(len(raw) == member['bytes'])
        members.append(strict_json(raw))
    source, probe = members
    # Use exactly the same coordinate exclusion rule as the independent auditor.
    ProtectedReference(source, database=database['main']['path'])
    ProtectedReference(probe, database=database['main']['path'])
    maps = source['sourceMaps']
    require(source['sourceMaps'] == probe['sourceMaps']
            and doc.get('sourceMapCount') == len(maps)
            and doc.get('sourceLocationCount') == source['sourceLocationCount']
            and doc.get('uniqueLocationCount') == source['uniqueLocationCount']
            and doc['snapshot']['sha256'] == snapshot['sha256']
            and doc['snapshot']['bytes'] == snapshot['bytes']
            and doc['snapshot'].get('generatedAt') == source['generatedAt'] == snapshot['generatedAt'])
    ids = set()
    paths = [absolute(database['main']['path']), absolute(database['wal']['path'])]
    for entry in maps:
        key = entry['id']
        require(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', key)
                and not re.fullmatch(r'(con|prn|aux|nul|com[0-9]|lpt[0-9])', key, re.I)
                and key.lower() not in ids)
        ids.add(key.lower())
        paths += [paths[0].parent / 'arrow' / (key + suffix) for suffix in ('.arrow', '_delta.arrow')]
    require(str(paths[1]) == str(paths[0]) + '-wal'
            and len({str(p).lower() for p in paths}) == len(paths))
    deadline = time.monotonic() + 300
    declared = doc.get('sourceArtifacts')
    require(isinstance(declared, list) and len(declared) == len(paths)
            and all(isinstance(m, dict) for m in declared))
    current = [fingerprint(str(p), deadline, optional=i != 0,
               metadata=None if full else declared[i]) for i, p in enumerate(paths)]
    require(doc.get('sourceArtifacts') == current)
    identities = [(m['identity'][0], m['identity'][1]) for m in current if m['exists']]
    require(len(set(identities)) == len(identities)
            and all(current[i]['exists'] or current[i + 1]['exists'] for i in range(2, len(current), 2)))
    for key, member in zip(('main', 'wal'), current):
        require(all(member.get(k) == v for k, v in database[key].items()))
    exporter = doc.get('exporter')
    require(isinstance(exporter, dict)
            and exporter == fingerprint(exporter.get('path'), deadline, metadata=None if full else exporter))
    generated = millis(source['generatedAt'])
    require(started - 1000 <= generated <= completed + 1000
            and all(not m['exists'] or m['modifiedUnixMillis'] <= generated + 1000 for m in current)
            and time.time() * 1000 - started <= MAX_AGE_MS)
    return {'manifestSha256': expected_sha256, 'snapshotSha256': doc['snapshot']['sha256'],
            'sourceMaps': len(maps), 'verifiedOnOriginalSourceMachine': True,
            'objectImportApproved': False, 'portableImportApproved': False, 'sourceContentHashesVerified': full}
