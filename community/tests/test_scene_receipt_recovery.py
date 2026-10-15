from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
import urllib.error

from community import scene_receipt_recovery as recovery
from community.submission_outbox import SubmissionOutbox
from community.vision_index import outputs_for_items


class SavedReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = self.root / 'account.json'
        self.account.write_text(json.dumps({'url': recovery.ORIGIN, 'accountId': 'a'*32, 'recoveryCode': 'synthetic-code-123456'}))
        self.lease = 'b'*32
        self.run = self.root / 'indexes' / self.lease
        (self.run / 'index').mkdir(parents=True)
        blob = bytearray(3080)
        for v in range(4): blob[v*770+1] = 60
        (self.run / 'index/shard-000000.i8').write_bytes(bytes(blob)*2)
        (self.run / 'locations.tsv').write_text('\n'.join(f'fixture\t{i}\t1\t2\t0\t0\t0\tfixture-{i}\tItaly\tgen4\troad' for i in (81, 82)), encoding='utf-8')
        native = {'completed': True, 'totalLocations': 2, 'nextLocationIndex': 2,
                  'fetchErrors': 0, 'inferenceErrors': 0, 'incompleteLocations': 0}
        for name in ('output.json', 'checkpoint.json'): (self.run / name).write_text(json.dumps(native))
        (self.run / 'index/manifest.json').write_text(json.dumps({'completed': True, 'indexedLocations': 2, 'bytesPerLocation': 3080, 'version': 4}))
        (self.run / 'index-run.json').write_text(json.dumps({'customRunner': False, 'inferenceThreads': 1,
            'locations': {'sha256': recovery.sha((self.run / 'locations.tsv').read_bytes())}}))
        outbox = SubmissionOutbox(self.root/'indexes/submissions.sqlite', recovery.ORIGIN, 'a'*32)
        outbox.remember(self.lease, outputs_for_items([{'locationId': i} for i in (81, 82)], self.run/'index'))
        outbox.result(self.lease, {'accepted': 2, 'unitsEarned': 2, 'pendingAudit': False,
                                 'replayed': False, 'admissionMode': 'qualified-device-v1', 'segments': []})
        self.original = self.root/'trial.receipt.private.json'
        self.original.write_text(json.dumps({'status': 'INCOMPLETE', 'accepted': 2, 'unitsEarned': 2,
            'pending': 0, 'productionQualified': False, 'reason': 'original_failure'}))
        self.pin = recovery.sha(self.original.read_bytes())

    def prepare(self):
        return recovery.prepare_recovery(trial_dir=self.root, account_file=self.account, trial_sha256=self.pin, policy_id='staging.synthetic')

    def reply(self, plan):
        return {'receiptContractVersion': 1, 'readOnly': True, 'targetSha256': plan['targetSha256'],
            'submissionId': self.lease, 'submissionSha256': 'c'*64, 'admissionMode': 'qualified-device-v1',
            'accepted': 2, 'originalAwardUnits': 2, 'unitsEarned': 0, 'ledgerEntries': 1, 'currentUnits': 102,
            'publicationDigestsMatched': True, 'r2ArtifactRead': False, 'qualificationRenewed': False,
            'auditReplay': {'accepted': 0, 'unitsEarned': 0, 'replayed': True, 'pendingAudit': False,
                'admissionMode': 'qualified-device-v1', 'pending': 0, 'rejected': False, 'submissionId': self.lease, 'segments': []}}

    def test_prepare_rebuilds_discarded_payload_digest_without_modifying_any_file(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        plan = self.prepare()
        self.assertFalse(plan['currentServerReconciled'])
        self.assertEqual(plan['originalReason'], 'original_failure')
        self.assertEqual(plan['networkRequests'], 0)
        self.assertNotIn('synthetic-code-123456', json.dumps(plan))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_changed_original_or_index_or_ambiguous_source_ids_refuse(self):
        self.original.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'original_trial_changed'): self.prepare()
        self.original.write_text(json.dumps({'status': 'INCOMPLETE', 'accepted': 2, 'unitsEarned': 2,
            'pending': 0, 'productionQualified': False, 'reason': 'original_failure'}))
        path = self.run/'index/shard-000000.i8'
        raw = path.read_bytes(); path.write_bytes(raw[:-1]+b'\x01')
        with self.assertRaisesRegex(ValueError, 'payload_digest_mismatch'): self.prepare()
        path.write_bytes(raw)
        tsv = self.run/'locations.tsv'
        tsv.write_text(tsv.read_text().replace('\t81\t', '\t91\t'))
        (self.run/'index-run.json').write_text(json.dumps({'customRunner': False, 'inferenceThreads': 1,
            'locations': {'sha256': recovery.sha(tsv.read_bytes())}}))
        with self.assertRaisesRegex(ValueError, 'payload_digest_mismatch'): self.prepare()

    def test_active_journal_wrong_account_and_incomplete_native_refuse(self):
        wal = self.root/'indexes/submissions.sqlite-wal'; wal.touch()
        with self.assertRaisesRegex(ValueError, 'outbox_not_sealed'): self.prepare()
        wal.unlink()
        account = json.loads(self.account.read_text()); account['accountId'] = 'f'*32
        self.account.write_text(json.dumps(account))
        with self.assertRaisesRegex(ValueError, 'delivery_mismatch'): self.prepare()
        account['accountId'] = 'a'*32; self.account.write_text(json.dumps(account))
        (self.run/'output.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'native_output_incomplete'): self.prepare()

    def test_nonaccepted_or_inconsistent_saved_replies_refuse(self):
        path = self.root/'indexes/submissions.sqlite'
        with closing(sqlite3.connect(path)) as db, db: db.execute("UPDATE deliveries SET result_json=?", (json.dumps({'accepted': 1, 'unitsEarned': 1}),))
        with self.assertRaisesRegex(ValueError, 'invalid_submission_result'): self.prepare()
        with closing(sqlite3.connect(path)) as db, db: db.execute("UPDATE deliveries SET state='pending'")
        with self.assertRaisesRegex(ValueError, 'delivery_mismatch'): self.prepare()

    def test_two_reads_preserve_award_and_current_balance_without_recomputing_a_delta(self):
        plan = self.prepare(); reply = self.reply(plan); transport = Transport([reply, reply])
        result = recovery.run_recovery(plan, 'd'*64, opener=transport)
        self.assertTrue(result['currentServerReconciled']); self.assertEqual(len(transport.calls), 2)
        self.assertEqual(result['currentUnits'], 102); self.assertEqual(result['originalAwardUnits'], 2)
        self.assertFalse(result['credentialRotated']); self.assertFalse(result['gatewayClosed'])
        self.assertEqual(result['observedUsage'], {'read': 40, 'written': 0, 'puts': 0, 'bytes': 0})
        self.assertTrue(all(x.full_url == recovery.ORIGIN+recovery.ROUTE for x in transport.calls))
        self.assertTrue(all('embedding' not in x.data.decode() for x in transport.calls))

    def test_missing_usage_overrun_writes_http_error_never_retry(self):
        plan = self.prepare(); reply = self.reply(plan)
        for kwargs, expected in (({'complete': False}, 'usage_unknown'), ({'read': 201}, 'usage_limit'),
                                 ({'written': 1}, 'usage_limit'), ({'http_error': True}, 'http_failure')):
            with self.subTest(kwargs=kwargs):
                transport = Transport([reply, reply], **kwargs)
                result = recovery.run_recovery(plan, 'd'*64, opener=transport)
                self.assertEqual(len(transport.calls), 1)
                self.assertFalse(result['currentServerReconciled']); self.assertIn(expected, result['reason'])

    def test_changed_saved_file_or_invalid_token_prevents_any_transport(self):
        plan = self.prepare(); transport = Transport([])
        with self.assertRaisesRegex(ValueError, 'token'): recovery.run_recovery(plan, '', opener=transport)
        (self.run/'output.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'saved_evidence_changed'): recovery.run_recovery(plan, 'd'*64, opener=transport)
        self.assertEqual(transport.calls, [])

    def test_unmetered_refusal_keeps_only_safe_diagnostics_and_never_retries(self):
        plan = self.prepare()
        secret = 'private-response-value-do-not-log'
        cases = [
            ('application/json; charset=utf-8', json.dumps({'error': 'unauthorized', 'recoveryCode': secret}).encode(), 'unauthorized'),
            ('text/html', ('<html>'+secret+'</html>').encode(), None),
            ('application/json', json.dumps({'error': secret, 'token': secret}).encode(), None),
            ('private-header-value', secret.encode(), None),
            ('application/json', b'x'*(recovery.HTTP_DIAGNOSTIC_BYTES+100), None),
        ]
        for content_type, raw, expected in cases:
            with self.subTest(content_type=content_type, bytes=len(raw)):
                body = TrackedBody(raw)
                class Refused:
                    calls = 0
                    def open(self, request, timeout):
                        self.calls += 1
                        raise urllib.error.HTTPError(request.full_url, 403, secret,
                            {'content-type': content_type}, body)
                transport = Refused()
                result = recovery.run_recovery(plan, 'd'*64, opener=transport)
                self.assertEqual(transport.calls, 1)
                self.assertEqual(result['reason'], 'recovery_usage_unknown')
                self.assertFalse(result['currentServerReconciled'])
                diagnostic = result['requestUsage'][0]['responseDiagnostic']
                self.assertEqual(diagnostic.get('recognizedGatewayError'), expected)
                self.assertLessEqual(diagnostic['bodyBytesRead'], recovery.HTTP_DIAGNOSTIC_BYTES+1)
                self.assertEqual(diagnostic['bodyTruncated'], len(raw)>recovery.HTTP_DIAGNOSTIC_BYTES)
                self.assertEqual(body.read_sizes, [recovery.HTTP_DIAGNOSTIC_BYTES+1])
                self.assertTrue(body.closed)
                self.assertNotIn(secret, json.dumps(result))
                self.assertNotIn('synthetic-code-123456', json.dumps(result))

    def test_diagnostic_read_failure_does_not_replace_usage_stop_or_log_exception(self):
        plan = self.prepare()
        class BrokenBody(io.BytesIO):
            def read(self, size=-1): raise OSError('private-error-message')
        body = BrokenBody()
        class Refused:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise urllib.error.HTTPError(request.full_url, 403, 'private-reason',
                    {'content-type': 'text/html'}, body)
        transport = Refused()
        result = recovery.run_recovery(plan, 'd'*64, opener=transport)
        self.assertEqual(transport.calls, 1)
        self.assertEqual(result['reason'], 'recovery_usage_unknown')
        self.assertTrue(result['requestUsage'][0]['responseDiagnostic']['diagnosticUnavailable'])
        self.assertNotIn('private-error-message', json.dumps(result))
        self.assertTrue(body.closed)

    def test_diagnostic_does_not_start_body_read_after_deadline(self):
        body = TrackedBody(b'not-read')
        error = urllib.error.HTTPError('https://fixture.test', 403, 'private-reason',
            {'content-type': 'text/plain'}, body)
        try:
            diagnostic = recovery._http_error_diagnostic(error, allow_read=False)
            self.assertFalse(diagnostic['bodyRead'])
            self.assertEqual(body.read_sizes, [])
        finally:
            error.close()

    def test_changed_current_credit_or_ledger_or_publication_refuses_success(self):
        plan = self.prepare(); reply = self.reply(plan)
        for patch in ({'unitsEarned': 2}, {'ledgerEntries': 2}, {'publicationDigestsMatched': False}, {'accepted': True}):
            with self.subTest(patch=patch):
                transport = Transport([{**reply, **patch}])
                self.assertFalse(recovery.run_recovery(plan, 'd'*64, opener=transport)['currentServerReconciled'])
        transport = Transport([reply, {**reply, 'currentUnits': 101}])
        self.assertEqual(recovery.run_recovery(plan, 'd'*64, opener=transport)['reason'], 'current_receipt_changed_between_reads')

    def test_supervisor_requires_child_success_and_never_claims_gateway_closure(self):
        output = self.root/'recovery.json'
        def child(args, *, env, cwd, stdout, stderr, timeout):
            self.assertEqual(timeout, 120)
            self.assertEqual(env, dict(os.environ))
            self.assertIsNot(env, os.environ)
            self.assertIn('--owned-child', args)
            output.write_text(json.dumps({'status': 'EXISTING_SCENE_RECEIPT_RECONCILED'}))
            return subprocess.CompletedProcess(args, 0)
        result = recovery.supervise_recovery(['--run'], output, owned_runner=child)
        self.assertTrue(result['currentServerReconciled']); self.assertFalse(result['gatewayClosed'])

    def test_actual_owned_child_prepares_offline_receipt_with_inherited_environment(self):
        output = self.root/'owned-offline.json'
        original = self.original.read_bytes()
        result = recovery.supervise_recovery([
            '--trial-dir', str(self.root), '--account-file', str(self.account),
            '--trial-sha256', self.pin, '--policy-id', 'staging.synthetic',
            '--output', str(output)], output)
        self.assertEqual(result.get('childExitCode'), 0, result)
        self.assertFalse(result['currentServerReconciled'])
        self.assertFalse(result['gatewayClosed'])
        plan = json.loads(output.read_bytes())
        self.assertEqual(plan['status'], 'OFFLINE_EXISTING_RECEIPT_PREPARED')
        self.assertEqual(plan['targetSha256'], self.prepare()['targetSha256'])
        self.assertEqual(plan['networkRequests'], 0)
        self.assertEqual(self.original.read_bytes(), original)
        self.assertEqual(output.with_suffix('.stderr.private.log').read_bytes(), b'')

    def test_supervisor_timeout_retains_incomplete_receipt(self):
        output = self.root/'recovery-timeout.json'
        def child(args, **kwargs): raise subprocess.TimeoutExpired(args, 120)
        result = recovery.supervise_recovery(['--run'], output, owned_runner=child)
        self.assertEqual(result['reason'], 'recovery_child_timeout')
        self.assertFalse(result['currentServerReconciled']); self.assertTrue(output.with_suffix('.supervisor.private.json').is_file())


class TrackedBody(io.BytesIO):
    def __init__(self, raw):
        super().__init__(raw)
        self.read_sizes = []
    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class Reply(io.BytesIO):
    status = 200
    def __init__(self, value, *, complete=True, **usage):
        super().__init__(json.dumps(value).encode())
        self.headers = {v: str(usage.get(k, 20 if k == 'read' else 0)) for k, v in recovery.HEADERS.items()}
        self.headers['x-vision-trial-usage-complete'] = '1' if complete else '0'


class Transport:
    def __init__(self, replies, *, http_error=False, **usage):
        self.replies, self.usage, self.http_error, self.calls = replies, usage, http_error, []
    def open(self, request, timeout):
        self.calls.append(request)
        reply = Reply(self.replies.pop(0), **self.usage)
        if self.http_error: raise urllib.error.HTTPError(request.full_url, 409, 'fixture', reply.headers, reply)
        return reply


if __name__ == '__main__': unittest.main()
