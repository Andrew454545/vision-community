"""Verified Mac background entrypoint with cooperative sign-out/shutdown."""
import json
from pathlib import Path
import secrets
import signal
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from community.background import main as background_main
    from community.mac_starter import regular
    if sys.platform != 'darwin':
        raise RuntimeError('mac_required')
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        background_main(stop=stop)
    except Exception as error:
        # Fixed redacted startup report, preserved rather than overwritten.
        try:
            root = regular(Path(sys.argv[sys.argv.index('--root') + 1]), directory=True)
            folder = regular(root / 'setup-failures', directory=True, missing=True)
            folder.mkdir(mode=0o700, exist_ok=True)
            report = {'status':'INCOMPLETE', 'phase':'background-startup',
                'errorType':type(error).__name__, 'timeUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
            with (folder / (secrets.token_hex(16) + '.json')).open('x', encoding='utf-8') as output:
                json.dump(report, output)
            regular(root / 'NEEDS-ATTENTION', missing=True).touch(exist_ok=True)
        except (OSError, ValueError, IndexError):
            pass
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
