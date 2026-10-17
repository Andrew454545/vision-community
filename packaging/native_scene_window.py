"""Compile optional native windows locally; no SDK/network installation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import plistlib

from stage import REPO,regular


def build_host(project,output,platform,*,sdk=None,refs=None):
    folder=project/'native-window';folder.mkdir()
    sources={}
    if platform=='darwin-arm64':
        source=REPO/'packaging/macos/SceneWindow.swift'
        executable=folder/'VISION Desktop Window'
        info=output/'window-info.plist'
        info.write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.visioncommunity.local-scene-window',
            'CFBundleName':'VISION Local Scenes','NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}))
        command=['/usr/bin/swiftc','-O','-target','arm64-apple-macosx13.0',
            '-module-cache-path',str(output/'swift-modules'),'-framework','AppKit','-framework','WebKit',
            '-Xlinker','-sectcreate','-Xlinker','__TEXT','-Xlinker','__info_plist','-Xlinker',str(info),str(source),'-o',str(executable)]
        sources[str(source.relative_to(REPO))]=hashlib.sha256(source.read_bytes()).hexdigest()
    else:
        sdk=regular(sdk,directory=True);refs=regular(refs,directory=True)
        lock=json.loads((REPO/'packaging/webview2-sdk-lock.json').read_text())
        for name,pin in lock['files'].items():
            path=regular(sdk/name)
            if path.stat().st_size!=pin['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=pin['sha256']:
                raise ValueError('webview_sdk_mismatch')
            shutil.copy2(path,folder/name)
        source=REPO/'packaging/windows/SceneWindow.cs'
        executable=folder/'VISION Desktop Window.exe'
        sources[str(source.relative_to(REPO))]=hashlib.sha256(source.read_bytes()).hexdigest()
        assemblies=['mscorlib.dll','System.dll','System.Core.dll','System.Windows.Forms.dll',
            'System.Drawing.dll','System.Web.Extensions.dll','System.Net.Http.dll']
        compiler=[os.environ.get('VISION_LOCAL_DOTNET','dotnet'),str(regular(Path(os.environ['VISION_LOCAL_CSC'])))]
        if os.name=='nt':
            compiler=[str(Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe')]
        command=[*compiler,'/nologo','/noconfig','/nostdlib+','/target:winexe','/platform:x64','/optimize+',
            '/out:'+str(executable),*('/reference:'+str(regular(refs/name)) for name in assemblies),
            *('/reference:'+str(folder/name) for name in ('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll')),str(source)]
    result=subprocess.run(command,capture_output=True,timeout=120)
    (output/'window-build.stdout.log').write_bytes(result.stdout)
    (output/'window-build.stderr.log').write_bytes(result.stderr)
    if result.returncode:
        raise ValueError('native_window_build_failed')
    if platform=='darwin-arm64':
        result=subprocess.run([str(executable),'--self-check'],capture_output=True,timeout=15,check=True)
        if b'LOCAL_NATIVE_WINDOW_BOUNDARY_VERIFIED' not in result.stdout:
            raise ValueError('native_window_self_check_failed')
        (output/'window-self-check.log').write_bytes(result.stdout+result.stderr)
    files={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in folder.iterdir()}
    value={'version':1,'platform':platform,'executable':executable.name,'files':files}
    (folder/'manifest.json').write_text(json.dumps(value,sort_keys=True)+'\n')
    return {'nativeWindow':True,'nativeWindowSources':sources,'nativeWindowSelfCheck':platform=='darwin-arm64',
        'nativeWindowGuiExecuted':False,'webviewSDK':None if platform=='darwin-arm64' else lock['version']}


def mac_launcher(kit,output,revision,checksum):
    app=kit/'VISION Local Scenes.app'
    binary=app/'Contents/MacOS/VISION Local Scenes';binary.parent.mkdir(parents=True)
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'VISION Local Scenes',
        'CFBundleIdentifier':'org.visioncommunity.local-scenes','CFBundleName':'VISION Local Scenes',
        'CFBundleVersion':'1','CFBundleShortVersionString':'0.2.0','CFBundlePackageType':'APPL',
        'LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,'VISIONSourceRevision':revision}))
    build=output/'mac-launcher-source';build.mkdir()
    (build/'Build.swift').write_text('enum Build {static let inventorySHA="'+checksum+'";static let revision="'+revision+'"}\n')
    (build/'main.swift').write_bytes((REPO/'packaging/macos/LocalScenes.swift').read_bytes())
    result=subprocess.run(['/usr/bin/swiftc','-O','-target','arm64-apple-macosx13.0',
        '-module-cache-path',str(output/'swift-modules'),'-framework','AppKit',
        str(build/'Build.swift'),str(build/'main.swift'),'-o',str(binary)],capture_output=True,timeout=120)
    (output/'mac-launcher-build.stdout.log').write_bytes(result.stdout)
    (output/'mac-launcher-build.stderr.log').write_bytes(result.stderr)
    if result.returncode:
        raise ValueError('mac_scene_launcher_build_failed')
    result=subprocess.run([str(binary),'--self-check'],capture_output=True,timeout=20,check=True)
    if b'LOCAL_PILOT_PACKAGE_VERIFIED' not in result.stdout:
        raise ValueError('mac_scene_launcher_self_check_failed')
    (output/'mac-launcher-self-check.log').write_bytes(result.stdout+result.stderr)
    return {'nativeMacLauncher':True,'nativeMacLauncherSelfCheck':True,'nativeMacLauncherGuiExecuted':False}
