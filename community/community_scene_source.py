"""Private, audited Community Scene membership for a separate native import route.

Preserve original native source rows; never manufacture owner MMA completion,
official coverage, protected authority, quality masks, Object approval or credit.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from .object_canary import regular
from .scene_publication_snapshot import seal_publications
from .search_snapshot import digest, encoded, pinned_read, resource_for_environment, write_file

MAX_SOURCE_BYTES = 1024 * 1024
MAX_SOURCE_ROWS = 4096


class CommunitySceneSourceError(ValueError):
    pass


def require(value):
    if not value:
        raise CommunitySceneSourceError('invalid_community_scene_source_membership')


def identity(pose):
    numbers = [pose[key] for key in ('lat', 'lng', 'heading', 'pitch', 'zoom')]
    require(all(type(value) in (int, float) and math.isfinite(value) for value in numbers))
    require(abs(numbers[0]) <= 90 and abs(numbers[1]) <= 180 and abs(numbers[3]) <= 90
            and 0 <= numbers[4] <= 5)
    # Hex retains the binary64 value, including signed zero. Never use distance,
    # rounding, capture date, or pano-only matching to assert Scene completion.
    return (pose['panoId'], pose['country'], pose['cameraGeneration'],
            *(float(value).hex() for value in numbers))


def select_source(raw, members):
    require(0 < len(raw) <= MAX_SOURCE_BYTES and raw.endswith(b'\n'))
    lines = raw.splitlines(keepends=True)
    require(0 < len(lines) <= MAX_SOURCE_ROWS and 0 < len(members) <= MAX_SOURCE_ROWS)
    selected = {}
    for member in members:
        key = identity(member['pose'])
        require(key not in selected)
        selected[key] = member
    source_ids, seen, output, mapping, dialects = set(), set(), [], [], set()
    for ordinal, line in enumerate(lines):
        require(line.endswith(b'\n'))
        body = line[:-2] if line.endswith(b'\r\n') else line[:-1]
        require(b'\r' not in body and b'\n' not in body)
        fields = body.decode('utf-8').split('\t')
        require(len(fields) == 11 and all(not any(ord(c) < 32 for c in field) for field in fields)
                and all(fields[index] and not any(ord(c) < 32 for c in fields[index])
                for index in (0, 1, 7, 8, 9))
                and fields[10] in ('has road name', 'no road name', 'has-road', 'no-road'))
        dialects.add('native-scene-road-labels-v1' if fields[10] in ('has road name', 'no road name')
                     else 'community-hyphen-road-labels-v1')
        require(len(dialects) == 1)
        source_id = tuple(fields[:2])
        require(source_id not in source_ids)
        source_ids.add(source_id)
        pose = dict(zip(('lat', 'lng', 'heading', 'pitch', 'zoom'), map(float, fields[2:7])),
                    panoId=fields[7], country=fields[8], cameraGeneration=fields[9])
        key = identity(pose)
        if key not in selected:
            continue
        require(key not in seen)
        seen.add(key)
        member = selected[key]
        output.append(line)
        mapping.append({'sourceId': fields[0], 'sourceLocationId': fields[1], 'originalSourceRow': ordinal,
                        'communityLocationId': member['locationId'], 'outputSha256': member['outputSha256']})
    require(seen == set(selected))
    return b''.join(output), mapping, next(iter(dialects))


def export_community_scene_source(inventory, inventory_sha256, control, control_sha256, authority,
        authority_sha256, cache, source, source_sha256, destination, *, environment):
    destination = Path(destination).absolute()
    regular(destination.parent, directory=True)
    destination.mkdir(mode=0o700, exist_ok=False)
    try:
        source = regular(source)
        raw = pinned_read(source, source_sha256, MAX_SOURCE_BYTES)
        proof = destination / 'scene-publication-proof'
        receipt = seal_publications(inventory, inventory_sha256, control, control_sha256, authority,
            authority_sha256, cache, proof, environment=environment)
        members_raw = (proof / 'snapshot/members.json').read_bytes()
        members = json.loads(members_raw)
        selected, mapping, dialect = select_source(raw, members)
        require(pinned_read(source, source_sha256, MAX_SOURCE_BYTES) == raw)
        source_pin = write_file(destination / 'scene-source.tsv', selected)
        catalog = {'version': 1, 'scope': 'vision-community-audited-scene-source-v1',
            'environment': environment, 'resource': resource_for_environment(environment),
            'sceneAuthority': 'native-audited-community-publications-not-owner-mma-v1',
            'originalSourceSha256': source_sha256, 'viewsPerLocation': 4, 'rows': len(members),
            'sourceDialect': dialect,
            'originalSourceRowBase': 0,
            'source': {'path': str(destination / 'scene-source.tsv'), **source_pin},
            'publicationReceipt': {'path': str(proof / 'receipt.json'),
                                   'sha256': digest((proof / 'receipt.json').read_bytes())},
            'snapshot': {'path': str(proof / 'snapshot/snapshot.json'), 'sha256': receipt['snapshotSha256']},
            'membersSha256': digest(members_raw), 'mapping': mapping,
            'officialCoverageVerified': False, 'protectedAuthorityVerified': False,
            'objectQualityVerified': False, 'objectImportApproved': False, 'productionQualified': False}
        catalog_raw = encoded(catalog)
        write_file(destination / 'community-scene-catalog.private.json', catalog_raw)
        report = {'version': 1, 'status': 'AUDITED_COMMUNITY_SCENE_SOURCE_EXPORTED', 'locations': len(members),
            'catalogSha256': digest(catalog_raw), 'sourceSha256': source_pin['sha256'],
            'snapshotSha256': receipt['snapshotSha256'], 'ownerMmaMembershipAsserted': False,
            'sourceDialect': dialect,
            'objectImportApproved': False, 'productionQualified': False, 'networkUsed': False,
            'newCreditGranted': 0}
        write_file(destination / 'receipt.json', encoded(report))
        return report
    except Exception:
        write_file(destination / 'failure-report.json', encoded({'complete': False,
            'code': 'community_scene_source_export_failed', 'objectImportApproved': False}))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inventory', 'control', 'authority', 'source'):
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--environment', choices=('staging', 'production'), required=True)
    args = parser.parse_args()
    try:
        report = export_community_scene_source(args.inventory, args.inventory_sha256, args.control,
            args.control_sha256, args.authority, args.authority_sha256, args.cache, args.source,
            args.source_sha256, args.output, environment=args.environment)
    except Exception:
        print(json.dumps({'complete': False, 'code': 'community_scene_source_export_failed'}))
        return 1
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
