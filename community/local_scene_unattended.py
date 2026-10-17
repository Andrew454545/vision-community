"""Local campaign supervision. Never leases, uploads, charges, or runs a cloud model."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time

from .background import ProcessingSchedule, single_instance
from .local_scene_campaign import campaign_packet, load_manifest
from .local_scene_packets import canonical, digest
from .local_scene_pilot import CheckedRuntime, LocalScenePilot, atomic_json, immutable, verify_runtime
from .local_scene_qualification import validate_approval
from .mac_starter import regular
from .vision_index import assert_not_live_vision_path


def on_battery():
    if sys.platform == 'darwin':
        result = subprocess.run(['/usr/bin/pmset', '-g', 'batt'], capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise ValueError('power_status_unavailable')
        return "'Battery Power'" in result.stdout
    if os.name == 'nt':
        import ctypes
        class Power(ctypes.Structure):
            _fields_ = [('ac', ctypes.c_ubyte), ('flags', ctypes.c_ubyte), ('percent', ctypes.c_ubyte),
                        ('reserved', ctypes.c_ubyte), ('life', ctypes.c_ulong), ('full', ctypes.c_ulong)]
        power = Power()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power)) or power.ac == 255:
            raise ValueError('power_status_unavailable')
        return power.ac == 0
    return False


class LocalSceneCampaign:
    def __init__(self, manifest_path, data_dir, runtime_root, *, installation_id=None,
                 pilot_factory=LocalScenePilot, runtime_verifier=verify_runtime,
                 clock=datetime.now, battery=on_battery, disk=shutil.disk_usage):
        self.path = regular(manifest_path)
        self.manifest = load_manifest(self.path)
        from .local_scene_campaign import PERSONAL_CONTRACT
        self.personal_only = self.manifest['contract'] == PERSONAL_CONTRACT
        data_dir = regular(data_dir, directory=True, missing=True)
        assert_not_live_vision_path(data_dir)
        self.root = regular(Path(data_dir) / self.manifest['sha256'], directory=True, missing=True)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        immutable(self.root / 'campaign.json', canonical(self.manifest) + b'\n')
        # Login agents read the private application folder, never a Downloads/
        # Documents packet selected through an interactive file picker. Stage
        # metadata once, bounded packet by packet; retain a partial import on
        # interruption and publish the completion marker last.
        staged = self.root / 'assigned-input-complete.json'
        expected = canonical({'campaignSha256': self.manifest['sha256'],
                              'packets': len(self.manifest['packets'])}) + b'\n'
        if staged.exists():
            if regular(staged).read_bytes() != expected:
                raise ValueError('saved_campaign_input_changed')
        else:
            for i, entry in enumerate(self.manifest['packets']):
                source = campaign_packet(self.path.parent, self.manifest, i)
                target = regular(self.root / entry['path'], missing=True)
                if not target.exists() and disk(self.root).free < 5 * 1024**3 + source.stat().st_size:
                    raise ValueError('campaign_import_storage_required')
                immutable(target, source.read_bytes())
            immutable(staged, expected)
        if self.personal_only:
            metadata = regular(self.path.parent/'personal-map.json')
            if metadata.stat().st_size>64*1024**2:
                raise ValueError('personal_map_size_limit')
            immutable(self.root/'personal-map.json',metadata.read_bytes())
        self.path = self.root / 'campaign.json'
        identity = regular(Path(data_dir) / 'installation-id.json', missing=True)
        if installation_id is not None:
            immutable(identity, canonical({'id': installation_id}) + b'\n')
        if not identity.exists():
            immutable(identity, canonical({'id': secrets.token_hex(32)}) + b'\n')
        self.installation_id = json.loads(identity.read_text())['id']
        self.runtime_root = Path(runtime_root)
        self.pilot_factory = pilot_factory
        self.runtime_verifier = CheckedRuntime() if runtime_verifier is verify_runtime else runtime_verifier
        self.clock, self.battery, self.disk = clock, battery, disk
        self.guard = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.current = None
        self.packet = {'packetId': self.manifest['sha256']}
        self.phase, self.message = 'ready', 'Choose your day and night speeds, then Start.'
        self.settings_path = self.root / 'settings.json'
        self.settings = {'dayPace': 'medium', 'nightPace': 'max', 'dayStart': '06:00',
                         'nightStart': '00:00', 'enabled': False, 'pauseOnBattery': True}
        if self.settings_path.exists():
            self.settings = self._settings(json.loads(self.settings_path.read_text()))
        if not self.settings_path.exists():
            self._save_settings()
        with self._db() as db:
            saved = db.execute('SELECT value FROM meta WHERE key="manifest"').fetchone()
            if saved and saved[0] != self.manifest['sha256']:
                raise ValueError('campaign_progress_changed')
            db.execute('INSERT OR IGNORE INTO meta VALUES("manifest",?)', (self.manifest['sha256'],))
            db.executemany('INSERT OR IGNORE INTO work(ordinal,locations) VALUES(?,?)',
                           ((i, p['locations']) for i, p in enumerate(self.manifest['packets'])))
        self._profiles()  # Fail before processing if this installation/profile was not approved.

    def _db(self):
        path = regular(self.root / 'progress.sqlite', missing=True)
        db = sqlite3.connect(path, timeout=10)
        db.executescript('''CREATE TABLE IF NOT EXISTS work(ordinal INTEGER PRIMARY KEY,
            locations INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', failures INTEGER NOT NULL DEFAULT 0,
            retry REAL NOT NULL DEFAULT 0, profile TEXT, error TEXT);
            CREATE INDEX IF NOT EXISTS work_next ON work(status,retry,ordinal);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS totals(id INTEGER PRIMARY KEY CHECK(id=1),completed INTEGER NOT NULL);
            INSERT OR IGNORE INTO totals VALUES(1,0);''')
        return db

    def _settings(self, value):
        expected = {'dayPace', 'nightPace', 'dayStart', 'nightStart', 'enabled', 'pauseOnBattery'}
        if (not isinstance(value, dict) or set(value) != expected
                or type(value['enabled']) is not bool or type(value['pauseOnBattery']) is not bool):
            raise ValueError('invalid_campaign_settings')
        ProcessingSchedule(value['dayPace'], value['nightPace'], value['dayStart'], value['nightStart'])
        return value

    def _save_settings(self):
        atomic_json(self.settings_path, self.settings)

    def configure(self, value):
        with self.guard:
            self.settings = self._settings({**self.settings, **value})
            self._save_settings()

    def _profiles(self):
        profiles = {}
        for approval in self.manifest['approvals']:
            threads = approval['inferenceThreads']
            binary, models, profile = self.runtime_verifier(self.runtime_root, inference_threads=threads)
            if self.personal_only:
                from .local_scene_personal import validate_personal_approval
                validate_personal_approval(approval,self.installation_id,profile)
            else:
                validate_approval(approval, self.installation_id, profile)
            profiles[threads] = (binary, models, profile)
        if 1 not in profiles:
            raise ValueError('baseline_scene_approval_required')
        return profiles

    def status(self):
        with self.guard, self._db() as db:
            current = self.current.status() if self.current else {}
            completed = db.execute('SELECT completed FROM totals WHERE id=1').fetchone()[0]
            held = db.execute('SELECT count(*) FROM work WHERE status="held"').fetchone()[0]
            startup = regular(self.root / 'startup.json', missing=True)
            startup_enabled = False
            if startup.exists() and startup.stat().st_size <= 16 * 1024:
                startup_enabled = json.loads(startup.read_text()).get('enabled') is True
            return {'phase': self.phase, 'message': current.get('message',self.message), 'completed': completed,
                    'total': self.manifest['locations'], 'packetId': self.packet['packetId'],
                    'participant': self.manifest['participant'], 'outputDirectory': str(self.root),
                    'exportAvailable': completed > 0 and not (self.thread and self.thread.is_alive()),
                    'localOnly': True, 'uploaded': False, 'creditsEarned': 0,
                    'campaign': True, 'personalOnly':self.personal_only, 'settings': dict(self.settings), 'heldPackets': held, 'startupEnabled': startup_enabled,
                    'qualifiedThreads': sorted(a['inferenceThreads'] for a in self.manifest['approvals'])}

    def start(self):
        with self.guard:
            if self.thread and self.thread.is_alive():
                return
            self._profiles()
            with self._db() as db:
                db.execute('UPDATE work SET status="pending",failures=0,retry=0 WHERE status="held"')
            self.settings['enabled'] = True
            self._save_settings()
            self.stop.clear()
            self.phase = 'processing'
            self.thread = threading.Thread(target=self._work, name='local-scene-campaign', daemon=False)
            self.thread.start()

    def resume_automatically(self):
        if self.settings['enabled']:
            self.start()

    def pause(self):
        with self.guard:
            self.settings['enabled'] = False
            self._save_settings()
            self.stop.set()
            if self.current:
                self.current.pause()
            self.phase, self.message = 'pausing', 'Pausing after the current saved group. Your queue is kept.'

    def close(self):
        # Closing an owned process preserves automatic-resume intent. Explicit Pause/Exit clears it.
        self.stop.set()
        if self.current:
            self.current.close()
        if self.thread:
            self.thread.join(650)
            if self.thread.is_alive():
                raise RuntimeError('campaign_child_not_stopped')

    def _work(self):
        try:
            with single_instance(self.root):
                while not self.stop.is_set():
                    if self.settings['pauseOnBattery'] and self.battery():
                        self.phase, self.message = 'waiting_for_power', 'Waiting for mains power. Work will resume automatically.'
                        self.stop.wait(30)
                        continue
                    if self.disk(self.root).free < 5 * 1024**3:
                        self.phase, self.message = 'low_disk', 'Free some disk space, then choose Resume. Your indexes are kept.'
                        return
                    schedule = ProcessingSchedule(self.settings['dayPace'], self.settings['nightPace'],
                                                  self.settings['dayStart'], self.settings['nightStart'])
                    pace = schedule.pace_at(self.clock())
                    if pace == 'pause':
                        self.phase, self.message = 'waiting_for_schedule', 'Waiting for your next processing period.'
                        self.stop.wait(30)
                        continue
                    profiles = self._profiles()
                    threads = max(profiles) if pace == 'max' else 1
                    with self._db() as db:
                        pending = db.execute('SELECT ordinal,locations,failures FROM work WHERE status="pending" AND retry<=? '
                                             'ORDER BY retry,ordinal LIMIT 1', (time.time(),)).fetchone()
                        unfinished = db.execute('SELECT 1 FROM work WHERE status!="complete" LIMIT 1').fetchone()
                    if not pending:
                        if not unfinished:
                            self.phase, self.message = 'complete', 'Your allocation is finished. All indexes are saved locally.'
                            self.settings['enabled'] = False
                            self._save_settings()
                            return
                        with self._db() as db:
                            pending_count = db.execute('SELECT count(*) FROM work WHERE status="pending"').fetchone()[0]
                        if not pending_count:
                            self.phase, self.message = 'needs_attention', 'Some groups failed repeatedly. Work is kept. Choose Resume to retry after fixing the connection or runtime.'
                            return
                        self.phase, self.message = 'waiting_to_retry', 'Waiting before retrying interrupted work. Saved indexes are kept.'
                        self.stop.wait(30)
                        continue
                    i, count, failures = pending
                    path = campaign_packet(self.path.parent, self.manifest, i)
                    profile = profiles[threads][2]
                    work_root = self.root / 'work' / profile['sha256']
                    def verified(root):
                        return self.runtime_verifier(root, inference_threads=threads)
                    # Retain the exact saved layout of older work. New queues
                    # use16-location saved groups so download pauses are useful.
                    group_size = 16
                    layout = regular(work_root/self.manifest['packets'][i]['packetId']/'work-layout.json',missing=True)
                    if layout.exists():
                        saved_layout = json.loads(layout.read_text())
                        if set(saved_layout) != {'groupSize'} or type(saved_layout['groupSize']) is not int or saved_layout['groupSize'] not in (16,128):
                            raise ValueError('saved_work_changed')
                        group_size = saved_layout['groupSize']
                    pilot = self.pilot_factory(path, work_root, self.runtime_root,
                        runtime_verifier=verified, inference_threads=threads, pace=pace, group_size=group_size)
                    with self.guard:
                        if self.stop.is_set():
                            break
                        self.current = pilot
                        self.phase, self.message = 'processing', f'Processing your queue using {threads} qualified inference thread(s).'
                        pilot.start()
                    while pilot.thread.is_alive():
                        if self.stop.wait(.25):
                            pilot.pause()
                            break
                    pilot.close()
                    state = pilot.status()
                    if state.get('errorCode') in ('imagery_access_denied', 'imagery_rate_limited'):
                        # A provider refusal applies to the connection, not just
                        # this panorama. Stop instead of marching through the
                        # whole allocation and repeatedly requesting denied data.
                        self.current = None
                        with self.guard:
                            self.settings['enabled'] = False
                            self._save_settings()
                            self.phase = 'imagery_unavailable'
                            self.message = ('Google refused or limited imagery access on this connection. '
                                'Processing is stopped and your queue is saved. Resume after normal imagery access is available.')
                        return
                    if state['phase'] == 'complete':
                        with self._db() as db:
                            changed = db.execute('UPDATE work SET status="complete",profile=?,error=NULL WHERE ordinal=? AND status!="complete"',
                                                 (profile['sha256'], i)).rowcount
                            if changed:
                                db.execute('UPDATE totals SET completed=completed+? WHERE id=1', (count,))
                        callback = getattr(self,'on_completed_pilot',None)
                        if callback:
                            callback(pilot.root)
                    elif not self.stop.is_set():
                        failures += 1
                        with self._db() as db:
                            db.execute('UPDATE work SET failures=?,retry=?,status=?,error=? WHERE ordinal=?',
                                (failures, time.time() + min(3600, 60 * 2**min(failures-1,6)),
                                 'held' if failures >= 5 else 'pending', 'local_processing_failed', i))
                    self.current = None
                    if getattr(pilot,'network_execution',None) is not None and not self.stop.is_set():
                        with self._db() as db:
                            unfinished = db.execute('SELECT 1 FROM work WHERE status!="complete" LIMIT 1').fetchone()
                        if not unfinished:
                            continue
                        from .local_scene_transport import GROUP_PAUSE_SECONDS
                        self.message = 'Waiting briefly before the next imagery group. Your saved work is kept.'
                        self.stop.wait(GROUP_PAUSE_SECONDS)
        except Exception as error:
            self.phase, self.message = 'failed', 'Processing stopped safely. Check the local diagnostic and resume after repair.'
            atomic_json(self.root / 'failure.json', {'errorClass': type(error).__name__, 'savedWorkPreserved': True})
        finally:
            if self.stop.is_set():
                self.phase, self.message = 'paused', 'Paused. Your queue and completed indexes are saved.'

    def export_results(self):
        """One action exports every completed packet, keeping memory bounded.

        The collection is a local folder of independently verifiable ZIPs. A
        browser must never buffer a many-GB campaign download. Interrupted saves
        keep completed ZIPs; the collection manifest is published last.
        """
        with self.guard:
            if self.thread and self.thread.is_alive():
                raise ValueError('pause_before_export')
            with single_instance(self.root), self._db() as db:
                rows = db.execute('SELECT ordinal,profile FROM work WHERE status="complete" ORDER BY ordinal').fetchall()
                if not rows:
                    raise ValueError('no_completed_scene_work')
                from .local_scene_archive import export_saved_results
                destination = regular(self.root / 'exports', directory=True, missing=True)
                destination.mkdir(parents=True, exist_ok=True)
                exports, count, size = [], 0, 0
                for i, profile in rows:
                    campaign_packet(self.path.parent, self.manifest, i)
                    target = regular(destination / f'{i:06d}.zip', missing=True)
                    if not target.exists() and self.disk(destination).free < 5 * 1024**3 + 64 * 1024**2:
                        raise ValueError('insufficient_backup_space')
                    root = self.root / 'work' / profile / self.manifest['packets'][i]['packetId']
                    result = export_saved_results(root, target, portable=True)
                    exports.append({'path': target.name, 'packetId': self.manifest['packets'][i]['packetId'],
                        'runtimeProfileSha256': profile, 'locations': result['locations'],
                        'sha256': result['sha256'], 'bytes': result['bytes']})
                    count += result['locations']
                    size += result['bytes']
                collection = {'contract': 'vision-personal-scene-collection-v1' if self.personal_only else 'vision-local-scene-collection-v1', 'campaignSha256': self.manifest['sha256'],
                    'locations': count, 'total': self.manifest['locations'], 'complete': count == self.manifest['locations'],
                    'archives': exports, 'uploaded': False, 'qualityStatus': 'LOCAL_PROVISIONAL'}
                checksum = digest(collection)
                immutable(destination / f'collection-{checksum}.json', canonical(collection) + b'\n')
                return {'kind': 'local_directory', 'path': str(destination), 'locations': count,
                        'total': self.manifest['locations'], 'complete': collection['complete'],
                        'sha256': checksum, 'bytes': size, 'archives': len(exports)}
