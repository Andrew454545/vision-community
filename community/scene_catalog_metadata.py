"""Offline Scene catalog preparation; no imagery, model or provider calls.

Generation rules follow Andrew's pinned VISION catalog validator. They are
search classifications, not proof of official coverage or Object eligibility.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from .rank import canonicalize_country

REFERENCE_REVISION = '9811448e3e05259e08f5106ab5a7740dce0c6b4a'
CLASSIFICATION_POLICY = 'vision-camera-metadata-9811448-v1'
GEN2_COUNTRIES = frozenset('AD AU BE BR CA CH CL CZ DE DK ES FI FR GB GR HK IE IM IT JE JP LU MC MO MX NL NZ PL PT RO RU SE SG SJ SM TW US ZA'.split())
BAD_AFTER = {'BD': (2021, 4), 'EC': (2022, 3), 'FI': (2020, 9), 'IN': (2021, 10),
             'KH': (2022, 10), 'LB': (2021, 1), 'LK': (2021, 2), 'NG': (2021, 6),
             'NP': (2020, 1), 'VN': (2020, 1),
             **dict.fromkeys('AT BG CZ DK EE ES FR GB GR HR IT LT LV PL PT RO SE'.split(), (2021, 1))}
MAX_INPUT = 128 * 1024 * 1024
MAX_ROWS = 500000
COUNTRIES = Path(__file__).with_name('data') / 'vision-country-codes.tsv'
COUNTRY_AUTHORITY_SHA256 = 'f9e4d66dcec953865b14626d956d45fd1e72b0a3bcf6f07bf72fdad7337dd8f8'
FIELDS = {'pano_id', 'lat', 'lng', 'heading', 'pitch', 'zoom', 'country', 'country_code',
          'capture_year', 'capture_month', 'image_height', 'camera_source', 'has_level_id',
          'road_name_state', 'source_row', 'map_id', 'camera_generation'}
REQUIRED = {'pano_id', 'lat', 'lng', 'country_code', 'capture_year', 'capture_month', 'image_height'}


class MetadataError(ValueError):
    pass


def classify_generation(*, height, country_code, year, month, latitude, source='', has_level_id=False):
    """Preserve the reference validator's ordering and strict cutoff boundaries."""
    if (type(height) is not int or type(year) is not int or type(month) is not int
            or not 2000 <= year <= datetime.now(timezone.utc).year + 1 or not 1 <= month <= 12
            or type(latitude) not in (int, float) or not math.isfinite(latitude) or abs(latitude) > 90
            or not isinstance(country_code, str) or not re.fullmatch('[A-Z]{2}', country_code)
            or type(has_level_id) is not bool or not isinstance(source, str)):
        return {'generation': 'unknown', 'basis': 'insufficient-metadata'}
    scout = source.casefold() == 'scout'
    if height == 1664:
        return {'generation': 'gen1', 'basis': 'image-height'}
    if height == 8192:
        return {'generation': 'trekker' if scout else 'gen4', 'basis': 'image-height-and-source'}
    if height != 6656:
        return {'generation': 'unknown', 'basis': 'unsupported-image-height'}
    date = (year, month)
    bad = year > 2000 and (country_code in {'CY', 'ST'} or country_code in BAD_AFTER and date > BAD_AFTER[country_code]
                          or country_code == 'US' and latitude > 52 and date > (2019, 1))
    if bad:
        return {'generation': 'badcam', 'basis': 'country-date-latitude-heuristic'}
    if has_level_id:
        return {'generation': 'unknown', 'basis': 'indoor-level-ambiguous'}
    if scout:
        return {'generation': 'trekker', 'basis': 'camera-source'}
    return {'generation': 'gen2' if country_code in GEN2_COUNTRIES and date <= (2011, 11) else 'gen3',
            'basis': 'country-date-heuristic'}


def country_authority():
    if hashlib.sha256(COUNTRIES.read_bytes()).hexdigest() != COUNTRY_AUTHORITY_SHA256:
        raise MetadataError('country_authority_changed')
    with COUNTRIES.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    result = {row['country_code']: row['country'] for row in rows}
    if len(result) != len(rows) or any(not re.fullmatch('[A-Z]{2}', code) or not name for code, name in result.items()):
        raise MetadataError('invalid_country_authority')
    return result


def number(row, name, default=None, maximum=None):
    value = row.get(name, '')
    try:
        value = float(value) if value else default
    except (ValueError, TypeError):
        raise MetadataError('invalid_pose') from None
    if value is None or not math.isfinite(value) or maximum is not None and abs(value) > maximum:
        raise MetadataError('invalid_pose')
    return 0.0 if value == 0 else value


def metadata_row(row, ordinal, countries):
    if None in row or any(not isinstance(value, str) or len(value) > 1000 or any(ord(c) < 32 for c in value)
                          for value in row.values()):
        raise MetadataError('invalid_metadata_row')
    pano = row['pano_id']
    if not re.fullmatch('[A-Za-z0-9_-]{4,80}', pano):
        raise MetadataError('invalid_pano_id')
    code = row['country_code']
    country = countries.get(code)
    if not country or row.get('country') and canonicalize_country(row['country']) != country:
        raise MetadataError('country_metadata_mismatch')
    lat, lng = number(row, 'lat', maximum=90), number(row, 'lng', maximum=180)
    heading, pitch, zoom = number(row, 'heading', 0), number(row, 'pitch', 0, 90), number(row, 'zoom', 0)
    if not 0 <= heading < 360 or not 0 <= zoom <= 5:
        raise MetadataError('invalid_pose')
    values = []
    for name in ('image_height', 'capture_year', 'capture_month'):
        value = row[name]
        if value and not re.fullmatch('[0-9]{1,6}', value):
            raise MetadataError('invalid_capture_metadata')
        values.append(int(value) if value else 0)
    height, year, month = values
    level = row.get('has_level_id', '')
    if level not in ('', '0', '1', 'false', 'true'):
        raise MetadataError('invalid_level_metadata')
    source = row.get('camera_source', '')
    classified = classify_generation(height=height, country_code=code, year=year, month=month,
                                     latitude=lat, source=source, has_level_id=level in ('1', 'true'))
    supplied = row.get('camera_generation', '')
    if supplied and supplied not in ('unknown', 'gen2or3', classified['generation']):
        raise MetadataError('supplied_generation_conflict')
    road = row.get('road_name_state') or 'unknown'
    if road not in ('no road name', 'has road name', 'unknown'):
        raise MetadataError('invalid_road_metadata')
    # A supplied saved heading is kept exactly; no inferred car-front bearing.
    source_row = row.get('source_row') or str(ordinal)
    if not re.fullmatch('[0-9]{1,15}', source_row):
        raise MetadataError('invalid_source_row')
    fields = [row.get('map_id') or 'vision-community', source_row,
              format(lat, '.15g'), format(lng, '.15g'), format(heading, '.15g'),
              format(pitch, '.15g'), format(zoom, '.15g'), pano, country, classified['generation'], road]
    evidence = {'row': ordinal, 'panoId': pano, 'countryCode': code, 'country': country,
                'captureYear': year, 'captureMonth': month, 'imageHeight': height,
                'cameraSource': source, 'hasLevelId': level in ('1', 'true'),
                'classification': classified, 'policy': CLASSIFICATION_POLICY,
                'officialCoverageVerified': False, 'objectEligibilityGranted': False}
    return '\t'.join(fields) + '\n', evidence


def prepare_catalog(source, expected_sha256, destination):
    """Write a new finite shard, evidence sidecar and last-written manifest."""
    source, destination = Path(source), Path(destination)
    if not re.fullmatch('[a-f0-9]{64}', expected_sha256):
        raise MetadataError('input_pin_required')
    if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= MAX_INPUT:
        raise MetadataError('input_limit')
    with source.open('rb') as stream:
        raw_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if raw_digest != expected_sha256:
        raise MetadataError('input_digest_mismatch')
    destination.mkdir(parents=True, exist_ok=False)
    try:
        counts, count, seen = {}, 0, set()
        with source.open(encoding='utf-8', newline='') as src, (destination / 'locations.tsv').open('x', encoding='utf-8', newline='') as out, (destination / 'metadata.jsonl').open('x', encoding='utf-8', newline='') as evidence:
            reader = csv.DictReader(src, delimiter='\t')
            headers = reader.fieldnames or []
            if not REQUIRED <= set(headers) or not set(headers) <= FIELDS or len(set(headers)) != len(headers):
                raise MetadataError('invalid_metadata_headers')
            countries = country_authority()
            for count, row in enumerate(reader, 1):
                if count > MAX_ROWS:
                    raise MetadataError('row_limit')
                line, record = metadata_row(row, count, countries)
                if record['panoId'] in seen:
                    raise MetadataError('duplicate_panorama')
                seen.add(record['panoId'])
                out.write(line)
                evidence.write(json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n')
                camera = record['classification']['generation']
                counts[camera] = counts.get(camera, 0) + 1
        if not count:
            raise MetadataError('empty_catalog')
        with source.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected_sha256:
                raise MetadataError('source_changed')
        files = {}
        for name in ('locations.tsv', 'metadata.jsonl'):
            with (destination / name).open('rb') as stream:
                files[name] = {'bytes': (destination / name).stat().st_size,
                               'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
        manifest = {'version': 1, 'policy': CLASSIFICATION_POLICY, 'referenceRevision': REFERENCE_REVISION,
                    'inputSha256': expected_sha256, 'countryAuthoritySha256': hashlib.sha256(COUNTRIES.read_bytes()).hexdigest(),
                    'locations': count, 'generations': counts, 'files': files,
                    'metadataSource': 'operator-supplied', 'officialCoverageVerified': False,
                    'objectEligibilityGranted': False, 'imageryStored': False, 'networkRequests': 0,
                    'indexed': False, 'published': False, 'creditsGranted': 0}
        with (destination / 'manifest.json').open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, indent=2)
        return manifest
    except Exception as failure:
        code = str(failure) if isinstance(failure, MetadataError) else 'catalog_preparation_failed'
        with (destination / 'failure-report.json').open('x', encoding='utf-8') as stream:
            json.dump({'sealed': False, 'reason': code, 'networkRequests': 0}, stream)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--input-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_catalog(args.input, args.input_sha256, args.output)))


if __name__ == '__main__':
    main()
