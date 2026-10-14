"""Offline recovery plan for already accepted Scenes; never resubmit or index.

Execution is a separate, explicit, bounded readback of one pinned saved batch.
Original journals, replies, native files and failed trial receipts stay untouched.
The plan contains private identities/digests, but no recovery code or token.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .contribute import _RefuseServiceRedirects, load_session
from .four_view import BYTES_PER_LOCATION, VISION_FOUR_VIEW_MODEL, valid_four_view_record
from .process_owner import run_owned
from .submission_outbox import submission_result_state

ORIGIN = 'https://vision-community-staging.visioncommunity.workers.dev'
ROUTE = '/api/scene-receipt-recovery'
HEADERS = {'read': 'x-vision-trial-rows-read', 'written': 'x-vision-trial-rows-written',
           'puts': 'x-vision-trial-r2-puts', 'bytes': 'x-vision-trial-r2-bytes'}
LIMITS = {'read': 200, 'written': 0, 'puts': 0, 'bytes': 0}
MAX_FILE = 1048576


class ReceiptRecoveryError(ValueError):
    pass


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def prepare_recovery(*, trial_dir, account_file, trial_sha256, policy_id):
    """Read-only snapshot validation; accepted payloads are rebuilt only to hash.

    TSV IDs can differ from coordinator IDs in other catalogs. A differing
    reconstructed outbox digest refuses recovery instead of guessing that map.
    """
    root, account_file = Path(trial_dir).resolve(), Path(account_file).resolve()
    evidence = []

    def read(path):
        path = Path(path)
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            raise ReceiptRecoveryError('saved_evidence_unavailable')
        raw = path.read_bytes()
        evidence.append({'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)})
        return raw

    original = read(root / 'trial.receipt.private.json')
    if not re.fullmatch(r'[0-9a-f]{64}', trial_sha256) or sha(original) != trial_sha256:
        raise ReceiptRecoveryError('original_trial_changed')
    trial = json.loads(original)
    if (trial.get('status') != 'INCOMPLETE' or trial.get('accepted') not in (1, 2)
            or type(trial.get('accepted')) is not int or trial.get('unitsEarned') != trial['accepted']
            or trial.get('pending') != 0 or trial.get('productionQualified') is not False):
        raise ReceiptRecoveryError('saved_acceptance_required')
    read(account_file)
    account = load_session(account_file, ORIGIN)
    if (not account or account.get('url') != ORIGIN
            or not re.fullmatch(r'[0-9a-f]{32}', account.get('accountId', ''))
            or not isinstance(account.get('recoveryCode'), str) or not 16 <= len(account['recoveryCode']) <= 80):
        raise ReceiptRecoveryError('saved_account_required')
    if not re.fullmatch(r'staging\.[A-Za-z0-9._-]{1,190}', policy_id):
        raise ReceiptRecoveryError('invalid_saved_policy')
    outbox = root / 'indexes/submissions.sqlite'
    # Refuse an active writer. Do not open SubmissionOutbox: its constructor
    # performs migrations. mode=ro plus query_only never modifies this journal.
    if any(Path(str(outbox) + suffix).exists() for suffix in ('-wal', '-journal')):
        raise ReceiptRecoveryError('saved_outbox_not_sealed')
    read(outbox)
    with closing(sqlite3.connect(outbox.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        rows = db.execute('SELECT * FROM deliveries LIMIT 3').fetchall()
    if len(rows) != 1:
        raise ReceiptRecoveryError('one_saved_delivery_required')
    row = dict(rows[0])
    if (row['origin'] != ORIGIN or row['account_id'] != account['accountId'] or row['lane'] != 'scene'
            or row['state'] != 'accepted' or row['payload_json'] is not None
            or not re.fullmatch(r'[0-9a-f]{32}', row['lease_id'])):
        raise ReceiptRecoveryError('saved_delivery_mismatch')
    reply = json.loads(row['result_json'])
    n = trial['accepted']
    if (submission_result_state(row['lease_id'], reply, n) != 'accepted'
            or reply.get('admissionMode') != 'qualified-device-v1'
            or reply.get('accepted') != n or reply.get('unitsEarned') != n or reply.get('replayed') is not False):
        raise ReceiptRecoveryError('saved_reply_mismatch')
    run = root / 'indexes' / row['lease_id']
    native = json.loads(read(run / 'output.json'))
    checkpoint = json.loads(read(run / 'checkpoint.json'))
    manifest = json.loads(read(run / 'index/manifest.json'))
    identity = json.loads(read(run / 'index-run.json'))
    if (any(x.get('completed') is not True or x.get('totalLocations') != n
            or x.get('nextLocationIndex') != n or any(x.get(k) != 0 for k in
            ('fetchErrors', 'inferenceErrors', 'incompleteLocations')) for x in (native, checkpoint))
            or manifest.get('completed') is not True or manifest.get('indexedLocations') != n
            or manifest.get('bytesPerLocation') != BYTES_PER_LOCATION or manifest.get('version') != 4
            or identity.get('customRunner') is not False or identity.get('inferenceThreads') != 1):
        raise ReceiptRecoveryError('saved_native_output_incomplete')
    tsv = read(run / 'locations.tsv')
    if identity.get('locations', {}).get('sha256') != sha(tsv):
        raise ReceiptRecoveryError('saved_locations_changed')
    lines = [line.split('\t') for line in tsv.decode('utf-8').splitlines()]
    if len(lines) != n or any(len(line) != 11 or not re.fullmatch(r'[1-9][0-9]*', line[1]) for line in lines):
        raise ReceiptRecoveryError('saved_locations_invalid')
    blob = read(run / 'index/shard-000000.i8')
    if len(blob) != n * BYTES_PER_LOCATION:
        raise ReceiptRecoveryError('saved_index_changed')
    outputs = []
    for i, line in enumerate(lines):
        record = blob[i * BYTES_PER_LOCATION:(i + 1) * BYTES_PER_LOCATION]
        if not valid_four_view_record(record):
            raise ReceiptRecoveryError('saved_index_changed')
        outputs.append({'locationId': int(line[1]), 'outputSha256': sha(record), 'embeddingSha256': sha(record),
                        'embedding': base64.b64encode(record).decode('ascii'), 'model': VISION_FOUR_VIEW_MODEL})
    if len({x['locationId'] for x in outputs}) != n or sha(compact(outputs).encode()) != row['payload_sha256']:
        raise ReceiptRecoveryError('saved_payload_digest_mismatch')
    target = {'accountId': row['account_id'], 'leaseId': row['lease_id'], 'payloadSha256': row['payload_sha256'],
              'policyId': 'qualified-device-v1|' + policy_id,
              'records': [{k: x[k] for k in ('locationId', 'outputSha256')} for x in outputs]}
    for entry in evidence:
        if sha(Path(entry['path']).read_bytes()) != entry['sha256']:
            raise ReceiptRecoveryError('saved_evidence_changed_during_read')
    return {'version': 1, 'status': 'OFFLINE_EXISTING_RECEIPT_PREPARED', 'origin': ORIGIN, 'target': target,
            'targetSha256': sha(compact(target).encode()), 'accountFile': str(account_file), 'evidence': evidence,
            'originalStatus': trial['status'], 'originalReason': trial.get('reason'),
            'locallyReportedAccepted': n, 'locallyReportedAwardUnits': reply['unitsEarned'],
            'currentServerReconciled': False, 'originalFilesModified': False, 'networkRequests': 0,
            'newAssignment': False, 'nativeInference': False, 'productionQualified': False}


def verify_reply(value, plan):
    n = plan['locallyReportedAccepted']
    if (not isinstance(value, dict) or type(value.get('receiptContractVersion')) is not int
            or value['receiptContractVersion'] != 1 or value.get('readOnly') is not True
            or value.get('targetSha256') != plan['targetSha256']
            or value.get('submissionId') != plan['target']['leaseId']
            or value.get('admissionMode') != 'qualified-device-v1'
            or any(type(value.get(k)) is not int for k in ('accepted', 'originalAwardUnits', 'unitsEarned', 'ledgerEntries', 'currentUnits'))
            or value['accepted'] != n or value['originalAwardUnits'] != n
            or value['unitsEarned'] != 0 or value['ledgerEntries'] != 1 or value['currentUnits'] < 0
            or value.get('publicationDigestsMatched') is not True or value.get('r2ArtifactRead') is not False
            or value.get('qualificationRenewed') is not False
            or not re.fullmatch(r'[0-9a-f]{64}', value.get('submissionSha256', ''))):
        raise ReceiptRecoveryError('current_receipt_mismatch')
    replay = value.get('auditReplay')
    if (submission_result_state(plan['target']['leaseId'], replay, n) != 'accepted'
            or replay.get('replayed') is not True or replay.get('accepted') != 0 or replay.get('unitsEarned') != 0
            or replay.get('admissionMode') != 'qualified-device-v1'):
        raise ReceiptRecoveryError('current_replay_mismatch')


def run_recovery(plan, token, *, opener=None, clock=time.monotonic):
    """Two read-only replies, no retries, no credential rotation, no outbox writes."""
    if not re.fullmatch(r'[0-9a-f]{64}', token):
        raise ReceiptRecoveryError('invalid_recovery_token')
    for entry in plan['evidence']:
        if sha(Path(entry['path']).read_bytes()) != entry['sha256']:
            raise ReceiptRecoveryError('saved_evidence_changed')
    if plan['origin'] != ORIGIN or plan['targetSha256'] != sha(compact(plan['target']).encode()):
        raise ReceiptRecoveryError('recovery_plan_changed')
    account = load_session(Path(plan['accountFile']), ORIGIN)
    if not account or account.get('accountId') != plan['target']['accountId']:
        raise ReceiptRecoveryError('saved_account_changed')
    body = compact({'target': plan['target'], 'recoveryCode': account['recoveryCode']}).encode()
    if len(body) > 2048:
        raise ReceiptRecoveryError('recovery_request_limit')
    result = {'status': 'INCOMPLETE', 'currentServerReconciled': False, 'newAssignment': False,
              'nativeInference': False, 'gatewayClosed': False, 'shutdownReadbackRequired': True,
              'credentialRotated': False, 'originalFilesModified': False, 'productionQualified': False,
              'requestUsage': [], 'observedUsage': dict.fromkeys(LIMITS, 0)}
    delegate = opener or urllib.request.build_opener(_RefuseServiceRedirects())
    end = clock() + 120
    first = None
    def measure(headers, attempt):
        if headers.get('x-vision-trial-usage-complete') != '1':
            raise ReceiptRecoveryError('recovery_usage_unknown')
        usage = {}
        for k, name in HEADERS.items():
            raw = headers.get(name, '')
            if not re.fullmatch(r'0|[1-9][0-9]{0,15}', raw):
                raise ReceiptRecoveryError('recovery_usage_unknown')
            usage[k] = int(raw)
        attempt.update(usage=usage, usageComplete=True)
        for k in LIMITS:
            result['observedUsage'][k] += usage[k]
        if any(result['observedUsage'][k] > v for k, v in LIMITS.items()):
            raise ReceiptRecoveryError('recovery_usage_limit')
    try:
        for i in range(2):
            if clock() >= end:
                raise ReceiptRecoveryError('recovery_deadline')
            headers = {'Origin': ORIGIN, 'Content-Type': 'application/json', 'Accept': 'application/json',
                       'Accept-Encoding': 'identity', 'X-Vision-Finite-Cohort': token}
            headers.update({'X-Vision-Trial-Remaining-' + k: str(v - result['observedUsage'][k]) for k, v in LIMITS.items()})
            request = urllib.request.Request(ORIGIN + ROUTE, data=body, method='POST', headers=headers)
            attempt = {'attempt': i + 1, 'method': 'POST', 'path': ROUTE, 'httpStatus': None, 'usageComplete': False}
            result['requestUsage'].append(attempt)
            try:
                response = delegate.open(request, timeout=min(10, end - clock()))
            except urllib.error.HTTPError as error:
                attempt['httpStatus'] = error.code
                try:
                    measure(error.headers, attempt)
                finally:
                    error.close()
                raise ReceiptRecoveryError('recovery_http_failure') from None
            with response:
                attempt['httpStatus'] = response.status
                measure(response.headers, attempt)
                raw = response.read(8193)
                if len(raw) > 8192 or clock() >= end or response.status != 200:
                    raise ReceiptRecoveryError('recovery_response_limit')
                value = json.loads(raw)
            verify_reply(value, plan)
            if first is not None and value != first:
                raise ReceiptRecoveryError('current_receipt_changed_between_reads')
            first = value
        result.update(status='EXISTING_SCENE_RECEIPT_RECONCILED', currentServerReconciled=True,
                      accepted=first['accepted'], originalAwardUnits=first['originalAwardUnits'],
                      replayEarnedUnits=0, currentUnits=first['currentUnits'], ledgerEntries=1)
    except Exception as error:
        result['failureClass'] = type(error).__name__
        result['reason'] = str(error) if isinstance(error, ReceiptRecoveryError) else 'recovery_transport_or_reply_failure'
    return result


def supervise_recovery(arguments, output, *, owned_runner=run_owned):
    """Bound slow headers/bodies and every owned child to 120 wall seconds."""
    output = Path(output)
    if any(path.exists() for path in (output, output.with_suffix('.stdout.private.log'),
            output.with_suffix('.stderr.private.log'), output.with_suffix('.supervisor.private.json'))):
        raise ReceiptRecoveryError('create_only_recovery_output_required')
    result = {'status': 'INCOMPLETE', 'currentServerReconciled': False, 'newAssignment': False,
              'nativeInference': False, 'productionQualified': False, 'gatewayClosed': False,
              'shutdownReadbackRequired': True, 'childDeadlineSeconds': 120}
    try:
        with output.with_suffix('.stdout.private.log').open('xb') as stdout, output.with_suffix('.stderr.private.log').open('xb') as stderr:
            child = owned_runner([sys.executable, '-B', '-m', 'community.scene_receipt_recovery',
                *arguments, '--owned-child'], cwd=Path(__file__).resolve().parents[1],
                stdout=stdout, stderr=stderr, timeout=120)
        result['childExitCode'] = child.returncode
        if output.is_file() and output.stat().st_size <= MAX_FILE:
            receipt = json.loads(output.read_bytes())
            result['childStatus'] = receipt.get('status')
            if child.returncode == 0 and receipt.get('status') == 'EXISTING_SCENE_RECEIPT_RECONCILED':
                result.update(status='EXISTING_SCENE_RECOVERY_CHILD_FINISHED_REQUIRES_CLOSE', currentServerReconciled=True)
    except subprocess.TimeoutExpired:
        result['reason'] = 'recovery_child_timeout'
    except Exception as error:
        result['failureClass'] = type(error).__name__
    with output.with_suffix('.supervisor.private.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial-dir', required=True, type=Path)
    parser.add_argument('--account-file', required=True, type=Path)
    parser.add_argument('--trial-sha256', required=True)
    parser.add_argument('--policy-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--allow-existing-receipt-recovery', action='store_true')
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--owned-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.output.exists():
        raise ReceiptRecoveryError('create_only_recovery_output_required')
    if args.run and (not args.allow_existing_receipt_recovery or not args.token_file):
        raise ReceiptRecoveryError('separate_recovery_consent_required')
    if args.run and not args.owned_child:
        result = supervise_recovery(sys.argv[1:], args.output)
        print(json.dumps(result))
        return 0 if result['currentServerReconciled'] else 1
    plan = prepare_recovery(trial_dir=args.trial_dir, account_file=args.account_file,
                            trial_sha256=args.trial_sha256, policy_id=args.policy_id)
    result = run_recovery(plan, args.token_file.read_text(encoding='utf-8').strip()) if args.run else plan
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({k: result[k] for k in ('status', 'currentServerReconciled', 'newAssignment', 'nativeInference', 'productionQualified')}))
    return 0 if not args.run or result['currentServerReconciled'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
