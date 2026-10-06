"""Finite, offline Object reference comparison; never approves contributions.

An operator supplies a checksum-pinned fixture of six saved faces per location
and native detector reference outputs. No imagery is fetched, account is read,
or result is uploaded. CPU diagnostics work on Windows and Mac; production
CoreML/indexing, historical Gen4 coverage and service approval remain separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import time

from .object_index import OBJECT_CLASSES, HOT_CONCEPTS, file_sha256
from .process_owner import run_owned
from .vision_index import THREAD_ENVIRONMENT_KEYS

MODELS = (
    'hybrid-object-runtime.json', 'object-model.json', 'owlv2-merges.txt',
    'owlv2-pq128-codebook.bin', 'owlv2-text-encoder.onnx', 'owlv2-tokenizer.json',
    'owlv2-vision-proposals.onnx', 'owlv2-vocab.json',
    'rfdetr-medium-576-b4.onnx', 'yoloe-26l-hot-prompts.npz', 'yoloe-26l-hot.onnx',
)
DLLS = ('DirectML.dll', 'msvcp140.dll', 'msvcp140_1.dll',
        'vcruntime140.dll', 'vcruntime140_1.dll')
THREAD_MARKER = '[vision-object] ONNX Runtime global threads: 1, spinning disabled'
MAX_JSON = 8 * 1024**2
MAX_INPUT_BYTES = 512 * 1024**2
CLASSES = dict(OBJECT_CLASSES)


class CheckError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise CheckError(code)


def regular(path, *, directory=False):
    path = Path(path).absolute()
    require('..' not in path.parts, 'unsafe_check_path')
    for parent in reversed(path.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'linked_check_path')
    info = path.lstat()
    require((stat.S_ISDIR if directory else stat.S_ISREG)(info.st_mode)
            and not getattr(info, 'st_file_attributes', 0) & 0x400, 'linked_check_path')
    return path


def checksum(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def relative(value):
    return (isinstance(value, str) and 0 < len(value) <= 240
            and all(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*', p)
                    and not p.endswith(('.', ' ')) for p in value.split('/')))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def read_json(path):
    path = regular(path)
    require(path.stat().st_size <= MAX_JSON, 'check_json_limit')
    raw = path.read_bytes()
    require(len(raw) <= MAX_JSON, 'check_json_limit')
    def pairs(entries):
        result = {}
        for key, value in entries:
            require(key not in result, 'duplicate_check_key')
            result[key] = value
        return result
    def constant(_value):
        raise CheckError('nonfinite_check_number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def pinned(root, entry, maximum):
    require(isinstance(entry, dict) and set(entry) == {'path', 'bytes', 'sha256'}
            and relative(entry['path']) and type(entry['bytes']) is int
            and 0 < entry['bytes'] <= maximum and checksum(entry['sha256']), 'invalid_check_pin')
    path = regular(Path(root) / entry['path'])
    require(path.stat().st_size == entry['bytes'] and file_sha256(path) == entry['sha256'],
            'check_asset_changed')
    return path


def number(value, low=0, high=1):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            'invalid_detection_number')


def box(values):
    require(isinstance(values, list) and len(values) == 4, 'invalid_detection_box')
    for value in values:
        number(value)
    require(values[0] < values[2] and values[1] < values[3], 'invalid_detection_box')


def canonical_rows(rows, *, images=None, query=None):
    """Validate all values and strip only the verified machine-local image paths."""
    require(isinstance(rows, list) and len(rows) == 6, 'incomplete_detection_views')
    result = []
    for i, row in enumerate(rows):
        keys = {'width', 'height', 'detections'} if query is None else {
            'width', 'height', 'query', 'semanticScore', 'semanticBox', 'hot'}
        if images is not None:
            keys.add('path')
        require(isinstance(row, dict) and set(row) == keys, 'invalid_detection_schema')
        require(type(row['width']) is int and type(row['height']) is int
                and row['width'] == row['height'] == 640, 'detection_dimensions_changed')
        if images is not None:
            require(row['path'] == str(images[i]), 'detection_input_changed')
        if query is not None:
            require(row['query'] == query, 'detection_query_changed')
            number(row['semanticScore'], -1, 1)
            box(row['semanticBox'])
        detections = row['detections' if query is None else 'hot']
        require(isinstance(detections, list) and len(detections) <= 10000, 'invalid_detection_count')
        for detection in detections:
            expected = {'confidence', 'x1', 'y1', 'x2', 'y2'} | (
                {'classId', 'className', 'rankingScore', 'supportCount'} if query is None else
                {'conceptId', 'concept'})
            require(isinstance(detection, dict) and set(detection) == expected, 'invalid_detection_schema')
            number(detection['confidence'])
            box([detection[key] for key in ('x1', 'y1', 'x2', 'y2')])
            if query is None:
                require(type(detection['classId']) is int and detection['classId'] in CLASSES
                        and CLASSES[detection['classId']] == detection['className']
                        and type(detection['supportCount']) is int
                        and 1 <= detection['supportCount'] <= 255, 'invalid_detection_identity')
                number(detection['rankingScore'])
            else:
                require(type(detection['conceptId']) is int
                        and 0 <= detection['conceptId'] < len(HOT_CONCEPTS)
                        and HOT_CONCEPTS[detection['conceptId']] == detection['concept'],
                        'invalid_detection_identity')
        result.append({key: value for key, value in row.items() if key != 'path'})
    return result


def compare_rows(actual, reference, *, query=None):
    """Keep detection order/count changes visible; never hide them by re-sorting.

Numeric differences are measured only between corresponding detections. A
changed identity/support/count/order is reported separately, not called parity.
No tolerance or production acceptance decision is invented here.
"""
    actual = canonical_rows(actual, query=query)
    reference = canonical_rows(reference, query=query)
    result = {'exact': actual == reference, 'structuralDifferences': 0,
              'numericValuesCompared': 0, 'maximumAbsoluteDifference': 0.0,
              'maximumScoreDifference': 0.0, 'maximumBoxDifference': 0.0}
    def delta(left, right, group):
        difference = abs(left - right)
        result['numericValuesCompared'] += 1
        result['maximumAbsoluteDifference'] = max(result['maximumAbsoluteDifference'], difference)
        key = 'maximum' + group + 'Difference'
        result[key] = max(result[key], difference)
    for row, gold in zip(actual, reference):
        if query is not None:
            delta(row['semanticScore'], gold['semanticScore'], 'Score')
            for left, right in zip(row['semanticBox'], gold['semanticBox']):
                delta(left, right, 'Box')
        name = 'detections' if query is None else 'hot'
        left, right = row[name], gold[name]
        if len(left) != len(right):
            result['structuralDifferences'] += 1
        identity = ('classId', 'className', 'supportCount') if query is None else ('conceptId', 'concept')
        for detection, baseline in zip(left, right):
            if any(detection[key] != baseline[key] for key in identity):
                result['structuralDifferences'] += 1
                continue
            for key in ('confidence', 'rankingScore') if query is None else ('confidence',):
                delta(detection[key], baseline[key], 'Score')
            for key in ('x1', 'y1', 'x2', 'y2'):
                delta(detection[key], baseline[key], 'Box')
    return result


class ObjectFixture:
    """Fixed input/gold bundle; its digest must come from a trusted source."""
    def __init__(self, path, expected_sha256):
        self.path = regular(path)
        require(checksum(expected_sha256) and file_sha256(self.path) == expected_sha256,
                'object_fixture_checksum_mismatch')
        self.sha256 = expected_sha256
        self.document = read_json(self.path)
        self.verify()

    def verify(self):
        require(file_sha256(regular(self.path)) == self.sha256, 'object_fixture_changed')
        doc = self.document
        require(isinstance(doc, dict) and set(doc) == {'version', 'reference', 'modelSha256', 'cases'}
                and type(doc['version']) is int and doc['version'] == 1, 'invalid_object_fixture')
        provenance = doc['reference']
        require(isinstance(provenance, dict) and set(provenance) == {
            'sourceRevision', 'runtimeProfileSha256', 'evidenceSha256', 'execution'}
            and isinstance(provenance['sourceRevision'], str)
            and re.fullmatch('[a-f0-9]{40}', provenance['sourceRevision'])
            and all(checksum(provenance[key]) for key in ('runtimeProfileSha256', 'evidenceSha256'))
            and provenance['execution'] in ('cpu', 'coreml'), 'invalid_reference_provenance')
        require(isinstance(doc['modelSha256'], dict) and set(doc['modelSha256']) == set(MODELS)
                and all(checksum(v) for v in doc['modelSha256'].values()), 'invalid_object_model_pins')
        cases = doc['cases']
        require(isinstance(cases, list) and 1 <= len(cases) <= 112, 'invalid_object_check_count')
        ids, paths, inventory, total = set(), set(), [], 0
        for case in cases:
            require(isinstance(case, dict) and set(case) == {'id', 'images', 'queries', 'reference'}
                    and isinstance(case['id'], str) and re.fullmatch('[a-z0-9-]{1,64}', case['id'])
                    and case['id'] not in ids, 'invalid_object_check_case')
            ids.add(case['id'])
            require(isinstance(case['images'], list) and len(case['images']) == 6,
                    'incomplete_frozen_views')
            images = []
            for entry in case['images']:
                image = pinned(self.path.parent, entry, 32 * 1024**2)
                require(entry['path'] not in paths, 'repeated_frozen_view')
                paths.add(entry['path'])
                total += entry['bytes']
                require(total <= MAX_INPUT_BYTES, 'object_fixture_budget')
                with image.open('rb') as stream:
                    header = stream.read(24)
                require(len(header) == 24 and header[:8] == b'\x89PNG\r\n\x1a\n'
                        and header[12:16] == b'IHDR'
                        and struct.unpack('>II', header[16:24]) == (640, 640), 'invalid_frozen_view')
                images.append(image)
            queries = case['queries']
            require(isinstance(queries, list) and 1 <= len(queries) <= 8
                    and all(isinstance(q, str) and 1 <= len(q) <= 160
                            and q.strip() == q and all(ord(c) >= 32 and ord(c) != 127 for c in q)
                            for q in queries) and len(set(queries)) == len(queries), 'invalid_object_queries')
            gold_path = pinned(self.path.parent, case['reference'], MAX_JSON)
            require(case['reference']['path'] not in paths, 'repeated_reference_path')
            paths.add(case['reference']['path'])
            total += case['reference']['bytes']
            require(total <= MAX_INPUT_BYTES, 'object_fixture_budget')
            gold = read_json(gold_path)
            require(isinstance(gold, dict) and set(gold) == {'common', 'hybrid'}
                    and isinstance(gold['hybrid'], dict) and set(gold['hybrid']) == set(queries),
                    'invalid_object_reference')
            canonical_rows(gold['common'])
            for query in queries:
                canonical_rows(gold['hybrid'][query], query=query)
            inventory.append((case, images, gold))
        return inventory


def runtime_profile(binary, model_dir):
    binary, model_dir = regular(binary), regular(model_dir, directory=True)
    assets = {'binary': file_sha256(binary)}
    for name in MODELS:
        assets['models/' + name] = file_sha256(regular(model_dir / name))
    dependencies = {}
    for path in binary.parent.iterdir():
        if path.suffix.lower() in ('.dll', '.dylib'):
            key = path.name.lower() if sys.platform == 'win32' else path.name
            require(key not in dependencies, 'ambiguous_native_dependency')
            dependencies[key] = path.name
    if sys.platform == 'win32':
        for name in DLLS:
            dependencies.setdefault(name.lower(), name)
    for key, name in sorted(dependencies.items()):
        assets['bin/' + key] = file_sha256(regular(binary.parent / name))
    profile = {'version': 1, 'platform': sys.platform, 'execution': 'cpu', 'assets': assets,
               'threads': 1, 'pipeline': {name: file_sha256(regular(Path(__file__).with_name(name)))
                                         for name in ('object_canary.py', 'object_index.py',
                                                      'vision_index.py', 'process_owner.py')}}
    return {'sha256': fingerprint(profile), 'profile': profile}


def native_runner(argv, env, cwd):
    """Bound each diagnostic; preserve logs and use the existing process owner."""
    stem = Path(cwd) / ('native-' + str(time.time_ns()))
    receipt = {'status': 'STARTED', 'timeoutSeconds': 900}
    def save():
        stem.with_suffix('.exit.json').write_text(json.dumps(receipt), encoding='utf-8')
    save()
    try:
        with stem.with_suffix('.stdout.log').open('xb') as stdout, \
                stem.with_suffix('.stderr.log').open('xb') as stderr:
            options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS} \
                if sys.platform == 'win32' else {}
            process = run_owned(argv, env=env, cwd=cwd, stdout=stdout, stderr=stderr, timeout=900, **options)
        receipt.update(status='EXITED', exitCode=process.returncode)
        require(process.returncode == 0, 'object_check_native_failed')
        require(stem.with_suffix('.stderr.log').stat().st_size <= MAX_JSON, 'object_check_log_limit')
        log = stem.with_suffix('.stderr.log').read_text(encoding='utf-8', errors='replace')
        require(THREAD_MARKER in log.splitlines(), 'object_check_shared_pool_unconfirmed')
    except BaseException as error:
        receipt.update(status='FAILED', errorType=type(error).__name__)
        raise
    finally:
        save()


def run_canary(work, *, binary, model_dir, fixture, fixture_sha256, runner=None, progress_callback=None):
    """Measure complete frozen detector outputs. A complete check is not approval."""
    work = Path(work).absolute()
    regular(work.parent, directory=True)
    work.mkdir(exist_ok=False)
    regular(work, directory=True)
    report = {'version': 1, 'status': 'INCOMPLETE', 'qualified': False, 'serverAuthorization': False,
              'productionPathVerified': False, 'coverageAdmissionVerified': False,
              'acceptedContributions': 0, 'searchCreditsCreated': 0, 'rawDataUploaded': False,
              'execution': 'cpu', 'comparisons': [], 'decision': 'DIAGNOSTIC_ONLY'}
    started = time.monotonic()
    def save():
        # Keep an incomplete receipt through abrupt process exit. Replacement
        # is atomic; an interrupted write leaves the preceding receipt intact.
        regular(work, directory=True)
        target = work / 'object-check-report.json'
        if target.exists() or target.is_symlink():
            regular(target)
        temporary = work / ('report-' + str(time.time_ns()) + '.tmp')
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    try:
        report['stage'] = 'fixture'
        save()
        binary, model_dir = Path(binary).absolute(), Path(model_dir).absolute()
        bundle = ObjectFixture(fixture, fixture_sha256)
        inventory = bundle.verify()
        report['stage'] = 'runtime'
        save()
        profile = runtime_profile(binary, model_dir)
        require({name: profile['profile']['assets']['models/' + name] for name in MODELS}
                == bundle.document['modelSha256'], 'object_check_models_differ_from_reference')
        report.update(runtimeProfile=profile, fixtureSha256=bundle.sha256,
                      reference=bundle.document['reference'], locations=len(inventory), views=len(inventory) * 6)
        # Keep private/cloud/account environment variables out of native children.
        env = {key: value for key, value in os.environ.items() if key.upper() in ('SYSTEMROOT', 'WINDIR')}
        system = str(Path(os.environ.get('SYSTEMROOT', 'C:/Windows')) / 'System32') \
            if sys.platform == 'win32' else '/usr/bin:/bin'
        env.update(PATH=str(Path(binary).parent) + os.pathsep + system,
                   HOME=str(work), TEMP=str(work), TMP=str(work), TMPDIR=str(work))
        env.update({key: '1' for key in THREAD_ENVIRONMENT_KEYS})
        cache = work / 'cache'
        cache.mkdir()
        active = runner or native_runner
        for ordinal, (case, images, gold) in enumerate(inventory):
            image_args = [value for image in images for value in ('--image', str(image))]
            for query in (None, *case['queries']):
                label = 'common' if query is None else 'hybrid-' + str(case['queries'].index(query))
                target = work / (case['id'] + '-' + label + '.json')
                arguments = ['detect-images', '--model', str(Path(model_dir) / 'rfdetr-medium-576-b4.onnx')] \
                    if query is None else ['detect-hybrid-images', '--runtime-manifest',
                                          str(Path(model_dir) / 'hybrid-object-runtime.json'), '--query', query]
                report.update(stage=label, currentCase=case['id'])
                save()
                active([str(binary), *arguments, *image_args, '--output', str(target), '--cpu',
                        '--model-cache', str(cache)], env, work)
                rows = canonical_rows(read_json(target), images=images, query=query)
                comparison = compare_rows(rows, gold['common'] if query is None else gold['hybrid'][query], query=query)
                report['comparisons'].append({'case': case['id'], 'lane': label, **comparison,
                                              'outputSha256': file_sha256(target)})
                # The portable evidence contains values, not private machine paths.
                (work / (case['id'] + '-' + label + '-portable.json')).write_text(
                    json.dumps(rows, allow_nan=False), encoding='utf-8')
                save()
            if progress_callback:
                progress_callback({'event': 'indexing', 'completedLocations': ordinal + 1,
                                   'totalLocations': len(inventory)})
        report['stage'] = 'recheck'
        save()
        require(runtime_profile(binary, model_dir) == profile, 'object_runtime_changed_during_check')
        require(bundle.verify() == inventory, 'object_fixture_changed_during_check')
        report.update(status='COMPLETE', stage='complete',
                      exactReferenceMatch=all(row['exact'] for row in report['comparisons']))
    except (Exception, KeyboardInterrupt) as error:
        report.update(status='FAILED', errorType=type(error).__name__,
                      error=str(error) if isinstance(error, CheckError) else 'object_check_failed')
    finally:
        report['wallSeconds'] = time.monotonic() - started
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--fixture-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = run_canary(args.out, binary=args.binary.absolute(), model_dir=args.model_dir.absolute(),
                        fixture=args.fixture.absolute(), fixture_sha256=args.fixture_sha256)
    print(json.dumps(report, allow_nan=False))
    return 0 if report['status'] == 'COMPLETE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
