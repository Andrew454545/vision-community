"""Object delivery across real HTTP, SQLite and fresh Python processes.

The native runner emits an explicit synthetic contract fixture. This tests
delivery and local prototype accounting, never model quality, hosted admission,
real imagery, a public account or real search credits.
"""
from contextlib import closing
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from community.contribute import CommunityClient, ContributeError
from community.delivery import DurableCommunityClient
from community.desktop import DesktopClient, public_error
from community.service import CommunityService, ServiceError
from community.submission_outbox import SubmissionOutbox

REPO = Path(__file__).resolve().parents[2]
CHILD = """
import hashlib,json,sys
from pathlib import Path
from community.contribute import ContributeError
from community.object_index import index_from_queue
from community.tests.test_object_index import contract_bundle
root,url=Path(sys.argv[1]),sys.argv[2]
settings=json.loads((root/'fixture-settings.json').read_text())
def runner(argv,env,cwd):
    if 'index-segment' in argv:
        with (root/'inference-calls.txt').open('a') as calls:calls.write('synthetic fixture only\\n')
        lease=json.loads((root/'fixture-lease.json').read_text())
        output=Path(argv[argv.index('--output-dir')+1])
        source=Path(argv[argv.index('--source-tsv')+1])
        if settings.get('nativeFailure'):
            output.mkdir(parents=True,exist_ok=True)
            (output/'checkpoint.json').write_text(json.dumps({'feature':'vision-object-index','nextLocationIndex':0,'completed':False}))
            if settings['nativeFailure']=='interrupt':raise KeyboardInterrupt()
            return 1,'','synthetic interrupted native program'
        manifest,files,tsv=contract_bundle(lease['items'],lease['leaseId'],source)
        # The real program pins the actual TSV bytes, including Windows CRLF.
        actual_source=source.read_bytes()
        manifest['sourceBytes']=len(actual_source)
        manifest['sourceSha256']=hashlib.sha256(actual_source).hexdigest()
        output.mkdir(parents=True,exist_ok=True)
        (output/'manifest.json').write_text(json.dumps(manifest))
        for name,payload in files.items():(output/name).write_bytes(payload)
        return 0,'','[vision-object] ONNX Runtime global threads: 1, spinning disabled'
    return 0,json.dumps({'valid':True,'indexVersion':4,'full':'--full' in argv}), '[vision-object] ONNX Runtime global threads: 1, spinning disabled'
try:
    value=index_from_queue(url=url,recovery_code=settings['recoveryCode'],batches=1,count=1,
        work_dir=root/'indexes',binary=root/'synthetic-program',model_dir=root/'synthetic-models',
        runner=runner,use_nice=False)
except (Exception,KeyboardInterrupt) as error:
    value={'error':getattr(error,'code',str(error)),'type':type(error).__name__}
print(json.dumps(value))
"""


class ObjectDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.service = CommunityService(self.root / 'fixture-service.sqlite')
        catalog = json.loads((REPO / 'community/demo_catalog.json').read_text(encoding='utf-8'))
        self.service.import_synthetic([next(item for item in catalog['locations'] if item['lane'] == 'object')])
        with self.service._connection() as connection:
            connection.execute("UPDATE locations SET lat=1.25,lon=-2.5,country='Greece',camera_generation='gen4'")
            ids = [row[0] for row in connection.execute('SELECT id FROM locations')]
        self.service.certify_official_gen4_objects(ids, 'a' * 64)
        account = self.service.create_account()
        self.account = account['accountId']
        (self.root / 'fixture-settings.json').write_text(json.dumps({'recoveryCode': account['recoveryCode']}))
        self.calls, self.submissions = [], []
        self.phase = 'drop-reply'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send(self, status, value, *, cookie=None, partial=False):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw) + 100 if partial else len(raw)))
                self.send_header('Connection', 'close')
                if cookie:
                    self.send_header('Set-Cookie', 'vision_session=' + cookie + '; Path=/')
                self.end_headers()
                self.wfile.write(raw[:5] if partial else raw)
                self.wfile.flush()
                self.close_connection = True
                if partial:
                    try:
                        self.connection.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass

            def do_GET(self):
                owner.calls.append(('GET', self.path))
                if self.path == '/api/me':
                    return self.send(200, owner.service.status(owner.account))
                self.send(404, {'error': 'not_found'})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls.append(('POST', self.path))
                try:
                    if self.path == '/api/recovery':
                        account = owner.service.recover_account(body['recoveryCode'])
                        return self.send(200, {'accountId': account['accountId']}, cookie=account['token'])
                    token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                    account_id = owner.service.account_for_token(token)
                    if self.path == '/api/leases':
                        lease = owner.service.lease(account_id, body['lane'], body['count'], pace=body['pace'])
                        (owner.root / 'fixture-lease.json').write_text(json.dumps(lease))
                        return self.send(200, lease)
                    if self.path == '/api/leases/renew':
                        if owner.phase == 'renew-expired':
                            return self.send(409, {'error': 'expired_lease'})
                        if owner.phase == 'renew-unauthorized':
                            return self.send(401, {'error': 'unauthorized'})
                        if owner.phase == 'renew-outage':
                            return self.send(503, {'error': 'http_error'})
                        return self.send(200, owner.service.renew_lease(account_id, body['leaseId']))
                    if self.path == '/api/submissions':
                        owner.submissions.append(body)
                        if owner.phase == 'expired':
                            return self.send(409, {'error': 'expired_lease'})
                        if owner.phase == 'rejected':
                            return self.send(200, {'rejected': True, 'submissionId': body['leaseId']})
                        result = owner.service.submit(account_id, body['leaseId'], body['outputs'],
                                                      object_index=body['objectIndex'])
                        if owner.phase == 'empty-reply':
                            result = {}
                        elif owner.phase == 'overclaim':
                            result = {'accepted': 2, 'unitsEarned': 20}
                        elif owner.phase == 'empty-success':
                            result = {'accepted': 0, 'unitsEarned': 0}
                        elif owner.phase == 'pending-object':
                            result = {'pendingAudit': True, 'submissionId': body['leaseId']}
                        return self.send(200, result, partial=owner.phase == 'drop-reply')
                    self.send(404, {'error': 'not_found'})
                except ServiceError as error:
                    self.send(error.status, {'error': error.code})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def child(self):
        process = subprocess.run([sys.executable, '-B', '-c', CHILD, str(self.root), self.url],
            cwd=REPO, env={**os.environ, 'VISION_COMMUNITY_RECOVERY': ''},
            capture_output=True, text=True, timeout=40)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout.strip().splitlines()[-1])

    def row(self):
        with closing(sqlite3.connect(self.root / 'indexes/submissions.sqlite')) as connection:
            return connection.execute('SELECT state,payload_json,payload_sha256,lane FROM deliveries').fetchone()

    def assert_only_one_fixture_processing(self):
        self.assertEqual((self.root / 'inference-calls.txt').read_text().splitlines(), ['synthetic fixture only'])
        self.assertFalse(any(path in {'/api/leases/release', '/api/scene-audits', '/api/accounts'}
                             for _, path in self.calls))

    def test_lost_reply_replays_exact_object_bundle_after_process_restart_and_credits_once(self):
        self.assertEqual(self.child()['error'], 'network_error')
        saved = self.row()
        self.assertEqual((saved[0], saved[3]), ('ready', 'object'))
        self.assertEqual(self.service.status(self.account)['units'], 10)
        self.phase = 'healthy'
        result = self.child()
        self.assertEqual((result['batches'], result['accepted'], result['unitsEarned']), (0, 1, 0))
        self.assertEqual(self.row()[0], 'accepted')
        self.assertIsNone(self.row()[1])
        self.assertEqual(self.row()[2], saved[2])
        self.assertEqual(self.service.status(self.account)['units'], 10)
        self.assertEqual(len(self.submissions), 4)  # Three lost replies, one fresh delivery.
        self.assertTrue(all(body == self.submissions[0] for body in self.submissions))
        self.assert_only_one_fixture_processing()
        self.assertEqual(self.child()['accepted'], 0)
        self.assertEqual(len(self.submissions), 4)
        code = json.loads((self.root / 'fixture-settings.json').read_text())['recoveryCode']
        self.assertNotIn(code.encode(), (self.root / 'indexes/submissions.sqlite').read_bytes())

    def test_malformed_acknowledgement_keeps_exact_bundle_and_does_not_release_the_lease(self):
        for phase in ('empty-reply', 'overclaim', 'empty-success', 'pending-object'):
            with self.subTest(phase=phase):
                self.phase = phase
                self.assertEqual(self.child()['error'], 'invalid_submission_result')
                self.assertEqual(self.row()[0], 'ready')
                self.assertEqual(self.service.status(self.account)['units'], 10)
                self.assert_only_one_fixture_processing()
        self.phase = 'healthy'
        self.assertEqual(self.child()['accepted'], 1)
        self.assertEqual(self.service.status(self.account)['units'], 10)
        self.assert_only_one_fixture_processing()

    def test_corrupt_valid_json_is_not_replayed_or_recomputed(self):
        self.child()
        original = self.row()
        with closing(sqlite3.connect(self.root / 'indexes/submissions.sqlite')) as connection:
            payload = json.loads(original[1])
            payload['objectIndex']['sourceTsv'] = 'Y29ycnVwdA=='
            connection.execute('UPDATE deliveries SET payload_json=?', (json.dumps(payload),))
            connection.commit()
        before = len(self.calls)
        self.phase = 'healthy'
        self.assertEqual(self.child()['error'], 'invalid_saved_submission')
        self.assertEqual(self.calls[before:], [('POST', '/api/recovery')])
        self.assertEqual(self.row()[0], 'ready')
        self.assert_only_one_fixture_processing()

    def test_definitive_expiry_keeps_object_evidence_and_does_not_retry_it_again(self):
        self.child()
        original = self.row()
        self.phase = 'expired'
        self.assertEqual(self.child()['accepted'], 0)
        self.assertEqual(self.row(), ('lease_lost', original[1], original[2], 'object'))
        before = len(self.submissions)
        self.phase = 'healthy'
        self.child()
        self.assertEqual(len(self.submissions), before)
        self.assert_only_one_fixture_processing()

    def test_explicit_rejection_stops_and_keeps_all_object_files_for_review(self):
        self.phase = 'rejected'
        self.assertEqual(self.child()['error'], 'object_submission_rejected')
        self.assertEqual(self.row()[0], 'rejected')
        self.assertIsNotNone(self.row()[1])
        self.assertEqual(self.service.status(self.account)['units'], 0)
        self.assertTrue(list((self.root / 'indexes').glob('*/index/semantic-pq128.bin')))
        self.assert_only_one_fixture_processing()

    def test_object_journal_is_scoped_to_account_and_service_and_cannot_become_a_scene(self):
        self.child()
        row = self.row()
        payload = json.loads(row[1])
        lease = self.submissions[0]['leaseId']
        for origin, account in ((self.url, 'f' * 32), ('https://other.example', self.account)):
            other = SubmissionOutbox(self.root / 'indexes/submissions.sqlite', origin, account)
            self.assertEqual(other.pending(), [])
        journal = SubmissionOutbox(self.root / 'indexes/submissions.sqlite', self.url, self.account)
        with self.assertRaisesRegex(ValueError, 'submission_payload_changed'):
            journal.remember(lease, payload['outputs'])
        self.assertEqual(self.row(), row)

    def test_original_scene_schema_migrates_without_rewriting_its_payload_or_hash(self):
        path = self.root / 'older.sqlite'
        payload = json.dumps([{'locationId': 9}], sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('''CREATE TABLE deliveries (origin TEXT,account_id TEXT,lease_id TEXT,
                payload_json TEXT,payload_sha256 TEXT,state TEXT,result_json TEXT,
                PRIMARY KEY(origin,account_id,lease_id))''')
            connection.execute('INSERT INTO deliveries VALUES (?,?,?,?,?,?,?)',
                (self.url, self.account, 'b' * 32, payload, digest, 'ready', None))
            connection.commit()
        journal = SubmissionOutbox(path, self.url, self.account)
        delivery = journal.pending()[0]
        self.assertEqual((delivery['payload_json'], delivery['payload_sha256'], delivery['lane']),
                         (payload, digest, 'scene'))
        self.assertEqual(journal.decode_delivery(delivery), [{'locationId': 9}])
        journal.remember_object('c' * 32, [{'locationId': 10}], {'files': {'empty.bin': ''}})
        self.assertEqual(journal.count(), 2)

    def test_scene_and_object_recover_together_without_cross_routing(self):
        self.child()
        client = DurableCommunityClient(self.url)
        client.enable_outbox(self.root / 'mixed', self.account)
        client.outbox.remember('b' * 32, [{'locationId': 9}])
        client.outbox.result('b' * 32, {'pendingAudit': True})
        client.outbox.remember_object('c' * 32, [{'locationId': 10}], {'files': {'empty.bin': ''}})
        calls = []
        def reply(_client, method, path, body=None):
            calls.append((path, body))
            return 200, {'accepted': 1, 'unitsEarned': 1 if path == '/api/scene-audits' else 10}, None
        with patch.object(CommunityClient, 'request', new=reply):
            self.assertEqual(client.resume_submissions(), {'accepted': 2, 'unitsEarned': 11})
        self.assertEqual(calls, [('/api/submissions', {'leaseId': 'c' * 32,
            'outputs': [{'locationId': 10}], 'objectIndex': {'files': {'empty.bin': ''}}}),
            ('/api/scene-audits', {'submissionId': 'b' * 32})])

    def test_exhausted_native_attempts_preserve_the_same_active_lease_for_restart(self):
        settings = json.loads((self.root / 'fixture-settings.json').read_text())
        settings['nativeFailure'] = 'exit'
        (self.root / 'fixture-settings.json').write_text(json.dumps(settings))
        self.assertEqual(self.child()['error'], 'vision_binary_failed')
        original = json.loads((self.root / 'fixture-lease.json').read_text())['leaseId']
        checkpoint = self.root / 'indexes' / original / 'index/checkpoint.json'
        self.assertTrue(checkpoint.exists())
        failures = list((self.root / 'indexes' / original).glob('object-failure-*.json'))
        self.assertEqual(len(failures), 1)
        self.assertEqual(json.loads(failures[0].read_text())['failedAttempts'], 3)
        self.assertEqual(self.submissions, [])
        settings.pop('nativeFailure')
        (self.root / 'fixture-settings.json').write_text(json.dumps(settings))
        self.phase = 'healthy'
        self.assertEqual(self.child()['accepted'], 1)
        self.assertEqual(self.submissions[0]['leaseId'], original)
        self.assertEqual(self.service.status(self.account)['units'], 10)
        self.assertEqual(len((self.root / 'inference-calls.txt').read_text().splitlines()), 4)
        self.assertTrue(failures[0].exists())
        self.assertFalse(any(path == '/api/leases/release' for _, path in self.calls))

    def test_interrupted_object_command_keeps_its_checkpoint_and_active_lease(self):
        settings = json.loads((self.root / 'fixture-settings.json').read_text())
        settings['nativeFailure'] = 'interrupt'
        (self.root / 'fixture-settings.json').write_text(json.dumps(settings))
        self.assertEqual(self.child()['type'], 'KeyboardInterrupt')
        original = json.loads((self.root / 'fixture-lease.json').read_text())['leaseId']
        self.assertTrue((self.root / 'indexes' / original / 'index/checkpoint.json').exists())
        self.assertEqual(self.submissions, [])
        settings.pop('nativeFailure')
        (self.root / 'fixture-settings.json').write_text(json.dumps(settings))
        self.phase = 'healthy'
        self.assertEqual(self.child()['accepted'], 1)
        self.assertEqual(self.submissions[0]['leaseId'], original)
        self.assertFalse(any(path == '/api/leases/release' for _, path in self.calls))

    def test_wrong_recovery_code_has_a_simple_message_and_never_touches_saved_output(self):
        self.child()
        original = self.row()
        settings = json.loads((self.root / 'fixture-settings.json').read_text())
        client = DesktopClient(self.url)
        with self.assertRaises(ContributeError) as caught:
            client.recover('wrong-code-value')
        self.assertEqual(caught.exception.code, 'invalid_recovery')
        self.assertEqual(public_error(caught.exception), 'That account code was not accepted. Check it and try again.')
        self.assertEqual(self.row(), original)
        self.assertNotIn(settings['recoveryCode'], public_error(caught.exception))

    def test_explicit_renewal_ownership_loss_cannot_offer_the_finished_object_index(self):
        self.phase = 'renew-expired'
        self.assertEqual(self.child()['error'], 'expired_lease')
        self.assertEqual(self.submissions, [])
        self.assertIsNone(self.row())
        self.assertEqual(self.service.status(self.account)['units'], 0)
        self.assertTrue(list((self.root / 'indexes').glob('*/index/semantic-pq128.bin')))

    def test_revoked_credentials_during_renewal_stop_before_upload(self):
        self.phase = 'renew-unauthorized'
        self.assertEqual(self.child()['error'], 'unauthorized')
        self.assertEqual(self.submissions, [])
        self.assertIsNone(self.row())
        self.assertEqual(self.service.status(self.account)['units'], 0)

    def test_temporary_renewal_outage_can_deliver_and_is_credited_once(self):
        self.phase = 'renew-outage'
        self.assertEqual(self.child()['accepted'], 1)
        self.assertEqual(self.row()[0], 'accepted')
        self.assertEqual(self.service.status(self.account)['units'], 10)
        self.assertEqual(sum(path == '/api/leases/renew' for _, path in self.calls), 3)
        self.assert_only_one_fixture_processing()


if __name__ == '__main__':
    unittest.main()
