import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from community.owner_search_agent import OwnerSearchAgent, OwnerSearchError, _exclusive
from community.owner_search_supervisor import OwnerSearchSupervisor, OwnerSupervisorError, MAX_RETRY_SECONDS
from community.tests.test_owner_search_agent import Coordinator, Engine, job


class Clock:
    def __init__(self): self.now = 2_000_000_000
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


class Agent:
    def __init__(self, state):
        self.state, self.calls = state, 0
        self.result = {"status": "idle", "retryAfterSeconds": 30}
        self.error, self.hook = None, None

    def run_once(self):
        self.calls += 1
        if self.hook: self.hook()
        if self.error: raise self.error
        return self.result


class OwnerSearchSupervisorTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.clock, self.agent = Clock(), Agent(self.root)

    def supervisor(self, agent=None, jitter=lambda: 0):
        return OwnerSearchSupervisor(agent or self.agent, wall_clock=self.clock, jitter=jitter)

    def state(self): return json.loads((self.root / 'supervisor.json').read_bytes())

    def test_idle_timer_survives_restart_and_jitter_never_undercuts_thirty_seconds(self):
        result = self.supervisor(jitter=lambda: 1).step()
        self.assertEqual(result, {"status": "idle", "waitSeconds": 38})
        self.assertEqual(self.supervisor().step(), {"status": "deferred", "waitSeconds": 38})
        self.clock.advance(37); self.assertEqual(self.supervisor().step()["status"], "deferred")
        self.assertEqual(self.agent.calls, 1)
        self.clock.advance(1); self.assertEqual(self.supervisor().step()["waitSeconds"], 30)
        self.assertEqual(self.agent.calls, 2)

    def test_quota_and_outage_backoff_is_durable_capped_and_preserves_first_failure(self):
        self.agent.error = OwnerSearchError("coordinator_unavailable", 429)
        delays = []
        for index in range(10):
            if index: self.agent.error = OwnerSearchError("coordinator_unavailable", 503)
            result = self.supervisor().step(); delays.append(result["waitSeconds"])
            self.assertEqual(result["error"], "connection_unavailable")
            before = self.agent.calls
            self.assertEqual(self.supervisor().step()["status"], "deferred")
            self.assertEqual(self.agent.calls, before)
            self.clock.advance(result["waitSeconds"])
        self.assertEqual(delays, [60, 120, 240, 480, 960, 1920, 3600, 3600, 3600, 3600])
        receipt = (self.root / 'supervisor.failure.json').read_bytes()
        self.agent.error = None; self.agent.result = {"status": "completed"}
        self.assertEqual(self.supervisor().step(), {"status": "completed", "waitSeconds": 5})
        self.assertEqual(self.state()["failures"], 0)
        self.assertEqual((self.root / 'supervisor.failure.json').read_bytes(), receipt)
        self.assertEqual(len(list(self.root.iterdir())), 3)

    def test_authentication_latches_without_probes_and_explicit_resume_keeps_outbox(self):
        coordinator, engine = Coordinator(job()), Engine()
        coordinator.delivery_error = OwnerSearchError("coordinator_unavailable", 401)
        agent = OwnerSearchAgent(coordinator, {"scene": engine}, self.root)
        result = self.supervisor(agent).step()
        self.assertEqual(result["status"], "operator_required")
        saved = (self.root / 'outbox.json').read_bytes(); calls = len(coordinator.calls)
        self.clock.advance(86400)
        self.assertEqual(self.supervisor(agent).step()["status"], "operator_required")
        self.assertEqual(len(coordinator.calls), calls)
        self.supervisor(agent).resume_after_operator_fix()
        self.assertEqual((self.root / 'outbox.json').read_bytes(), saved)
        coordinator.delivery_error = None
        self.assertEqual(self.supervisor(agent).step()["status"], "completed")
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual([action for action, _ in coordinator.calls], ['claim', 'complete', 'complete'])

    def test_unknown_error_latches_and_cannot_echo_private_details(self):
        self.agent.error = RuntimeError('PRIVATE PROMPT credential secret C:/private/path')
        result = self.supervisor().step()
        self.assertEqual(result["error"], "owner_configuration_required")
        for path in self.root.iterdir():
            if path.suffix == '.json':
                content = path.read_text()
                self.assertNotIn('PRIVATE', content); self.assertNotIn('credential', content)
        self.clock.advance(86400)
        self.assertEqual(self.supervisor().step()["status"], "operator_required")
        self.assertEqual(self.agent.calls, 1)

    def test_stale_owner_bindings_latch_across_restart_without_repeated_probes(self):
        self.agent.error = OwnerSearchError('owner_binding_configuration_required', 409)
        self.assertEqual(self.supervisor().step()['status'], 'operator_required')
        self.assertEqual(self.state()['lastError'], 'owner_configuration_required')
        self.clock.advance(86400)
        self.assertEqual(self.supervisor().step()['status'], 'operator_required')
        self.assertEqual(self.agent.calls, 1)
        self.agent.error = None
        self.supervisor().resume_after_operator_fix()
        self.assertEqual(self.supervisor().step()['status'], 'idle')
        self.assertEqual(self.agent.calls, 2)

    def test_native_failures_back_off_and_idle_success_resets_failure_count(self):
        self.agent.result = {"status": "failed"}
        self.assertEqual(self.supervisor().step()["waitSeconds"], 60)
        self.clock.advance(60)
        self.assertEqual(self.supervisor().step()["waitSeconds"], 120)
        self.clock.advance(120); self.agent.result = {"status": "idle"}
        self.assertEqual(self.supervisor().step()["waitSeconds"], 30)
        self.assertEqual(self.state()["failures"], 0)

    def test_crash_after_durable_attempt_start_cannot_reset_retry_timer(self):
        def interrupted():
            self.assertGreater(self.state()["nextAttemptAt"], self.clock.now)
            raise KeyboardInterrupt()
        self.agent.hook = interrupted
        with self.assertRaises(KeyboardInterrupt): self.supervisor().step()
        self.agent.hook = None
        self.assertEqual(self.supervisor().step(), {"status": "deferred", "waitSeconds": 60})
        self.assertEqual(self.agent.calls, 1)
        self.clock.advance(60)
        self.assertEqual(self.supervisor().step()["status"], "idle")
        self.assertEqual(json.loads((self.root/'supervisor.failure.json').read_bytes())["error"], "attempt_interrupted")

    def test_pause_and_stop_prevent_execution_and_explicit_reset_never_clears_markers(self):
        for marker, status in [('PAUSE', 'paused'), ('STOP', 'stopped')]:
            (self.root / marker).touch()
            self.assertEqual(self.supervisor().step()["status"], status)
            self.supervisor().resume_after_operator_fix()
            self.assertTrue((self.root / marker).exists())
            self.assertEqual(self.supervisor().step()["status"], status)
            self.assertEqual(self.agent.calls, 0)
            (self.root / marker).unlink()

    def test_pause_written_after_preflight_still_prevents_agent_execution(self):
        supervisor = self.supervisor(); original = supervisor._save
        def save(state):
            original(state); (self.root / 'PAUSE').touch()
        with patch.object(supervisor, '_save', side_effect=save):
            self.assertEqual(supervisor.step()["status"], "paused")
        self.assertEqual(self.agent.calls, 0)
        self.assertIsNone(self.state()["lastError"])
        self.assertFalse((self.root/'supervisor.failure.json').exists())

    def test_repeated_crashes_increase_backoff_and_malformed_agent_results_latch(self):
        self.agent.error = KeyboardInterrupt()
        for expected in [60, 120, 240]:
            with self.assertRaises(KeyboardInterrupt): self.supervisor().step()
            self.assertEqual(self.state()["nextAttemptAt"] - self.clock.now, expected)
            self.clock.advance(expected)
        self.agent.error = None; self.agent.result = {"status": ["private", "data"]}
        self.assertEqual(self.supervisor().step()["error"], "owner_configuration_required")

    def test_corrupt_state_and_partial_pending_are_preserved_and_never_poll(self):
        for filename in ['supervisor.json', 'supervisor.pending']:
            path = self.root / filename; raw = b'{"revision":1,'; path.write_bytes(raw)
            with self.assertRaisesRegex(OwnerSupervisorError, 'owner_supervision_state_invalid'):
                self.supervisor().step()
            with self.assertRaises(OwnerSupervisorError): self.supervisor().resume_after_operator_fix()
            self.assertEqual(path.read_bytes(), raw); self.assertEqual(self.agent.calls, 0)
            path.unlink()

    def test_complete_pending_retry_state_recovers_rename_without_new_request(self):
        self.agent.error = OwnerSearchError('coordinator_unavailable', 503)
        self.supervisor().step()
        path = self.root / 'supervisor.json'; pending = self.root / 'supervisor.pending'
        path.replace(pending)
        self.assertEqual(self.supervisor().step()["status"], 'deferred')
        self.assertFalse(pending.exists()); self.assertTrue(path.exists()); self.assertEqual(self.agent.calls, 1)

    def test_state_cannot_accept_extra_fields_nonfinite_values_or_private_error_text(self):
        base = {"revision":1,"mode":"waiting","nextAttemptAt":0,"failures":0,"lastError":None}
        for changes in [{"secret":"do not persist"}, {"nextAttemptAt":True}, {"failures":21}, {"lastError":[]},
                        {"lastError":"upstream PRIVATE stderr"}, {"mode":"blocked"}, {"revision":True}]:
            path = self.root / 'supervisor.json'; path.write_text(json.dumps({**base, **changes}))
            with self.assertRaises(OwnerSupervisorError): self.supervisor().step()
            self.assertEqual(self.agent.calls, 0)

    def test_competing_supervisor_cannot_overwrite_timer_or_call_agent(self):
        with _exclusive(self.root, name='supervisor.lock'):
            self.assertEqual(self.supervisor().step(), {"status":"busy","waitSeconds":30})
        self.assertEqual(self.agent.calls, 0); self.assertFalse((self.root/'supervisor.json').exists())

    def test_clock_rollback_does_not_turn_waiting_work_into_immediate_retry(self):
        self.supervisor().step(); self.clock.advance(-86400)
        self.assertEqual(self.supervisor().step(), {"status":"deferred","waitSeconds":MAX_RETRY_SECONDS})
        self.assertEqual(self.agent.calls, 1)

    def test_storage_failure_prevents_any_network_or_native_work(self):
        with patch('community.owner_search_supervisor.os.fsync', side_effect=OSError('private filesystem detail')):
            with self.assertRaisesRegex(OwnerSupervisorError, 'owner_supervision_storage_unavailable'):
                self.supervisor().step()
        self.assertEqual(self.agent.calls, 0); self.assertTrue((self.root/'supervisor.pending').exists())

    def test_explicit_loop_waits_interruptibly_and_exits_on_operator_latch_or_stop(self):
        class Stop:
            def __init__(self): self.waits = []; self.stopped = False
            def is_set(self): return self.stopped
            def wait(self, delay): self.waits.append(delay); self.stopped = True; return True
        stop = Stop(); self.assertEqual(self.supervisor().run(stop), {"status":"stopped"})
        self.assertEqual(stop.waits, [30]); self.assertEqual(self.agent.calls, 1)
        self.clock.advance(30); self.agent.error = OwnerSearchError('coordinator_unavailable',403)
        stop = Stop(); self.assertEqual(self.supervisor().run(stop)["status"], 'operator_required')
        self.assertEqual(stop.waits, [])
        (self.root/'STOP').touch()
        self.assertEqual(self.supervisor().run(Stop())["status"], 'stopped')

    def test_invalid_clocks_and_jitter_fail_before_agent_calls(self):
        for invalid in [True, float('nan'), float('inf'), -1, 'private']:
            with self.assertRaisesRegex(OwnerSupervisorError, 'owner_clock_invalid'):
                OwnerSearchSupervisor(self.agent, wall_clock=lambda: invalid).step()
            with self.assertRaisesRegex(OwnerSupervisorError, 'owner_pacing_invalid'):
                self.supervisor(jitter=lambda: invalid).step()
        self.assertEqual(self.agent.calls, 0)
