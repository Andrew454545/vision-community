"""Account-free, local-only Scene work. Results remain provisional on disk."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import subprocess
import sys
import threading
import time

from .bootstrap import files_for_platform, runtime_platform
from .local_scene_packets import canonical, load_packet
from .mac_starter import regular
from .pc_canary import runtime_profile
from .process_owner import run_owned
from .vision_index import (assert_not_live_vision_path, checkpoint_state, file_identity,
                           index_locations_tsv, require_complete_index, VisionIndexError)

CHUNK = 16
CHILD_SECONDS = 600
MANIFEST = Path(__file__).with_name('local_scene_runtime.json')


def immutable(path, body):
    path = regular(path, missing=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != body:
            raise ValueError('saved_work_changed') from None


def atomic_json(path, value):
    regular(path, missing=True)
    pending = path.with_name(path.name + '.' + secrets.token_hex(5) + '.tmp')
    with os.fdopen(os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(canonical(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def verify_runtime(root, *, inference_threads=1):
    root = regular(root, directory=True)
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    platform = runtime_platform()
    if platform not in ('windows-x86_64', 'darwin-arm64'):
        raise ValueError('unsupported_platform')
    for item in files_for_platform(manifest, platform, lane='scene'):
        path = regular(root / item['path'])
        if file_identity(path) != {'bytes': item['bytes'], 'sha256': item['sha256']}:
            raise ValueError('pilot_runtime_mismatch')
    binary = root / 'bin' / ('mma-vision.exe' if sys.platform == 'win32' else 'mma-vision')
    models = root / 'models/siglip-b16-224-canonical'
    return binary, models, runtime_profile(binary, models, inference_threads=inference_threads)


class CheckedRuntime:
    """Hash once per unchanged local runtime, recheck file identity each group.

    This is a performance cache for cooperative local installations, not an
    adversarial attestation boundary. Changed file metadata forces full pinned
    validation before any new group can run.
    """
    def __init__(self):
        self.signature = None
        self.profiles = {}

    def __call__(self, root, *, inference_threads=1):
        root = regular(root, directory=True)
        manifest = json.loads(regular(MANIFEST).read_text())
        paths = [MANIFEST, *[root / item['path'] for item in
                 files_for_platform(manifest, runtime_platform(), lane='scene')],
                 *[Path(__file__).with_name(name) for name in
                   ('vision_index.py', 'four_view.py', 'process_owner.py')]]
        signature = []
        for path in paths:
            info = regular(path).stat()
            signature.append((str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
        if signature != self.signature:
            self.profiles.clear()
            self.signature = None
        if inference_threads not in self.profiles:
            result = verify_runtime(root, inference_threads=inference_threads)
            self.profiles[inference_threads] = result
            self.signature = signature
        return self.profiles[inference_threads]


class LocalScenePilot:
    def __init__(self, packet: Path, data_dir: Path, runtime_root: Path, *, indexer=index_locations_tsv,
                 runtime_verifier=verify_runtime, inference_threads=1, pace='medium', group_size=CHUNK):
        if inference_threads not in (1, 2, 4) or pace not in ('slow', 'medium', 'max') or group_size not in (16, 128):
            raise ValueError('invalid_local_processing_profile')
        self.inference_threads, self.pace, self.group_size = inference_threads, pace, group_size
        self.packet = load_packet(packet)
        data_dir = regular(data_dir, directory=True, missing=True)
        assert_not_live_vision_path(data_dir)
        self.root = data_dir / self.packet['packetId']
        regular(self.root, directory=True, missing=True).mkdir(parents=True, exist_ok=True)
        self.runtime_root = Path(runtime_root)
        self.indexer, self.runtime_verifier = indexer, runtime_verifier
        immutable(self.root / 'packet.json', canonical(self.packet) + b'\n')
        layout = self.root / 'work-layout.json'
        if layout.exists() or group_size != CHUNK:
            immutable(layout, canonical({'groupSize': group_size}) + b'\n')
        self.guard = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.phase, self.message = 'ready', 'Ready to process this Scene batch on your computer.'
        self.completed = 0
        self.error_code = None
        self._refresh_completed()
        if self.completed:
            self.phase, self.message = 'ready', 'Saved work found. Choose Start to check it and continue.'

    def _chunk_path(self, number):
        return self.root / f'part-{number:04d}'

    def _refresh_completed(self):
        count = 0
        for number, start in enumerate(range(0, len(self.packet['rows']), self.group_size)):
            receipt = checkpoint_state(self._chunk_path(number) / 'complete.json')
            if receipt is not None:
                expected = [row['id'] for row in self.packet['rows'][start:start+self.group_size]]
                if receipt.get('packetId') != self.packet['packetId'] or receipt.get('rowIds') != expected:
                    raise ValueError('saved_work_changed')
                count += len(expected)
        self.completed = count
        if count == len(self.packet['rows']):
            self.phase, self.message = 'complete', 'Finished. Your Scene indexes are saved on this computer.'

    def status(self):
        with self.guard:
            return {'phase': self.phase, 'message': self.message, 'completed': self.completed,
                'total': len(self.packet['rows']), 'packetId': self.packet['packetId'],
                'participant': self.packet['participant'], 'outputDirectory': str(self.root),
                'exportAvailable': self.completed > 0 and not (self.thread and self.thread.is_alive()),
                'localOnly': True, 'uploaded': False, 'creditsEarned': 0, 'errorCode': self.error_code}

    def export_results(self):
        """Back up finished groups only, without starting processing or uploading."""
        from .background import single_instance
        from .local_scene_archive import export_saved_results
        with self.guard:
            if self.thread and self.thread.is_alive():
                raise ValueError('pause_before_export')
            with single_instance(self.root):
                self._refresh_completed()
                destination = self.root.parent / 'exports' / (
                    f'VISION-Scenes-{self.packet["packetId"][:12]}-{self.completed}.zip')
                return export_saved_results(self.root, destination)

    def start(self):
        with self.guard:
            if self.thread and self.thread.is_alive():
                return
            self.stop.clear()
            self.error_code = None
            self.phase, self.message = 'processing', 'Checking processing files, then starting Scenes.'
            self.thread = threading.Thread(target=self._work, name='local-scene-pilot', daemon=False)
            self.thread.start()

    def pause(self):
        with self.guard:
            self.stop.set()
            if self.thread and self.thread.is_alive():
                self.phase, self.message = 'pausing', f'Pausing after the current saved group of up to {self.group_size} locations.'

    def close(self):
        self.pause()
        if self.thread:
            self.thread.join(timeout=CHILD_SECONDS + 30)
            if self.thread.is_alive():
                raise RuntimeError('pilot_child_not_stopped')

    def _runner(self, argv, env, cwd):
        if sys.platform == 'darwin':
            argv = ['/usr/bin/nice', '-n', str({'slow':19, 'medium':8, 'max':0}[self.pace]), *argv]
        stem = Path(cwd) / ('native-' + str(time.time_ns()))
        env = {**env, 'TEMP': str(cwd), 'TMP': str(cwd), 'TMPDIR': str(cwd)}
        receipt = {'status': 'STARTED', 'timeoutSeconds': CHILD_SECONDS}
        atomic_json(stem.with_suffix('.exit.json'), receipt)
        try:
            with stem.with_suffix('.stdout.log').open('xb') as out, stem.with_suffix('.stderr.log').open('xb') as err:
                result = run_owned(argv, env=env, cwd=cwd, stdout=out, stderr=err,
                    timeout=60 if 'index-layout' in argv else CHILD_SECONDS,
                    creationflags=(subprocess.NORMAL_PRIORITY_CLASS if self.pace == 'max'
                        else subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == 'nt' else 0)
            receipt.update(status='EXITED', exitCode=result.returncode)
        except BaseException as error:
            receipt.update(status='STOPPED', error=type(error).__name__)
            raise
        finally:
            atomic_json(stem.with_suffix('.exit.json'), receipt)
        def tail(path):
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 1024 * 1024))
                return stream.read().decode('utf-8', errors='replace')
        output, errors = tail(stem.with_suffix('.stdout.log')), tail(stem.with_suffix('.stderr.log'))
        if result.returncode and re.search(r'candidate fetch failed [^\n]*: HTTP 403(?: Forbidden)?(?:\r?\n|$)', errors):
            raise VisionIndexError('imagery_access_denied')
        if result.returncode and re.search(r'candidate fetch failed [^\n]*: HTTP 429(?: Too Many Requests)?(?:\r?\n|$)', errors):
            raise VisionIndexError('imagery_rate_limited')
        return result.returncode, output, errors

    def _verify_saved_part(self, folder, receipt, rows, profile):
        if (receipt.get('runtimeProfile') != profile or receipt.get('packetId') != self.packet['packetId']
                or receipt.get('rowIds') != [row['id'] for row in rows]
                or not isinstance(receipt.get('attempt'), str)
                or receipt['attempt'] not in {p.name for p in folder.glob('attempt-*') if p.is_dir()}):
            raise ValueError('saved_work_changed')
        attempt = regular(folder / receipt['attempt'], directory=True)
        for relative, pin in receipt.get('files', {}).items():
            if relative not in {'locations.tsv', 'input.json', 'index-run.json', 'checkpoint.json',
                                'index/manifest.json', 'index/shard-000000.i8', 'index/shard-000000.mask'}:
                raise ValueError('saved_work_changed')
            if file_identity(regular(attempt / relative)) != pin:
                raise ValueError('saved_work_changed')
        if set(receipt.get('files', {})) != {'locations.tsv', 'input.json', 'index-run.json', 'checkpoint.json',
                                           'index/manifest.json', 'index/shard-000000.i8', 'index/shard-000000.mask'}:
            raise ValueError('saved_work_changed')
        require_complete_index(attempt/'checkpoint.json', attempt/'index', len(rows))

    def _work(self):
        # Hold an OS lock for the full run. Other local-pilot processes cannot
        # write this packet even if a second browser or launcher is opened.
        from .background import single_instance, keep_awake
        try:
            with single_instance(self.root):
                binary, models, profile = self.runtime_verifier(self.runtime_root)
                immutable(self.root/'runtime-profile.json', canonical(profile) + b'\n')
                with keep_awake():
                    for number, start in enumerate(range(0, len(self.packet['rows']), self.group_size)):
                        rows = self.packet['rows'][start:start+self.group_size]
                        folder = self._chunk_path(number)
                        regular(folder, directory=True, missing=True).mkdir(exist_ok=True)
                        receipt = checkpoint_state(folder/'complete.json')
                        if (folder/'complete.json').exists() and receipt is None:
                            raise ValueError('saved_work_changed')
                        if receipt:
                            self._verify_saved_part(folder, receipt, rows, profile)
                            continue
                        if self.stop.is_set():
                            break
                        attempts = sorted(folder.glob('attempt-*'))
                        attempt = attempts[-1] if attempts else folder/'attempt-0001'
                        regular(attempt, directory=True, missing=True).mkdir(exist_ok=True)
                        # Uncheckpointed partial bytes are retained, never reused.
                        if (attempt/'index').exists() and any((attempt/'index').iterdir()) and not (attempt/'checkpoint.json').is_file():
                            attempt = folder / f'attempt-{len(attempts)+1:04d}'
                            regular(attempt, directory=True, missing=True).mkdir(exist_ok=False)
                        immutable(attempt/'locations.tsv', ('\n'.join(row['line'] for row in rows)+'\n').encode())
                        with self.guard:
                            self.message = 'Processing Scenes. Pause keeps completed work.'
                        self.indexer(attempt/'locations.tsv', index_dir=attempt/'index',
                            checkpoint=attempt/'checkpoint.json', output=attempt/'output.json',
                            binary=binary, model_dir=models, pace=self.pace, run_id=self.packet['packetId']+f'-{number}',
                            inference_threads=self.inference_threads, runner=self._runner, use_nice=False)
                        require_complete_index(attempt/'checkpoint.json', attempt/'index', len(rows))
                        if self.runtime_verifier(self.runtime_root)[2] != profile:
                            raise ValueError('pilot_runtime_changed')
                        names = ('locations.tsv', 'input.json', 'index-run.json', 'checkpoint.json',
                                 'index/manifest.json', 'index/shard-000000.i8', 'index/shard-000000.mask')
                        receipt = {'packetId': self.packet['packetId'], 'rowIds': [row['id'] for row in rows],
                            'runtimeProfile': profile, 'attempt': attempt.name,
                            'files': {name: file_identity(regular(attempt/name)) for name in names},
                            'qualityStatus': 'LOCAL_PROVISIONAL', 'uploaded': False, 'creditsEarned': 0}
                        atomic_json(folder/'complete.json', receipt)
                        with self.guard:
                            self._refresh_completed()
                with self.guard:
                    if self.completed == len(self.packet['rows']):
                        atomic_json(self.root/'result.json', {'contract': 'vision-local-scene-result-v1',
                            'packetId': self.packet['packetId'], 'packetSha256': self.packet['payloadSha256'],
                            'locations': self.completed, 'runtimeProfile': profile,
                            'parts': [json.loads((self._chunk_path(i)/'complete.json').read_text())
                                      for i in range((self.completed+self.group_size-1)//self.group_size)],
                            'qualityStatus': 'LOCAL_PROVISIONAL', 'uploaded': False, 'creditsEarned': 0})
                        self.phase, self.message = 'complete', 'Finished. Keep this folder for later contribution.'
                    else:
                        self.phase, self.message = 'paused', 'Paused. Choose Start to continue your saved batch.'
        except BaseException as error:
            code = getattr(error, 'code', None) or (str(error) if isinstance(error, ValueError) else type(error).__name__)
            self.error_code = code
            atomic_json(self.root/('failure-'+str(time.time_ns())+'.json'), {'code': code, 'savedWorkPreserved': True})
            with self.guard:
                self.phase, self.message = 'error', 'Processing stopped. Your work and a local report are saved. Ask the maintainer to review it before restarting.'
