"""Beginner-facing offline check; owner approval is a separate comparison."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import re
import threading
import zipfile

from .local_scene_packets import canonical, digest
from .local_scene_pilot import atomic_json, immutable, verify_runtime
from .local_scene_qualification import fixed_policy, read_document
from .mac_starter import regular
from .pc_canary import run_canary, runtime_profile
from .pc_canary import index_synthetic_canary

CONTRACT = 'vision-local-scene-readiness-v1'


def installation_identity(data_dir):
    path = regular(Path(data_dir) / 'installation-id.json', missing=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        immutable(path, canonical({'id': secrets.token_hex(32)}) + b'\n')
    return read_document(path)['id']


def load_readiness(path):
    path = regular(path)
    value = read_document(path, 32 * 1024)
    if (set(value) != {'contract', 'policies'} or value['contract'] != CONTRACT
            or not isinstance(value['policies'], list) or not 1 <= len(value['policies']) <= 3):
        raise ValueError('invalid_readiness_setup')
    seen = set()
    for item in value['policies']:
        if (set(item) != {'path', 'sha256', 'threads'} or item['threads'] not in (1, 2, 4)
                or item['threads'] in seen or not isinstance(item['path'], str)
                or '\\' in item['path'] or Path(item['path']).is_absolute()
                or any(p in ('..', '.') for p in item['path'].split('/'))):
            raise ValueError('invalid_readiness_policy')
        fixed_policy(path.parent / item['path'], item['sha256'])
        seen.add(item['threads'])
    if 1 not in seen:
        raise ValueError('baseline_scene_policy_required')
    return value


class LocalSceneReadiness:
    def __init__(self, path, data_dir, runtime_root):
        self.path = regular(path)
        self.setup = load_readiness(self.path)
        self.installation_id = installation_identity(data_dir)
        self.runtime_root = Path(runtime_root)
        self.root = regular(Path(data_dir) / 'checks' / self.installation_id, directory=True, missing=True)
        self.root.mkdir(parents=True, exist_ok=True)
        # Keep the exact fixed reference alongside reports for later personal
        # map checks. This copies trusted local kit files; it runs no inference.
        for item in self.setup['policies']:
            source = self.path.parent/item['path']
            policy = fixed_policy(source,item['sha256'])
            inputs = policy.pinned_inputs()
            cached = self.root/'policy-cache'/item['sha256']
            for field in ('fixture','reference'):
                immutable(cached/policy.document['dataset'][field]['path'],inputs[field+'Bytes'])
            immutable(cached/'policy.json',source.read_bytes())
        self.packet = {'packetId': self.installation_id}
        self.guard = threading.RLock()
        self.thread = None
        self.stop = threading.Event()
        self.phase, self.message = 'ready', 'Choose Start to check compatibility. No location queue will run yet.'
        self.completed = 0
        self.reports = []
        self.progress = self.root / ('readiness-' + digest(self.setup) + '.json')
        if self.progress.exists():
            saved = read_document(self.progress)
            if set(saved) != {'reports'} or not isinstance(saved['reports'], list):
                raise ValueError('readiness_progress_changed')
            for item in saved['reports']:
                if (set(item) != {'attempt','threads','policySha256'}
                        or not re.fullmatch('attempt-[a-f0-9]{24}', str(item['attempt']))
                        or not any(p['threads'] == item['threads'] and p['sha256'] == item['policySha256']
                                   for p in self.setup['policies'])):
                    raise ValueError('readiness_progress_changed')
                report_path = regular(self.root / item['attempt'] / 'canary-report.json')
                self.reports.append({'path': report_path, 'threads': item['threads'],
                                     'policySha256': item['policySha256']})
            self.completed = sum(112 for r in self.reports if read_document(r['path']).get('qualified') is True)
            self.message = 'Saved compatibility reports found. Save results or Resume the unfinished checks.'

    def _save_progress(self):
        atomic_json(self.progress, {'reports': [{'attempt': r['path'].parent.name,
            'threads': r['threads'], 'policySha256': r['policySha256']} for r in self.reports]})

    def status(self):
        return {'phase': self.phase, 'message': self.message, 'completed': self.completed,
                'total': 112 * len(self.setup['policies']), 'packetId': self.installation_id,
                'participant': 'Compatibility check', 'outputDirectory': str(self.root),
                'exportAvailable': bool(self.reports) and not (self.thread and self.thread.is_alive()),
                'localOnly': True, 'uploaded': False, 'creditsEarned': 0, 'readiness': True}

    def start(self):
        with self.guard:
            if self.thread and self.thread.is_alive():
                return
            self.stop.clear()
            self.phase = 'processing'
            self.thread = threading.Thread(target=self._work, name='local-scene-readiness', daemon=False)
            self.thread.start()

    def _work(self):
        from .background import single_instance, keep_awake
        try:
            with single_instance(self.root), keep_awake():
                for item in self.setup['policies']:
                    if self.stop.is_set():
                        self.phase, self.message = 'paused', 'Compatibility check paused. Completed reports are kept.'
                        return
                    self.message = f"Checking the {item['threads']}-thread processing profile. This runs locally."
                    policy = fixed_policy(self.path.parent / item['path'], item['sha256'])
                    binary, models, _ = verify_runtime(self.runtime_root)
                    if runtime_profile(binary, models, inference_threads=item['threads'])['sha256'] != policy.document['runtimeProfileSha256']:
                        raise ValueError('qualification_profile_mismatch')
                    saved = next((r for r in self.reports if r['threads'] == item['threads']), None)
                    if saved:
                        report = read_document(saved['path'])
                        if (report.get('qualified') is True and report.get('status') == 'COMPLETE'
                                and report.get('runtimeProfile', {}).get('sha256') == policy.document['runtimeProfileSha256']):
                            continue
                        # Retain the failed attempt on disk; only replace its
                        # current progress pointer after a new finite report.
                    attempt = self.root / ('attempt-' + secrets.token_hex(12))
                    from types import SimpleNamespace
                    from functools import partial
                    from .local_scene_pilot import LocalScenePilot
                    runner = partial(LocalScenePilot._runner, SimpleNamespace(pace='medium'))
                    indexer = partial(index_synthetic_canary, runner=runner)
                    report = run_canary(attempt, binary=binary, model_dir=models, policy=policy,
                                        inference_threads=item['threads'], indexer=indexer)
                    self.reports = [r for r in self.reports if r['threads'] != item['threads']]
                    self.reports.append({'path': attempt / 'canary-report.json', 'threads': item['threads'],
                                         'policySha256': item['sha256']})
                    self._save_progress()
                    if not report.get('qualified'):
                        self.message = 'This processing profile did not pass. Save the check results for the maintainer.'
                        self.phase = 'failed'
                        return
                    self.completed = sum(112 for r in self.reports if read_document(r['path']).get('qualified') is True)
                self.phase, self.message = 'complete', 'Checks passed. Save results and send them to the maintainer for your approved queue.'
        except Exception as error:
            self.phase, self.message = 'failed', 'The compatibility check stopped safely. Your existing work is unchanged.'
            from .local_scene_pilot import atomic_json
            atomic_json(self.root / 'failure.json', {'errorClass': type(error).__name__})

    def pause(self):
        self.stop.set()
        if self.thread and self.thread.is_alive():
            self.message = 'Finishing the current finite compatibility check, then stopping.'

    def close(self):
        self.pause()
        if self.thread:
            self.thread.join(650)
            if self.thread.is_alive():
                raise RuntimeError('compatibility_check_not_stopped')

    def export_results(self):
        if self.thread and self.thread.is_alive():
            raise ValueError('check_not_finished')
        if not self.reports:
            raise ValueError('no_compatibility_report')
        dest = self.root / ('check-results-' + secrets.token_hex(12) + '.zip')
        with zipfile.ZipFile(dest, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('installation.json', canonical({'installationId': self.installation_id,
                                                            'scope': 'OWNER_REVIEW_REQUIRED'}))
            for item in self.reports:
                report = read_document(item['path'])
                if 'error' in report:
                    report['error'] = 'compatibility_check_failed'
                archive.writestr(f"threads-{item['threads']}/canary-report.json", canonical(report))
        return {'path': str(dest), 'bytes': dest.stat().st_size,
                'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()}
