import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from unittest.mock import patch
from community import finite_scene_trial as trial
from community.finite_scene_trial import BoundedOpener, FiniteTrialError, FiniteSceneClient, HEADERS, ORIGIN


class Reply(io.BytesIO):
    def __init__(self, **usage):
        super().__init__(b'{}')
        self.headers = {name: str(usage.get(key, 0)) for key, name in HEADERS.items()}
        self.headers['x-vision-trial-usage-complete'] = '1'


class Transport:
    def __init__(self, **usage):
        self.calls, self.usage = [], usage
    def open(self, request, timeout):
        self.calls.append((request, timeout))
        return Reply(**self.usage)


class FiniteSceneBudgetTests(unittest.TestCase):
    def budget(self, transport=None):
        return BoundedOpener(transport or Transport(), 'a' * 64, deadline=600, clock=lambda: 0)
    def request(self, path='/api/me', **kwargs):
        return urllib.request.Request(ORIGIN + path, **kwargs)

    def test_attempt_limit_counts_real_transport_and_caps_socket_timeout(self):
        transport = Transport(read=1)
        budget = self.budget(transport)
        for _ in range(32):
            with budget.open(self.request(), timeout=120): pass
        with self.assertRaisesRegex(FiniteTrialError, 'request_limit'):
            budget.open(self.request())
        self.assertEqual(len(transport.calls), 32)
        self.assertEqual(budget.usage['read'], 32)
        self.assertTrue(all(timeout <= 10 for _, timeout in transport.calls))
        self.assertTrue(all(req.get_header('X-vision-finite-cohort') == 'a' * 64 for req, _ in transport.calls))
        self.assertEqual(transport.calls[-1][0].get_header('X-vision-trial-remaining-read'), '1969')

    def test_new_account_qualification_search_other_origin_and_deadline_never_send(self):
        transport = Transport(); budget = self.budget(transport)
        for path in ('/api/accounts', '/api/scene-qualifications', '/api/searches', '/api/object-audits'):
            with self.assertRaisesRegex(FiniteTrialError, 'request_scope'):
                budget.open(self.request(path, data=b'{}'))
        with self.assertRaisesRegex(FiniteTrialError, 'request_scope'):
            budget.open(urllib.request.Request('https://unrelated.example/api/me'))
        budget.deadline = 0
        with self.assertRaisesRegex(FiniteTrialError, 'request_limit'):
            budget.open(self.request())
        self.assertEqual(transport.calls, [])

    def test_cumulative_observed_usage_and_upload_bounds_stop_before_further_requests(self):
        for usage in ({'read': 1001}, {'written': 65}, {'puts': 3}, {'bytes': 262145}):
            transport = Transport(**usage); budget = self.budget(transport)
            budget.open(self.request()).close()
            with self.assertRaisesRegex(FiniteTrialError, 'usage_limit'):
                budget.open(self.request())
            with self.assertRaisesRegex(FiniteTrialError, 'request_limit'):
                budget.open(self.request())
            self.assertEqual(len(transport.calls), 2)
        transport = Transport(); budget = self.budget(transport)
        budget.open(self.request('/api/submissions', data=b'x' * 524288)).close()
        with self.assertRaisesRegex(FiniteTrialError, 'request_limit'):
            budget.open(self.request('/api/submissions', data=b'x'))
        self.assertEqual(len(transport.calls), 1)

    def test_unknown_usage_or_network_failure_cannot_silently_retry(self):
        for failure in ('metadata', 'network', 'http'):
            class Broken:
                calls = 0
                def open(self, request, timeout):
                    self.calls += 1
                    if failure == 'network': raise urllib.error.URLError('private diagnostic')
                    if failure == 'http': raise urllib.error.HTTPError(request.full_url, 503, 'unavailable', {}, io.BytesIO())
                    response = Reply(); response.headers['x-vision-trial-usage-complete'] = '0'; return response
            transport = Broken(); budget = self.budget(transport)
            with self.assertRaises((FiniteTrialError, urllib.error.URLError)):
                budget.open(self.request())
            with self.assertRaisesRegex(FiniteTrialError, 'request_limit'):
                budget.open(self.request())
            self.assertEqual(transport.calls, 1)

    def test_no_second_assignment_even_after_first_assignment_fails(self):
        client = FiniteSceneClient('a' * 64, deadline=600)
        client.budget.clock = lambda: 0
        calls = []
        def fail(*args, **kwargs):
            calls.append(args); raise FiniteTrialError('finite_scene_http_failure')
        client.request = fail
        with self.assertRaises(FiniteTrialError): client.lease('scene', 2, 'slow')
        with self.assertRaisesRegex(FiniteTrialError, 'assignment_limit'): client.lease('scene', 2, 'slow')
        self.assertEqual(len(calls), 1)


class FiniteSceneExecutionTests(unittest.TestCase):
    def client(self, qualification_valid=True):
        class Client:
            pending = 0
            assigned_lease = None
            budget = type('Budget', (), {'stopped': False, 'requests': 0, 'sent_bytes': 0,
                                        'usage': {'read': 0, 'written': 0, 'puts': 0, 'bytes': 0}})()
            reads = 0
            def recover(self, code): return {'accountId': 'a' * 32}
            def enable_outbox(self, *args): pass
            def me(self):
                self.reads += 1
                return {'units': 0 if self.reads == 1 else 2}
            def request(self, method, path):
                if path == '/api/capabilities':
                    return 200, {'sceneContributions': {'ready': True, 'admissionMode': 'qualified-device-v1',
                        'model': 'vision-four-view-v4', 'scope': 'qualified-new-locations', 'maxBatchLocations': 2,
                        'verification': 'trusted-profile-canary-and-upload-integrity', 'policyId': 'test',
                        'deviceQualificationRequired': True, 'canaryLocations': 112}, 'objectContributions': {'ready': False}}, None
                return 200, {'qualified': qualification_valid, 'profileId': 'b' * 64,
                             'policyId': 'test', 'expiresAt': int(time.time()) + 3600}, None
            def audit_submission(self, lease): return {'admissionMode': 'qualified-device-v1', 'unitsEarned': 0}
        return Client()

    def run_fixture(self, root, client, indexer):
        with patch.object(trial, 'FiniteSceneClient', return_value=client), patch.object(trial.vision_index, 'index_from_queue', side_effect=indexer):
            return trial.run_trial(account={'accountId': 'a' * 32, 'recoveryCode': 'SYNTHETIC'},
                report={'runtimeProfile': {'sha256': 'b' * 64}}, policy=type('Policy', (), {'document': {'policyId': 'test'}})(),
                binary=Path('fixture.exe'), model_dir=Path('fixture-models'), work_dir=root, token='c' * 64)

    def test_one_batch_uses_default_native_runner_and_cannot_claim_gateway_shutdown(self):
        with tempfile.TemporaryDirectory() as folder:
            client = self.client()
            def indexer(**kwargs):
                self.assertEqual((kwargs['count'], kwargs['batches'], kwargs['pace']), (2, 1, 'slow'))
                self.assertNotIn('runner', kwargs)
                client.assigned_lease = 'd' * 32
                return {'batches': 1, 'accepted': 2, 'unitsEarned': 2}
            result = self.run_fixture(Path(folder), client, indexer)
            self.assertEqual(result['status'], 'FINITE_QUALIFIED_SCENE_COHORT_PASSED')
            self.assertEqual(result['replayEarnedUnits'], 0)
            self.assertFalse(result['gatewayClosed'])
            self.assertTrue(result['shutdownReadbackRequired'])
            self.assertTrue(client.budget.stopped)

    def test_unusable_server_qualification_never_starts_native_work(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            result = self.run_fixture(Path(folder), self.client(False), lambda **kwargs: calls.append(kwargs))
            self.assertEqual(result['status'], 'INCOMPLETE')
            self.assertEqual(result['reason'], 'finite_scene_qualification_required')
            self.assertFalse(result['workStarted'])
            self.assertEqual(calls, [])

    def test_supervisor_bounds_the_owned_child_and_preserves_timed_out_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'trial'
            def timeout(argv, **kwargs):
                self.assertEqual(kwargs['timeout'], 600)
                self.assertIn('--owned-child', argv)
                (root / 'saved-work').write_bytes(b'keep')
                raise subprocess.TimeoutExpired(argv, 600)
            result = trial.supervise_trial(['--run'], root, owned_runner=timeout)
            self.assertEqual(result['status'], 'INCOMPLETE')
            self.assertEqual(result['reason'], 'finite_scene_child_timeout')
            self.assertEqual((root / 'saved-work').read_bytes(), b'keep')
            self.assertTrue((root / 'supervisor.receipt.private.json').is_file())
            self.assertFalse(result['gatewayClosed'])
            with self.assertRaises(FileExistsError):
                trial.supervise_trial(['--run'], root, owned_runner=timeout)


if __name__ == '__main__':
    unittest.main()
