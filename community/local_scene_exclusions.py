"""Offline reconciliation of retained Scene inventory and unused owner-filtered shards.

Reads saved metadata responses only. It does not reserve Cloudflare rows or keep
an online allocator synchronized: retain the cloud hold while issuing offline work.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from .local_scene_packets import canonical, digest
from .local_scene_pilot import immutable
from .mac_starter import regular


def pinned_document(path, checksum, limit=8 * 1024**2):
    path = regular(path)
    if path.stat().st_size > limit:
        raise ValueError('metadata_inventory_too_large')
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != checksum:
        raise ValueError('metadata_inventory_changed')
    return json.loads(body)


def inventory(value):
    if not value.get('success') or len(value.get('result', [])) != 1:
        raise ValueError('incomplete_saved_metadata_response')
    result = value['result'][0]
    if (result.get('success') is not True or result.get('meta', {}).get('rows_written') != 0
            or len(result.get('results', [])) != 1):
        raise ValueError('incomplete_saved_metadata_response')
    data = json.loads(result['results'][0]['inventory'])
    if (set(data) != {'panoramaIds', 'catalog'} or not isinstance(data['panoramaIds'], list)
            or not isinstance(data['catalog'], list)):
        raise ValueError('incomplete_saved_metadata_response')
    return data


def reconcile(pool, production, staging, historical, selected, cutoff, destination):
    """Complete only for explicitly selected, never-advanced replacement shards.

    Historical pre-cutover identities cover retired catalog families. Retaining
    every ID in both current inventories excludes pending/failed work as well as
    successful contributions. Quarantining whole advanced replacement shards
    avoids trusting surviving rows as a complete record of later assignments.
    """
    if datetime.fromisoformat(cutoff.replace('Z', '+00:00')).utcoffset() is None:
        raise ValueError('utc_exclusion_cutoff_required')
    allocation = pool.get('allocation', {})
    if (pool.get('contract') != 'vision-community-pose-catalog-v1'
            or type(allocation.get('excludedLocalRows')) is not int or allocation['excludedLocalRows'] < 1
            or allocation.get('excludedReservedRows') != 5_000_000
            or allocation.get('duplicateSourceRows') != 0
            or not isinstance(pool.get('shards'), list) or not pool['shards']):
        raise ValueError('owner_filtered_pool_required')
    prod, stage = inventory(production), inventory(staging)
    approved = {s['sha256']: s for s in pool['shards']}
    catalog = {s['sha256']: s for s in prod['catalog']}
    if (len(approved) != len(pool['shards']) or len(catalog) != len(prod['catalog'])
            or set(approved) != set(catalog)):
        raise ValueError('replacement_catalog_inventory_incomplete')
    for sha, entry in catalog.items():
        if (entry['key'] != approved[sha]['key'] or entry['rowCount'] != approved[sha]['rows']
                or type(entry['nextRow']) is not int or not 0 <= entry['nextRow'] <= entry['rowCount']):
            raise ValueError('replacement_catalog_inventory_changed')
    if (not selected or len(selected) != len(set(selected))
            or any(s not in approved or catalog[s]['nextRow'] != 0 for s in selected)):
        raise ValueError('unused_source_shards_required')
    historical = regular(historical)
    if historical.stat().st_size == 0 or historical.stat().st_size > 64 * 1024**2:
        raise ValueError('retained_pre_cutover_history_required')
    ids = set(prod['panoramaIds']) | set(stage['panoramaIds'])
    with historical.open(encoding='ascii') as stream:
        for line in stream:
            ids.add(line.strip())
    if any(not isinstance(i, str) or not re.fullmatch('[A-Za-z0-9_-]{4,80}', i) for i in ids):
        raise ValueError('invalid_exclusion_identity')
    body = ''.join(i + '\n' for i in sorted(ids)).encode('ascii')
    with historical.open('rb') as stream:
        historical_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    authority = {'contract': 'vision-local-scene-exclusions-v1', 'complete': True,
        'scope': 'SELECTED_UNUSED_OWNER_FILTERED_SHARDS_ONLY', 'onlineAllocatorMustRemainPaused': True,
        'ownerIndexed': digest({'poolSource': pool['sourceSha256'], 'excluded': allocation['excludedLocalRows']}),
        'ownerReserved': digest({'poolSource': pool['sourceSha256'], 'excluded': allocation['excludedReservedRows']}),
        'communityProduction': digest(production), 'communityStaging': digest(staging),
        'historicalInventorySha256': historical_sha,
        'cutoff': cutoff, 'sources': sorted(selected), 'rows': len(ids), 'sha256': hashlib.sha256(body).hexdigest(),
        'quarantinedAdvancedShards': sum(s['nextRow'] > 0 for s in prod['catalog'])}
    destination = regular(destination, directory=True, missing=True)
    destination.mkdir(parents=True, exist_ok=True)
    immutable(destination / 'excluded-panorama-ids.private.txt', body)
    immutable(destination / 'exclusion-authority.private.json', canonical(authority) + b'\n')
    return authority


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('pool', 'production', 'staging'):
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--historical-ids', type=Path, required=True)
    parser.add_argument('--source-sha256', action='append', required=True)
    parser.add_argument('--cutoff', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    authority = reconcile(*[pinned_document(getattr(args, name), getattr(args, name + '_sha256'))
        for name in ('pool', 'production', 'staging')], args.historical_ids,
        args.source_sha256, args.cutoff, args.output)
    print(json.dumps({'rows': authority['rows'], 'sha256': authority['sha256'],
                      'approvedSources': len(authority['sources']), 'scope': authority['scope']}))


if __name__ == '__main__':
    main()
