"""Large offline Scene allocations: one issuer, bounded packets, no cloud leases."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from .local_scene_packets import (canonical, connection, digest, export_packet,
                                  load_packet, validate_packet)
from .mac_starter import regular

CONTRACT = 'vision-local-scene-campaign-v1'
MAX_LOCATIONS = 5_000_000
PACKET_LOCATIONS = 128
MAX_MANIFEST = 16 * 1024 * 1024


def campaign_connection(path):
    db = connection(path)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS excluded(pano TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS exclusion_authority(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY, participant TEXT NOT NULL,
          locations INTEGER NOT NULL, body TEXT NOT NULL);
    ''')
    return db


def import_exclusions(registry, ids_path, authority):
    """Owner supplies complete retained history, never just successful publications."""
    path = regular(ids_path)
    if (authority.get('contract') != 'vision-local-scene-exclusions-v1'
            or authority.get('complete') is not True
            or not all(authority.get(k) for k in ('ownerIndexed', 'ownerReserved',
                                                 'communityProduction', 'communityStaging', 'cutoff'))):
        raise ValueError('complete_exclusion_authority_required')
    sources = authority.get('sources')
    if (not isinstance(sources, list) or not 1 <= len(sources) <= 1000
            or any(not isinstance(s, str) or not re.fullmatch('[a-f0-9]{64}', s) for s in sources)):
        raise ValueError('approved_catalog_sources_required')
    db = campaign_connection(registry)
    count = 0
    hashed = hashlib.sha256()
    try:
        db.execute('BEGIN IMMEDIATE')
        with path.open('rb') as stream:
            for raw in stream:
                hashed.update(raw)
                pano = raw.decode('ascii').strip()
                if not re.fullmatch('[A-Za-z0-9_-]{4,80}', pano):
                    raise ValueError('invalid_excluded_panorama')
                db.execute('INSERT OR IGNORE INTO excluded VALUES(?)', (pano,))
                count += 1
        if count != authority.get('rows') or hashed.hexdigest() != authority.get('sha256'):
            raise ValueError('exclusion_inventory_mismatch')
        db.execute('INSERT OR REPLACE INTO exclusion_authority VALUES(1,?)', (canonical(authority).decode(),))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    return {'rows': count, 'sha256': hashed.hexdigest()}


def validate_manifest(value):
    if (not isinstance(value, dict) or value.get('contract') != CONTRACT
            or set(value) != {'contract', 'campaignId', 'participant', 'locations', 'packets',
                              'exclusionAuthoritySha256', 'approvals', 'sha256'}
            or not re.fullmatch('[A-Za-z0-9_-]{1,80}', str(value.get('campaignId', '')))
            or not re.fullmatch('[A-Za-z0-9_-]{1,48}', str(value.get('participant', '')))
            or type(value.get('locations')) is not int or not 1 <= value['locations'] <= MAX_LOCATIONS
            or not re.fullmatch('[a-f0-9]{64}', str(value.get('exclusionAuthoritySha256', '')))
            or not isinstance(value.get('approvals'), list) or not 1 <= len(value['approvals']) <= 3
            or not isinstance(value.get('packets'), list)
            or len(value['packets']) != (value['locations'] + PACKET_LOCATIONS - 1) // PACKET_LOCATIONS
            or digest({k: v for k, v in value.items() if k != 'sha256'}) != value.get('sha256')):
        raise ValueError('invalid_scene_campaign')
    total, seen = 0, set()
    for i, packet in enumerate(value['packets']):
        if (not isinstance(packet, dict) or set(packet) != {'path', 'sha256', 'packetId', 'locations'}
                or packet['path'] != f'packets/{i:06d}.json'
                or type(packet['locations']) is not int or packet['locations'] != min(PACKET_LOCATIONS, value['locations'] - total)
                or any(not re.fullmatch('[a-f0-9]{64}', str(packet[k])) for k in ('sha256', 'packetId'))
                or packet['packetId'] in seen):
            raise ValueError('invalid_campaign_packet')
        total += packet['locations']
        seen.add(packet['packetId'])
    if total != value['locations']:
        raise ValueError('invalid_campaign_size')
    return value


def load_manifest(path):
    path = regular(path)
    if path.stat().st_size > MAX_MANIFEST:
        raise ValueError('campaign_manifest_too_large')
    return validate_manifest(json.loads(path.read_text()))


def campaign_packet(folder, manifest, index):
    entry = manifest['packets'][index]
    path = regular(Path(folder) / entry['path'])
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('campaign_packet_too_large')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('campaign_packet_changed')
    packet = load_packet(path)
    if (packet['packetId'] != entry['packetId'] or len(packet['rows']) != entry['locations']
            or packet['participant'] != manifest['participant']):
        raise ValueError('campaign_packet_changed')
    return path


def allocate_campaign(registry, participant, count, allocation_id, approvals, destination=None):
    """Commit all reservations before writing any packet. A failed delivery is retained."""
    if (not re.fullmatch('[A-Za-z0-9_-]{1,48}', participant)
            or not re.fullmatch('[A-Za-z0-9_-]{1,80}', allocation_id)
            or type(count) is not int or not 1 <= count <= MAX_LOCATIONS):
        raise ValueError('invalid_campaign_allocation')
    from .local_scene_qualification import validate_approval
    if not isinstance(approvals, list) or not 1 <= len(approvals) <= 3:
        raise ValueError('local_scene_approval_required')
    devices, profiles = set(), set()
    for approval in approvals:
        validate_approval(approval, approval.get('installationId'), approval.get('runtimeProfile'))
        devices.add(approval['installationId'])
        profiles.add(approval['inferenceThreads'])
    if len(devices) != 1 or len(profiles) != len(approvals) or 1 not in profiles:
        raise ValueError('campaign_approval_profiles_invalid')
    db = campaign_connection(registry)
    try:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT participant,locations,body FROM campaigns WHERE id=?', (allocation_id,)).fetchone()
        if prior:
            manifest = validate_manifest(json.loads(prior[2]))
            if prior[:2] != (participant, count) or manifest['approvals'] != approvals:
                raise ValueError('campaign_allocation_conflict')
        else:
            row = db.execute('SELECT body FROM exclusion_authority WHERE id=1').fetchone()
            if not row:
                raise ValueError('complete_exclusion_authority_required')
            authority = json.loads(row[0])
            sources = authority.get('sources')
            if not isinstance(sources, list) or not sources:
                raise ValueError('approved_catalog_sources_required')
            manifest = {'contract': CONTRACT, 'campaignId': allocation_id, 'participant': participant,
                        'locations': count, 'packets': [], 'approvals': approvals,
                        'exclusionAuthoritySha256': digest(authority)}
            after, allocated = 0, 0
            while allocated < count:
                chosen = []
                while len(chosen) < min(PACKET_LOCATIONS, count - allocated):
                    rows = db.execute('''SELECT s.rowid,s.source,s.ordinal,s.line,s.pano FROM source_rows s
                        WHERE s.rowid>? AND NOT EXISTS(SELECT 1 FROM assigned a WHERE a.pano=s.pano)
                        AND NOT EXISTS(SELECT 1 FROM excluded e WHERE e.pano=s.pano)
                        AND s.source IN (SELECT value FROM json_each(?))
                        ORDER BY s.rowid LIMIT ?''', (after, canonical(sources).decode(),
                            min(PACKET_LOCATIONS - len(chosen), count - allocated))).fetchall()
                    if not rows:
                        raise ValueError('not_enough_unassigned_locations')
                    number = len(manifest['packets'])
                    allocation = f'{allocation_id}:{number}'
                    for rowid, source, ordinal, line, pano in rows:
                        after = rowid
                        if db.execute('INSERT OR IGNORE INTO assigned VALUES(?,?)', (pano, allocation)).rowcount:
                            chosen.append((source, ordinal, line))
                source_pin = digest(sorted({source for source, _ordinal, _line in chosen}))
                # Ordinals are packet-local; original native source ID remains in each exact TSV line.
                packet = {'contract': 'vision-local-scene-packet-v1', 'participant': participant,
                          'sourceSha256': source_pin, 'lane': 'scene',
                          'rows': [{'id': hashlib.sha256(line.encode()).hexdigest(),
                                    'sourceIndex': allocated + i, 'line': line}
                                   for i, (_source, _ordinal, line) in enumerate(chosen)]}
                packet['packetId'] = digest(packet)
                packet['payloadSha256'] = digest(packet)
                validate_packet(packet)
                db.execute('INSERT INTO packets VALUES(?,?,?,?)',
                           (allocation, participant, len(chosen), canonical(packet).decode()))
                manifest['packets'].append({'path': f'packets/{number:06d}.json',
                    'sha256': hashlib.sha256(canonical(packet) + b'\n').hexdigest(),
                    'packetId': packet['packetId'], 'locations': len(chosen)})
                allocated += len(chosen)
            manifest['sha256'] = digest(manifest)
            validate_manifest(manifest)
            db.execute('INSERT INTO campaigns VALUES(?,?,?,?)',
                       (allocation_id, participant, count, canonical(manifest).decode()))
        db.commit()
        if destination is None:
            return manifest  # Durable reservation; stream a portable delivery separately.
        destination = regular(destination, directory=True, missing=True)
        destination.mkdir(parents=True, exist_ok=True)
        for number, entry in enumerate(manifest['packets']):
            row = db.execute('SELECT body FROM packets WHERE allocation=?', (f'{allocation_id}:{number}',)).fetchone()
            export_packet(destination / entry['path'], json.loads(row[0]))
        from .local_scene_pilot import immutable
        immutable(destination / 'campaign.json', canonical(manifest) + b'\n')
        return manifest
    except BaseException:
        db.rollback()  # A post-commit delivery failure deliberately keeps every reservation.
        raise
    finally:
        db.close()


def export_campaign_zip(registry, allocation_id, destination):
    """Stream retained packets into one delivery ZIP, without an unpacked duplicate."""
    import os
    import tempfile
    import zipfile
    destination = regular(destination, missing=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with campaign_connection(registry) as db:
        row = db.execute('SELECT body FROM campaigns WHERE id=?', (allocation_id,)).fetchone()
        if not row:
            raise ValueError('unknown_campaign')
        manifest = validate_manifest(json.loads(row[0]))
        with tempfile.TemporaryDirectory(prefix='.scene-delivery-', dir=destination.parent) as temporary:
            pending = Path(temporary) / 'queue.zip'
            with zipfile.ZipFile(pending, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
                def write(name, body):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100600 << 16
                    archive.writestr(info, body)
                write('campaign.json', canonical(manifest) + b'\n')
                write('START-HERE.txt', b'Extract this whole folder. Open VISION Local Scenes and choose campaign.json.\nKeep the packets folder together with it. Nothing starts until you choose Start.\n')
                for number, entry in enumerate(manifest['packets']):
                    saved = db.execute('SELECT body FROM packets WHERE allocation=?',
                                       (f'{allocation_id}:{number}',)).fetchone()
                    if not saved:
                        raise ValueError('retained_campaign_packet_missing')
                    body = saved[0].encode('utf-8') + b'\n'
                    if hashlib.sha256(body).hexdigest() != entry['sha256']:
                        raise ValueError('retained_campaign_packet_changed')
                    write(entry['path'], body)
            with pending.open('rb') as stream:
                checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            size = pending.stat().st_size
            if destination.exists():
                with regular(destination).open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != checksum:
                        raise ValueError('campaign_delivery_conflict')
            else:
                os.link(pending, destination)
    return {'path': str(destination), 'bytes': size, 'sha256': checksum,
            'campaignId': allocation_id, 'locations': manifest['locations']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('exclude', 'assign'))
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--ids', type=Path)
    parser.add_argument('--authority', type=Path)
    parser.add_argument('--participant')
    parser.add_argument('--count', type=int, default=MAX_LOCATIONS)
    parser.add_argument('--allocation-id')
    parser.add_argument('--approvals', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'exclude':
        if not args.ids or not args.authority:
            parser.error('--ids and --authority required')
        result = import_exclusions(args.registry, args.ids, json.loads(regular(args.authority).read_text()))
    else:
        if not all((args.participant, args.allocation_id, args.approvals, args.output)):
            parser.error('--participant, --allocation-id, --approvals and --output required')
        result = allocate_campaign(args.registry, args.participant, args.count, args.allocation_id,
                                   json.loads(regular(args.approvals).read_text()), args.output)
        result = {'campaignId': result['campaignId'], 'locations': result['locations'],
                  'packets': len(result['packets']), 'sha256': result['sha256']}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
