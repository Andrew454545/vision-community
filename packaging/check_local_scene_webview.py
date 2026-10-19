"""Windows-only hidden WebView2 integration using the real local page, no inference."""
from __future__ import annotations

import argparse
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import threading
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from community.local_scene_app import LocalSceneApp
from community.local_scene_library_ui import LibrarySession
from community.local_scene_ui import handler_for
from community.process_owner import run_owned

HARNESS = r'''
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

static class RenderChecks {
    static string root;
    static int result=3;
    static bool running;
    static Stopwatch clock=Stopwatch.StartNew();
    static void End(SceneWindow form,int code) {
        result=code;
        typeof(SceneWindow).GetField("stopping",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(form,true);
        form.Close();
    }
    static async Task Check(SceneWindow form,WebView2 web) {
        if(running)return;running=true;
        try {
            // All requests here are same-origin reads. No start, queue, setup or model path is invoked.
            await web.CoreWebView2.ExecuteScriptAsync(@"window.renderCheck='pending';
(async()=>{try {
const s=await request('/api/library');
const unauth=await fetch('/api/status',{cache:'no-store'});
await update(); await document.fonts.ready;
window.renderCheck=JSON.stringify({
localOnly:s.localOnly===true,
unauthDenied:unauth.status===403,
personalMap:document.getElementById('personal-map-open')!==null,
photoSupport:typeof createImageBitmap==='function',
tokenRemoved:location.hash==='',
pageLayout:document.querySelector('main').getBoundingClientRect().width>400
});
}catch(e){window.renderCheck='failed';}})();");
            while(clock.Elapsed.TotalSeconds<20) {
                var raw=await web.CoreWebView2.ExecuteScriptAsync("window.renderCheck");
                if(raw!="\"pending\""&&raw!="null") {
                    var js=new System.Web.Script.Serialization.JavaScriptSerializer();
                    var text=js.Deserialize<string>(raw);
                    var value=js.Deserialize<System.Collections.Generic.Dictionary<string,bool>>(text);
                    if(value.Count!=6)throw new Exception("render_contract");
                    foreach(var item in value)if(!item.Value)throw new Exception(item.Key);
                    File.WriteAllText(Path.Combine(root,"render-result.json"),text);
                    using(var file=File.Create(Path.Combine(root,"window.png")))
                        await web.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png,file);
                    File.WriteAllText(Path.Combine(root,"runtime-version.txt"),web.CoreWebView2.Environment.BrowserVersionString);
                    // The production host must reject a non-loopback navigation before any request.
                    var blocked=new TaskCompletionSource<bool>();
                    web.CoreWebView2.NavigationStarting+=(s,e)=>{
                        if(e.Uri=="https://outside.invalid/")blocked.TrySetResult(e.Cancel);
                    };
                    web.CoreWebView2.Navigate("https://outside.invalid/");
                    var completed=await Task.WhenAny(blocked.Task,Task.Delay(3000));
                    if(completed!=blocked.Task||!blocked.Task.Result)throw new Exception("navigation_not_blocked");
                    Console.WriteLine("PASS installed WebView2 initialized, shipped page rendered, auth enforced, outside navigation blocked");
                    End(form,0);return;
                }
                await Task.Delay(100);
            }
            throw new Exception("render_timeout");
        } catch(Exception error) {
            File.WriteAllText(Path.Combine(root,"render-failure.txt"),error.GetType().Name+":"+error.Message);
            End(form,3);
        }
    }
    [STAThread]public static int Main(string[] args) {
        root=args[1];
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        var connection=Connection.Read(args[0]);
        using(var form=new SceneWindow(connection,args[0])) {
            form.ShowInTaskbar=false;form.Opacity=0;form.StartPosition=FormStartPosition.Manual;
            form.Location=new Point(-20000,-20000);
            var web=(WebView2)typeof(SceneWindow).GetField("web",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(form);
            web.CoreWebView2InitializationCompleted+=(s,e)=>{
                if(!e.IsSuccess) {
                    File.WriteAllText(Path.Combine(root,"initialization-failure.txt"),
                        e.InitializationException==null?"unknown":e.InitializationException.GetType().Name+":"+e.InitializationException.HResult);
                    return;
                }
                web.CoreWebView2.AddWebResourceRequestedFilter("*",CoreWebView2WebResourceContext.All);
                web.CoreWebView2.WebResourceRequested+=(sender,eventArgs)=>{
                    if(!connection.Local(eventArgs.Request.Uri)) {
                        File.AppendAllText(Path.Combine(root,"blocked-resource.txt"),"blocked\n");
                        eventArgs.Response=web.CoreWebView2.Environment.CreateWebResourceResponse(null,403,"Local check only","");
                    }
                };
                web.CoreWebView2.NavigationCompleted+=async(sender,eventArgs)=>{
                    if(eventArgs.IsSuccess)await Check(form,web);
                };
            };
            using(var timer=new Timer {Interval=100}) {
                timer.Tick+=(s,e)=>{if(clock.Elapsed.TotalSeconds>25)End(form,3);};
                timer.Start();Application.Run(form);timer.Stop();
            }
            return result;
        }
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Requires Windows with WebView2 already installed; never installs it.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    temp = output/'temp'
    temp.mkdir()
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp), PYTHONDONTWRITEBYTECODE='1')
    # Child-only flags suppress browser background setup/update activity; no security feature is disabled.
    env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--disable-background-networking --disable-component-update --no-first-run'
    lock = json.loads((REPO/'packaging/webview2-sdk-lock.json').read_text())
    for name, expected in lock['files'].items():
        data = (args.sdk/name).read_bytes()
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('webview_sdk_mismatch')
        (output/name).write_bytes(data)
    source = output/'RenderChecks.cs'
    source.write_text(HARNESS)
    executable = output/'RenderChecks.exe'
    compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    command = [str(compiler),'/nologo','/target:exe','/platform:x64','/main:RenderChecks',
        '/out:'+str(executable),'/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
        '/reference:System.Web.Extensions.dll','/reference:System.Net.Http.dll',
        *('/reference:'+str(output/name) for name in ('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll')),
        str(source),str(REPO/'packaging/windows/SceneWindow.cs')]
    with (output/'compile.stdout.log').open('xb') as stdout,(output/'compile.stderr.log').open('xb') as stderr:
        result=run_owned(command,env=env,cwd=REPO,stdout=stdout,stderr=stderr,timeout=60)
    if result.returncode:
        raise SystemExit('Compilation failed; logs preserved.')
    data_dir=output/'app-data';data_dir.mkdir()
    app=LocalSceneApp(data_dir,output/'unused-runtime')
    session=LibrarySession(app,data_dir);app.library_session=session
    app.native_window=SimpleNamespace(active=True,state=lambda:{'active':True,'showCounter':0})
    token=secrets.token_hex(32)
    requests=[]
    base=handler_for(app,token)
    class Handler(base):
        def do_GET(self):
            requests.append({'method':'GET','path':self.path})
            super().do_GET()
        def do_POST(self):
            requests.append({'method':'POST','path':self.path})
            # A rendering check may never start processing or call any mutation.
            self.send(403,{'error':'read_only_check'})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    connection=output/'connection.json'
    connection.write_text(json.dumps({'version':1,'url':f'http://127.0.0.1:{server.server_port}/#{token}'}))
    try:
        with (output/'render.stdout.log').open('xb') as stdout,(output/'render.stderr.log').open('xb') as stderr:
            result=run_owned([str(executable),str(connection),str(output)],env=env,cwd=output,
                stdout=stdout,stderr=stderr,timeout=40)
    finally:
        server.shutdown();server.server_close();worker.join(5);session.close();app.close()
        connection.unlink()
        (output/'requests.json').write_text(json.dumps(requests,indent=2)+'\n')
    receipt={'exitCode':result.returncode,'sourceSha256':hashlib.sha256((REPO/'packaging/windows/SceneWindow.cs').read_bytes()).hexdigest(),
        'windowsWebViewInitialized':result.returncode==0,'shippedPageRendered':result.returncode==0,
        'actualLocalBackend':True,'emptyLibrary':True,'hiddenOwnedChild':True,'interactiveUserAcceptance':False,
        'nativeFilePanels':False,'modelsDownloaded':False,'inference':False,'liveImagery':False,'cloudAccess':False,
        'runtimeInstallation':False,'mutatingRequests':sum(r['method']!='GET' for r in requests)}
    (output/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))
    if result.returncode:
        raise SystemExit('Rendering failed; all private diagnostics retained.')


if __name__=='__main__':
    main()

