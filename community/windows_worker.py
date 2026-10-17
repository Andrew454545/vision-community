"""Verified Windows background entrypoint; startup errors stop for review."""
import json
from pathlib import Path
import secrets
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if sys.platform != 'win32':
        raise RuntimeError('windows_required')
    try:
        from community.background import main as background_main
        background_main()
    except Exception as error:
        # Never include native output, paths, account codes or exception messages.
        try:
            from community.mac_starter import regular
            root = regular(Path(sys.argv[sys.argv.index('--root') + 1]), directory=True)
            folder = regular(root / 'setup-failures', directory=True, missing=True)
            folder.mkdir(exist_ok=True)
            report = {'status': 'INCOMPLETE', 'phase': 'background-startup',
                      'errorType': type(error).__name__,
                      'timeUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            with (folder / (secrets.token_hex(16) + '.json')).open('x', encoding='utf-8') as output:
                json.dump(report, output)
            regular(root / 'NEEDS-ATTENTION', missing=True).touch(exist_ok=True)
        except (OSError, ValueError, IndexError):
            pass
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
