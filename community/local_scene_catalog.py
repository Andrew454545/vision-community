"""Prepare/apply additive segments for the owner's existing VISION v2 catalog.

No inference or job restart. Applying requires paused catalog writers and keeps
complete before/after copies. Only assignment-checked owner imports are accepted.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile

from .four_view import BYTES_PER_LOCATION
from .local_scene_library import SceneLibrary
from .local_scene_packets import canonical
from .local_scene_pilot import MANIFEST, immutable
from .mac_starter import regular
from .vision_index import file_identity

FILES = {'locations.tsv', 'checkpoint.json', 'index/manifest.json',
         'index/shard-000000.i8', 'index/shard-000000.mask'}


def read_json(path, limit=16*1024*1024):
    path = regular(path)
    if path.stat().st_size > limit:
        raise ValueError('owner_catalog_too_large')
    raw = path.read_bytes()
    return raw, json.loads(raw)


def prefix_hash(path, length):
    result = hashlib.sha256()
    with regular(path).open('rb') as source:
        while length:
            block = source.read(min(1024*1024, length))
            if not block:
                raise ValueError('owner_catalog_prefix_changed')
            length -= len(block)
            result.update(block)
    return result.hexdigest()


def merge_catalog(base, sources, library_id):
    if (not isinstance(base, dict) or base.get('version') != 2 or not isinstance(base.get('sources'), list)
            or any(not isinstance(s, dict) or not isinstance(s.get('id'), str) for s in base['sources'])
            or len({s['id'] for s in base['sources']}) != len(base['sources'])):
        raise ValueError('owner_version2_catalog_required')
    if any(s.get('communityLibraryId') not in (None, library_id) for s in base['sources']):
        raise ValueError('one_authoritative_owner_library_required')
    result = copy.deepcopy(base)
    positions = {s['id']:i for i,s in enumerate(result['sources'])}
    for source in sources:
        previous = result['sources'][positions[source['id']]] if source['id'] in positions else None
        if previous:
            if previous.get('communityLibraryId') != library_id or source['processedLocations'] < previous['processedLocations']:
                raise ValueError('owner_catalog_source_conflict')
            # Replace a growing last segment only if all previously published
            # source rows and vector bytes remain an exact prefix.
            old_tsv = regular(Path(previous['sourceTsv']))
            old_vectors = regular(Path(previous['indexDir'])/'shard-000000.i8')
            size = previous['processedLocations']*BYTES_PER_LOCATION
            if (old_vectors.stat().st_size != size
                    or prefix_hash(Path(source['sourceTsv']), old_tsv.stat().st_size) != file_identity(old_tsv)['sha256']
                    or prefix_hash(Path(source['indexDir'])/'shard-000000.i8', size) != file_identity(old_vectors)['sha256']):
                raise ValueError('owner_catalog_prefix_changed')
            result['sources'][positions[source['id']]] = source
        else:
            positions[source['id']] = len(result['sources'])
            result['sources'].append(source)
    result['processedLocations'] = sum(s['processedLocations'] for s in result['sources'])
    return result


def prepare_catalog(library, models, base_path, base_sha, output):
    base_raw, base = read_json(base_path)
    if hashlib.sha256(base_raw).hexdigest() != base_sha:
        raise ValueError('owner_catalog_changed')
    if not isinstance(base, dict) or base.get('version') != 2 or not isinstance(base.get('sources'), list):
        raise ValueError('owner_version2_catalog_required')
    with library.writing(), library._db() as db:
        roots = {Path(r[0]).parents[1] for r in db.execute('SELECT path FROM sources')}
        if not roots:
            raise ValueError('owner_imported_library_required')
        for root in roots:
            try:
                relative = root.relative_to(library.root/'imports')
            except ValueError:
                raise ValueError('owner_imported_library_required') from None
            if len(relative.parts) != 1:
                raise ValueError('owner_imported_library_required')
            _, receipt = read_json(root/'import-receipt.json', 32*1024)
            if (receipt.get('contract') != 'vision-local-scene-import-v1'
                    or receipt.get('archiveSha256') != root.name
                    or receipt.get('scope') != 'QUALIFIED_DEVICE_OUTPUT_NOT_RECOMPUTED'):
                raise ValueError('owner_imported_library_required')
        models = regular(models, directory=True)
        runtime = json.loads(MANIFEST.read_text())
        for item in runtime['files']:
            if item['path'].startswith('models/'):
                if file_identity(regular(models/Path(item['path']).name)) != {'bytes':item['bytes'], 'sha256':item['sha256']}:
                    raise ValueError('owner_canonical_models_required')
        identity = regular(library.root/'owner-publication-id.json', missing=True)
        if not identity.exists():
            immutable(identity, canonical({'id':secrets.token_hex(32)})+b'\n')
        _, document = read_json(identity, 4096)
        library_id = document['id']
        segments, total = library._segments(models)
        output = regular(output, directory=True, missing=True)
        if any(output == p or p in output.parents for p in (models, library.root/'segments', library.root/'imports')):
            raise ValueError('owner_output_overlaps_inputs')
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        sources = []
        for number, source in enumerate(segments):
            raw, manifest = read_json(source/'index/manifest.json')
            content = hashlib.sha256(raw).hexdigest()
            destination = regular(output/'segments'/content, directory=True, missing=True)
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='.building-', dir=destination.parent) as temporary:
                    stage = Path(temporary)
                    (stage/'index').mkdir()
                    for name in ('locations.tsv', 'index/shard-000000.i8', 'index/shard-000000.mask'):
                        original = regular(source/name)
                        try:
                            os.link(original, stage/name)
                        except OSError:
                            shutil.copyfile(original, stage/name)
                        if file_identity(stage/name) != file_identity(original):
                            raise ValueError('owner_segment_copy_changed')
                    rebound = {**manifest, 'sourceTsv':str(destination/'locations.tsv'), 'modelDir':str(models)}
                    immutable(stage/'index/manifest.json', canonical(rebound)+b'\n')
                    immutable(stage/'checkpoint.json', canonical({**rebound, 'nextLocationIndex':manifest['totalLocations'],
                        'nextInputOffset':manifest['sourceBytes'], 'fetchErrors':0, 'inferenceErrors':0,
                        'incompleteLocations':0, 'producer':'BYTE_COPY_OF_QUALIFIED_DEVICE_OUTPUT'})+b'\n')
                    immutable(stage/'community-segment.json', canonical({'version':1,
                        'files':{n:file_identity(stage/n) for n in sorted(FILES)}})+b'\n')
                    stage.rename(destination)
            _, proof = read_json(destination/'community-segment.json', 32*1024)
            if set(proof.get('files', {})) != FILES:
                raise ValueError('owner_segment_changed')
            for name, pin in proof['files'].items():
                if file_identity(regular(destination/name)) != pin:
                    raise ValueError('owner_segment_changed')
            sources.append({'id':f'community-local-{library_id[:20]}-{number:06d}',
                'label':f'Community Scenes {number+1}', 'processedLocations':manifest['totalLocations'],
                'totalLocations':manifest['totalLocations'], 'sourceTsv':str(destination/'locations.tsv'),
                'indexDir':str(destination/'index'), 'manifestPath':str(destination/'index/manifest.json'),
                'checkpointPath':str(destination/'checkpoint.json'), 'viewsPerLocation':4, 'sourceColumnCount':11,
                'storage':'local', 'evictAfterSearch':False, 'communityLibraryId':library_id})
        merged = merge_catalog(base, sources, library_id)
        immutable(output/'catalog.before.json', base_raw)
        immutable(output/'catalog.next.json', canonical(merged)+b'\n')
        plan = {'version':1, 'baseCatalog':str(regular(base_path)), 'baseSha256':base_sha,
            'nextSha256':file_identity(output/'catalog.next.json')['sha256'], 'communityLocations':total,
            'nativeInferenceRuns':0, 'cloudCalls':0, 'requiresPausedCatalogWriters':True}
        immutable(output/'catalog-update-plan.json', canonical(plan)+b'\n')
        return plan


def apply_catalog(plan, output, *, writers_paused=False):
    if not writers_paused:
        raise ValueError('pause_owner_catalog_writers_first')
    if file_identity(regular(Path(output)/'catalog.before.json'))['sha256'] != plan['baseSha256']:
        raise ValueError('owner_catalog_backup_changed')
    target = regular(Path(plan['baseCatalog']))
    if file_identity(target)['sha256'] != plan['baseSha256']:
        raise ValueError('owner_catalog_changed')
    next_path = regular(Path(output)/'catalog.next.json')
    if file_identity(next_path)['sha256'] != plan['nextSha256']:
        raise ValueError('owner_catalog_plan_changed')
    pending = target.with_name(target.name+'.community-'+secrets.token_hex(8)+'.pending')
    immutable(pending, next_path.read_bytes())
    if file_identity(target)['sha256'] != plan['baseSha256']:
        raise ValueError('owner_catalog_changed')
    pending.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--base-catalog', type=Path, required=True)
    parser.add_argument('--base-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--writers-paused', action='store_true')
    args = parser.parse_args()
    plan = prepare_catalog(SceneLibrary(args.library), args.models, args.base_catalog, args.base_sha256, args.output)
    if args.apply:
        apply_catalog(plan, args.output, writers_paused=args.writers_paused)
    print(json.dumps({**plan, 'applied':args.apply}))


if __name__ == '__main__':
    main()
