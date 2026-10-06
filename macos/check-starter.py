"""Finite Mac starter/window check. Writes only aggregate public diagnostics.

No native runtime/model download, account, imagery, contribution or search.
Private loopback credentials stay in the disposable root and are never printed.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from community.mac_starter import copy_source, regular


def check(root):
    if sys.platform != 'darwin':
        raise ValueError('mac_required')
    app, digest = copy_source(Path(__file__).resolve().parents[1], root)
    window = regular(root/'finite-window-check', directory=True, missing=True)
    window.mkdir()
    child = subprocess.Popen([sys.executable, '-I', '-B', str(app/'community/desktop.py'),
        '--root', str(window), '--no-browser'], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        while not (window/'instance.json').is_file():
            if child.poll() is not None or time.monotonic() >= deadline:
                raise ValueError('local_window_start_failed')
            time.sleep(.1)
        instance = json.loads((window/'instance.json').read_text())
        address = urlsplit(instance['url'])
        if (instance.get('pid') != child.pid or address.scheme != 'http'
                or address.hostname != '127.0.0.1' or not address.port
                or not address.fragment or address.path != '/'):
            raise ValueError('local_window_identity_failed')
        base = f'http://127.0.0.1:{address.port}'
        for name in ('/', '/app.js', '/style.css'):
            with urlopen(base+name, timeout=5) as response:
                if response.status != 200 or not response.read(1024*1024):
                    raise ValueError('local_asset_failed')
                if (response.headers.get('Cache-Control') != 'no-store'
                        or response.headers.get('Referrer-Policy') != 'no-referrer'):
                    raise ValueError('local_privacy_headers_failed')
        try:
            urlopen(base+'/api/status', timeout=5).close()
        except HTTPError as denied:
            if denied.code != 403:
                raise ValueError('local_token_guard_failed') from None
        else:
            raise ValueError('local_token_guard_failed')
        headers = {'X-Vision-Token': address.fragment, 'Content-Type': 'application/json'}
        with urlopen(Request(base+'/api/status', headers=headers), timeout=5) as response:
            state = json.load(response)
        if any(state.get(key) for key in ('ready', 'qualified', 'connected', 'busy')):
            raise ValueError('unexpected_setup_or_account')
        if state.get('completed') != 0 or state.get('units') != 0:
            raise ValueError('unexpected_contribution_or_credit')
        # A second setup-only entry must stop at the held lock. Replace setup
        # with a failing sentinel so a regression cannot download native assets.
        lock_check = '''import sys
sys.path.insert(0, sys.argv.pop(1))
from community import desktop
def forbidden_setup(self):
    raise RuntimeError("unexpected_second_setup")
desktop.DesktopApp.prepare = forbidden_setup
sys.argv = ["desktop.py", "--root", sys.argv[1], "--prepare-only"]
desktop.main()
'''
        duplicate = subprocess.run([sys.executable, '-I', '-B', '-c', lock_check,
            str(app), str(window)], capture_output=True, text=True, timeout=10)
        if duplicate.returncode != 0 or 'VISION is already open.' not in duplicate.stdout:
            raise ValueError('single_instance_setup_guard_failed')
        with urlopen(Request(base+'/api/quit', data=b'{}', headers=headers, method='POST'), timeout=5) as response:
            if response.status != 200 or json.load(response) != {'ok':True}:
                raise ValueError('local_window_quit_failed')
        child.communicate(timeout=10)
        if child.returncode != 0 or (window/'instance.json').exists() or (window/'local-test-url.txt').exists():
            raise ValueError('local_window_cleanup_failed')
        if any(window.rglob('account.json')):
            raise ValueError('unexpected_account_file')
        return {'status': 'MAC_PRIVATE_STARTER_WINDOW_VERIFIED', 'sourceSha256': digest,
            'platform': 'darwin-arm64', 'pythonVersion': sys.version.split()[0],
            'publicAssetsChecked': 3, 'unauthenticatedAccessDenied': True,
            'authenticatedStatusChecked': True, 'ownedWindowExited': True,
            'singleInstanceSetupGuardChecked': True,
            'accountsCreated': 0, 'imageryRetrieved': False, 'nativeCommands': 0,
            'contributionsUploaded': 0, 'productionQualified': False}
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = check(regular(args.root, directory=True))
        code = 0
    except Exception as error:
        result = {'status': 'INCOMPLETE', 'code': str(error) if isinstance(error, ValueError)
            else type(error).__name__, 'productionQualified': False}
        code = 1
    with args.report.open('x', encoding='utf-8') as output:
        json.dump(result, output, sort_keys=True); output.write('\n')
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(code)
