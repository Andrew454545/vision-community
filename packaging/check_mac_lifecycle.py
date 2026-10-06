"""Actual per-user Mac app install, launch, repeat, repair, update and removal.

Disposable CI accounts only: it refuses to run beside an existing VISION app,
private folder or startup agent. Private files are synthetic. The app is opened
without download consent, so no account, service, model, imagery or native work
is used. Gatekeeper is only assessed (read-only) on a separately quarantined
copy; no quarantine attribute is removed and no security setting is changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import time
from stage import regular

HOME = Path.home()
APPS = HOME / 'Applications'
APP = APPS / 'VISION Community.app'
PRIVATE = HOME / 'Library/Application Support/VISION Community'
AGENT = HOME / 'Library/LaunchAgents/org.visioncommunity.background.plist'
BINARY = 'Contents/MacOS/VISION'
FIXTURES = {
    'account.json': '{"url":"https://vision-community.visioncommunity.workers.dev","recoveryCode":"SYNTHETIC-LIFECYCLE-FIXTURE-NOT-AN-ACCOUNT"}',
    'work-selection.json': '{"version":1,"workType":"both","next":"object","unfinished":"scene"}',
    'indexes/submissions.sqlite': 'synthetic pending delivery fixture',
    'indexes/scene/checkpoint.json': '{"completed":7,"synthetic":true}',
    'indexes/object/checkpoint.json': '{"completed":1,"synthetic":true}',
    'pc-check.json': '{"status":"COMPLETE","synthetic":true}',
    'desktop-failure.json': '{"status":"INCOMPLETE","synthetic":true}',
}


class Lifecycle:
    def __init__(self, work):
        self.work = work
        self.checks = {}
        self.observations = {}

    def check(self, name, value):
        self.checks[name] = bool(value)
        print(('PASS ' if value else 'FAIL ') + name, flush=True)
        if not value:
            raise RuntimeError('check_failed: ' + name)

    def extract(self, archive, name, quarantine=False):
        folder = self.work / name
        folder.mkdir()
        download = folder / archive.name
        shutil.copyfile(archive, download)
        if quarantine:
            # Mark the copy as a browser download, as Safari would.
            stamp = format(int(time.time()), 'x')
            subprocess.run(['xattr', '-w', 'com.apple.quarantine', f'0081;{stamp};Safari;', str(download)], check=True)
        subprocess.run(['ditto', '-x', '-k', str(download), str(folder)], check=True)
        return folder / 'VISION Community.app'

    @staticmethod
    def self_check(app):
        result = subprocess.run([str(app / BINARY), '--self-check'], capture_output=True, text=True, timeout=30)
        return result.returncode == 0 and 'PACKAGE_VERIFIED' in result.stdout

    @staticmethod
    def revision(app):
        return plistlib.loads((app / 'Contents/Info.plist').read_bytes())['VISIONSourceRevision']

    def install(self, source):
        APPS.mkdir(exist_ok=True)
        if APP.exists():
            shutil.rmtree(APP)
        subprocess.run(['ditto', str(source), str(APP)], check=True)

    @staticmethod
    def private_hashes():
        return {name: hashlib.sha256((PRIVATE / name).read_bytes()).hexdigest() for name in FIXTURES}

    @staticmethod
    def private_listing():
        return sorted(str(path.relative_to(PRIVATE)) for path in PRIVATE.rglob('*'))

    @staticmethod
    def pids():
        result = subprocess.run(['pgrep', '-f', str(APP / BINARY)], capture_output=True, text=True)
        return [int(value) for value in result.stdout.split()]

    def launch_and_quit(self, label):
        before = self.private_listing()
        subprocess.run(['open', '-n', str(APP)], check=True)
        deadline = time.monotonic() + 30
        while not self.pids() and time.monotonic() < deadline:
            time.sleep(0.25)
        pids = self.pids()
        self.check(f'{label}_app_starts', len(pids) == 1)
        time.sleep(5)
        self.check(f'{label}_app_stays_open', self.pids() == pids)
        children = subprocess.run(['pgrep', '-P', str(pids[0])], capture_output=True, text=True).stdout.split()
        self.check(f'{label}_no_processing_before_consent', not children and self.private_listing() == before)
        windows = subprocess.run(['osascript', '-e', f'tell application "System Events" to count windows of (first process whose unix id is {pids[0]})'],
                                 capture_output=True, text=True, timeout=30)
        self.observations[f'{label}_window_count'] = windows.stdout.strip() if windows.returncode == 0 else 'not readable without accessibility permission'
        method = 'apple-event'
        try:
            subprocess.run(['osascript', '-e', 'tell application id "org.visioncommunity.app" to quit'], capture_output=True, timeout=20)
        except subprocess.TimeoutExpired:
            pass
        deadline = time.monotonic() + 20
        while self.pids() and time.monotonic() < deadline:
            time.sleep(0.25)
        if self.pids():
            method = 'terminate-signal'
            for pid in self.pids():
                os.kill(pid, 15)
            time.sleep(2)
        self.observations[f'{label}_quit_method'] = method
        self.check(f'{label}_app_quits_without_work', not self.pids())


def run(archive_a, archive_b, report):
    if os.environ.get('VISION_DISPOSABLE_LIFECYCLE') != '1':
        raise SystemExit('Set VISION_DISPOSABLE_LIFECYCLE=1 only on a disposable test account.')
    regular(APPS, directory=True, missing=True)
    for path in (APP, PRIVATE, AGENT):
        regular(path, directory=path != AGENT, missing=True)
        if path.exists() or path.is_symlink():
            raise SystemExit(f'Refusing to run: existing VISION state at {path}')
    work = Path(tempfile.mkdtemp(prefix='vision-mac-lifecycle-')).resolve()
    state = Lifecycle(work)
    status, failure = 'INCOMPLETE', None
    try:
        # Read-only Gatekeeper assessment of a quarantined download.
        quarantined = state.extract(archive_a, 'quarantined-download', quarantine=True)
        attribute = subprocess.run(['xattr', '-p', 'com.apple.quarantine', str(quarantined)], capture_output=True, text=True)
        if attribute.returncode:
            # ditto does not always copy the archive's attribute; Archive Utility does.
            subprocess.run(['xattr', '-w', 'com.apple.quarantine', f'0081;{format(int(time.time()), "x")};Safari;', str(quarantined)], check=True)
        status_text = subprocess.run(['spctl', '--status'], capture_output=True, text=True).stdout.strip()
        assessment = subprocess.run(['spctl', '--assess', '--type', 'execute', '-vv', str(quarantined)], capture_output=True, text=True)
        state.observations['gatekeeper_status'] = status_text
        state.observations['gatekeeper_assessment'] = (assessment.stdout + assessment.stderr).strip().splitlines()[-1:]
        if 'enabled' in status_text:
            state.check('unsigned_download_is_not_accepted_by_gatekeeper', assessment.returncode != 0)

        app_a = state.extract(archive_a, 'download-a')
        app_b = state.extract(archive_b, 'download-b')
        revision_a, revision_b = state.revision(app_a), state.revision(app_b)
        state.check('two_distinct_revisions', revision_a != revision_b)

        for name, body in FIXTURES.items():
            target = PRIVATE / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        private = state.private_hashes()

        state.install(app_a)
        state.check('install_verifies', state.self_check(APP) and state.revision(APP) == revision_a)
        state.launch_and_quit('first_open')
        state.install(app_a)
        state.check('repeat_install_verifies', state.self_check(APP))

        changed = APP / 'Contents/Resources/project/community/desktop.py'
        original = changed.read_bytes()
        changed.write_bytes(original + b'\nchanged fixture\n')
        state.check('changed_app_file_refused', not state.self_check(APP))
        state.install(app_a)
        state.check('reinstall_repairs_changed_app', state.self_check(APP) and changed.read_bytes() == original)

        state.install(app_b)
        state.check('update_verifies_new_revision', state.self_check(APP) and state.revision(APP) == revision_b)
        state.launch_and_quit('after_update')
        state.check('update_keeps_private_files', state.private_hashes() == private)

        shutil.rmtree(APP)
        state.check('removal_deletes_app', not APP.exists())
        state.check('removal_keeps_account_indexes_checkpoints_deliveries', state.private_hashes() == private)
        state.check('no_startup_agent_left', not AGENT.exists())
        status = 'LIFECYCLE_PASS'
    except Exception as error:
        failure = str(error)
        print('Lifecycle failed: ' + failure, flush=True)
    finally:
        for pid in state.pids():
            os.kill(pid, 15)
    value = {'status': status, 'checks': state.checks, 'observations': state.observations,
             'accountsCreated': 0, 'serviceRequests': 0, 'nativeInference': False, 'signed': False,
             'productionQualified': False, 'cleanDeviceVerified': False}
    if failure:
        value['failure'] = failure
    Path(report).write_text(json.dumps(value, indent=2) + '\n')
    return status == 'LIFECYCLE_PASS'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-a', type=Path, required=True)
    parser.add_argument('--archive-b', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.archive_a.resolve(), args.archive_b.resolve(), args.report) else 1)
