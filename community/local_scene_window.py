"""Verified optional native view for the existing authenticated loopback app."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
import webbrowser

REPO = Path(os.path.abspath(__file__)).parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0,str(REPO))

from community.local_scene_pilot import atomic_json,immutable
from community.mac_starter import regular,pin
from community.process_owner import run_owned

NAMES = {
    'darwin-arm64': {'VISION Desktop Window'},
    'windows-x86_64': {'VISION Desktop Window.exe','Microsoft.Web.WebView2.Core.dll',
        'Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll','LICENSE.txt'},
}


def host_inventory(folder,expected=None):
    folder = regular(folder,directory=True)
    path = regular(folder/'manifest.json')
    if path.stat().st_size>16384:
        raise ValueError('native_window_inventory_changed')
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if expected is not None and sha != expected:
        raise ValueError('native_window_inventory_changed')
    value = json.loads(raw)
    if (not isinstance(value,dict) or set(value) != {'version','platform','executable','files'}
            or value['version'] != 1 or value['platform'] not in NAMES
            or set(value['files']) != NAMES[value['platform']]
            or value['executable'] != ('VISION Desktop Window' + ('.exe' if value['platform']=='windows-x86_64' else ''))):
        raise ValueError('native_window_inventory_changed')
    # Extra config files or assemblies can affect native startup before Main.
    # This sealed folder has no mutable files; browser data lives elsewhere.
    if {entry.name for entry in folder.iterdir()} != {*value['files'],'manifest.json'}:
        raise ValueError('native_window_inventory_changed')
    for name,identity in value['files'].items():
        if pin(folder/name) != identity:
            raise ValueError('native_window_file_changed')
    return value,raw,sha


def provision(source,root):
    """Caller first verifies the sealed release inventory in its native launcher."""
    source,root = regular(source,directory=True),regular(root,directory=True)
    inventory = regular(source/'release-inventory.json')
    if inventory.stat().st_size>1024**2:
        raise ValueError('native_window_inventory_changed')
    entry = json.loads(inventory.read_text())['files']['native-window/manifest.json']
    value,raw,sha = host_inventory(source/'native-window',entry['sha256'])
    if entry['bytes'] != len(raw):
        raise ValueError('native_window_inventory_changed')
    target = regular(root/'native-windows'/sha,directory=True,missing=True)
    for name in value['files']:
        immutable(target/name,regular(source/'native-window'/name).read_bytes())
    immutable(target/'manifest.json',raw)
    if value['platform']=='darwin-arm64':
        (target/value['executable']).chmod(0o755)
    host_inventory(target,sha)
    return target


class NativeWindow:
    def __init__(self,folder,app,server,url):
        self.folder,self.app,self.server,self.url = folder,app,server,url
        self.guard = threading.RLock()
        self.active,self.counter,self.thread = False,0,None
        self.closing,self.pid = threading.Event(),None

    def show(self):
        with self.guard:
            if not self.active:
                return False
            self.counter += 1
            return True

    def state(self):
        with self.guard:
            return {'active':self.active,'showCounter':self.counter}

    def start(self):
        if self.folder is None:
            webbrowser.open(self.url)
            return
        self.active = True
        self.thread = threading.Thread(target=self._run,name='vision-native-window',daemon=False)
        self.thread.start()

    def _run(self):
        try:
            folder = regular(self.folder,directory=True)
            if not re.fullmatch('[a-f0-9]{64}',folder.name):
                raise ValueError('native_window_inventory_changed')
            value,_,_ = host_inventory(folder,folder.name)
            platform = 'windows-x86_64' if os.name=='nt' else 'darwin-arm64' if sys.platform=='darwin' else ''
            if value['platform'] != platform:
                raise ValueError('native_window_platform_mismatch')
            diagnostics = regular(self.app.root/'native-window-diagnostics',directory=True,missing=True)
            diagnostics.mkdir(mode=0o700,exist_ok=True)
            stem = diagnostics/str(time.time_ns())
            connection = stem.with_suffix('.connection.json')
            atomic_json(connection,{'version':1,'url':self.url})
            try:
                with stem.with_suffix('.stdout.log').open('xb') as out,stem.with_suffix('.stderr.log').open('xb') as err:
                    result = run_owned([str(folder/value['executable']),'--connection',str(connection)],
                        env=dict(os.environ),cwd=folder,stdout=out,stderr=err,timeout=None,on_owned=self._owned)
                with self.guard:
                    self.pid = None
                if result.returncode == 23:
                    # Missing WebView runtime is an optional-view failure, not
                    # permission to download/install software automatically.
                    self.active = False
                    if not self.closing.is_set():
                        webbrowser.open(self.url)
                elif result.returncode:
                    raise ValueError('native_window_failed')
                else:
                    if not self.closing.is_set():
                        self.app.pause()
                        self.server.shutdown()
            finally:
                connection.unlink(missing_ok=True)
        except Exception as error:
            self.active = False
            try:
                atomic_json(self.app.root/'native-window-failure.json',{
                    'code':str(error) if re.fullmatch('[a-z_]{1,70}',str(error)) else 'native_window_failed',
                    'errorClass':type(error).__name__,'savedWorkPreserved':True})
            except Exception:
                # A full or unwritable disk must not suppress the working
                # browser fallback. Do not claim that a report was saved.
                pass
            # An invalid host never executes. The authenticated browser remains
            # a complete working interface, so do not abandon saved work.
            if not self.closing.is_set():
                webbrowser.open(self.url)
        finally:
            self.active = False
            with self.guard:
                self.pid = None

    def _owned(self,pid):
        with self.guard:
            self.pid=pid

    def close(self):
        self.closing.set()
        if self.thread:
            self.thread.join(15)
            if self.thread.is_alive():
                with self.guard:
                    if self.pid is not None:
                        try:
                            os.kill(self.pid,signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                self.thread.join(10)
                if self.thread.is_alive():
                    raise RuntimeError('native_window_not_stopped')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--provision-from',required=True,type=Path)
    parser.add_argument('--root',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps({'nativeWindowDirectory':str(provision(args.provision_from,args.root))}))


if __name__=='__main__':
    main()
