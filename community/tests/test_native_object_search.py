"""Synthetic native packets only: no inference, imagery, vault or network."""
import copy
import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from community import native_object_search as objects
from community import native_scene_search as native
from community.native_scene_verifier import source_pins
from community.object_canary import DLLS, MODELS, runtime_profile
from community.owner_search_agent import OwnerSearchAgent
from community.process_owner import run_owned
from community.search_snapshot import digest, encoded, CONFIRMED_RESOURCE
from community.tests.test_native_scene_search import query
from community.tests.test_object_snapshot import ObjectSnapshotTest as SnapshotFixture


class NativeObjectSearchTest(unittest.TestCase):
    def setUp(self):
        # Reuse real snapshot sealing/feature validation, with the existing
        # explicitly synthetic feature bundle. It is not an audit approval.
        fixture = SnapshotFixture(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root = fixture.root
        report = fixture.build()
        self.snapshot = self.root / 'snapshot'
        self.snapshot_pin = report['snapshotSha256']
        self.binary_dir = self.root / 'bin'
        self.binary_dir.mkdir()
        self.binary = self.binary_dir / 'unexecuted-native.exe'
        self.binary.write_bytes(b'synthetic native, never executed')
        for name in DLLS:
            (self.binary_dir / name).write_bytes(b'synthetic DLL ' + name.encode())
        self.models = self.root / 'models'
        self.models.mkdir()
        for name in MODELS:
            (self.models / name).write_bytes(b'synthetic model ' + name.encode())
        model_doc = {}
        for group, fields in objects.MODEL_REFERENCES.items():
            model_doc[group] = {}
            for field, (filename, pin_field) in fields.items():
                model_doc[group][field] = filename
                model_doc[group][pin_field] = digest((self.models / filename).read_bytes())
        (self.models / 'hybrid-object-runtime.json').write_bytes(encoded(model_doc))
        # Fake model bytes cannot have authentic model hashes. Patch only these
        # two expectations; runtime/source hashing and snapshot checks are real.
        for key, filename in [('COMMON_MODEL_SHA256', 'rfdetr-medium-576-b4.onnx'),
                              ('CODEBOOK_SHA256', 'owlv2-pq128-codebook.bin')]:
            patched = patch.object(objects, key, digest((self.models / filename).read_bytes()))
            patched.start(); self.addCleanup(patched.stop)
        self.runtime_dir = self.root / 'policy'
        self.runtime_dir.mkdir()
        self.runtime = self.runtime_dir / 'runtime.json'
        self.config = {'version': 1, 'scope': 'trusted-native-object-search', 'contractVersion': 2,
            'policyId': 'synthetic-object-search', 'pythonVersion': platform.python_version(),
            'sourceFiles': source_pins(), 'runtimeProfileSha256': runtime_profile(self.binary, self.models)['sha256'],
            'environment': 'production', 'resource': CONFIRMED_RESOURCE,
            'maxLocations': 4096, 'maxBundles': 32, 'timeoutSeconds': 110}
        self.runtime.write_bytes(encoded(self.config))
        self.work = self.root / 'work'
        self.work.mkdir()
        self.engine = self.start()
        self.native_calls = 0

    def start(self, **changes):
        args = dict(binary=self.binary, models=self.models, runtime=self.runtime,
                    runtime_sha256=digest(self.runtime.read_bytes()), snapshot=self.snapshot,
                    snapshot_sha256=self.snapshot_pin, work=self.work)
        return objects.NativeObjectSearchEngine(**{**args, **changes})

    def request(self, **changes):
        q = query(**{'lane': 'object', 'prompt': 'car',
                     'filters': {'mode': 'all', 'countries': [], 'generations': ['gen4']}, **changes})
        return {'contractVersion': 2, 'policyId': self.config['policyId'], 'runtimeSha256': self.engine.runtime_sha256,
                'snapshotSha256': self.snapshot_pin, 'requestSha256': digest(json.dumps(q, ensure_ascii=False,
                 separators=(',', ':')).encode()), 'query': q}

    def result(self, definition, batch):
        source, members, fields = batch
        route = definition['route']
        found = {'className': 'car', 'classId': 3, 'lane': 'common', 'confidence': .8, 'supportCount': 2,
                 'heading': 45., 'pitch': 10., 'zoom': 2., 'bboxArea': .2}
        if route != 'common':
            found.pop('classId')
            found.update(lane=route, className=objects.HOT_CONCEPTS[definition['hotConceptId']]
                         if route == 'hot' else definition['query'])
        hits = []
        for index, member in enumerate(members):
            pose = member['pose']
            if ((definition['includeCountries'] and pose['country'] not in definition['includeCountries'])
                    or pose['country'] in definition['excludeCountries']):
                continue
            location = {k: pose[k] for k in ('lat', 'lng', 'heading', 'pitch', 'zoom', 'panoId', 'country', 'cameraGeneration')}
            for k in ('lat', 'lng', 'heading', 'pitch', 'zoom'):
                location[k] = float(location[k])
            location.update(hasRoadName=fields[index][10] == 'has road name', globalLocationId=index)
            hits.append({'locationIndex': index, 'similarity': .8, 'viewOffset': 2,
                         'location': location, 'object': copy.deepcopy(found)})
        return {'contractVersion': 2, 'totalLocations': len(members), 'queries': [
            {'name': definition['name'], 'query': definition['query'], 'mode': 'objects', 'hits': hits}]}

    def fake_native(self, command, job, timeout):
        self.native_calls += 1
        self.assertEqual(command, [str(self.binary), 'search', '--input', str(job / 'input.json'), '--output', str(job / 'output.json')])
        self.assertGreater(timeout, 0); self.assertLessEqual(timeout, 110)
        packet = native.strict_json((job / 'input.json').read_bytes())
        self.assertIs(packet['cpu'], True)
        self.assertEqual(packet['resultPruneMeters'], 0)
        self.assertEqual(packet['queries'][0]['resultCount'], 10000)
        self.assertNotIn('minimumGlobalLocation', packet['queries'][0])
        self.assertNotIn('private-account', json.dumps(packet))
        source = packet['sources'][0]
        batch = next(b for b in self.engine.batches if b[0]['id'] == source['id'])
        original = native.strict_json(Path(batch[0]['manifestPath']).read_bytes())
        mounted = native.strict_json(Path(source['manifestPath']).read_bytes())
        self.assertEqual(mounted, {**original, 'sourceTsv': source['sourceTsv']})
        self.assertEqual(original['sourceTsv'], 'locations.tsv')
        (job / 'stderr.log').write_text(objects.THREAD_MARKER + '\n', encoding='utf-8')
        (job / 'output.json').write_bytes(encoded(self.result(packet['queries'][0], batch)))

    def search(self, request=None):
        with patch.object(native, 'run_native', side_effect=self.fake_native):
            return self.engine.search(request or self.request())

    def test_two_batches_keep_native_ids_distinct_and_stable_ordinals_sorted(self):
        before = {p: p.read_bytes() for p in self.snapshot.rglob('*') if p.is_file()}
        result = self.search()
        self.assertEqual(self.native_calls, 2)
        self.assertEqual(result['processedLocations'], 3)
        self.assertEqual([(h['locationId'], h['sourceIndex']) for h in result['hits']], [(3, 0), (10, 1), (20, 2)])
        self.assertEqual(result['hits'][0]['object']['classId'], 3)
        self.assertNotIn('query', result)
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertTrue(all(p.read_bytes() == raw for p, raw in before.items()))

    def test_hot_and_semantic_routes_use_reference_query_planner(self):
        for prompt, expected in [('bird nest', 'hot'), ('an unusual blue sculpture', 'semantic')]:
            with self.subTest(prompt=prompt):
                result = self.search(self.request(prompt=prompt))
                self.assertEqual({h['object']['lane'] for h in result['hits']}, {expected})
                self.assertTrue(all('classId' not in h['object'] for h in result['hits']))

    def test_global_minimum_and_country_cap_apply_after_cross_batch_merge(self):
        result = self.search(self.request(minimumGlobalLocation=1, maxPerCountry=1))
        self.assertEqual([h['locationId'] for h in result['hits']], [10])
        self.assertEqual(self.search(self.request(resultCount=1))['hits'][0]['sourceIndex'], 0)

    def test_exclusion_by_pano_and_coordinate_works_without_refilling_or_recharging(self):
        for point in [{'panoId': 'synthetic-3', 'lat': 0, 'lng': 0}, {'lat': 3, 'lng': 20}]:
            with self.subTest(point=point):
                self.assertEqual([h['locationId'] for h in self.search(self.request(excluded=[point]))['hits']], [10, 20])

    def test_country_filter_can_return_complete_empty_reply(self):
        result = self.search(self.request(filters={'mode': 'exclude', 'countries': ['Italy'], 'generations': ['gen4']}))
        self.assertEqual(result['hits'], [])
        self.assertEqual(result['processedLocations'], 3)

    def test_current_gen4_road_authority_and_limits_fail_before_execution(self):
        bad = [{'rejectRoadNames': True}, {'examples': [{}]}, {'viewDirection': 'bestOfSix'},
               {'resultCount': 1001}, {'prompt': 'x'*1001}, {'maxPerCountry': True},
               {'minimumGlobalLocation': True}, {'objectConfidence': []},
               {'filters': {'mode': 'all', 'countries': [], 'generations': ['gen3']}}]
        for change in bad:
            with self.subTest(change=change), patch.object(native, 'run_native') as run:
                with self.assertRaises(native.NativeSearchError):
                    self.engine.search(self.request(**change))
                run.assert_not_called()

    def test_all_request_pins_are_required_before_execution(self):
        for key in ('contractVersion', 'policyId', 'runtimeSha256', 'snapshotSha256', 'requestSha256'):
            request = self.request(); request[key] = 'wrong'
            with self.subTest(key=key), self.assertRaises(native.NativeSearchError):
                self.engine.search(request)
        request = self.request(); request['query']['prompt'] = 'changed'
        with self.assertRaisesRegex(native.NativeSearchError, 'search_request_mismatch'):
            self.engine.search(request)

    def test_query_original_exponent_bytes_are_hashed_without_reserialization(self):
        request = self.request(excluded=[{'lat': 1e-7, 'lng': 20}])
        raw = json.dumps(request['query'], ensure_ascii=False, separators=(',', ':')).encode().replace(b'1e-07', b'1e-7')
        request['requestSha256'] = digest(raw)
        with patch.object(native, 'run_native', side_effect=self.fake_native):
            self.assertEqual(self.engine.search(request, raw_query=raw)['processedLocations'], 3)
        with self.assertRaisesRegex(native.NativeSearchError, 'search_request_mismatch'):
            self.engine.search(request)

    def test_modified_snapshot_features_fail_before_native_execution(self):
        bundle = self.engine.batches[0][0]
        path = Path(bundle['indexDir']) / 'semantic-pq128.bin'
        raw = path.read_bytes(); path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with patch.object(native, 'run_native') as run, self.assertRaises(native.NativeSearchError):
            self.engine.search(self.request())
        run.assert_not_called()

    def test_extra_unpinned_snapshot_file_and_runtime_dependency_are_denied(self):
        extra = self.snapshot / 'unapproved.bin'; extra.write_bytes(b'private')
        with self.assertRaisesRegex(native.NativeSearchError, 'object_search_snapshot_changed'):
            self.search()
        extra.unlink()
        (self.binary_dir / 'unapproved.dll').write_bytes(b'different dependency')
        with self.assertRaisesRegex(native.NativeSearchError, 'object_search_runtime_changed'):
            self.search()

    def test_snapshot_and_runtime_limits_are_checked_before_execution(self):
        for key, value in [('maxLocations', 2), ('maxBundles', 1), ('timeoutSeconds', 111), ('environment', 'staging')]:
            self.config[key] = value; self.runtime.write_bytes(encoded(self.config))
            with self.subTest(key=key), self.assertRaises(native.NativeSearchError):
                self.start()
            self.config = copy.deepcopy(self.engine.config)
        self.runtime.write_bytes(encoded(self.config))

    def test_even_a_pinned_profile_cannot_reference_a_model_outside_its_directory(self):
        path = self.models / 'hybrid-object-runtime.json'
        document = native.strict_json(path.read_bytes())
        document['owlv2']['textFile'] = '../private-elsewhere.onnx'
        path.write_bytes(encoded(document))
        self.config['runtimeProfileSha256'] = runtime_profile(self.binary, self.models)['sha256']
        self.runtime.write_bytes(encoded(self.config))
        with patch.object(native, 'run_native') as run, self.assertRaisesRegex(
                native.NativeSearchError, 'invalid_object_search_models'):
            self.start()
        run.assert_not_called()

    def test_oversized_completion_is_refused_and_query_scratch_removed(self):
        with patch.object(objects, 'MAX_RESULT', 64), self.assertRaisesRegex(
                native.NativeSearchError, 'search_response_limit'):
            self.search()
        self.assertFalse(list(self.work.glob('object-query-*')))

    def test_native_output_cannot_invent_members_aims_classes_order_or_filters(self):
        definition = self.engine.validate_request(self.request())
        batch = self.engine.batches[0]
        output = self.result(definition, batch)
        cases = []
        for key, value in [('locationIndex', 20), ('similarity', float('nan')), ('viewOffset', 6)]:
            bad = copy.deepcopy(output); bad['queries'][0]['hits'][0][key] = value; cases.append(bad)
        for key, value in [('supportCount', 0), ('zoom', 6), ('heading', 360), ('className', 'wrong'), ('classId', True)]:
            bad = copy.deepcopy(output); bad['queries'][0]['hits'][0]['object'][key] = value; cases.append(bad)
        bad = copy.deepcopy(output); bad['queries'][0]['hits'][0]['location']['panoId'] = 'unpublished'; cases.append(bad)
        bad = copy.deepcopy(output); bad['queries'][0]['hits'].reverse(); cases.append(bad)
        bad = copy.deepcopy(output); bad['totalLocations'] = 1; cases.append(bad)
        for index, bad in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(native.NativeSearchError):
                self.engine.batch_hits(bad, definition, batch)
        definition['excludeCountries'] = ['Italy']
        with self.assertRaisesRegex(native.NativeSearchError, 'native_filter_mismatch'):
            self.engine.batch_hits(output, definition, batch)

    def test_100_meter_pruning_and_pano_deduplication_span_batches(self):
        # Test merge logic with valid fixture replies; changing the trusted
        # snapshot itself would need an entirely new independent approval.
        with patch.object(self.engine, 'verify_inputs'):
            self.engine.members[2]['pose']['lat'] = 10.00001
            result = self.search()
            self.assertEqual([h['locationId'] for h in result['hits']], [3, 10])
            self.engine.members[2]['pose']['lat'] = 20
            self.engine.members[2]['pose']['panoId'] = self.engine.members[0]['pose']['panoId']
            result = self.search()
            self.assertEqual([h['locationId'] for h in result['hits']], [3, 10])

    def test_timeout_and_missing_pool_receipt_remove_query_scratch_and_keep_first_failure(self):
        def wrong_pool(command, job, timeout):
            self.fake_native(command, job, timeout)
            (job / 'stderr.log').write_text('PRIVATE stderr', encoding='utf-8')
        for unused in range(2):
            with patch.object(native, 'run_native', side_effect=wrong_pool), self.assertRaisesRegex(
                    native.NativeSearchError, 'native_search_runtime_update_required'):
                self.engine.search(self.request())
        reports = list(self.work.glob('failure-*.json'))
        self.assertEqual(len(reports), 1)
        self.assertNotIn(b'PRIVATE', reports[0].read_bytes())
        self.assertFalse(list(self.work.glob('object-query-*')))
        with patch.object(native, 'run_native', side_effect=native.NativeSearchError('native_search_timeout')):
            with self.assertRaisesRegex(native.NativeSearchError, 'native_search_timeout'):
                self.engine.search(self.request())
        self.assertFalse(list(self.work.glob('object-query-*')))

    def test_changed_inputs_after_native_execution_refuse_the_whole_completion(self):
        def changed(command, job, timeout):
            self.fake_native(command, job, timeout)
            if self.native_calls == 2:
                (self.models / 'owlv2-text-encoder.onnx').write_bytes(b'changed during native execution')
        with patch.object(native, 'run_native', side_effect=changed), self.assertRaisesRegex(
                native.NativeSearchError, 'object_search_runtime_changed'):
            self.engine.search(self.request())
        self.assertFalse(list(self.work.glob('object-query-*')))

    def test_shared_deadline_bounds_all_batches_and_verification(self):
        calls = iter([0., 1., 111.])
        with patch.object(objects.time, 'monotonic', side_effect=lambda: next(calls)), \
                patch.object(native, 'run_native', side_effect=self.fake_native), self.assertRaisesRegex(
                    native.NativeSearchError, 'native_search_timeout'):
            self.engine.search(self.request())
        self.assertEqual(self.native_calls, 1)

    def test_busy_instance_never_starts_another_process(self):
        self.engine.busy.acquire()
        try:
            with patch.object(native, 'run_native') as run, self.assertRaisesRegex(native.NativeSearchError, 'search_engine_busy'):
                self.engine.search(self.request())
            run.assert_not_called()
        finally:
            self.engine.busy.release()

    def test_owner_agent_accepts_complete_object_envelope_and_replays_lost_ack(self):
        from community.owner_search_agent import OwnerSearchError
        state = self.root / 'agent'; state.mkdir()
        request = self.request()
        class Coordinator:
            def __init__(this):
                this.calls = []; this.lost = True
            def post(this, action, body):
                this.calls.append((action, body))
                if action == 'claim':
                    return {'job': {'jobId': 'a'*32, 'claimToken': 'b'*64, 'claimUntil': 300, 'expiresAt': 3600,
                                    'requestJson': json.dumps(request, ensure_ascii=False, separators=(',', ':'))}}
                if this.lost:
                    this.lost = False
                    raise OwnerSearchError('coordinator_unavailable', 503)
                return {'completed': True, 'searchId': 'a'*32}
        coordinator = Coordinator()
        agent = OwnerSearchAgent(coordinator, {'object': self.engine}, state)
        with patch.object(native, 'run_native', side_effect=self.fake_native):
            with self.assertRaises(OwnerSearchError):
                agent.run_once()
            self.assertEqual(self.native_calls, 2)
            self.assertEqual(OwnerSearchAgent(coordinator, {'object': self.engine}, state).run_once()['status'], 'completed')
            self.assertEqual(self.native_calls, 2)
        self.assertEqual(coordinator.calls[1], coordinator.calls[2])
        self.assertNotIn('query', coordinator.calls[1][1]['result'])
        self.assertFalse((state / 'outbox.json').exists())

    def test_python_object_packets_pass_actual_gateway_queue_and_once_only_sqlite_settlement(self):
        node = os.environ.get('VISION_TEST_NODE') or shutil.which('node')
        if not node:
            self.skipTest('existing private Node runtime not supplied')
        cases = []
        for prompt, route in [('car', 'common'), ('bird nest', 'hot'), ('an unusual blue sculpture', 'semantic')]:
            request = self.request(prompt=prompt)
            cases.append({'query': request['query'], 'result': self.search(request), 'route': route})
        packet = self.root / 'interop.json'
        # Do not use encoded(): its sorted keys would change each normalized
        # query's field order and therefore its gateway fingerprint.
        packet.write_bytes(json.dumps({'scope': 'synthetic-owner-object-search-interop', 'cases': cases,
                                       'members': self.engine.members}, ensure_ascii=False, separators=(',', ':')).encode())
        repo = Path(__file__).resolve().parents[2]
        stdout, stderr = self.root / 'node.stdout.log', self.root / 'node.stderr.log'
        with stdout.open('xb') as out, stderr.open('xb') as err:
            result = run_owned([node, '--disable-warning=ExperimentalWarning',
                str(repo / 'deploy/cloudflare/tools/owner-object-search-interop.mjs'), str(packet)],
                env=dict(os.environ), cwd=repo, stdout=out, stderr=err, timeout=30)
        if os.environ.get('VISION_TEST_EVIDENCE_DIR'):
            evidence = Path(os.environ['VISION_TEST_EVIDENCE_DIR'])
            evidence.mkdir(parents=True, exist_ok=True)
            for path in (stdout, stderr):
                shutil.copyfile(path, evidence / ('interop-' + path.name))
        self.assertEqual(result.returncode, 0, stderr.read_text()[-5000:])
        self.assertEqual(json.loads(stdout.read_bytes()), {'status': 'OWNER_OBJECT_SEARCH_INTEROP_PASSED',
            'routes': 3, 'staleAuthorityRefusals': 9, 'onceOnlyDebits': 3, 'synthetic': True, 'liveReady': False})


class NativeObjectRunnerTest(unittest.TestCase):
    def test_native_pid_named_temporary_output_is_bounded_before_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            job = Path(temporary)
            script = "import os,time;from pathlib import Path;Path('output.'+str(os.getpid())+'.tmp').write_bytes(b'x'*2048);time.sleep(30)"
            # A real hidden Python child, with a tiny output limit. No native
            # model or provider execution is involved.
            with patch.object(native, 'MAX_NATIVE_OUTPUT', 1024), self.assertRaisesRegex(
                    native.NativeSearchError, 'native_output_limit'):
                native.run_native([sys.executable, '-c', script], job, 3)
            self.assertEqual(len(list(job.glob('output.*.tmp'))), 1)


if __name__ == '__main__':
    unittest.main()
