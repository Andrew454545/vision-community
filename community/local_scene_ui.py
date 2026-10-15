"""A private local Scene pilot window; no remote API or account."""
from __future__ import annotations
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import re
import urllib.request
import webbrowser

REPO = Path(os.path.abspath(__file__)).parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from community.local_scene_pilot import LocalScenePilot
from community.vision_index import community_support_root

PAGE = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VISION • Local Scenes</title><style>
body{font:17px system-ui,sans-serif;background:#101924;color:#eff5ff;margin:0;padding:8vh 24px}
main{max-width:640px;margin:auto}h1{font-size:38px}p{line-height:1.6;color:#c4d2e3}
.card{background:#1b293b;padding:25px;border-radius:16px;margin:24px 0}
progress{width:100%;height:20px;accent-color:#68cdbb}button{font:inherit;padding:12px 24px;
border:0;border-radius:9px;background:#79decc;color:#101924;margin:12px 8px 0 0;cursor:pointer}
button:disabled{opacity:.45;cursor:default}#folder{overflow-wrap:anywhere;font-size:14px}
small{color:#a5b6ce}</style><main><small>VISION · INVITED LOCAL PILOT</small>
<h1>Process Scenes on your computer</h1>
<p>Your assigned locations are processed here. Your indexes stay on this computer
until a later contribution step. No account is needed.</p>
<div class="card"><p id="batch">Loading your assigned batch…</p>
<progress id="bar" max="1" value="0"></progress><p id="count"></p><p id="message"></p>
<button id="start" disabled>Start / Resume</button><button id="pause" disabled>Pause</button>
<button id="exit">Exit</button></div>
<p>Start uses your CPU and internet connection to retrieve imagery. Keep the computer
plugged in. Pause finishes the current group of up to 16 locations; it can take several minutes.</p>
<p>Closing this browser tab keeps processing running. Use Pause or Exit to stop.</p>
<p>Saved work folder:</p><p id="folder"></p>
<button id="save" disabled>Save results (.zip)</button><p id="backup-message" role="status"></p>
<p>Pause first to save a portable backup of finished groups. Your original folder is kept.
A partial backup does not include unfinished locations. Keep your packet and original folder to resume.</p>
<small>Local pilot results await later validation. Uploads, search and credit earning are not enabled.</small>
</main><script nonce="NONCE">
const token=location.hash.slice(1);history.replaceState(null,'',location.pathname);
let ended=false,saving=false;
async function request(path,method='GET'){
const r=await fetch(path,{method,headers:{Authorization:'Bearer '+token},cache:'no-store'});
if(!r.ok)throw Error('local_window_unavailable');return r.json();}
async function update(){if(ended)return;try{const s=await request('/api/status');
document.getElementById('batch').textContent='Assigned to '+s.participant+' · '+s.total+' locations';
document.getElementById('bar').max=s.total;document.getElementById('bar').value=s.completed;
document.getElementById('count').textContent=s.completed+' of '+s.total+' saved';
document.getElementById('message').textContent=s.message;document.getElementById('folder').textContent=s.outputDirectory;
document.getElementById('start').disabled=saving||['processing','pausing','complete'].includes(s.phase);
document.getElementById('pause').disabled=s.phase!=='processing';
document.getElementById('save').disabled=saving||!s.exportAvailable;
}catch(e){document.getElementById('message').textContent='This local window is unavailable. Reopen the pilot launcher to continue your saved work.';
document.getElementById('start').disabled=true;document.getElementById('pause').disabled=true;
document.getElementById('save').disabled=true;}}
document.getElementById('save').onclick=async()=>{
if(saving||ended)return;saving=true;
document.getElementById('save').disabled=true;document.getElementById('start').disabled=true;
document.getElementById('exit').disabled=true;
document.getElementById('backup-message').textContent='Checking finished groups and preparing your backup…';
try{const r=await fetch('/api/export',{method:'POST',headers:{Authorization:'Bearer '+token},cache:'no-store'});
if(!r.ok)throw Error('export_unavailable');
const blob=await r.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
link.href=url;link.download='VISION-Scene-results.zip';document.body.appendChild(link);link.click();link.remove();
setTimeout(()=>URL.revokeObjectURL(url),60000);
document.getElementById('backup-message').textContent='Your results backup is ready. Check your browser downloads. Keep the original folder to resume; nothing was uploaded.';
}catch(e){document.getElementById('backup-message').textContent='The backup could not be made. Pause processing first. If it still fails, keep your original folder and ask the maintainer for help.';}
finally{saving=false;document.getElementById('exit').disabled=ended;await update();}};
for(const action of ['start','pause','exit'])document.getElementById(action).onclick=async()=>{
try{await request('/api/'+action,'POST');if(action==='exit'){ended=true;
document.getElementById('message').textContent='Exiting after the current group. Your saved work is kept.';
for(const el of document.querySelectorAll('button'))el.disabled=true;}else await update();}
catch(e){document.getElementById('message').textContent='The action could not finish. Your saved work is kept.';}};
update();setInterval(update,2000);
</script></html>'''


def handler_for(app, token):
    nonce = secrets.token_hex(16)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status, body, mime='application/json', *, download=False):
            body = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            if download:
                self.send_header('Content-Disposition', 'attachment; filename="VISION-Scene-results.zip"')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; connect-src 'self'; style-src 'unsafe-inline'; script-src 'nonce-"+nonce+"'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, *, action=False):
            origin = f'http://127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != origin.removeprefix('http://'):
                return False
            if action and self.headers.get('Origin') != origin:
                return False
            return hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+token)

        def do_GET(self):
            if self.path == '/' and self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}':
                self.send(200, PAGE.replace('NONCE', nonce).encode(), 'text/html; charset=utf-8')
            elif self.path == '/api/status' and self.allowed():
                self.send(200, app.status())
            else:
                self.send(403, {'error': 'local_access_denied'})

        def do_POST(self):
            if (not self.allowed(action=True) or self.headers.get('Transfer-Encoding') is not None
                    or self.headers.get('Content-Length', '0') != '0'):
                self.send(403, {'error':'local_access_denied'})
                self.close_connection = True
                return
            if self.path not in ('/api/start', '/api/pause', '/api/exit', '/api/export'):
                self.send(404, {'error':'unknown_action'})
                return
            try:
                if self.path == '/api/export':
                    from community.mac_starter import regular
                    archive = app.export_results()
                    path = regular(Path(archive['path']))
                    if path.stat().st_size > 64 * 1024 * 1024:
                        raise ValueError('backup_too_large')
                    self.send(200, path.read_bytes(), 'application/zip', download=True)
                    return
                if self.path == '/api/start':
                    app.start()
                else:
                    app.pause()
                self.send(200, {'ok':True})
                if self.path == '/api/exit':
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
            except Exception:
                self.send(409, {'error':'local_action_failed'})
    return Handler


def reopen_existing(app):
    from community.mac_starter import regular
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None
    try:
        path=regular(app.root/'window.json')
        if path.stat().st_size>1024:return False
        saved=json.loads(path.read_text())
        match=re.fullmatch(r'http://127\.0\.0\.1:([0-9]{1,5})/#([a-f0-9]{64})',saved['url'])
        if not match or not 1<=int(match[1])<=65535 or saved['packetId']!=app.packet['packetId']:return False
        request=urllib.request.Request(f'http://127.0.0.1:{match[1]}/api/status',headers={'Authorization':'Bearer '+match[2]})
        # Ignore system HTTP proxies for this exact loopback-only request.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with opener.open(request,timeout=2) as response:
            body=response.read(4097)
            if len(body)>4096 or json.loads(body).get('packetId')!=app.packet['packetId']:return False
        webbrowser.open(saved['url'])
        return True
    except (OSError,ValueError,KeyError,TypeError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', required=True, type=Path)
    parser.add_argument('--data-dir', type=Path, default=community_support_root()/'local-scene-pilot')
    parser.add_argument('--runtime-root', type=Path, default=community_support_root()/'desktop/runtime')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check-only', action='store_true', help='validate this packet without setup or processing')
    parser.add_argument('--reopen-only', action='store_true', help='reopen the existing local window without starting a server')
    args = parser.parse_args()
    if args.check_only:
        from community.local_scene_packets import load_packet
        packet=load_packet(args.packet)
        print(json.dumps({'ok':True,'locations':len(packet['rows']),'localOnly':True}))
        return
    app = LocalScenePilot(args.packet, args.data_dir, args.runtime_root)
    if not args.no_browser and reopen_existing(app):
        return
    if args.reopen_only:
        raise RuntimeError('local_pilot_window_unavailable')
    token = secrets.token_hex(32)
    server = ThreadingHTTPServer(('127.0.0.1',0), handler_for(app, token))
    server.daemon_threads = True
    url = f'http://127.0.0.1:{server.server_port}/#{token}'
    from community.local_scene_pilot import atomic_json
    atomic_json(app.root/'window.json',{'url':url,'packetId':app.packet['packetId']})
    if not args.no_browser:
        webbrowser.open(url)
    print('VISION local pilot is open. Use its Start and Pause buttons.', flush=True)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == '__main__':
    main()
