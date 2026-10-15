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
