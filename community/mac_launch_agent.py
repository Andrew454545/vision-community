"""Shared per-user Mac startup contract; registration UI remains unreleased.

This constructs a launchd configuration, not a qualified runtime or permission
to contribute. The installer must verify its immutable entrypoint/interpreter,
perform idle handover, and read back registration before allowing real work.
"""
import re

from community.background import ProcessingSchedule
from community.mac_starter import regular

LABEL = 'org.visioncommunity.background'


def agent_config(root, python, entrypoint, *, home, label=LABEL, schedule=None,
                 retry_minutes=30, storage_limit_gb=0, prevent_sleep=True):
    root = regular(root, directory=True)
    python, entrypoint = regular(python), regular(entrypoint)
    home = regular(home, directory=True)
    if (not re.fullmatch(r'org\.visioncommunity\.(?:background|check\.[a-f0-9]{32})', label)
            or root not in python.parents or root not in entrypoint.parents
            or any(any(c in str(path) for c in '\r\n\x00{}') for path in (root, python, entrypoint, home))):
        raise ValueError('invalid_mac_background_scope')
    if (type(retry_minutes) is not int or not 1 <= retry_minutes <= 1440
            or type(storage_limit_gb) is not int or not 0 <= storage_limit_gb <= 4096
            or type(prevent_sleep) is not bool):
        raise ValueError('invalid_mac_background_settings')
    if schedule is None:
        schedule = ProcessingSchedule(day_start='06:00', night_start='00:00')
    if not isinstance(schedule, ProcessingSchedule):
        raise ValueError('invalid_mac_background_settings')
    arguments = [str(python), '-I', '-B', str(entrypoint), '--root', str(root), '--accept-contributions',
        '--day-pace', schedule.day_pace, '--night-pace', schedule.night_pace,
        '--day-start', schedule.day_start, '--night-start', schedule.night_start,
        '--retry-minutes', str(retry_minutes), '--storage-limit-gb', str(storage_limit_gb)]
    if not prevent_sleep:
        arguments.append('--no-keep-awake')
    return {'Label': label, 'ProgramArguments': arguments, 'WorkingDirectory': str(root),
        'EnvironmentVariables': {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(home), 'LC_ALL': 'C'},
        'RunAtLoad': True, 'KeepAlive': False, 'StartInterval': 900, 'ThrottleInterval': 300,
        'ProcessType': 'Background', 'Umask': 0o077, 'AbandonProcessGroup': False,
        'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null'}


def verify_loaded(text, expected):
    """Reject a different loaded program/scope before clearing a stop request.

    launchctl's diagnostic format is validated by the real Mac fixture; it is
    not a stable API. A format change must fail closed and preserve reports.
    Saved plist verification is still required separately by an installer.
    """
    if not isinstance(text, str) or len(text.encode('utf-8')) > 65536:
        raise ValueError('mac_background_readback_failed')
    block = re.search(r'^\s*arguments = \{\s*\n(.*?)^\s*\}', text, re.M | re.S)
    arguments = [line.strip() for line in block.group(1).splitlines()] if block else []
    program = re.search(r'^\s*program = (.+)$', text, re.M)
    interval = re.search(r'^\s*run interval = (\d+) seconds$', text, re.M)
    if (arguments != expected['ProgramArguments'] or not program
            or program.group(1).strip() != expected['ProgramArguments'][0]
            or not interval or int(interval.group(1)) != expected['StartInterval']):
        raise ValueError('mac_background_readback_failed')

