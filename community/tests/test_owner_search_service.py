from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from community import owner_search_service as service
from community.owner_search_agent import OwnerSearchError, _exclusive
from community.search_snapshot import CONFIRMED_STAGING_RESOURCE, digest, encoded
from community.tests.test_owner_search_agent import Coordinator, Engine, job

ROOT = Path(__file__).resolve().parents[2]


class OwnerSearchServiceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.state = self.root/'state'; self.state.mkdir()
        self.config = {'version': 1, 'scope': service.SCOPE, 'origin': 'https://community.example.test',
                       'environment': 'staging', 'state': str(self.state), 'lanes': {}}
        for lane in ('scene', 'object'):
            runtime = self.root/(lane+'-runtime'); runtime.mkdir()
            snapshot = self.root/(lane+'-snapshot'); snapshot.mkdir()
            raw = encoded({'contractVersion': 2, 'policyId': 'fixture', 'environment': 'staging',
                           'resource': CONFIRMED_STAGING_RESOURCE, 'fixtureLane': lane})
            (runtime/'runtime.json').write_bytes(raw)
            members = encoded({'resource': CONFIRMED_STAGING_RESOURCE, 'fixtureLane': lane})
            (snapshot/'snapshot.json').write_bytes(members)
            definition = {'policyId': 'fixture', 'runtime': str(runtime/'runtime.json'),
                'runtimeSha256': digest(raw), 'snapshot': str(snapshot), 'snapshotSha256': digest(members)}
            if lane == 'object': definition.update(binary=str(runtime/'native'), models=str(runtime/'models'))
            self.config['lanes'][lane] = definition
        self.object_definition = self.config['lanes'].pop('object')
        self.path = self.root/'service.private.json'
        self.save()
        self.coordinator, self.engines = Coordinator(self.job()), {'scene': Engine(), 'object': Engine()}
        self.stack = self.enterContext(ExitStack())
        self.credentials = self.stack.enter_context(patch.object(service.HTTPSCoordinator, 'from_os_credentials', return_value=self.coordinator))
        self.scene = self.stack.enter_context(patch('community.native_scene_search.NativeSceneEngine', return_value=self.engines['scene']))
        self.objects = self.stack.enter_context(patch('community.native_object_search.NativeObjectSearchEngine', return_value=self.engines['object']))

    def save(self, activate=True):
        self.path.write_bytes(encoded(self.config)); self.pin = digest(self.path.read_bytes())
        if activate:
            (self.state/service.ACTIVATION).write_bytes(encoded({'version': 1,
                'scope': 'explicit-owner-search-activation', 'approved': True, 'configSha256': self.pin,
                'origin': self.config['origin'], 'environment': self.config['environment']}))

    def job(self, lane='scene'):
        value = job(); d = self.config['lanes'][lane]
        value['requestJson'] = value['requestJson'].replace('d'*64, d['runtimeSha256']).replace('e'*64, d['snapshotSha256'])
        value['requestJson'] = value['requestJson'].replace('"lane":"scene"', '"lane":"'+lane+'"')
        return value

    def run_once(self): return service.run_service(self.path, self.pin, once=True)

    def allow_next_step(self):
        path = self.state/'supervisor.json'; doc = json.loads(path.read_bytes())
        doc['nextAttemptAt'] = 0; path.write_bytes(encoded(doc))

    def test_actual_assembled_scene_path_uses_exact_bindings_raw_query_and_reusable_mount(self):
        self.assertEqual(self.run_once()['status'], 'completed')
        self.assertEqual([a for a, _ in self.coordinator.calls], ['claim', 'complete'])
        self.credentials.assert_called_once_with(self.config['origin'])
        self.assertEqual(self.scene.call_args.kwargs, {'reuse_mount': True})
        self.assertIn(b'"lat":1e-7', self.engines['scene'].calls[0][1])
        self.assertEqual(self.coordinator.calls[0][1]['bindings']['scene']['runtimeSha256'], self.config['lanes']['scene']['runtimeSha256'])
        self.objects.assert_not_called()

    def test_both_routes_use_independent_pins_and_initialize_only_the_claimed_engine(self):
        self.config['lanes']['object'] = self.object_definition; self.save()
        self.coordinator.job = self.job('object')
        self.assertEqual(self.run_once()['status'], 'completed')
        claim = self.coordinator.calls[0][1]
        self.assertEqual(claim['lanes'], ['object', 'scene'])
        self.assertNotEqual(claim['bindings']['scene']['runtimeSha256'], claim['bindings']['object']['runtimeSha256'])
        self.scene.assert_not_called(); self.objects.assert_called_once()
        self.assertIn(b'"lat":1e-7', self.engines['object'].calls[0][1])

    def test_lost_ack_restart_replays_exact_completion_with_native_inputs_unavailable(self):
        self.coordinator.lose_reply = True
        self.assertEqual(self.run_once()['status'], 'retry_wait')
        before = (self.state/'outbox.json').read_bytes()
        failure = (self.state/'supervisor.failure.json').read_bytes()
        for definition in self.config['lanes'].values():
            Path(definition['runtime']).unlink(); (Path(definition['snapshot'])/'snapshot.json').unlink()
        self.scene.reset_mock(); self.allow_next_step()
        self.assertEqual(self.run_once()['status'], 'completed')
        self.assertFalse((self.state/'outbox.json').exists())
        self.assertEqual(encoded(self.coordinator.calls[-1][1]), encoded(json.loads(before)['body']))
        self.assertEqual([a for a, _ in self.coordinator.calls], ['claim', 'complete', 'complete'])
        self.scene.assert_not_called(); self.objects.assert_not_called()
        self.assertEqual(len(self.engines['scene'].calls), 1)
        self.assertEqual((self.state/'supervisor.failure.json').read_bytes(), failure)

    def test_pause_stop_and_missing_activation_never_touch_credentials_or_engines(self):
        (self.state/service.ACTIVATION).unlink()
        (self.state/'PAUSE').write_text('fixture pause')
        self.assertEqual(self.run_once(), {'status': 'paused'})
        (self.state/'STOP').write_text('fixture stop')
        self.assertEqual(self.run_once(), {'status': 'stopped'})
        self.credentials.assert_not_called(); self.scene.assert_not_called(); self.objects.assert_not_called()
        self.assertFalse((self.state/'supervisor.json').exists())

    def test_explicit_activation_is_required_and_first_redacted_failure_is_preserved(self):
        (self.state/service.ACTIVATION).unlink()
        with self.assertRaisesRegex(service.OwnerServiceError, 'owner_service_operator_required'): self.run_once()
        report = (self.state/'owner-service.failure.json').read_bytes()
        with self.assertRaisesRegex(service.OwnerServiceError, 'owner_service_operator_required'): self.run_once()
        self.assertEqual(report, (self.state/'owner-service.failure.json').read_bytes())
        self.assertFalse((self.state/service.ACTIVATION).exists())
        for private in (str(self.path), str(self.root), self.config['origin']): self.assertNotIn(private.encode(), report)
        self.credentials.assert_not_called()

    def test_wrong_activation_identity_cannot_be_reused_after_configuration_change(self):
        self.config['origin'] = 'https://changed.example.test'; self.save(activate=False)
        with self.assertRaises(service.OwnerServiceError): self.run_once()
        self.credentials.assert_not_called()

    def test_process_lock_prevents_competing_initialization_or_delivery(self):
        with _exclusive(self.state, name='service.lock'):
            self.assertEqual(self.run_once(), {'status': 'busy'})
        self.credentials.assert_not_called(); self.scene.assert_not_called()

    def test_deferred_or_blocked_restarts_do_not_read_vaults_or_native_assets(self):
        self.coordinator.job = None
        self.assertEqual(self.run_once()['status'], 'idle')
        self.credentials.reset_mock()
        self.assertEqual(self.run_once()['status'], 'deferred')
        self.credentials.assert_not_called(); self.scene.assert_not_called()
        self.allow_next_step(); self.coordinator.job = self.job()
        self.coordinator.delivery_error = OwnerSearchError('coordinator_unavailable', 401)
        self.assertEqual(self.run_once()['status'], 'operator_required')
        saved = (self.state/'outbox.json').read_bytes()
        self.credentials.reset_mock(); self.scene.reset_mock()
        self.assertEqual(self.run_once()['status'], 'operator_required')
        self.credentials.assert_not_called(); self.scene.assert_not_called()
        self.assertEqual((self.state/'outbox.json').read_bytes(), saved)

    def test_revocation_during_computation_retains_completion_without_delivering_or_recomputing(self):
        original = self.engines['scene'].search
        def revoke(request, *, raw_query):
            result = original(request, raw_query=raw_query)
            (self.state/service.ACTIVATION).unlink()
            return result
        self.engines['scene'].search = revoke
        self.assertEqual(self.run_once()['status'], 'operator_required')
        self.assertEqual([a for a, _ in self.coordinator.calls], ['claim'])
        self.assertEqual(json.loads((self.state/'outbox.json').read_bytes())['action'], 'complete')
        self.assertEqual(len(self.engines['scene'].calls), 1)

    def test_revocation_during_vault_read_prevents_first_network_request(self):
        def revoke(_):
            (self.state/service.ACTIVATION).unlink(); return self.coordinator
        self.credentials.side_effect = revoke
        self.assertEqual(self.run_once()['status'], 'operator_required')
        self.assertFalse(self.coordinator.calls); self.scene.assert_not_called()

    def test_configuration_change_after_claim_prevents_native_execution_and_preserves_failure_outbox(self):
        original = self.coordinator.post
        def change(action, value):
            result = original(action, value)
            if action == 'claim': self.path.write_bytes(self.path.read_bytes()+b' ')
            return result
        self.coordinator.post = change
        self.assertEqual(self.run_once()['status'], 'operator_required')
        self.assertEqual([a for a, _ in self.coordinator.calls], ['claim'])
        self.scene.assert_not_called()
        self.assertEqual(json.loads((self.state/'outbox.json').read_bytes())['action'], 'fail')

    def test_resource_mismatch_refuses_before_native_initialization_with_no_prompt_in_reports(self):
        d = self.config['lanes']['scene']; path = Path(d['snapshot'])/'snapshot.json'
        path.write_bytes(encoded({'resource': {'bucket': 'wrong-fixture-resource'}}))
        d['snapshotSha256'] = digest(path.read_bytes()); self.save(); self.coordinator.job = self.job()
        self.assertEqual(self.run_once()['error'], 'native_search_failed')
        self.assertEqual([a for a, _ in self.coordinator.calls], ['claim', 'fail'])
        self.scene.assert_not_called()
        for report in self.state.glob('*failure*.json'):
            for private in ('private café', 'PRIVATE', str(self.root), self.config['origin']):
                self.assertNotIn(private.encode(), report.read_bytes())

    def test_native_exception_sends_only_fixed_failure_and_keeps_original_evidence(self):
        self.scene.side_effect = ValueError('PRIVATE model path and credential details')
        self.assertEqual(self.run_once()['error'], 'native_search_failed')
        self.assertEqual(self.coordinator.calls[-1], ('fail', {'jobId': 'a'*32, 'claimToken': 'b'*64}))
        self.assertNotIn(b'PRIVATE', (self.state/'failure-owner_search_failed.json').read_bytes())

    def test_private_configuration_rejects_extra_secrets_overlapping_inputs_and_wrong_environment(self):
        changes = [lambda d: d.update(secret='PRIVATE forbidden credential'),
                   lambda d: d.update(state=str(ROOT/'private-state-fixture')),
                   lambda d: d['lanes']['scene'].update(snapshot=str(self.state)),
                   lambda d: d['lanes']['scene'].update(runtime='relative/runtime.json'),
                   lambda d: d['lanes']['scene'].update(policyId='staging.private') or d.update(environment='production'),
                   lambda d: d.update(origin='https://private:credential@community.example.test')]
        original = copy.deepcopy(self.config)
        for change in changes:
            self.config = copy.deepcopy(original); change(self.config); self.save()
            with self.subTest(config=self.config), self.assertRaises(ValueError):
                service.load_configuration(self.path, self.pin)
        self.credentials.assert_not_called()

    def test_shutdown_event_exits_the_explicit_loop_before_credentials_or_native_work(self):
        stop = threading.Event(); stop.set()
        self.assertEqual(service.run_service(self.path, self.pin, stop_event=stop), {'status': 'stopped'})
        self.credentials.assert_not_called(); self.scene.assert_not_called()

    def test_isolated_real_cli_refuses_activation_without_importing_pythonpath_or_echoing_private_configuration(self):
        (self.state/service.ACTIVATION).unlink()
        poison = self.root/'untrusted-pythonpath'; (poison/'community').mkdir(parents=True)
        marker = self.root/'UNSAFE-IMPORT'
        (poison/'community/__init__.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("bad")\n')
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT/'owner-search.py'), '--config', str(self.path),
            '--config-sha256', self.pin, '--once'], capture_output=True, text=True, timeout=20,
            env={**os.environ, 'PYTHONPATH': str(poison)},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout), {'status': 'operator_required', 'error': 'owner_service_operator_required'})
        self.assertFalse(marker.exists()); self.assertFalse(result.stderr)
        for private in (str(self.path), str(self.root), self.config['origin']): self.assertNotIn(private, result.stdout)


if __name__ == '__main__': unittest.main()
