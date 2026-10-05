"""Owned, per-user Mac registration and cooperative background controls.

No administrator privileges or machine-wide startup settings are used. Saved
work is never deleted; replacement/removal waits for the shared worker lock.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import subprocess
import sys
import time

from community.background import ProcessingSchedule, WorkerAlreadyRunning, single_instance
from community.contribute import DEFAULT_URL, load_session
from community.mac_launch_agent import LABEL, verify_loaded
from community.mac_launch_guard import guarded_config
from community.mac_starter import regular

DEFAULT_SETTINGS = {'dayPace':'medium', 'nightPace':'max', 'dayStart':'06:00', 'nightStart':'00:00',
    'retryMinutes':30, 'storageLimitGb':0, 'preventSleep':True}
STATES = {'running':'Waiting for the next batch.', 'processing':'Processing a batch.',
    'preparing':'Preparing private processing files.', 'checking_pc':'Checking this computer.',
    'paused':'Paused between batches.', 'waiting_for_schedule':'Waiting for the scheduled time.',
    'waiting_for_work':'Waiting for more locations.', 'waiting_for_service':'The service is unavailable; retrying automatically.',
    'waiting_for_verification':'Saved batches are waiting for verification.',
    'retrying_indexing':'Retrying an interrupted batch after a rest.',
    'waiting_for_space':'More free space or a larger storage allowance is needed.',
    'needs_attention':'A saved failure needs review.', 'stopped':'Stopped safely between batches.'}


def read_json(path, *, missing=False):
    path = regular(path, missing=missing)
    if missing and not path.exists():
        return None
    if path.stat().st_size > 65536:
        raise ValueError('saved_settings_need_review')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('saved_settings_need_review')
    return value


def publish(path, body):
    """Unique staging file; never write through an existing redirected path."""
    path = regular(path, missing=True)
    stage = path.parent / ('staging-' + secrets.token_hex(16))
    with stage.open('xb') as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())
    os.chmod(stage, 0o600)
    regular(path, missing=True)
    stage.replace(path)


def settings_config(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_SETTINGS):
        raise ValueError('invalid_mac_background_settings')
    schedule = ProcessingSchedule(value['dayPace'], value['nightPace'], value['dayStart'], value['nightStart'])
    if (type(value['retryMinutes']) is not int or not 1 <= value['retryMinutes'] <= 1440
            or type(value['storageLimitGb']) is not int or not 0 <= value['storageLimitGb'] <= 4096
            or type(value['preventSleep']) is not bool):
        raise ValueError('invalid_mac_background_settings')
    return {'schedule':schedule, 'retry_minutes':value['retryMinutes'],
        'storage_limit_gb':value['storageLimitGb'], 'prevent_sleep':value['preventSleep']}


class MacBackground:
    def __init__(self, root, source, *, home=None, label=LABEL, runner=subprocess.run,
                 uid=None, handover_seconds=60):
        if sys.platform != 'darwin':
            raise ValueError('mac_required')
        self.root = regular(root, directory=True)
        self.source = regular(source, directory=True)
        self.home = regular(home or Path.home(), directory=True)
        self.label, self.runner = label, runner
        self.uid = os.getuid() if uid is None else uid
        if type(self.uid) is not int or self.uid < 0:
            raise ValueError('invalid_mac_background_scope')
        # Use the same validation as the registration contract.
        self.config = guarded_config(self.root, self.source, home=self.home, label=self.label)
        self.target = 'gui/' + str(self.uid) + '/' + self.label
        self.folder = regular(self.home / 'Library/LaunchAgents', directory=True, missing=True)
        self.plist = self.folder / (self.label + '.plist')
        self.receipt = self.root / 'mac-background-registration.json'
        self.handover_seconds = handover_seconds

    def call(self, *arguments, absent=False):
        result = self.runner(['/bin/launchctl', *arguments], capture_output=True, text=True, timeout=15,
            env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin', 'HOME':str(self.home), 'LC_ALL':'C'})
        if (len(result.stdout.encode('utf-8')) > 65536 or len(result.stderr.encode('utf-8')) > 65536
                or result.returncode and not (absent and result.returncode in {3, 113})):
            raise ValueError('mac_background_registration_failed')
        return result

    def owned(self):
        """Both the saved plist and loaded program must match our private receipt."""
        receipt = read_json(self.receipt, missing=True)
        path = regular(self.plist, missing=True)
        loaded = self.call('print', self.target, absent=True)
        if receipt is None:
            if path.exists() or loaded.returncode == 0:
                raise ValueError('unfamiliar_mac_background_registration')
            return None, None
        if (receipt.get('version') != 1 or receipt.get('label') != self.label
                or receipt.get('root') != str(self.root) or receipt.get('home') != str(self.home)
                or receipt.get('uid') != self.uid):
            raise ValueError('unfamiliar_mac_background_registration')
        settings_config(receipt.get('settings'))
        if receipt.get('removed') is True:
            if path.exists() or loaded.returncode == 0:
                raise ValueError('unfamiliar_mac_background_registration')
            return receipt, None
        if not path.exists() or path.stat().st_size > 65536:
            raise ValueError('unfamiliar_mac_background_registration')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != receipt.get('plistSha256'):
            raise ValueError('unfamiliar_mac_background_registration')
        config = plistlib.loads(body)
        if (config.get('Label') != self.label or config.get('WorkingDirectory') != str(self.root)
                or config.get('ProgramArguments', [])[:1] != ['/usr/bin/env']):
            raise ValueError('unfamiliar_mac_background_registration')
        if loaded.returncode == 0:
            verify_loaded(loaded.stdout, config)
        return receipt, (loaded.stdout if loaded.returncode == 0 else None)

    @contextmanager
    def operation(self):
        folder = regular(self.root / 'mac-control-lock', directory=True, missing=True)
        folder.mkdir(mode=0o700, exist_ok=True)
        regular(folder / 'desktop.lock', missing=True)
        try:
            with single_instance(folder):
                yield
        except WorkerAlreadyRunning:
            raise ValueError('background_controls_busy') from None

    @contextmanager
    def handover(self):
        """Cooperative stop; never unload or kill a worker during a batch."""
        stop = regular(self.root / 'STOP-AFTER-BATCH', missing=True)
        stop.touch(mode=0o600, exist_ok=True)
        regular(self.root / 'desktop.lock', missing=True)
        deadline = time.monotonic() + self.handover_seconds
        while True:
            context = single_instance(self.root)
            try:
                context.__enter__()
                break
            except WorkerAlreadyRunning:
                if time.monotonic() >= deadline:
                    raise ValueError('finish_current_batch_then_retry') from None
                time.sleep(0.2)
        try:
            yield
        finally:
            context.__exit__(None, None, None)

    def account(self, code=''):
        path = regular(self.root / 'account.json', missing=True)
        saved = read_json(path, missing=True)
        if saved is not None:
            session = load_session(path, DEFAULT_URL)
            if (not session or session.get('url') != DEFAULT_URL
                    or not isinstance(session.get('recoveryCode'), str) or not session['recoveryCode']):
                raise ValueError('saved_account_needs_review')
            return
        if not isinstance(code, str) or not 1 <= len(code.strip()) <= 256 or any(c in code for c in '\r\n\x00'):
            raise ValueError('paste_saved_recovery_code')
        body = (json.dumps({'url':DEFAULT_URL, 'accountId':None, 'recoveryCode':code.strip()})+'\n').encode()
        # The operation lock serializes these controls; do not overwrite a
        # concurrently created account from a guided instance.
        with path.open('xb') as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(path, 0o600)

    def enable(self, settings, *, accept=False, code=''):
        if accept is not True:
            raise ValueError('contribution_consent_required')
        options = settings_config(settings)
        config = guarded_config(self.root, self.source, home=self.home, label=self.label, **options)
        with self.operation():
            receipt, loaded = self.owned()
            with self.handover():
                self.account(code)
                self.folder.mkdir(parents=True, mode=0o700, exist_ok=True)
                regular(self.folder, directory=True)
                if loaded is not None:
                    self.call('bootout', self.target)
                    if self.call('print', self.target, absent=True).returncode == 0:
                        raise ValueError('mac_background_registration_failed')
                body = plistlib.dumps(config, sort_keys=True)
                # Keep each prior registration/settings receipt for review.
                if receipt:
                    history = regular(self.root / 'mac-background-history', directory=True, missing=True)
                    history.mkdir(mode=0o700, exist_ok=True)
                    with (history / (secrets.token_hex(16)+'.json')).open('x', encoding='utf-8') as output:
                        json.dump(receipt, output)
                publish(self.plist, body)
                record = {'version':1, 'label':self.label, 'root':str(self.root), 'home':str(self.home),
                    'uid':self.uid, 'settings':settings, 'plistSha256':hashlib.sha256(body).hexdigest()}
                publish(self.receipt, (json.dumps(record)+'\n').encode())
                self.call('enable', self.target)
                self.call('bootstrap', 'gui/' + str(self.uid), str(self.plist))
                self.owned()  # Exact saved and loaded readback before clearing stop.
                if self.call('print', self.target, absent=True).returncode:
                    raise ValueError('mac_background_registration_failed')
                regular(self.root / 'STOP-AFTER-BATCH').unlink()
            # No -k: starting an idle job must never kill an existing process.
            self.start_idle()

    def pause(self, paused):
        if type(paused) is not bool:
            raise ValueError('invalid_pause_request')
        with self.operation():
            receipt, loaded = self.owned()
            if not receipt or receipt.get('removed') or loaded is None:
                raise ValueError('enable_background_first')
            marker = regular(self.root / 'PAUSE', missing=True)
            if paused:
                marker.touch(mode=0o600, exist_ok=True)
            else:
                for name in ('NEEDS-ATTENTION', 'STOP-AFTER-BATCH'):
                    if regular(self.root / name, missing=True).exists():
                        raise ValueError('saved_failure_or_stop_needs_review')
                marker.unlink(missing_ok=True)
                self.start_idle()

    def remove(self):
        with self.operation():
            receipt, loaded = self.owned()
            if not receipt or receipt.get('removed'):
                return
            with self.handover():
                if loaded is not None:
                    self.call('bootout', self.target)
                if self.call('print', self.target, absent=True).returncode == 0:
                    raise ValueError('mac_background_registration_failed')
                regular(self.plist).unlink()
                # Keep registration evidence. A new enable explicitly clears
                # this owned removed receipt after checking the absent job.
                record = read_json(self.receipt)
                record['removed'] = True
                publish(self.receipt, (json.dumps(record)+'\n').encode())

    def status(self):
        receipt, loaded = self.owned()
        saved = read_json(self.root / 'background-status.json', missing=True)
        running = self.is_running(loaded)
        enabled = bool(receipt and not receipt.get('removed'))
        attention = regular(self.root / 'NEEDS-ATTENTION', missing=True).exists()
        pause = regular(self.root / 'PAUSE', missing=True).exists()
        message = 'Automatic processing is not enabled.' if not enabled else (
            'Background process is running now.' if running else 'Enabled; background process is not running now.')
        if saved:
            state = STATES.get(saved.get('state'), 'Saved progress needs review.')
            message += ' Last saved report: ' + state
        if attention:
            message += ' A saved failure needs review; Resume will not clear it.'
        if pause:
            message += ' Pause is requested after the current batch.'
        return {'enabled':enabled, 'running':running, 'paused':pause, 'needsAttention':attention,
            'accountSaved':read_json(self.root / 'account.json', missing=True) is not None,
            'settings':receipt['settings'] if receipt else dict(DEFAULT_SETTINGS), 'message':message}

    @staticmethod
    def is_running(loaded):
        import re
        return bool(loaded and re.search(r'^\s*pid = [1-9][0-9]*$', loaded, re.M))

    def start_idle(self):
        _, loaded = self.owned()
        if self.is_running(loaded):
            return
        try:
            self.call('kickstart', self.target)
        except ValueError:
            # A scheduled start can win this race. Accept only a verified owned
            # running job, never hide an unrelated scheduler failure.
            _, loaded = self.owned()
            if not self.is_running(loaded):
                raise

    def preserve_failure(self, error):
        folder = regular(self.root / 'setup-failures', directory=True, missing=True)
        folder.mkdir(mode=0o700, exist_ok=True)
        with (folder / (secrets.token_hex(16)+'.json')).open('x', encoding='utf-8') as output:
            json.dump({'status':'INCOMPLETE', 'phase':'mac-background-control',
                'errorType':type(error).__name__}, output)
