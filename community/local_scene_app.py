"""One local library window can open a prepared private queue without ZIP handling."""
from __future__ import annotations

import json
from pathlib import Path
import threading

from .background import single_instance,WorkerAlreadyRunning
from .local_scene_campaign import load_manifest,PERSONAL_CONTRACT
from .local_scene_packets import digest
from .local_scene_pilot import atomic_json
from .mac_starter import regular


class LocalSceneApp:
    def __init__(self,data_dir,runtime_root,*,engine_factory=None):
        self.data_dir = regular(data_dir,directory=True)
        self.root = regular(self.data_dir/'library',directory=True,missing=True)
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.runtime_root = Path(runtime_root)
        self.packet = {'packetId':digest(['local-library',str(self.root)])}
        self.guard = threading.RLock()
        self.engine,self.engine_lock = None,None
        self.engine_factory = engine_factory
        self.on_completed_pilot = None
        self.window_url = None
        self.queue_name = ''

    @property
    def thread(self):
        return self.engine.thread if self.engine else None

    @property
    def startup_app(self):
        if self.engine is None:
            raise ValueError('open_personal_queue_to_process')
        return self.engine

    def status(self):
        with self.guard:
            if self.engine:
                return {**self.engine.status(),'activePacketId':self.engine.packet['packetId'],
                    'packetId':self.packet['packetId'],'localApp':True,'queueName':self.queue_name}
            return {'phase':'ready','participant':'My library','completed':0,'total':0,
                'packetId':self.packet['packetId'],'outputDirectory':str(self.root),
                'message':'Add an MMA map in My library, then choose Open my queue here.',
                'exportAvailable':False,'libraryOnly':True,'localApp':True,'localOnly':True}

    def open_personal_queue(self,path,*,data_dir):
        """Open only, never start inference or change login registration here."""
        with self.guard:
            if self.thread and self.thread.is_alive():
                raise ValueError('pause_processing_before_search')
            path = regular(path)
            manifest = load_manifest(path)
            if manifest['contract'] != PERSONAL_CONTRACT:
                raise ValueError('personal_queue_required')
            target = regular(Path(data_dir)/manifest['sha256'],directory=True,missing=True)
            if self.engine and self.engine.root == target:
                return
            owner = regular(target/'window-owner',directory=True,missing=True)
            owner.mkdir(parents=True,exist_ok=True,mode=0o700)
            claimed = single_instance(owner)
            try:
                claimed.__enter__()
            except WorkerAlreadyRunning:
                raise ValueError('queue_open_elsewhere') from None
            engine = None
            try:
                from .local_scene_unattended import LocalSceneCampaign
                engine = (self.engine_factory or LocalSceneCampaign)(path,data_dir,self.runtime_root)
                engine.on_completed_pilot = self.on_completed_pilot
                metadata = regular(engine.root/'personal-map.json')
                if metadata.stat().st_size>64*1024**2:
                    raise ValueError('personal_map_size_limit')
                name = json.loads(metadata.read_text()).get('name','My MMA map')
                if not isinstance(name,str) or len(name)>300:
                    raise ValueError('personal_map_metadata_required')
                # Opening is deliberately paused, even if an old queue had
                # automatic-resume intent. The user chooses Start explicitly.
                engine.pause()
                if self.window_url:
                    atomic_json(engine.root/'window.json',{'url':self.window_url,'packetId':engine.packet['packetId']})
                if self.engine:
                    self.engine.pause()
                self._retire()
                self.engine,self.engine_lock,self.queue_name = engine,claimed,name
            except BaseException:
                if engine:
                    engine.close()
                claimed.__exit__(None,None,None)
                raise

    def _retire(self):
        if self.engine:
            self.engine.close()
            alias = regular(self.engine.root/'window.json',missing=True)
            if alias.exists() and self.window_url:
                value = json.loads(alias.read_text())
                if value == {'url':self.window_url,'packetId':self.engine.packet['packetId']}:
                    alias.unlink()
        if self.engine_lock:
            self.engine_lock.__exit__(None,None,None)
        self.engine,self.engine_lock = None,None

    def start(self):
        return self.startup_app.start()

    def pause(self):
        with self.guard:
            if self.engine:
                self.engine.pause()

    def configure(self,value):
        return self.startup_app.configure(value)

    def export_results(self):
        return self.startup_app.export_results()

    def close(self):
        with self.guard:
            self._retire()
