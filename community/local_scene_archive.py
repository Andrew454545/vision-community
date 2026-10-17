"""Portable backups of completed local Scene work; never upload or run inference."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import zipfile

from .local_scene_packets import MAX_PACKET_BYTES, canonical, load_packet
from .local_scene_pilot import CHUNK, LocalScenePilot
from .mac_starter import regular

CONTRACT = 'vision-local-scene-archive-v1'
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 32 * 1024 * 1024
ARTIFACTS = frozenset(('locations.tsv', 'input.json', 'index-run.json', 'checkpoint.json',
                       'index/manifest.json', 'index/shard-000000.i8', 'index/shard-000000.mask'))


def _pin(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


def _read(path, limit=MAX_FILE_BYTES):
    path = regular(path)
    if path.stat().st_size > limit:
        raise ValueError('archive_file_too_large')
    with path.open('rb') as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError('archive_file_too_large')
    return body


def _json(body):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('saved_work_changed')
            value[key] = item
        return value
    try:
        value = json.loads(body, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise ValueError('saved_work_changed') from None
    if not isinstance(value, dict):
        raise ValueError('saved_work_changed')
    return value


def _same_bytes(left, right):
    left, right = regular(left), regular(right)
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open('rb') as a, right.open('rb') as b:
        while True:
            block = a.read(1024 * 1024)
            if block != b.read(1024 * 1024):
                return False
            if not block:
                return True


def _completed_parts(root, packet):
    found = []
    layout = root / 'work-layout.json'
    size = CHUNK
    if layout.exists():
        value = _json(_read(layout))
        if set(value) != {'groupSize'} or type(value['groupSize']) is not int or value['groupSize'] not in (16,128):
            raise ValueError('saved_work_changed')
        size = value['groupSize']
    for number, start in enumerate(range(0, len(packet['rows']), size)):
        name = f'part-{number:04d}'
        folder = regular(root / name, directory=True, missing=True)
        receipt = regular(folder / 'complete.json', missing=True)
        if receipt.exists():
            found.append((name, packet['rows'][start:start + size]))
    return found


def export_saved_results(root: Path, destination: Path, *, portable=False) -> dict:
    """Create a new deterministic ZIP from verified completed groups only.

    Callers must hold their pilot's guard and OS packet lock while paused or
    finished. Captured bytes are checked again before publishing; an archive
    never asserts account admission or server acceptance. Original files remain
    untouched, including incomplete attempts and prior failure evidence.
    """
    root = regular(root, directory=True)
    destination = regular(destination, missing=True)
    if destination == root or root in destination.parents:
        raise ValueError('archive_destination_inside_work')
    packet = load_packet(root / 'packet.json')
    packet_body = _read(root / 'packet.json', MAX_PACKET_BYTES)
    if _json(packet_body) != packet:
        raise ValueError('saved_work_changed')
    profile_body = _read(root / 'runtime-profile.json')
    profile = _json(profile_body)
    if (set(profile) != {'sha256', 'profile'} or not isinstance(profile['profile'], dict)
            or not profile['profile'] or profile['sha256'] != _pin(canonical(profile['profile']))['sha256']):
        raise ValueError('saved_runtime_profile_changed')
    parts = _completed_parts(root, packet)
    if not parts:
        raise ValueError('no_completed_scene_work')
    captured = {'packet.json': packet_body, 'runtime-profile.json': profile_body}
    if (root / 'work-layout.json').exists():
        captured['work-layout.json'] = _read(root / 'work-layout.json')
    total_bytes = sum(map(len, captured.values()))

    def capture(name):
        nonlocal total_bytes
        body = _read(root / name)
        total_bytes += len(body)
        if total_bytes > MAX_SOURCE_BYTES:
            raise ValueError('archive_work_too_large')
        captured[name] = body
        return body

    receipts = []
    for name, rows in parts:
        receipt = _json(capture(f'{name}/complete.json'))
        if (set(receipt)-{'networkExecution'} != {'packetId', 'rowIds', 'runtimeProfile', 'attempt', 'files',
                             'qualityStatus', 'uploaded', 'creditsEarned'}
                or receipt['qualityStatus'] != 'LOCAL_PROVISIONAL' or receipt['uploaded'] is not False
                or type(receipt['creditsEarned']) is not int or receipt['creditsEarned'] != 0
                or not isinstance(receipt['attempt'], str)
                or not re.fullmatch(r'attempt-[0-9]{4,10}', receipt['attempt'])
                or not isinstance(receipt['files'], dict) or set(receipt['files']) != ARTIFACTS):
            raise ValueError('saved_work_changed')
        for relative in sorted(ARTIFACTS):
            body = capture(f"{name}/{receipt['attempt']}/{relative}")
            if receipt['files'][relative] != _pin(body):
                raise ValueError('saved_work_changed')
        tsv = captured[f"{name}/{receipt['attempt']}/locations.tsv"]
        if tsv != ('\n'.join(row['line'] for row in rows) + '\n').encode('utf-8'):
            raise ValueError('saved_work_changed')
        receipts.append((name, rows, receipt))

    # Reuse the exact runner validator on the captured bytes. No constructor,
    # runtime probe, model file, native process, account or network is involved.
    destination.parent.mkdir(parents=True, exist_ok=True)
    regular(destination.parent, directory=True)
    with tempfile.TemporaryDirectory(prefix='.vision-scene-export-', dir=destination.parent) as temporary:
        snapshot = Path(temporary)
        for name, body in captured.items():
            path = snapshot / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        verifier = SimpleNamespace(packet=packet)
        for name, rows, receipt in receipts:
            # Also enforce the runner's rejection of unexpected source shards;
            # only its seven named artifacts are copied into the archive.
            LocalScenePilot._verify_saved_part(verifier, root / name, receipt, rows, profile)
            LocalScenePilot._verify_saved_part(verifier, snapshot / name, receipt, rows, profile)

        locations = sum(len(rows) for _name, rows in parts)
        complete = locations == len(packet['rows'])
        manifest = {'contract': CONTRACT, 'packetId': packet['packetId'],
            'packetSha256': packet['payloadSha256'], 'runtimeProfileSha256': profile['sha256'],
            'locations': locations, 'total': len(packet['rows']), 'complete': complete,
            'parts': [name for name, _rows in parts], 'qualityStatus': 'LOCAL_PROVISIONAL',
            'uploaded': False, 'creditsEarned': 0,
            'files': {name: _pin(body) for name, body in sorted(captured.items())}}
        # Portable contributions retain the exact packed vectors, masks, TSV and
        # original hashes. Native resume files can contain personal home paths;
        # normalize their two known path fields in the copy only. This archive
        # is an import/backup artifact, never a replacement for a live checkpoint.
        exported = dict(captured)
        if portable:
            for name, _rows, receipt in receipts:
                prefix = f"{name}/{receipt['attempt']}/"
                for relative in ('checkpoint.json', 'index/manifest.json'):
                    key = prefix + relative
                    document = _json(exported[key])
                    if 'sourceTsv' in document:
                        document['sourceTsv'] = 'locations.tsv'
                    if 'modelDir' in document:
                        document['modelDir'] = 'models/siglip-b16-224-canonical'
                    exported[key] = canonical(document) + b'\n'
                updated = dict(receipt)
                updated['files'] = {relative: _pin(exported[prefix + relative]) for relative in sorted(ARTIFACTS)}
                exported[f'{name}/complete.json'] = canonical(updated) + b'\n'
            manifest.update(contract='vision-local-scene-archive-v2', portable=True,
                resumeFromOriginalsOnly=True, originalFiles=manifest['files'],
                files={name: _pin(body) for name, body in sorted(exported.items())})
        archive = snapshot / 'archive.zip'
        with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_STORED, allowZip64=False) as output:
            for name, body in sorted({**exported, 'export-manifest.json': canonical(manifest) + b'\n'}.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                output.writestr(info, body)
        with archive.open('rb+') as stream:
            stream.flush()
            os.fsync(stream.fileno())
        with archive.open('rb') as stream:
            sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        size = archive.stat().st_size
        # Check every original again, including receipts/profile, and refuse
        # newly completed groups as well as changed or removed source bytes.
        if _completed_parts(root, packet) != parts:
            raise ValueError('saved_work_changed')
        for name, body in captured.items():
            if _read(root / name) != body:
                raise ValueError('saved_work_changed')
        regular(destination, missing=True)
        # A same-filesystem hard link publishes the already complete archive
        # atomically and fails if any file now occupies the destination.
        try:
            os.link(archive, destination)
        except FileExistsError:
            # Repeated Save is safe only for this exact immutable archive.
            # Different/partial files are preserved and never overwritten.
            if not _same_bytes(archive, destination):
                raise ValueError('archive_destination_exists') from None
    return {'path': str(destination), 'locations': locations, 'total': len(packet['rows']),
            'complete': complete, 'sha256': sha256, 'bytes': size}
