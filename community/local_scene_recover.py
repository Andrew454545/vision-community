"""Owned metadata-only recovery; a stalled filesystem read cannot hang the UI."""
from __future__ import annotations

import faulthandler
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

REPO = Path(os.path.abspath(__file__)).parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0,str(REPO))

from community.local_scene_pilot import atomic_json
from community.mac_starter import regular
from community.process_owner import run_owned

STALL_SECONDS = 20


def watchdog(last, done, cancelled, timeout, terminate, *, dump=faulthandler.dump_traceback):
    while not done.wait(.1):
        if cancelled():
            terminate(0)
            return
        if time.monotonic()-last[0] > timeout:
            # Diagnostics are best effort: an unavailable disk must not block
            # the watchdog itself while it tries to write a stack trace.
            threading.Thread(target=dump,daemon=True).start()
            terminate(79)
            return


def recover(data_dir, roots, library, *, stop):
    return metadata_task(data_dir,roots,library,stop=stop)


def metadata_task(data_dir, roots, library, *, stop, personal=None):
    diagnostic = regular(library.root/'diagnostics'/('recovery-'+str(time.time_ns())),directory=True,missing=True)
    diagnostic.mkdir(mode=0o700,parents=True)
    done = threading.Event()
    with tempfile.TemporaryDirectory(prefix='recover-',dir=library.root) as folder:
        folder = Path(folder)
        marker = folder/'stop'
        value = {'version':1,'dataDir':str(data_dir),
            'sourceRoots':[str(p) for p in roots],'stopFile':str(marker),'timeoutSeconds':120 if personal else STALL_SECONDS}
        if personal is not None:
            value['personal'] = personal
        atomic_json(folder/'request.json',value)
        def cancel():
            while not done.wait(.1):
                if stop.is_set():
                    try:
                        with marker.open('xb') as stream:stream.write(b'stop\n')
                    except OSError:
                        pass
                    return
        watcher = threading.Thread(target=cancel,name='recovery-cancel',daemon=True)
        watcher.start()
        try:
            with (diagnostic/'stdout.log').open('xb') as out,(diagnostic/'stderr.log').open('xb') as err:
                result = run_owned([sys.executable,'-I','-B',str(Path(__file__).absolute()),str(folder/'request.json')],
                    env=dict(os.environ),cwd=REPO,stdout=out,stderr=err,timeout=4*3600)
            if result.returncode == 79:
                raise ValueError('library_recovery_stalled')
            if result.returncode:
                response = folder/'response.json'
                if personal is not None and response.exists():
                    raise ValueError(json.loads(response.read_text()).get('error','personal_queue_failed'))
                raise ValueError('library_recovery_failed')
            if stop.is_set():
                raise ValueError('library_search_cancelled')
            if personal is not None:
                return json.loads(regular(folder/'response.json').read_text())
        finally:
            done.set()


def main():
    path = regular(Path(sys.argv[1]))
    if path.stat().st_size > 64*1024**2:
        raise ValueError('invalid_recovery_request')
    value = json.loads(path.read_text())
    if (not isinstance(value,dict) or set(value) not in ({'version','dataDir','sourceRoots','stopFile','timeoutSeconds'},
            {'version','dataDir','sourceRoots','stopFile','timeoutSeconds','personal'})
            or value['version'] != 1 or not isinstance(value['sourceRoots'],list)
            or not 1 <= len(value['sourceRoots']) <= 32
            or type(value['timeoutSeconds']) not in (int,float) or not math.isfinite(value['timeoutSeconds'])
            or not .1 <= value['timeoutSeconds'] <= 120):
        raise ValueError('invalid_recovery_request')
    data = regular(Path(value['dataDir']),directory=True)
    roots = [regular(Path(p),directory=True,missing=True) for p in value['sourceRoots']]
    marker = regular(Path(value['stopFile']),missing=True)
    from types import SimpleNamespace
    from community.local_scene_library_ui import LibrarySession
    session = LibrarySession(SimpleNamespace(),data,source_roots=roots)
    last,done,cancelled = [time.monotonic()],threading.Event(),threading.Event()
    session.stop = cancelled
    def observe_cancel():
        while not done.wait(.1):
            if marker.exists():
                cancelled.set()
                return
    threading.Thread(target=observe_cancel,daemon=True).start()
    watcher = threading.Thread(target=watchdog,args=(last,done,cancelled.is_set,value['timeoutSeconds'],os._exit),daemon=True)
    watcher.start()
    def tick():
        last[0] = time.monotonic()
    try:
        if 'personal' in value:
            from community.local_scene_personal import prepare_map
            request = value['personal']
            if (not isinstance(request,dict) or set(request) != {'document','runtimeRoot','installationId'}):
                raise ValueError('invalid_personal_request')
            try:
                result = prepare_map(request['document'],data,roots,
                    regular(Path(request['runtimeRoot']),directory=True),request['installationId'])
                atomic_json(path.parent/'response.json',result)
            except ValueError as error:
                atomic_json(path.parent/'response.json',{'error':str(error)})
                raise
        else:
            session._recover_inline(heartbeat=tick)
        print(json.dumps({'ok':True,'locations':session.collection.status()['locations']}),flush=True)
    finally:
        done.set()


if __name__ == '__main__':
    main()
