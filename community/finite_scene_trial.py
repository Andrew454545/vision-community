"""Operator-only two-Scene trial. Preparation is offline; --run needs separate approval.

Uses an existing account and unchanged, previously qualified processing files.
No account creation, qualification renewal, search, downloads or scheduled tasks.
The separately approved operator is responsible for deploy/close and a final
shutdown readback; this module never grants those permissions or deploys itself.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import urllib.error
from urllib.parse import urlsplit

from .contribute import ContributeError, load_session
from .desktop import DesktopClient
from .pc_canary import CanaryPolicy, canary_profile_matches
from .process_owner import run_owned
from . import vision_index

ORIGIN = 'https://vision-community-staging.visioncommunity.workers.dev'
HEADERS = {'read': 'x-vision-trial-rows-read', 'written': 'x-vision-trial-rows-written',
           'puts': 'x-vision-trial-r2-puts', 'bytes': 'x-vision-trial-r2-bytes'}
LIMITS = {'read': 2000, 'written': 128, 'puts': 4, 'bytes': 524288}
ALLOWED = {('GET', '/api/capabilities'), ('GET', '/api/me'), ('GET', '/api/scene-qualifications'),
           ('POST', '/api/recovery'), ('POST', '/api/leases'), ('POST', '/api/leases/renew'),
           ('POST', '/api/leases/release'), ('POST', '/api/submissions'), ('POST', '/api/scene-audits')}


class FiniteTrialError(ContributeError):
    pass


class BoundedOpener:
    """Count actual transport attempts, including the underlying client's retries."""
    def __init__(self, delegate, token, *, deadline, clock=time.monotonic):
        if not re.fullmatch(r'[0-9a-f]{64}', token):
            raise ValueError('invalid_finite_trial_token')
        self.delegate, self.token, self.deadline, self.clock = delegate, token, deadline, clock
        self.lock = threading.Lock()
        self.requests, self.sent_bytes = 0, 0
        self.usage = dict.fromkeys(LIMITS, 0)
        self.stopped = False
        self.stop_reason = None
        self.history = []

    def _record(self, method, path, status, before, *, complete, reason=None):
        # Paths come from ALLOWED; omit query strings, credentials and bodies.
        self.history.append({'attempt': self.requests, 'method': method, 'path': path,
            'httpStatus': status, 'usageComplete': complete,
            'usage': {key: self.usage[key] - before[key] for key in LIMITS},
            **({'reason': reason} if reason else {})})

    def _measure(self, headers):
        if headers.get('x-vision-trial-usage-complete') != '1':
            raise FiniteTrialError('finite_scene_usage_unknown')
        additions = {}
        for key, name in HEADERS.items():
            raw = headers.get(name, '')
            if not re.fullmatch(r'0|[1-9][0-9]{0,15}', raw):
                raise FiniteTrialError('finite_scene_usage_unknown')
            additions[key] = int(raw)
        for key, value in additions.items():
            self.usage[key] += value
        if any(self.usage[key] > limit for key, limit in LIMITS.items()):
            raise FiniteTrialError('finite_scene_usage_limit')

    def open(self, request, timeout=None):
        with self.lock:
            url = urlsplit(request.full_url)
            origin = f'{url.scheme}://{url.netloc}'
            size = len(request.data or b'')
            remaining = self.deadline - self.clock()
            if self.stopped:
                raise FiniteTrialError(self.stop_reason or 'finite_scene_request_limit')
            if (remaining <= 0 or self.requests >= 32
                    or self.sent_bytes + size > 524288):
                raise FiniteTrialError('finite_scene_request_limit')
            if origin != ORIGIN or (request.get_method(), url.path) not in ALLOWED or url.fragment:
                raise FiniteTrialError('finite_scene_request_scope')
            request.add_header('X-Vision-Finite-Cohort', self.token)
            for key, limit in LIMITS.items():
                request.add_header('X-Vision-Trial-Remaining-' + key, str(max(0, limit - self.usage[key])))
            self.requests += 1
            self.sent_bytes += size
            before = dict(self.usage)
            try:
                response = self.delegate.open(request, timeout=min(10, remaining))
            except urllib.error.HTTPError as error:
                self.stopped = True
                self.stop_reason = 'finite_scene_http_failure'
                try:
                    self._measure(error.headers)
                    self._record(request.get_method(), url.path, error.code, before, complete=True,
                                 reason=self.stop_reason)
                except BaseException as failure:
                    self.stop_reason = failure.code if isinstance(failure, FiniteTrialError) else 'finite_scene_usage_unknown'
                    self._record(request.get_method(), url.path, error.code, before,
                                 complete=self.stop_reason == 'finite_scene_usage_limit',
                                 reason=self.stop_reason)
                    raise
                finally:
                    error.close()
                raise FiniteTrialError('finite_scene_http_failure', error.code) from error
            except BaseException:
                self.stopped = True
                self.stop_reason = 'finite_scene_network_failure'
                self._record(request.get_method(), url.path, None, before, complete=False,
                             reason=self.stop_reason)
                raise
            try:
                self._measure(response.headers)
            except BaseException as failure:
                self.stopped = True
                self.stop_reason = failure.code if isinstance(failure, FiniteTrialError) else 'finite_scene_usage_unknown'
                self._record(request.get_method(), url.path, getattr(response, 'status', None), before,
                             complete=self.stop_reason == 'finite_scene_usage_limit',
                             reason=self.stop_reason)
                response.close()
                raise
            self._record(request.get_method(), url.path, getattr(response, 'status', None), before, complete=True)
            return response


class FiniteSceneClient(DesktopClient):
    def __init__(self, token, *, deadline):
        super().__init__(ORIGIN)
        self.budget = BoundedOpener(self.opener, token, deadline=deadline)
        self.opener = self.budget
        self.assigned_lease = None
        self.assignment_attempted = False

    def me(self):
        status, value, _ = self.request('GET', '/api/me?credit=1')
        if (status != 200 or not isinstance(value, dict) or type(value.get('creditContractVersion')) is not int
                or value['creditContractVersion'] != 1
                or type(value.get('units')) is not int or value['units'] < 0):
            raise FiniteTrialError('finite_scene_balance_unavailable')
        return value

    def lease(self, lane, count, pace, **kwargs):
        if self.assignment_attempted or lane != 'scene' or count != 2:
            raise FiniteTrialError('finite_scene_assignment_limit')
        self.assignment_attempted = True
        result = super().lease(lane, count, pace, **kwargs)
        if (not isinstance(result.get('items'), list) or not 1 <= len(result['items']) <= 2
                or not re.fullmatch(r'[0-9a-f]{32}', result.get('leaseId', ''))):
            raise FiniteTrialError('finite_scene_assignment_invalid')
        self.assigned_lease = result['leaseId']
        return result


def prepare(*, account_file, canary_file, policy_file, policy_sha256, binary, model_dir):
    account = load_session(Path(account_file), ORIGIN)
    if (not account or account.get('url') != ORIGIN
            or not re.fullmatch(r'[0-9a-f]{32}', account.get('accountId', ''))
            or not isinstance(account.get('recoveryCode'), str) or not account['recoveryCode']):
        raise FiniteTrialError('finite_scene_existing_account_required')
    report = json.loads(Path(canary_file).read_bytes())
    policy = CanaryPolicy.load(Path(policy_file), policy_sha256)
    if (report.get('qualified') is not True or report.get('policyId') != policy.document['policyId']
            or not canary_profile_matches(report, binary=Path(binary), model_dir=Path(model_dir), inference_threads=1)
            or not policy.evaluate(report['runtimeProfile']['sha256'], report['identity'], report['decoded'])[0]):
        raise FiniteTrialError('finite_scene_saved_profile_changed')
    return account, report, policy


def run_trial(*, account, report, policy, binary, model_dir, work_dir, token):
    deadline = time.monotonic() + 600
    client = FiniteSceneClient(token, deadline=deadline)
    result = {'status': 'INCOMPLETE', 'nativeCloudCompute': False, 'newQualification': False,
              'searchExecuted': False, 'recurringTasksStarted': False, 'workStarted': False}
    try:
        recovered = client.recover(account['recoveryCode'])
        if recovered.get('accountId') != account['accountId']:
            raise FiniteTrialError('finite_scene_account_changed')
        client.enable_outbox(Path(work_dir) / 'indexes', account['accountId'])
        before = client.me()['units']
        _, capabilities, _ = client.request('GET', '/api/capabilities')
        scene = capabilities.get('sceneContributions', {})
        if (scene.get('ready') is not True or scene.get('admissionMode') != 'qualified-device-v1'
                or scene.get('model') != 'vision-four-view-v4' or scene.get('scope') != 'qualified-new-locations'
                or scene.get('maxBatchLocations') != 2
                or scene.get('verification') != 'trusted-profile-canary-and-upload-integrity'
                or scene.get('policyId') != policy.document['policyId']
                or scene.get('deviceQualificationRequired') is not True or scene.get('canaryLocations') != 112
                or capabilities.get('objectContributions', {}).get('ready') is not False):
            raise FiniteTrialError('finite_scene_admission_changed')
        profile = report['runtimeProfile']['sha256']
        _, qualification, _ = client.request('GET', '/api/scene-qualifications?profileId=' + profile)
        if (qualification.get('qualified') is not True or qualification.get('profileId') != profile
                or qualification.get('policyId') != policy.document['policyId']
                or type(qualification.get('expiresAt')) is not int
                or qualification['expiresAt'] <= time.time() + 600):
            raise FiniteTrialError('finite_scene_qualification_required')
        client.profile_id = profile

        result['workStarted'] = True
        prior_timeout = vision_index.INDEX_TIMEOUT_SECONDS
        try:
            vision_index.INDEX_TIMEOUT_SECONDS = max(1, int(min(deadline - time.monotonic(), 600)))
            indexed = vision_index.index_from_queue(url=ORIGIN, pace='slow', batches=1, count=2,
                client=client, persist_session=False, work_dir=Path(work_dir) / 'indexes',
                binary=Path(binary), model_dir=Path(model_dir), use_nice=False)
        finally:
            vision_index.INDEX_TIMEOUT_SECONDS = prior_timeout
        accepted = indexed.get('accepted')
        if (indexed.get('batches') != 1 or type(accepted) is not int or not 1 <= accepted <= 2
                or indexed.get('unitsEarned') != accepted or client.pending):
            raise FiniteTrialError('finite_scene_acceptance_incomplete')
        result.update(accepted=accepted, unitsEarned=accepted)
        replay = client.audit_submission(client.assigned_lease)
        after = client.me()['units']
        if (replay.get('admissionMode') != 'qualified-device-v1' or replay.get('unitsEarned') != 0
                or after - before != accepted):
            raise FiniteTrialError('finite_scene_credit_replay_incomplete')
        result.update(status='FINITE_QUALIFIED_SCENE_COHORT_PASSED', beforeUnits=before, afterUnits=after,
                      replayEarnedUnits=0, pending=0)
    except BaseException as error:
        result['failureClass'] = type(error).__name__
        if isinstance(error, FiniteTrialError):
            result['reason'] = error.code
    finally:
        client.budget.stopped = True
        result.update(coordinatorRequests=client.budget.requests, coordinatorBytesSent=client.budget.sent_bytes,
                      observedUsage=client.budget.usage, pending=client.pending,
                      requestUsage=getattr(client.budget, 'history', []),
                      transportStopReason=getattr(client.budget, 'stop_reason', None),
                      gatewayClosed=False, shutdownReadbackRequired=True, productionQualified=False)
        with (Path(work_dir) / 'trial.receipt.private.json').open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
    return result


def supervise_trial(arguments, work_dir, *, owned_runner=run_owned):
    # One owned child bounds the complete trial, including HTTP, native helpers
    # and descendants. The existing default native runner/provenance is retained.
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=False)
    result = {'status': 'INCOMPLETE', 'childDeadlineSeconds': 600, 'gatewayClosed': False,
              'shutdownReadbackRequired': True, 'productionQualified': False}
    try:
        with (root / 'child.stdout.private.log').open('xb') as stdout, (root / 'child.stderr.private.log').open('xb') as stderr:
            child = owned_runner([sys.executable, '-B', '-m', 'community.finite_scene_trial', *arguments, '--owned-child'],
                env=dict(os.environ), cwd=Path(__file__).resolve().parents[1], stdout=stdout, stderr=stderr, timeout=600)
        result['childExitCode'] = child.returncode
        path = root / 'trial.receipt.private.json'
        if path.is_file():
            receipt = json.loads(path.read_bytes())
            result['childStatus'] = receipt.get('status')
            if child.returncode == 0 and receipt.get('status') == 'FINITE_QUALIFIED_SCENE_COHORT_PASSED':
                result['status'] = 'FINITE_SCENE_CHILD_FINISHED_REQUIRES_GATEWAY_CLOSE'
    except subprocess.TimeoutExpired:
        result['reason'] = 'finite_scene_child_timeout'
    except BaseException as error:
        result['failureClass'] = type(error).__name__
    with (root / 'supervisor.receipt.private.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('account-file', 'canary-file', 'policy-file', 'binary', 'model-dir', 'work-dir'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--policy-sha256', required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--allow-staging-contribution', action='store_true')
    parser.add_argument('--owned-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.run and (not args.allow_staging_contribution or not args.token_file):
        raise FiniteTrialError('finite_scene_execution_consent_required')
    if args.run and not args.owned_child:
        result = supervise_trial(sys.argv[1:], args.work_dir)
        print(json.dumps(result))
        return 0 if result['status'] == 'FINITE_SCENE_CHILD_FINISHED_REQUIRES_GATEWAY_CLOSE' else 1
    account, report, policy = prepare(account_file=args.account_file, canary_file=args.canary_file,
        policy_file=args.policy_file, policy_sha256=args.policy_sha256, binary=args.binary, model_dir=args.model_dir)
    if not args.run:
        print(json.dumps({'status': 'LOCAL_PROFILE_PREPARED', 'networkRequests': 0,
                          'assignmentLimit': 1, 'locationLimit': 2, 'deadlineSeconds': 600,
                          'requiresSeparateRunAndTransferApproval': True}))
        return 0
    token = args.token_file.read_text(encoding='utf-8').strip()
    result = run_trial(account=account, report=report, policy=policy, binary=args.binary,
                       model_dir=args.model_dir, work_dir=args.work_dir, token=token)
    print(json.dumps(result))
    return 0 if result['status'] == 'FINITE_QUALIFIED_SCENE_COHORT_PASSED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
