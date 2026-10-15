"""One offline issuer of disjoint Scene packets; no accounts or networking."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from .mac_starter import regular

CONTRACT = 'vision-local-scene-packet-v1'
MAX_ROWS = 500_000
MAX_PACKET = 1000
MAX_PACKET_BYTES = 2 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_line(line):
    if not isinstance(line, str) or len(line) > 1500 or any(ord(c) < 32 and c != '\t' for c in line):
        raise ValueError('invalid_location_tsv')
    parts = line.split('\t')
    if len(parts) != 11 or not parts[0] or not re.fullmatch(r'[A-Za-z0-9_-]{4,80}', parts[7]):
        raise ValueError('invalid_location_tsv')
    try:
        values = [float(v) for v in parts[1:7]]
        if (not all(math.isfinite(v) for v in values) or not values[0].is_integer()
                or abs(values[0]) > 2**53-1 or abs(values[1]) > 90 or abs(values[2]) > 180
                or not 0 <= values[3] < 360 or not -90 <= values[4] <= 90 or not 0 <= values[5] <= 5):
            raise ValueError()
    except (ValueError, OverflowError):
        raise ValueError('invalid_location_pose') from None
    return parts[7]


def connection(registry):
    path = regular(registry, missing=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS catalogs(sha TEXT PRIMARY KEY, rows INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS source_rows(source TEXT, ordinal INTEGER, pano TEXT,
          line TEXT NOT NULL, PRIMARY KEY(source,ordinal), UNIQUE(source,pano));
        CREATE TABLE IF NOT EXISTS active(id INTEGER PRIMARY KEY CHECK(id=1), source TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS packets(allocation TEXT PRIMARY KEY, participant TEXT NOT NULL,
          count INTEGER NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assigned(pano TEXT PRIMARY KEY, allocation TEXT NOT NULL);
    ''')
    return db


def prepare_catalog(tsv: Path, registry: Path):
    tsv = regular(tsv)
    if tsv.stat().st_size > 128 * 1024**2:
        raise ValueError('catalog_too_large')
    raw = tsv.read_bytes()
    source = hashlib.sha256(raw).hexdigest()
    rows, seen = [], set()
    for line in raw.decode('utf-8-sig').splitlines():
        if not line.strip() or line.startswith('map_id\t'):
            continue
        pano = validate_line(line)
        if pano in seen:
            raise ValueError('duplicate_panorama')
        seen.add(pano)
        rows.append((source, len(rows), pano, line))
        if len(rows) > MAX_ROWS:
            raise ValueError('catalog_too_large')
    if not rows:
        raise ValueError('empty_catalog')
    db = connection(registry)
    try:
        with db:
            db.execute('INSERT OR IGNORE INTO catalogs VALUES(?,?)', (source, len(rows)))
            db.executemany('INSERT OR IGNORE INTO source_rows VALUES(?,?,?,?)', rows)
            db.execute('INSERT OR REPLACE INTO active VALUES(1,?)', (source,))
    finally:
        db.close()
    return {'sourceSha256': source, 'locations': len(rows)}


def validate_packet(packet):
    expected = {'contract', 'packetId', 'participant', 'sourceSha256', 'lane', 'rows', 'payloadSha256'}
    if not isinstance(packet, dict) or set(packet) != expected:
        raise ValueError('invalid_packet')
    if packet['contract'] != CONTRACT or packet['lane'] != 'scene':
        raise ValueError('invalid_packet')
    for field in ('packetId', 'sourceSha256', 'payloadSha256'):
        if not isinstance(packet[field], str) or not re.fullmatch('[a-f0-9]{64}', packet[field]):
            raise ValueError('invalid_packet')
    if not isinstance(packet['participant'], str) or not re.fullmatch('[A-Za-z0-9_-]{1,48}', packet['participant']):
        raise ValueError('invalid_participant')
    if not isinstance(packet['rows'], list) or not 1 <= len(packet['rows']) <= MAX_PACKET:
        raise ValueError('invalid_packet')
    seen, positions = set(), set()
    for row in packet['rows']:
        if (not isinstance(row, dict) or set(row) != {'id', 'sourceIndex', 'line'}
                or type(row['sourceIndex']) is not int or row['sourceIndex'] < 0):
            raise ValueError('invalid_packet')
        pano = validate_line(row['line'])
        if pano in seen or row['sourceIndex'] in positions or row['id'] != hashlib.sha256(row['line'].encode()).hexdigest():
            raise ValueError('invalid_packet_rows')
        seen.add(pano)
        positions.add(row['sourceIndex'])
    unsigned = {k: v for k, v in packet.items() if k != 'payloadSha256'}
    if packet['payloadSha256'] != digest(unsigned):
        raise ValueError('packet_checksum_mismatch')
    identity = {k: v for k, v in unsigned.items() if k != 'packetId'}
    if packet['packetId'] != digest(identity):
        raise ValueError('packet_identity_mismatch')
    return packet


def load_packet(path):
    path = regular(path)
    if path.stat().st_size > MAX_PACKET_BYTES:
        raise ValueError('packet_too_large')
    return validate_packet(json.loads(path.read_text(encoding='utf-8')))


def export_packet(destination, packet):
    destination = regular(destination, missing=True)
    body = canonical(packet) + b'\n'
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open('xb') as stream:
            stream.write(body)
            stream.flush()
            import os
            os.fsync(stream.fileno())
    except FileExistsError:
        if destination.read_bytes() != body:
            raise ValueError('packet_output_conflict') from None
    return packet


def allocate_packet(registry: Path, participant: str, count: int, allocation_id: str, destination: Path):
    if (not isinstance(participant, str) or not re.fullmatch('[A-Za-z0-9_-]{1,48}', participant)
            or not isinstance(allocation_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', allocation_id)
            or type(count) is not int or not 1 <= count <= MAX_PACKET):
        raise ValueError('invalid_allocation')
    db = connection(registry)
    try:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT participant,count,body FROM packets WHERE allocation=?', (allocation_id,)).fetchone()
        if prior:
            if prior[:2] != (participant, count):
                raise ValueError('allocation_conflict')
            packet = validate_packet(json.loads(prior[2]))
        else:
            active = db.execute('SELECT source FROM active WHERE id=1').fetchone()
            if not active:
                raise ValueError('catalog_required')
            rows = db.execute('''SELECT ordinal,line,pano FROM source_rows s WHERE source=?
                AND NOT EXISTS(SELECT 1 FROM assigned a WHERE a.pano=s.pano)
                ORDER BY ordinal LIMIT ?''', (active[0], count)).fetchall()
            if len(rows) != count:
                raise ValueError('not_enough_unassigned_locations')
            packet = {'contract': CONTRACT, 'participant': participant, 'sourceSha256': active[0],
                'lane': 'scene', 'rows': [{'id': hashlib.sha256(line.encode()).hexdigest(),
                    'sourceIndex': ordinal, 'line': line} for ordinal, line, _pano in rows]}
            packet['packetId'] = digest(packet)
            packet['payloadSha256'] = digest(packet)
            validate_packet(packet)
            db.execute('INSERT INTO packets VALUES(?,?,?,?)', (allocation_id, participant, count, canonical(packet).decode()))
            db.executemany('INSERT INTO assigned VALUES(?,?)', [(pano, allocation_id) for _, _, pano in rows])
        db.commit()  # Keep reservations even if export is interrupted. Reexport this allocation ID.
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    return export_packet(destination, packet)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'assign'))
    parser.add_argument('--registry', required=True, type=Path)
    parser.add_argument('--tsv', type=Path)
    parser.add_argument('--participant')
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--allocation-id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        if not args.tsv:
            parser.error('--tsv is required')
        result = prepare_catalog(args.tsv, args.registry)
    else:
        if not all((args.participant, args.allocation_id, args.output)):
            parser.error('--participant, --allocation-id and --output are required')
        packet = allocate_packet(args.registry, args.participant, args.count, args.allocation_id, args.output)
        result = {'packetId': packet['packetId'], 'locations': len(packet['rows']), 'participant': packet['participant']}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
