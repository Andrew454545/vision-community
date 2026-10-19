"""Finite actual launchd recovery fixture, using only an isolated fake batch.

Run with the verified private Mac interpreter. A random temporary per-user
agent is removed on completion or failure. No persistent login item, real
account, models, native inference, imagery, service or credits are used.
"""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import plistlib
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from community.background import atomic_json
from community.contribute import DEFAULT_URL, save_session
from community.mac_launch_agent import agent_config, verify_loaded
from community.mac_starter import regular


def command(*args):
    result = subprocess.run(['/bin/launchctl', *args], capture_output=True, text=True,
        timeout=15, env={'HOME': str(Path.home()), 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C'})
    if len(result.stdout.encode()) > 65536 or len(result.stderr.encode()) > 65536:
        raise RuntimeError('mac_fixture_readback_limit')
    return result


def wait_until(check, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.1)
    raise RuntimeError('mac_fixture_timeout')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        parser.error('This finite OS check requires an Apple silicon Mac.')
    root = regular(args.root, directory=True)
    report = regular(args.report, missing=True)
    if report.exists():
        parser.error('Keep the original report and choose a new report file.')
    nonce = secrets.token_hex(16)
    fixture = regular(root / ('launchd-check-' + nonce), directory=True, missing=True)
    fixture.mkdir(mode=0o700)
    worker_root = fixture / 'worker'
    worker_root.mkdir(mode=0o700)
    entry = fixture / 'entry.py'
    label = 'org.visioncommunity.check.' + nonce
    target = 'gui/' + str(os.getuid()) + '/' + label
    registered = False
    receipt = {'status': 'INCOMPLETE', 'platform': 'darwin-arm64', 'productionQualified': False,
        'nativeCommands': 0, 'imageryRetrieved': False, 'serviceRequests': 0,
        'realAccountsCreated': 0, 'contributionsUploaded': 0, 'temporaryAgentRemoved': False,
        'fixtureRecoveryIntervalSeconds': 3, 'productionRecoveryIntervalSeconds': 900,
        'actualOsRestartTested': False, 'loginRecoveryTested': False}
    try:
        # The worker is real; its service/model/indexer dependencies are deliberate
        # offline fixtures. This cannot qualify or admit a production contributor.
        entry.write_text('''import json, os, sqlite3, sys, threading
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, SOURCE)
from community.background import BackgroundContributor, ProcessingSchedule, atomic_json, single_instance
from community.work_plan import WorkPlan
root = Path(WORKER)
app = Mock()
app.work_plan = WorkPlan(root)
app.client = None
app.assets = {}
app.resume_submissions.return_value = {'accepted': 0, 'unitsEarned': 0}
def connect(code=None, **kwargs):
    if kwargs.get('create') or code != 'finite-offline-fixture-account':
        raise RuntimeError('fixture_account_changed')
    app.client = Mock(undelivered=0)
    return {'recoveryCode': code}
app.connect.side_effect = connect
app.record_failure.side_effect = lambda error: atomic_json(root/'new-failure.json', {'type':type(error).__name__})
def index(**kwargs):
    checkpoint = root/'checkpoint.json'
    if not checkpoint.exists():
        atomic_json(checkpoint, {'batchId':'finite-batch-1', 'complete':False})
        atomic_json(root/'ready.json', {'pid':os.getpid()})
        threading.Event().wait(120)
        raise RuntimeError('fixture_caller_was_not_interrupted')
    with sqlite3.connect(root/'awards.sqlite') as database:
        database.execute('CREATE TABLE IF NOT EXISTS awards(batch TEXT PRIMARY KEY)')
        before = database.execute('SELECT count(*) FROM awards').fetchone()[0]
        database.execute('INSERT OR IGNORE INTO awards VALUES (?)', ('finite-batch-1',))
    atomic_json(checkpoint, {'batchId':'finite-batch-1', 'complete':True})
    return {'accepted':16 if before == 0 else 0, 'batches':1}
app.indexer.side_effect = index
app.run_batch.side_effect = lambda: app.indexer(url=worker.url, pace="slow", batches=1,
    count=16, client=app.client, persist_session=False, work_dir=worker.root / "indexes",
    **app.assets, use_nice=False)
worker = BackgroundContributor(root, app_factory=lambda *args, **kwargs:app,
    schedule=ProcessingSchedule(day_pace='max',night_pace='max'))
with single_instance(root):
    with (root/'starts.jsonl').open('a',encoding='utf-8') as log:
        log.write(json.dumps({'pid':os.getpid()})+'\\n')
    worker.run(once=True)
    with (root/'done.jsonl').open('a',encoding='utf-8') as log:
        log.write(json.dumps({'pid':os.getpid()})+'\\n')
'''.replace('SOURCE', repr(str(Path(__file__).resolve().parents[1])))
   .replace('WORKER', repr(str(worker_root))), encoding='utf-8')
        account = worker_root / 'account.json'
        # Match the worker's public default origin without ever contacting it.
        save_session(account, url=DEFAULT_URL, account_id=None, recovery_code='finite-offline-fixture-account')
        account_pin = hashlib.sha256(account.read_bytes()).hexdigest()
        old_failure = worker_root / 'retained-failure.json'
        old_failure.write_bytes(b'{"status":"INCOMPLETE","code":"retained_fixture_failure"}')
        old_pin = hashlib.sha256(old_failure.read_bytes()).hexdigest()
        plan = agent_config(root, Path(sys.executable), entry, home=Path.home(), label=label)
        # Exercise exactly the same program/owner contract in a short finite
        # interval. Do not wait 15 minutes or claim this is an overnight test.
        plan.update(StartInterval=3, ThrottleInterval=1)
        plist = fixture / 'fixture.plist'
        plist.write_bytes(plistlib.dumps(plan, sort_keys=True))
        if plistlib.loads(plist.read_bytes()) != plan:
            raise RuntimeError('mac_fixture_plist_mismatch')
        result = command('bootstrap', 'gui/' + str(os.getuid()), str(plist))
        if result.returncode:
            raise RuntimeError('mac_fixture_registration_failed')
        registered = True
        loaded = command('print', target)
        if loaded.returncode:
            raise RuntimeError('mac_fixture_readback_failed')
        verify_loaded(loaded.stdout, plan)
        receipt['loadedProgramScopeVerified'] = True
        wait_until(lambda: (worker_root/'ready.json').exists())
        before = json.loads((worker_root/'checkpoint.json').read_text())
        if before != {'batchId':'finite-batch-1', 'complete':False}:
            raise RuntimeError('mac_fixture_checkpoint_mismatch')
        pid = json.loads((worker_root/'ready.json').read_text())['pid']
        loaded = command('print', target)
        verify_loaded(loaded.stdout, plan)
        found = re.search(r'^\s*pid = (\d+)\s*$', loaded.stdout, re.M)
        if not found or int(found.group(1)) != pid:
            raise RuntimeError('mac_fixture_caller_scope_mismatch')
        # Kill only the PID read back from this random owned temporary service.
        os.kill(pid, signal.SIGKILL)
        receipt['ownedCallerInterrupted'] = True
        def completed():
            return json.loads((worker_root/'checkpoint.json').read_text()).get('complete') is True
        wait_until(completed)
        receipt['scheduledRecoveryCompleted'] = True
        # A further actual scheduled launch must reuse saved work/account and
        # cannot create a second award for the same disposable batch.
        wait_until(lambda: (worker_root/'done.jsonl').exists() and
            len((worker_root/'done.jsonl').read_text().splitlines()) >= 2)
        with sqlite3.connect(worker_root/'awards.sqlite') as database:
            awards = database.execute('SELECT count(*) FROM awards').fetchone()[0]
        if awards != 1 or (worker_root/'new-failure.json').exists():
            raise RuntimeError('mac_fixture_recovery_failed')
        if hashlib.sha256(account.read_bytes()).hexdigest() != account_pin:
            raise RuntimeError('mac_fixture_saved_account_changed')
        if hashlib.sha256(old_failure.read_bytes()).hexdigest() != old_pin:
            raise RuntimeError('mac_fixture_saved_report_changed')
        if json.loads((worker_root/'checkpoint.json').read_text()) != {'batchId':'finite-batch-1', 'complete':True}:
            raise RuntimeError('mac_fixture_checkpoint_mismatch')
        receipt.update(sameSavedAccount=True, retainedFailureUnchanged=True, syntheticAwards=awards,
            scheduledStartsObserved=len((worker_root/'starts.jsonl').read_text().splitlines()),
            completedScheduledLaunchesObserved=len((worker_root/'done.jsonl').read_text().splitlines()),
            checkpointBatchUnchanged=True, status='MAC_SCHEDULED_RECOVERY_VERIFIED')
    except Exception as error:
        # Keep the fixture folder and fixed report. Never print raw OS output,
        # account content, program arguments or private paths.
        receipt['errorType'] = type(error).__name__
        receipt['code'] = str(error) if isinstance(error, RuntimeError) else 'mac_background_check_failed'
    finally:
        if registered:
            try:
                result = command('bootout', target)
                absent = command('print', target)
                if result.returncode == 0 and absent.returncode == 113:
                    receipt['temporaryAgentRemoved'] = True
                else:
                    receipt.update(status='INCOMPLETE', code='mac_fixture_cleanup_failed')
            except Exception:
                receipt.update(status='INCOMPLETE', code='mac_fixture_cleanup_failed')
        with report.open('x', encoding='utf-8') as output:
            json.dump(receipt, output, sort_keys=True, indent=2)
        print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt['status'] == 'MAC_SCHEDULED_RECOVERY_VERIFIED' and receipt['temporaryAgentRemoved'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
