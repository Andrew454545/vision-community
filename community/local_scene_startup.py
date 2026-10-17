"""Explicit opt-in user-login startup for one local campaign; never old VISION jobs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

from .local_scene_pilot import atomic_json
from .mac_starter import regular


def startup_config(app, *, python=None, entrypoint=None):
    identity = hashlib.sha256(str(app.root).encode()).hexdigest()[:16]
    label = 'org.visioncommunity.local-scenes.' + identity
    # Verified private Python distributions legitimately expose python3 as an
    # internal link. Store its canonical executable, never a mutable link.
    executable = regular(Path(python or sys.executable).resolve(strict=True))
    if os.name == 'nt' and executable.name.lower() == 'python.exe' and executable.with_name('pythonw.exe').is_file():
        executable = regular(executable.with_name('pythonw.exe'))
    source = regular(entrypoint or Path(__file__).with_name('local_scene_supervisor.py'))
    arguments = [str(executable), '-B', str(source), '--packet', str(app.path),
                 '--data-dir', str(app.root.parent), '--runtime-root', str(app.runtime_root),
                 '--no-browser', '--resume']
    return label, arguments


def configure_startup(app, enabled):
    if not hasattr(app, 'manifest') or type(enabled) is not bool:
        raise ValueError('campaign_startup_required')
    label, arguments = startup_config(app)
    receipt = app.root / 'startup.json'
    expected = {'label': label, 'arguments': arguments}
    if sys.platform == 'darwin':
        folder = regular(Path.home() / 'Library/LaunchAgents', directory=True, missing=True)
        folder.mkdir(parents=True, exist_ok=True)
        path = regular(folder / (label + '.plist'), missing=True)
        config = {'Label': label, 'ProgramArguments': arguments, 'RunAtLoad': True,
                  'KeepAlive': {'SuccessfulExit': False}, 'ThrottleInterval': 60,
                  'StandardOutPath': str(app.root / 'startup.stdout.log'),
                  'StandardErrorPath': str(app.root / 'startup.stderr.log')}
        if path.exists() and plistlib.loads(path.read_bytes()) != config:
            raise ValueError('startup_registration_not_owned')
        domain = f'gui/{os.getuid()}'
        if enabled:
            atomic_json(receipt, {**expected, 'enabled': False})
            if not path.exists():
                with path.open('xb') as stream:
                    stream.write(plistlib.dumps(config))
            result = subprocess.run(['launchctl', 'bootstrap', domain, str(path)], capture_output=True, timeout=20)
            if result.returncode:
                # A known exact label already registered is safe to retain.
                probe = subprocess.run(['launchctl', 'print', domain + '/' + label], capture_output=True, timeout=10)
                if probe.returncode:
                    raise ValueError('local_startup_registration_failed')
        elif path.exists():
            subprocess.run(['launchctl', 'bootout', domain, str(path)], capture_output=True, timeout=20)
            probe = subprocess.run(['launchctl', 'print', domain + '/' + label], capture_output=True, timeout=10)
            if probe.returncode == 0:
                raise ValueError('local_startup_removal_failed')
            path.unlink()
    elif os.name == 'nt':
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            command = subprocess.list2cmdline(arguments)
            try:
                old, kind = winreg.QueryValueEx(key, label)
            except FileNotFoundError:
                old = None
            if old is not None and old != command:
                raise ValueError('startup_registration_not_owned')
            if enabled:
                winreg.SetValueEx(key, label, 0, winreg.REG_SZ, command)
            elif old is not None:
                winreg.DeleteValue(key, label)
    else:
        raise ValueError('unsupported_startup_platform')
    atomic_json(receipt, {**expected, 'enabled': enabled})
