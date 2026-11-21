"""Actual Node/Worker protocol -> Python spool; inference is explicitly synthetic."""
import json
import os
from pathlib import Path
import shutil
import threading
import unittest
from unittest.mock import patch

from community.object_audit_jobs import make_server
from community.process_owner import run_owned
from community.search_snapshot import digest, encoded
from community.tests import test_object_audit_jobs as job_fixtures

REPO = Path(__file__).resolve().parents[2]


class ObjectDispatchInteropTests(unittest.TestCase):
    def test_hosted_handoff_lost_ack_and_deletion_use_actual_native_job_protocol(self):
        node = os.environ.get('VISION_TEST_NODE') or shutil.which('node')
        if not node:
            self.skipTest('existing private Node runtime not supplied')
        fixture = job_fixtures.ObjectAuditJobTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        service = fixture.service
        secret = 'synthetic-private-object-interop-secret'
        server = make_server(service, secret)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        manifest = fixture.body['objectIndex']['manifest']
        payload = fixture.root / 'dispatch-input.private.json'
        payload.write_bytes(encoded({
            'secret': secret, 'origin': f'http://127.0.0.1:{server.server_port}',
            'objectIndex': fixture.body['objectIndex'],
            'authority': {'leaseId': fixture.body['leaseId'], 'profileId': fixture.body['profileId'],
                'policyId': fixture.body['policyId'], 'assignmentSha256': fixture.body['assignmentSha256'],
                'sourceSha256': digest(fixture.native.source)},
            'items': fixture.native.trusted['records'],
            'nativeManifestSha256': digest(encoded(manifest))}))
        stdout = fixture.root / 'dispatch-node.stdout.private.log'
        stderr = fixture.root / 'dispatch-node.stderr.private.log'
        with patch.object(fixture.native.verifier, 'run', side_effect=fixture.native.fake_native):
            service.start()
            try:
                with stdout.open('wb') as out, stderr.open('wb') as err:
                    completed = run_owned([node, str(REPO/'deploy/cloudflare/tools/object-dispatch-interop.mjs'), str(payload)],
                        cwd=REPO, env=dict(os.environ), stdout=out, stderr=err, timeout=45)
            finally:
                # Keep the synthetic runner installed until owned native work
                # has stopped, including a failed/timeout Node harness.
                service.close()
            if os.environ.get('VISION_TEST_EVIDENCE_DIR'):
                evidence = Path(os.environ['VISION_TEST_EVIDENCE_DIR'])
                evidence.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(stdout, evidence/'node.stdout.private.log')
                shutil.copyfile(stderr, evidence/'node.stderr.private.log')
                with service.connect() as db:
                    saved = [dict(row) for row in db.execute('SELECT * FROM jobs')]
                (evidence/'native-jobs.private.json').write_bytes(encoded({'jobs': saved, 'syntheticNativeCalls': fixture.native.calls}))
                for report in fixture.work.glob('attempts-*/attempt-*/audit-report.json'):
                    shutil.copyfile(report, evidence/(report.parent.name+'-'+report.parent.parent.name+'.private.json'))
            self.assertEqual(completed.returncode, 0, stderr.read_text()[-10000:])
        result = json.loads(stdout.read_text())
        self.assertEqual(result['status'], 'NODE_PYTHON_OBJECT_DISPATCH_INTEROP_PASSED')
        self.assertEqual(result['starts'], 2)
        self.assertTrue(result['erased'])
        self.assertEqual(fixture.native.calls, ['runtime-info', 'index-segment', 'verify-index', 'verify-index'])
        with service.connect() as db:
            rows = db.execute('SELECT state,attempts FROM jobs').fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]['state'], rows[0]['attempts']), ('erased', 1))


if __name__ == '__main__':
    unittest.main()
