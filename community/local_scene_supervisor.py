"""User-opted local login watchdog; owns only its private window child."""
from pathlib import Path
import os
import subprocess
import sys
import time

REPO = Path(os.path.abspath(__file__)).parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def owned_window(arguments, *, stdin, stdout, stderr, creationflags):
    # Reuse existing parent-death/Windows Job ownership. Removing this campaign's
    # login entry must not leave an orphaned browser server or native worker.
    from community.process_owner import run_owned
    if '--data-dir' in arguments:
        from community.local_scene_pilot import atomic_json
        from community.mac_starter import regular
        folder = regular(Path(arguments[arguments.index('--data-dir') + 1]) / 'supervisor-diagnostics',
                         directory=True, missing=True)
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        stem = folder / str(time.time_ns())
        receipt = {'status': 'STARTED'}
        try:
            with os.fdopen(os.open(stem.with_suffix('.stdout.log'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as out, \
                 os.fdopen(os.open(stem.with_suffix('.stderr.log'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as err:
                result = run_owned(arguments, env=dict(os.environ), cwd=REPO, stdout=out,
                    stderr=err, timeout=None, creationflags=creationflags)
                receipt.update(status='EXITED', exitCode=result.returncode)
                return result
        except BaseException as error:
            receipt.update(status='STOPPED', errorClass=type(error).__name__)
            raise
        finally:
            atomic_json(stem.with_suffix('.json'), receipt)
    return run_owned(arguments, env=dict(os.environ), cwd=REPO, stdout=stdout,
                     stderr=stderr, timeout=None, creationflags=creationflags)


def supervise(arguments, *, run=owned_window, sleep=time.sleep):
    failures = 0
    while True:
        result = run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode == 0:
            return 0  # Explicit Exit, or an existing owned window: do not restart it.
        failures += 1
        sleep(min(3600, 60 * 2**min(failures-1,6)))


if __name__ == '__main__':
    ui = Path(__file__).with_name('local_scene_ui.py')
    arguments = sys.argv[1:]
    if '--resume' not in arguments:
        arguments = [*arguments, '--resume']
    raise SystemExit(supervise([sys.executable, '-B', str(ui), *arguments]))
