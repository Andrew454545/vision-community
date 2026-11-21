"""A private Scene library built from completed work, without re-embedding it.

Original packet receipts remain the recovery source. Searchable copies use the
normal VISION v4 format, in bounded 50,000-location segments. Only the last partial
segment changes as work arrives; a search never scans thousands of tiny packets.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace

from .four_view import BYTES_PER_LOCATION, SHARD_LOCATIONS, valid_four_view_record
from .local_scene_packets import canonical, load_packet
from .local_scene_pilot import LocalScenePilot, atomic_json, immutable, CheckedRuntime
from .mac_starter import regular
from .process_owner import run_owned
from .rank import prune_nearby
from .vision_index import (assert_not_live_vision_path, file_identity, inference_environment,
                           search_input, map_from_search, finish_scene_coordinates)


def fnv_update(value, body):
    for byte in body:
        value = ((value ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    return value


def model_identity(models):
    return '|'.join(f'{name}:{regular(models/name).stat().st_size}:{int((models/name).stat().st_mtime)}'
        for name in ('vision_model.onnx', 'vision_model_fp32.onnx', 'text_model.onnx', 'tokenizer.json'))


class SceneLibrary:
    def __init__(self, root, *, personal=False):
        self.personal = personal
        self.root = regular(root, directory=True, missing=True)
        assert_not_live_vision_path(self.root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.guard = threading.RLock()
        with self._db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS sources(
                identity TEXT PRIMARY KEY, path TEXT NOT NULL, receipt TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS locations(
                ordinal INTEGER PRIMARY KEY, pano TEXT NOT NULL UNIQUE, line TEXT NOT NULL,
                source TEXT NOT NULL, position INTEGER NOT NULL, record_sha TEXT NOT NULL,
                country TEXT NOT NULL, generation TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS library_country ON locations(country);
                CREATE INDEX IF NOT EXISTS library_generation ON locations(generation);
                CREATE TABLE IF NOT EXISTS segments(
                block INTEGER PRIMARY KEY, locations INTEGER NOT NULL, path TEXT NOT NULL);
            ''')

    def _db(self):
        return sqlite3.connect(regular(self.root/'library.sqlite', missing=True), timeout=30)

    @contextmanager
    def writing(self):
        from .background import single_instance
        with self.guard, single_instance(self.root):
            yield

    def status(self):
        with self._db() as db:
            return {'locations': db.execute('SELECT count(*) FROM locations').fetchone()[0],
                'countries': [r[0] for r in db.execute('SELECT DISTINCT country FROM locations WHERE country!="" ORDER BY country')],
                'generations': [r[0] for r in db.execute('SELECT DISTINCT generation FROM locations WHERE generation!="" ORDER BY generation')],
                'path': str(self.root), 'localOnly': True}

    def add_pilot(self, pilot_root):
        """Admit only completed, hash-checked parts; keep original camera/source rows."""
        root = regular(pilot_root, directory=True)
        packet = load_packet(root/'packet.json')
        profile = json.loads(regular(root/'runtime-profile.json').read_text())
        if (set(profile) != {'sha256', 'profile'}
                or hashlib.sha256(canonical(profile['profile'])).hexdigest() != profile['sha256']):
            raise ValueError('library_profile_changed')
        from .local_scene_archive import _completed_parts
        added = 0
        with self.writing(), self._db() as db:
            for part, rows in _completed_parts(root, packet):
                receipt_raw = regular(root/part/'complete.json').read_bytes()
                identity = hashlib.sha256(packet['packetId'].encode()+receipt_raw).hexdigest()
                if db.execute('SELECT 1 FROM sources WHERE identity=?', (identity,)).fetchone():
                    continue
                receipt = json.loads(receipt_raw)
                LocalScenePilot._verify_saved_part(SimpleNamespace(packet=packet), root/part, receipt, rows, profile)
                attempt = regular(root/part/receipt['attempt'], directory=True)
                expected = ('\n'.join(row['line'] for row in rows)+'\n').encode()
                if regular(attempt/'locations.tsv').read_bytes() != expected:
                    raise ValueError('library_source_changed')
                vectors = regular(attempt/'index/shard-000000.i8').read_bytes()
                if (len(vectors) != len(rows)*BYTES_PER_LOCATION
                        or regular(attempt/'index/shard-000000.mask').read_bytes() != bytes([15])*len(rows)):
                    raise ValueError('library_incomplete_views')
                ordinal = db.execute('SELECT coalesce(max(ordinal)+1,0) FROM locations').fetchone()[0]
                for position, row in enumerate(rows):
                    record = vectors[position*BYTES_PER_LOCATION:(position+1)*BYTES_PER_LOCATION]
                    if not valid_four_view_record(record):
                        raise ValueError('library_invalid_vector')
                    pin = hashlib.sha256(record).hexdigest()
                    fields = row['line'].split('\t')
                    prior = db.execute('SELECT line,record_sha FROM locations WHERE pano=?', (fields[7],)).fetchone()
                    if prior:
                        if self.personal:
                            # A private library keeps the first indexed camera
                            # pose for a panorama shared by multiple user maps.
                            continue
                        if prior != (row['line'], pin):
                            raise ValueError('library_panorama_conflict')
                        continue
                    db.execute('INSERT INTO locations VALUES(?,?,?,?,?,?,?,?)',
                        (ordinal, fields[7], row['line'], identity, position, pin, fields[8], fields[9]))
                    ordinal += 1
                    added += 1
                if regular(root/part/'complete.json').read_bytes() != receipt_raw:
                    raise ValueError('library_source_changed')
                db.execute('INSERT INTO sources VALUES(?,?,?)', (identity, str(attempt), receipt_raw.decode()))
        return added

    def _verify_segment(self, folder):
        folder = regular(folder, directory=True)
        marker = json.loads(regular(folder/'library-segment.json').read_text())
        expected = {'locations.tsv', 'index/manifest.json', 'index/shard-000000.i8', 'index/shard-000000.mask'}
        if marker.get('contract') != 'vision-local-scene-library-segment-v1' or set(marker.get('files', {})) != expected:
            raise ValueError('library_segment_changed')
        if {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()} != expected | {'library-segment.json'}:
            raise ValueError('library_segment_changed')
        for name, pin in marker['files'].items():
            if file_identity(regular(folder/name)) != pin:
                raise ValueError('library_segment_changed')
        return marker

    def _remove_previous_partial(self, folder):
        # Delete only this library's replaceable derived copy, after publication.
        # Packet originals and independently owned VISION indexes are never here.
        if folder.parent != self.root/'segments':
            raise ValueError('library_cleanup_path')
        self._verify_segment(folder)
        for name in ('locations.tsv', 'index/manifest.json', 'index/shard-000000.i8',
                     'index/shard-000000.mask', 'library-segment.json'):
            regular(folder/name).unlink()
        regular(folder/'index', directory=True).rmdir()
        folder.rmdir()

    def _segments(self, models, *, stop=None):
        identity = model_identity(models)
        destination = regular(self.root/'segments', directory=True, missing=True)
        destination.mkdir(exist_ok=True)
        paths = []
        with self._db() as db:
            total = db.execute('SELECT count(*) FROM locations').fetchone()[0]
            for block, start in enumerate(range(0, total, SHARD_LOCATIONS)):
                if stop is not None and stop.is_set():
                    raise ValueError('library_search_cancelled')
                count = min(SHARD_LOCATIONS, total-start)
                prior = db.execute('SELECT locations,path FROM segments WHERE block=?', (block,)).fetchone()
                if prior and prior[0] == count:
                    folder = regular(destination/prior[1], directory=True)
                    marker = self._verify_segment(folder)
                    if marker.get('modelIdentity') == identity:
                        paths.append(folder)
                        continue
                rows = db.execute('SELECT line,position,record_sha,source FROM locations '
                    'WHERE ordinal>=? AND ordinal<? ORDER BY ordinal',
                    (start, start+count)).fetchall()
                key = hashlib.sha256(canonical([identity, [(r[0], r[2]) for r in rows]])).hexdigest()
                folder = regular(destination/f'{block:06d}-{count}-{key[:20]}', directory=True, missing=True)
                if not folder.exists():
                    if __import__('shutil').disk_usage(destination).free < count*BYTES_PER_LOCATION + 128*1024**2:
                        raise ValueError('library_storage_required')
                    with tempfile.TemporaryDirectory(prefix='.building-', dir=destination) as temporary:
                        staging = Path(temporary)
                        (staging/'index').mkdir()
                        source_hash = 0xcbf29ce484222325
                        source_bytes = 0
                        current_source, records = None, None
                        with (staging/'locations.tsv').open('xb') as tsv, (staging/'index/shard-000000.i8').open('xb') as out:
                            for line, position, pin, source in rows:
                                if source != current_source:
                                    if stop is not None and stop.is_set():
                                        raise ValueError('library_search_cancelled')
                                    original, raw_receipt = db.execute('SELECT path,receipt FROM sources WHERE identity=?',(source,)).fetchone()
                                    original = regular(Path(original), directory=True)
                                    receipt = json.loads(raw_receipt)
                                    for name in ('locations.tsv', 'index/shard-000000.i8', 'index/shard-000000.mask'):
                                        if file_identity(regular(original/name)) != receipt['files'][name]:
                                            raise ValueError('library_source_changed')
                                    records = regular(original/'index/shard-000000.i8').read_bytes()
                                    current_source = source
                                record = records[position*BYTES_PER_LOCATION:(position+1)*BYTES_PER_LOCATION]
                                if hashlib.sha256(record).hexdigest() != pin:
                                    raise ValueError('library_source_changed')
                                out.write(record)
                                encoded = (line+'\n').encode()
                                tsv.write(encoded)
                                source_bytes += len(encoded)
                                source_hash = fnv_update(source_hash, encoded)
                            for stream in (tsv, out):
                                stream.flush(); os.fsync(stream.fileno())
                        immutable(staging/'index/shard-000000.mask', bytes([15])*count)
                        manifest = {'version': 4, 'runId': key, 'modelDir': str(models),
                            'sourceTsv': str(folder/'locations.tsv'), 'sourceBytes': source_bytes,
                            'sourcePrefixHash': f'fnv1a64:{source_hash:016x}', 'inputFingerprint': key,
                            'modelIdentity': identity, 'totalLocations': count, 'indexedLocations': count,
                            'embeddingDimension': 768, 'viewsPerLocation': 4, 'bytesPerLocation': BYTES_PER_LOCATION,
                            'shardLocations': SHARD_LOCATIONS, 'completed': True, 'updatedAtUnixMs': 0,
                            'storage': 'four quarter-turn scaled int8 vectors; little-endian binary16 scale'}
                        immutable(staging/'index/manifest.json', canonical(manifest)+b'\n')
                        names = ('locations.tsv', 'index/manifest.json', 'index/shard-000000.i8', 'index/shard-000000.mask')
                        immutable(staging/'library-segment.json', canonical({
                            'contract': 'vision-local-scene-library-segment-v1', 'modelIdentity': identity,
                            'files': {name: file_identity(staging/name) for name in names}})+b'\n')
                        staging.rename(folder)
                        # TemporaryDirectory tolerates the renamed staging path.
                self._verify_segment(folder)
                db.execute('INSERT OR REPLACE INTO segments VALUES(?,?,?)', (block, count, folder.name))
                db.commit()  # Publish the new complete segment before removing its old copy.
                if prior and prior[1] != folder.name:
                    self._remove_previous_partial(destination/prior[1])
                paths.append(folder)
        return paths, total

    def search(self, value, runtime_root, *, runtime_verifier=None, native_runner=None, stop=None, photo_rgb=None):
        if not isinstance(value, dict) or set(value)-{'prompt','country','generation','viewDirection','resultCount','examples','descriptionWeight'}:
            raise ValueError('invalid_library_query')
        prompt = value.get('prompt', '')
        if not isinstance(prompt, str) or len(prompt)>2000 or any(ord(c)<32 for c in prompt):
            raise ValueError('invalid_library_query')
        examples = value.get('examples', [])
        if not isinstance(examples, list) or len(examples)>8:
            raise ValueError('invalid_library_examples')
        for sample in examples:
            if (not isinstance(sample,dict) or set(sample)!={'panoId','heading','pitch','zoom'}
                    or not re.fullmatch('[A-Za-z0-9_-]{4,80}',str(sample['panoId']))
                    or any(type(sample[k]) not in (int,float) or not math.isfinite(sample[k]) for k in ('heading','pitch','zoom'))
                    or not 0<=sample['heading']<360 or not -90<=sample['pitch']<=90 or not 0<=sample['zoom']<=5):
                raise ValueError('invalid_library_examples')
        if photo_rgb is not None:
            from .local_scene_photo import RGB_BYTES
            if not isinstance(photo_rgb,bytes) or len(photo_rgb)!=RGB_BYTES or examples:
                raise ValueError('invalid_library_photo')
        visual = bool(examples) or photo_rgb is not None
        if not prompt.strip() and not visual:
            raise ValueError('invalid_library_query')
        count = value.get('resultCount',50)
        if type(count) is not int or not 1<=count<=200:
            raise ValueError('invalid_library_result_count')
        weight = value.get('descriptionWeight', 0 if visual else 100)
        if weight not in (0,25,50,75,100) or (visual and weight==100) or (not visual and weight!=100):
            raise ValueError('invalid_library_weight')
        from .features import VIEW_DIRECTION_OFFSETS
        direction = value.get('viewDirection','bestOfFour')
        if direction not in VIEW_DIRECTION_OFFSETS:
            raise ValueError('invalid_library_direction')
        country, generation = value.get('country',''), value.get('generation','')
        info = self.status()
        if country not in ['', *info['countries']] or generation not in ['', *info['generations']]:
            raise ValueError('invalid_library_filter')
        with self.writing():
            binary, models, runtime_profile = (runtime_verifier or CheckedRuntime())(runtime_root)
            paths, total = self._segments(models,stop=stop)
            if not paths:
                raise ValueError('library_empty')
            coordinates = []
            with tempfile.TemporaryDirectory(prefix='search-', dir=self.root) as temporary:
                job = Path(temporary)
                request = search_input(prompt or ('local photo' if photo_rgb is not None else ''), result_count=count, max_per_country=count,
                    country_mode='include' if country else 'all', countries=[country] if country else [],
                    camera_generations=[generation] if generation else [], view_direction=direction,
                    output_name='My VISION results', examples=examples, description_weight=weight)
                if photo_rgb is not None:
                    from .local_scene_photo import prepare_profile
                    from .vision_index import SCENE_QUERY_MODES
                    request['queries'][0]['mode'] = SCENE_QUERY_MODES[weight][0]
                    request['queries'][0]['minSimilarity'] = -1.0
                    try:
                        prepare_profile(photo_rgb,job,binary,models,runtime_profile,request,weight=weight)
                    except Exception:
                        self._native_failure(job/'photo-encoder')
                        raise
                request['resultPruneMeters'] = 0  # Apply the same distance rule globally across segments.
                request['topK'] = min(10000, max(200, count*8))
                atomic_json(job/'input.json', request)
                start = 0
                for folder in paths:
                    if stop is not None and stop.is_set():
                        raise ValueError('library_search_cancelled')
                    output = job/'output.json'
                    command = [str(binary),'search-four-view-index','--input',str(job/'input.json'),
                        '--model-dir',str(models),'--locations-tsv',str(folder/'locations.tsv'),
                        '--index-dir',str(folder/'index'),'--profile-cache-dir',str(job/'profiles'),'--output',str(output)]
                    if native_runner is None:
                        try:
                            with (job/'stdout.log').open('wb') as out, (job/'stderr.log').open('wb') as err:
                                completed = run_owned(command,env=inference_environment(job),cwd=job,
                                    stdout=out,stderr=err,timeout=180)
                        except Exception:
                            self._native_failure(job)
                            raise
                        if completed.returncode:
                            self._native_failure(job)
                            errors = (job/'stderr.log').read_text(errors='replace')
                            if re.search(r'HTTP (403|429)', errors):
                                raise ValueError('imagery_access_denied')
                            raise ValueError('library_native_search_failed')
                        if photo_rgb is not None and '[vision] loaded 1 cached query profiles' not in (job/'stderr.log').read_text(errors='replace'):
                            raise ValueError('photo_profile_not_used')
                    else:
                        native_runner(command,job)
                    if regular(output).stat().st_size>16*1024**2:
                        raise ValueError('library_search_output_limit')
                    payload = json.loads(output.read_text())
                    if (payload.get('completed') is not True or payload.get('version')!=4
                            or any(payload.get(k)!=0 for k in ('fetchErrors','inferenceErrors','incompleteLocations'))):
                        raise ValueError('library_search_incomplete')
                    built = map_from_search(payload,folder/'locations.tsv',prompt=prompt)
                    if built:
                        for row in built['customCoordinates']:
                            row['extra']['visionSourceIndex'] += start
                            coordinates.append(row)
                    start += json.loads((folder/'index/manifest.json').read_text())['totalLocations']
                    coordinates = sorted(coordinates,key=lambda r:(-r['extra']['visionScore'],r['extra']['visionSourceIndex']))[:request['topK']]
                    output.unlink()
                ordered = sorted(coordinates,key=lambda r:(-r['extra']['visionScore'],r['extra']['visionSourceIndex']))
                # Dedupe geographically before the result limit, across all segments.
                ordered = prune_nearby(ordered)
                document = finish_scene_coordinates(ordered,result_count=count,max_per_country=count,
                    output_name='My VISION results',prompt=prompt,processed_locations=total)
                return {'ok': True,'locations':total,'indexes':len(paths),'map':document,
                    'localOnly':True,'uploads':0,'liveExampleImagery':bool(examples),'localPhotoQuery':photo_rgb is not None}

    def _native_failure(self, job):
        destination = regular(self.root/'diagnostics'/str(time.time_ns()),directory=True,missing=True)
        destination.mkdir(mode=0o700,parents=True)
        for name in ('stdout.log','stderr.log'):
            path = regular(job/name,missing=True)
            if path.exists():
                with path.open('rb') as source:
                    source.seek(max(0,path.stat().st_size-1024**2))
                    immutable(destination/name,source.read(1024**2))
