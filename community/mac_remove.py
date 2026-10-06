"""Cooperative application removal using only existing private files.

The native app verifies its sealed source and the private interpreter before
this entrypoint runs. No downloads, account connection or inference occur.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import subprocess
import sys
import time
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from community.background import WorkerAlreadyRunning, single_instance
from community.mac_background import MacBackground, read_json, settings_config
from community.mac_launch_agent import LABEL
from community.mac_launch_guard import guarded_config
from community.mac_starter import regular


def absent_job(target, home, runner):
    result = runner(['/bin/launchctl', 'print', target], capture_output=True, text=True,
        timeout=15, env={'HOME':str(home), 'PATH':'/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL':'C'})
    if (len(result.stdout.encode()) > 65536 or len(result.stderr.encode()) > 65536
            or result.returncode not in {3, 113}):
        raise ValueError('unfamiliar_mac_background_registration')


@contextmanager
def idle(root, seconds):
    # The stop request survives a timeout. No process is killed or unloaded
    # until the shared writer lock has been released by its owner.
    regular(root / 'STOP-AFTER-BATCH', missing=True).touch(mode=0o600, exist_ok=True)
    regular(root / 'desktop.lock', missing=True)
    deadline = time.monotonic() + seconds
    while True:
        guard = single_instance(root)
        try:
            guard.__enter__()
            break
        except WorkerAlreadyRunning:
            if time.monotonic() >= deadline:
                raise ValueError('finish_current_batch_then_retry') from None
            time.sleep(.2)
    try:
        yield
    finally:
        guard.__exit__(None, None, None)


def prepare_removal(root, *, home=None, label=LABEL, runner=subprocess.run,
                    uid=None, handover_seconds=60):
    if sys.platform != 'darwin':
        raise ValueError('mac_required')
    home = regular(home or Path.home(), directory=True)
    root = regular(root, directory=True, missing=True)
    uid = os.getuid() if uid is None else uid
    if type(uid) is not int or uid < 0 or (label != LABEL and
            not (label.startswith('org.visioncommunity.check.') and
                 len(label.removeprefix('org.visioncommunity.check.')) == 32 and
                 all(c in '0123456789abcdef' for c in label.removeprefix('org.visioncommunity.check.')))):
        raise ValueError('invalid_mac_background_scope')
    target = 'gui/' + str(uid) + '/' + label
    plist = regular(home / 'Library/LaunchAgents' / (label + '.plist'), missing=True)
    receipt_path = regular(root / 'mac-background-registration.json', missing=True)
    receipt = read_json(receipt_path, missing=True)
    if receipt is not None:
        if (receipt.get('version') != 1 or receipt.get('label') != label
                or receipt.get('root') != str(root) or receipt.get('home') != str(home)
                or receipt.get('uid') != uid):
            raise ValueError('unfamiliar_mac_background_registration')
        settings_config(receipt.get('settings'))
    if receipt is None or receipt.get('removed') is True:
        if plist.exists():
            raise ValueError('unfamiliar_mac_background_registration')
        absent_job(target, home, runner)
        if root.exists():
            folder = regular(root / 'mac-control-lock', directory=True, missing=True)
            folder.mkdir(mode=0o700, exist_ok=True)
            regular(folder / 'desktop.lock', missing=True)
            try:
                with single_instance(folder), idle(root, handover_seconds):
                    # Recheck after acquiring both operation and writer locks.
                    if read_json(receipt_path, missing=True) != receipt or plist.exists():
                        raise ValueError('background_controls_busy')
                    absent_job(target, home, runner)
            except WorkerAlreadyRunning:
                raise ValueError('background_controls_busy') from None
        return {'status':'MAC_REMOVAL_READY', 'automaticStartupRemoved':True,
                'savedWorkKept':True, 'productionQualified':False}
    if not plist.exists() or plist.stat().st_size > 65536:
        raise ValueError('unfamiliar_mac_background_registration')
    body = plist.read_bytes()
    if hashlib.sha256(body).hexdigest() != receipt.get('plistSha256'):
        raise ValueError('unfamiliar_mac_background_registration')
    config = plistlib.loads(body)
    arguments = config.get('ProgramArguments', [])
    if not isinstance(arguments, list) or len(arguments) < 14 or not isinstance(arguments[9], str):
        raise ValueError('unfamiliar_mac_background_registration')
    source = regular(arguments[9], directory=True)
    # Only the exact verified private snapshot, runtime guard and recorded
    # settings can authorize stopping this job. No new snapshot is installed.
    expected = guarded_config(root, source, home=home, label=label,
                              **settings_config(receipt['settings']))
    if config != expected:
        raise ValueError('unfamiliar_mac_background_registration')
    manager = MacBackground(root, source, home=home, label=label, runner=runner,
        uid=uid, handover_seconds=handover_seconds)
    manager.remove(expected_plist_sha=hashlib.sha256(body).hexdigest())
    removed, loaded = manager.owned()
    if not removed or removed.get('removed') is not True or loaded is not None:
        raise ValueError('mac_background_registration_failed')
    return {'status':'MAC_REMOVAL_READY', 'automaticStartupRemoved':True,
            'savedWorkKept':True, 'productionQualified':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--check-label', help=argparse.SUPPRESS)
    parser.add_argument('--check-home', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if bool(args.check_label) != bool(args.check_home) or (args.check_label and
            not args.check_label.startswith('org.visioncommunity.check.')):
        parser.error('Finite checks require their own temporary label and home.')
    try:
        print(json.dumps(prepare_removal(args.root, home=args.check_home,
            label=args.check_label or LABEL)))
        return 0
    except Exception as error:
        try:
            root = regular(args.root, directory=True)
            folder = regular(root / 'setup-failures', directory=True, missing=True)
            folder.mkdir(mode=0o700, exist_ok=True)
            with (folder / (secrets.token_hex(16)+'.json')).open('x', encoding='utf-8') as output:
                json.dump({'status':'INCOMPLETE', 'phase':'mac-application-removal',
                           'errorType':type(error).__name__}, output)
        except Exception:
            pass  # Never redirect a report through an unfamiliar private path.
        print(json.dumps({'status':'INCOMPLETE', 'code':'mac_removal_not_safe',
                          'savedWorkKept':True, 'productionQualified':False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
