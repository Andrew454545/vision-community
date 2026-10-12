"""Inert owner-local Object search engine over independently sealed contributions.

No listener, downloader, account, approval or activation lives here. The operator
pins the runtime and snapshot separately; the online coordinator owns payment.
Native batch IDs are deliberately kept separate from stable snapshot ordinals.
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import platform
import re
import tempfile
import threading
import time

from . import native_scene_search as native
from .native_scene_verifier import source_pins
from .object_canary import MODELS, THREAD_MARKER, runtime_profile
from .object_index import (CODEBOOK_SHA256, COMMON_MODEL_SHA256, CONFIDENCE_FLOORS,
                           HOT_CONCEPTS, OBJECT_CLASSES, query_plan)
from .object_snapshot import MAX_SNAPSHOT_METADATA_BYTES, verify_object_snapshot
from .search_snapshot import (bounded_read, digest, encoded, pinned_read,
                             resource_for_environment, write_file)

MAX_LOCATIONS, MAX_BUNDLES = 4096, 32
MAX_RESULT, MAX_NATIVE_RESULT = 1024 * 1024, 8 * 1024 * 1024
CLASSES = dict(OBJECT_CLASSES)
MODEL_REFERENCES = {
    'pq': {'file': ('owlv2-pq128-codebook.bin', 'sha256')},
    'owlv2': {key: (name, key.replace('File', 'SHA256')) for key, name in (
        ('visionFile', 'owlv2-vision-proposals.onnx'), ('textFile', 'owlv2-text-encoder.onnx'),
        ('tokenizerFile', 'owlv2-tokenizer.json'), ('vocabFile', 'owlv2-vocab.json'),
        ('mergesFile', 'owlv2-merges.txt'))},
    'yoloe': {'modelFile': ('yoloe-26l-hot.onnx', 'modelSHA256'),
              'promptEmbeddingsFile': ('yoloe-26l-hot-prompts.npz', 'promptEmbeddingsSHA256')},
}


def require(condition, code):
    if not condition:
        raise native.NativeSearchError(code)


def number(value, low, high):
    return native.finite(value) and low <= value <= high


class NativeObjectSearchEngine:
    def __init__(self, binary, models, runtime, runtime_sha256, snapshot, snapshot_sha256, work):
        self.binary = native.plain_path(binary)
        self.models = native.plain_path(models, directory=True)
        self.runtime_path = native.plain_path(runtime)
        self.runtime_sha256, self.snapshot_sha256 = runtime_sha256, snapshot_sha256
        self.snapshot = native.plain_path(snapshot, directory=True)
        self.work = native.plain_path(work, directory=True)
        roots = (self.binary.parent, self.models, self.runtime_path.parent, self.snapshot)
        require(all(not (self.work == p or p in self.work.parents or self.work in p.parents)
                    for p in roots), 'engine_work_overlaps_input')
        self.config = config = native.strict_json(pinned_read(self.runtime_path, runtime_sha256, 1024*1024))
        require(isinstance(config, dict) and set(config) == {
            'version', 'scope', 'contractVersion', 'policyId', 'pythonVersion', 'sourceFiles',
            'runtimeProfileSha256', 'environment', 'resource', 'maxLocations', 'maxBundles', 'timeoutSeconds'
        } and type(config['version']) is int and config['version'] == 1
            and config['scope'] == 'trusted-native-object-search' and type(config['contractVersion']) is int
            and config['contractVersion'] == native.CONTRACT
            and isinstance(config['policyId'], str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', config['policyId'])
            and config['pythonVersion'] == platform.python_version()
            and config['sourceFiles'] == source_pins()
            and isinstance(config['runtimeProfileSha256'], str) and native.HEX.fullmatch(config['runtimeProfileSha256'])
            and config['environment'] in ('production', 'staging')
            and config['resource'] == resource_for_environment(config['environment'])
            and (not config['policyId'].startswith('staging.') or config['environment'] == 'staging')
            and type(config['maxLocations']) is int and 1 <= config['maxLocations'] <= MAX_LOCATIONS
            and type(config['maxBundles']) is int and 1 <= config['maxBundles'] <= MAX_BUNDLES
            and type(config['timeoutSeconds']) is int and 1 <= config['timeoutSeconds'] <= 110,
            'invalid_object_search_runtime')
        self.busy = threading.BoundedSemaphore(1)
        self.profile = self.checked_profile()
        require(self.profile['sha256'] == config['runtimeProfileSha256'], 'object_search_runtime_mismatch')
        self.document = self.verify_inputs()
        self.members = native.strict_json(bounded_read(self.snapshot / 'members.json', MAX_SNAPSHOT_METADATA_BYTES))
        self.batches = []
        for index, bundle in enumerate(self.document['bundles']):
            folder = self.snapshot / bundle['path']
            manifest = native.strict_json(bounded_read(folder / 'manifest.json', 1024*1024))
            members = sorted((m for m in self.members if m['bundleIndex'] == index), key=lambda m: m['localIndex'])
            fields = [line.split('\t') for line in (folder / 'locations.tsv').read_text(encoding='utf-8').splitlines()]
            self.batches.append(({'id': manifest['sourceId'], 'sourceTsv': str(folder / 'locations.tsv'),
                'indexDir': str(folder), 'manifestPath': str(folder / 'manifest.json'),
                'globalStart': manifest['globalStart'], 'indexedLocations': len(members)}, members, fields))
        for member in self.members:
            require(member['locationId'] < 2**53, 'invalid_object_search_member')
        # Bracket construction: a snapshot change cannot replace the mappings
        # kept in memory while retaining the preceding verification outcome.
        require(self.verify_inputs() == self.document, 'object_search_snapshot_changed')

    def checked_profile(self):
        # Bound before hashing, including adjacent native dependencies. Hashes
        # establish the exact platform build; "cpu" is never a parity approval.
        assets = [self.binary, *(self.models / name for name in MODELS)]
        dependencies = [p for p in self.binary.parent.iterdir() if p.suffix.lower() in ('.dll', '.dylib')]
        require(len(dependencies) <= 32, 'object_search_runtime_limit')
        assets += dependencies
        total = 0
        for path in assets:
            size = native.plain_path(path).stat().st_size
            require(0 < size <= 512*1024**2, 'object_search_runtime_limit')
            total += size
        require(total <= 2*1024**3, 'object_search_runtime_limit')
        return runtime_profile(self.binary, self.models)

    def verify_inputs(self):
        native.plain_path(self.snapshot, directory=True)
        require(native.strict_json(pinned_read(native.plain_path(self.runtime_path), self.runtime_sha256, 1024*1024)) == self.config
                and source_pins() == self.config['sourceFiles'], 'object_search_source_changed')
        require(self.checked_profile() == self.profile, 'object_search_runtime_changed')
        model = native.strict_json(bounded_read(self.models / 'hybrid-object-runtime.json', 1024*1024))
        require(isinstance(model, dict), 'invalid_object_search_models')
        for group, fields in MODEL_REFERENCES.items():
            require(isinstance(model.get(group), dict), 'invalid_object_search_models')
            for key, (filename, pin_key) in fields.items():
                require(model[group].get(key) == filename and model[group].get(pin_key)
                        == self.profile['profile']['assets']['models/' + filename], 'invalid_object_search_models')
        require(self.profile['profile']['assets']['models/rfdetr-medium-576-b4.onnx'] == COMMON_MODEL_SHA256
                and model['pq'].get('sha256') == CODEBOOK_SHA256, 'invalid_object_search_models')
        doc = native.strict_json(pinned_read(self.snapshot / 'snapshot.json', self.snapshot_sha256,
                                            MAX_SNAPSHOT_METADATA_BYTES))
        require(isinstance(doc, dict) and type(doc.get('locations')) is int
                and 0 < doc['locations'] <= self.config['maxLocations'] and isinstance(doc.get('bundles'), list)
                and 0 < len(doc['bundles']) <= self.config['maxBundles'], 'object_search_snapshot_limit')
        # Reject linked/extra files before the native binary can discover them.
        expected = {'snapshot.json', 'members.json'}
        for bundle in doc['bundles']:
            require(isinstance(bundle, dict) and isinstance(bundle.get('files'), dict)
                    and isinstance(bundle.get('path'), str) and re.fullmatch(r'objects/[a-f0-9]{64}', bundle['path'])
                    and len(bundle['files']) <= 100, 'invalid_object_search_snapshot')
            for name in bundle['files']:
                require(isinstance(name, str) and re.fullmatch(r'[a-z0-9][a-z0-9.-]*', name),
                        'invalid_object_search_snapshot')
                expected.add(bundle['path'] + '/' + name)
        expected_dirs = {p.as_posix() for name in expected for p in Path(name).parents if str(p) != '.'}
        actual = set()
        for current, dirs, files in os.walk(self.snapshot, followlinks=False):
            for name in dirs:
                path = native.plain_path(Path(current) / name, directory=True)
                require(path.relative_to(self.snapshot).as_posix() in expected_dirs, 'object_search_snapshot_changed')
            for name in files:
                path = native.plain_path(Path(current) / name)
                actual.add(path.relative_to(self.snapshot).as_posix())
                require(len(actual) <= len(expected), 'object_search_snapshot_changed')
        require(actual == expected, 'object_search_snapshot_changed')
        return verify_object_snapshot(self.snapshot, self.snapshot_sha256, environment=self.config['environment'])

    def validate_request(self, request, raw_query=None):
        require(isinstance(request, dict) and set(request) == {'contractVersion', 'policyId', 'runtimeSha256',
            'snapshotSha256', 'requestSha256', 'query'} and type(request['contractVersion']) is int
            and request['contractVersion'] == native.CONTRACT
            and request['policyId'] == self.config['policyId'] and request['runtimeSha256'] == self.runtime_sha256
            and request['snapshotSha256'] == self.snapshot_sha256, 'search_identity_mismatch')
        q = request['query']
        require(isinstance(q, dict) and set(q) == native.QUERY_KEYS and q['lane'] == 'object', 'unsupported_search_lane')
        raw = raw_query if raw_query is not None else json.dumps(q, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        require(len(raw) <= 65536 and native.strict_json(raw) == q and digest(raw) == request['requestSha256'],
                'search_request_mismatch')
        prompt, name = native.text(q['prompt'], 1000, True), native.text(q['queryName'], 200, True)
        require(q['examples'] == [] and type(q['descriptionWeight']) is int and q['descriptionWeight'] in native.MODES
                and q['viewDirection'] == 'bestOfFour' and isinstance(q['objectConfidence'], str)
                and q['objectConfidence'] in CONFIDENCE_FLOORS
                and type(q['resultCount']) is int and 1 <= q['resultCount'] <= 1000
                and type(q['maxPerCountry']) is int and 1 <= q['maxPerCountry'] <= 10000
                and type(q['rejectRoadNames']) is bool
                and (q['minimumGlobalLocation'] is None or type(q['minimumGlobalLocation']) is int
                     and 0 <= q['minimumGlobalLocation'] < 2**53), 'invalid_search_query')
        require(not q['rejectRoadNames'], 'road_authority_unavailable')
        filters = q['filters']
        require(isinstance(filters, dict) and set(filters) == {'mode', 'countries', 'generations'}
                and filters['mode'] in ('all', 'include', 'exclude') and filters['generations'] == ['gen4']
                and isinstance(filters['countries'], list) and len(filters['countries']) <= 300,
                'invalid_search_query')
        for country in filters['countries']:
            native.text(country, 100, True)
        require(len(set(filters['countries'])) == len(filters['countries'])
                and (filters['mode'] != 'all' or not filters['countries'])
                and (filters['mode'] != 'include' or filters['countries']), 'invalid_search_query')
        require(isinstance(q['excluded'], list) and len(q['excluded']) <= 10000, 'invalid_search_query')
        for point in q['excluded']:
            require(isinstance(point, dict) and number(point.get('lat'), -90, 90) and number(point.get('lng'), -180, 180)
                    and isinstance(point.get('panoId', ''), str) and len(point.get('panoId', '')) <= 1000,
                    'invalid_search_query')
        plan = query_plan(prompt)
        return {'name': name, 'query': prompt.strip(), **plan,
            'minimumConfidence': CONFIDENCE_FLOORS[q['objectConfidence']], 'resultCount': 10000,
            'cameraGenerations': ['gen4'],
            'includeCountries': filters['countries'] if filters['mode'] == 'include' else [],
            'excludeCountries': filters['countries'] if filters['mode'] == 'exclude' else [],
            'rejectRoadNames': False}

    def batch_hits(self, output, definition, batch):
        source, members, fields = batch
        require(isinstance(output, dict) and set(output) == {'contractVersion', 'totalLocations', 'queries'}
                and type(output['contractVersion']) is int and output['contractVersion'] == native.CONTRACT
                and type(output['totalLocations']) is int
                and output['totalLocations'] == len(members) and isinstance(output['queries'], list)
                and len(output['queries']) == 1, 'incomplete_native_search')
        result = output['queries'][0]
        require(isinstance(result, dict) and set(result) == {'name', 'query', 'mode', 'hits'}
                and result['name'] == definition['name'] and result['query'] == definition['query']
                and result['mode'] == 'objects' and isinstance(result['hits'], list)
                and len(result['hits']) <= len(members), 'invalid_native_search')
        hits, seen, panos, prior = [], set(), set(), None
        for hit in result['hits']:
            require(isinstance(hit, dict) and set(hit) == {'locationIndex', 'similarity', 'viewOffset', 'location', 'object'},
                    'invalid_native_search')
            index, score, view = hit['locationIndex'], hit['similarity'], hit['viewOffset']
            require(type(index) is int and 0 <= index < len(members) and index not in seen
                    and number(score, definition['minimumConfidence'], 1) and type(view) is int and 0 <= view < 6
                    and (prior is None or (-score, index) >= prior), 'invalid_native_search')
            member, location, found = members[index], hit['location'], hit['object']
            pose = member['pose']
            expected = {k: pose[k] for k in ('lat', 'lng', 'heading', 'pitch', 'zoom', 'panoId', 'country', 'cameraGeneration')}
            expected.update(hasRoadName=fields[index][10] == 'has road name', globalLocationId=index)
            require(isinstance(location, dict) and set(location) == set(expected) and location == expected
                    and all(type(location[k]) is type(v) if k in ('globalLocationId', 'hasRoadName') or type(v) is str
                            else native.finite(location[k])
                            for k, v in expected.items()) and pose['panoId'] not in panos, 'native_pose_mismatch')
            require((not definition['includeCountries'] or pose['country'] in definition['includeCountries'])
                    and pose['country'] not in definition['excludeCountries'], 'native_filter_mismatch')
            keys = {'className', 'lane', 'confidence', 'supportCount', 'heading', 'pitch', 'zoom', 'bboxArea'}
            if definition['route'] == 'common':
                keys.add('classId')
            require(isinstance(found, dict) and set(found) == keys and found['lane'] == definition['route']
                    and number(found['confidence'], definition['minimumConfidence'], 1)
                    and type(found['supportCount']) is int and 1 <= found['supportCount'] <= 255
                    and number(found['heading'], 0, 360) and found['heading'] < 360
                    and number(found['pitch'], -90, 90) and number(found['zoom'], 0, 5)
                    and number(found['bboxArea'], 0, 1), 'invalid_object_search_aim')
            require((definition['route'] == 'common' and type(found['classId']) is int
                     and found['classId'] in definition['classIds'] and found['className'] == CLASSES[found['classId']])
                    or (definition['route'] == 'hot' and found['className'] == HOT_CONCEPTS[definition['hotConceptId']])
                    or (definition['route'] == 'semantic' and found['className'] == definition['query']),
                    'object_search_class_mismatch')
            hits.append({'locationId': member['locationId'], 'outputSha256': member['outputSha256'],
                'sourceIndex': member['sourceIndex'], 'score': score, 'viewOffset': view,
                **{k: found[k] for k in ('heading', 'pitch', 'zoom')},
                'object': {k: v for k, v in found.items() if k not in ('heading', 'pitch', 'zoom')}})
            seen.add(index); panos.add(pose['panoId']); prior = (-score, index)
        return hits

    def search(self, request, *, raw_query=None):
        definition = self.validate_request(request, raw_query)
        require(self.busy.acquire(blocking=False), 'search_engine_busy')
        try:
            deadline = time.monotonic() + self.config['timeoutSeconds']
            native.plain_path(self.work, directory=True)
            self.verify_inputs()
            candidates = []
            with tempfile.TemporaryDirectory(prefix='object-query-', dir=self.work) as temporary:
                job_root = Path(temporary)
                os.chmod(job_root, 0o700)
                for index, batch in enumerate(self.batches):
                    remaining = deadline - time.monotonic()
                    require(remaining > 0, 'native_search_timeout')
                    job = job_root / str(index)
                    job.mkdir(mode=0o700)
                    # Each sealed batch has its own native 0-based IDs. Search
                    # it completely, then rank by the immutable snapshot ordinal.
                    # Do not rewrite accepted feature/ID bytes to join batches.
                    payload = {'contractVersion': 2, 'runId': request['requestSha256'], 'queries': [definition],
                        'sources': [{**batch[0], 'manifestPath': str(job / 'manifest.json')}], 'resultPruneMeters': 0,
                        'runtimeManifest': str(self.models / 'hybrid-object-runtime.json'),
                        'modelCache': str(job / 'models'), 'cpu': True}
                    # Native validation requires this machine's exact TSV path.
                    # Patch only that path in private ephemeral metadata; the
                    # immutable approved snapshot and all feature bytes stay put.
                    mounted = native.strict_json(bounded_read(Path(batch[0]['manifestPath']), 1024*1024))
                    write_file(job / 'manifest.json', encoded({**mounted, 'sourceTsv': batch[0]['sourceTsv']}))
                    write_file(job / 'input.json', encoded(payload))
                    native.run_native([str(self.binary), 'search', '--input', str(job / 'input.json'),
                                       '--output', str(job / 'output.json')], job, remaining)
                    log = bounded_read(native.plain_path(job / 'stderr.log'), 1024*1024).decode('utf-8', errors='replace')
                    require(THREAD_MARKER in log.splitlines(), 'native_search_runtime_update_required')
                    output = native.strict_json(bounded_read(native.plain_path(job / 'output.json'), MAX_NATIVE_RESULT))
                    candidates.extend(self.batch_hits(output, definition, batch))
                self.verify_inputs()
                require(time.monotonic() <= deadline, 'native_search_timeout')
                hits, panos, counts = [], set(), Counter()
                q = request['query']
                for hit in sorted(candidates, key=lambda h: (-h['score'], h['sourceIndex'])):
                    require(time.monotonic() <= deadline, 'native_search_timeout')
                    pose = self.members[hit['sourceIndex']]['pose']
                    if (pose['panoId'] in panos or counts[pose['country']] >= q['maxPerCountry']
                            or (q['minimumGlobalLocation'] is not None and hit['sourceIndex'] < q['minimumGlobalLocation'])
                            or any(p.get('panoId') == pose['panoId'] or native.distance(p, pose) < 25 for p in q['excluded'])
                            or any(native.distance(self.members[h['sourceIndex']]['pose'], pose) < 100 for h in hits)):
                        continue
                    hits.append(hit); panos.add(pose['panoId']); counts[pose['country']] += 1
                    if len(hits) == q['resultCount']:
                        break
                response = {k: v for k, v in request.items() if k != 'query'}
                response.update(processedLocations=len(self.members), hits=hits)
                require(len(encoded(response)) <= MAX_RESULT, 'search_response_limit')
                require(time.monotonic() <= deadline, 'native_search_timeout')
                return response
        except Exception as failure:
            code = str(failure) if isinstance(failure, native.NativeSearchError) else 'native_object_search_failed'
            if not re.fullmatch(r'[a-z0-9_]{1,80}', code):
                code = 'native_object_search_failed'
            try:
                write_file(self.work / ('failure-' + code + '.json'), encoded({'success': False, 'error': code}))
            except FileExistsError:
                pass
            raise native.NativeSearchError(code) from None
        finally:
            self.busy.release()
