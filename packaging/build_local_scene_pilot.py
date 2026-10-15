"""Build a local maintainer pilot kit; no models, packets, credentials or cloud."""
import argparse
import json
from pathlib import Path
import sys
import hashlib
import zipfile
import os
import subprocess

sys.path.insert(0,str(Path(__file__).parent))
from stage import REPO, regular, inventory, source_state
from community.mac_starter import source_inventory
from community.vision_index import file_identity
from community.bootstrap import files_for_platform


def windows_launcher(output,kit,project,revision,checksum, *, windows_reference_dir=None):
    names=json.loads((project/'release-inventory.json').read_text())['files']
    snapshot=sorted(name for name in names if name.startswith(('community/','calibration/')))
    generated=output/'BuildLocal.cs'
    generated.write_text('static class Build { public const string Revision='+json.dumps(revision)+'; '+
        'public const string InventorySHA='+json.dumps(checksum)+'; '+
        'public static readonly string[] PackageNames=new string[]{'+','.join(json.dumps(n) for n in sorted(names))+'}; '+
        'public static readonly string[] SnapshotNames=new string[]{'+','.join(json.dumps(n) for n in snapshot)+'}; }\n')
    compiler=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    executable=kit/'VISION Local Scenes.exe'
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    command=[str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',
        '/out:'+str(executable),'/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
        '/reference:System.Web.Extensions.dll','/reference:System.IO.Compression.dll',
        '/reference:System.IO.Compression.FileSystem.dll','/reference:System.Net.Http.dll',
        str(generated),str(REPO/'packaging/windows/LocalScenes.cs'),str(REPO/'packaging/windows/Starter.cs')]
    if os.name!='nt':
        if windows_reference_dir is None:raise ValueError('windows_reference_assemblies_required')
        refs=regular(windows_reference_dir,directory=True)
        dotnet=os.environ.get('VISION_LOCAL_DOTNET','dotnet')
        csc=regular(Path(os.environ['VISION_LOCAL_CSC']))
        command=[dotnet,str(csc),'/noconfig','/nostdlib+',*command[1:]]
        command=[('/reference:'+str(regular(refs/arg.split(':',1)[1])))
                 if arg.startswith('/reference:') else arg for arg in command]
        command.extend('/reference:'+str(regular(refs/name)) for name in ('mscorlib.dll','System.dll','System.Core.dll'))
    result=subprocess.run(command,
        capture_output=True,creationflags=flags,timeout=60)
    (output/'native-launcher-build.stdout.log').write_bytes(result.stdout)
    (output/'native-launcher-build.stderr.log').write_bytes(result.stderr)
    if result.returncode:raise ValueError('local_scene_launcher_build_failed')
    if os.name!='nt':
        return {'nativeLauncherSha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
                'nativeLauncherSelfCheck':False,'windowsExecutionRequired':True,'powershellRequired':False}
    result=subprocess.run([str(executable),'--self-check'],capture_output=True,creationflags=flags,timeout=60)
    (output/'native-launcher-self-check.log').write_bytes(result.stdout+result.stderr)
    if result.returncode or b'LOCAL_PILOT_PACKAGE_VERIFIED' not in result.stdout:
        raise ValueError('local_scene_launcher_self_check_failed')
    return {'nativeLauncherSha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
            'nativeLauncherSelfCheck':True,'powershellRequired':False}


def build(output, native_dir, revision, platform='windows-x86_64', *, windows_reference_dir=None, readiness_dir=None):
    if platform not in ('windows-x86_64','darwin-arm64'):raise ValueError('unsupported_platform')
    dirty=source_state(revision)
    output=regular(output,directory=True,missing=True)
    native_dir=regular(native_dir,directory=True)
    if output.exists():raise ValueError('package_output_exists')
    manifest=json.loads((REPO/'community/local_scene_runtime.json').read_text())
    native=[v for v in files_for_platform(manifest,platform,lane='scene') if v['path'].startswith('bin/')]
    for item in native:
        if file_identity(regular(native_dir/Path(item['path']).name))!={'bytes':item['bytes'],'sha256':item['sha256']}:
            raise ValueError('pilot_native_runtime_mismatch')
    names=set(source_inventory(REPO))
    names|={'docs/LOCAL_SCENE_PILOT.md'}
    if platform=='windows-x86_64':names|={'Start Local Scenes.cmd','windows/Start-LocalScenes.ps1','windows/Start-Vision.ps1'}
    else:names|={'macos/Start-Vision.command','Start Local Scenes.command'}
    for name in names:regular(REPO/name)
    output.mkdir();kit=output/'VISION Local Scenes';kit.mkdir()
    (kit/'START-HERE.md').write_bytes(regular(REPO/'LOCAL-SCENES-START-HERE.md').read_bytes())
    project=kit/'project' if platform=='windows-x86_64' else kit
    project.mkdir(exist_ok=True)
    for name in sorted(names):
        target=project/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((REPO/name).read_bytes())
    for item in native:
        target=project/'pilot-runtime'/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((native_dir/Path(item['path']).name).read_bytes())
        if item.get('executable'):target.chmod(0o755)
    if readiness_dir is not None:
        from community.local_scene_readiness import load_readiness
        readiness_dir=regular(readiness_dir,directory=True)
        setup=load_readiness(readiness_dir/'Check this computer.json')
        allowed={'Check this computer.json'}
        for item in setup['policies']:
            allowed.add(item['path'])
            policy=json.loads(regular(readiness_dir/item['path']).read_text())
            for k in ('fixture','reference'):
                allowed.add((Path(item['path']).parent/policy['dataset'][k]['path']).as_posix())
        for name in sorted(allowed):
            source=regular(readiness_dir/name)
            target=kit/'Readiness'/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(source.read_bytes())
    checksum=inventory(project,revision)
    launcher=windows_launcher(output,kit,project,revision,checksum,windows_reference_dir=windows_reference_dir) if platform=='windows-x86_64' else {}
    zipped=output/f'VISION-Local-Scenes-{platform}-MAINTAINER.zip'
    # The shared native-app archive stores resources as regular data. This kit
    # exposes .command starters directly, so retain their executable Unix mode.
    with zipfile.ZipFile(zipped,'x',compression=zipfile.ZIP_DEFLATED) as package:
        for path in sorted(kit.rglob('*')):
            if path.is_file():
                regular(path)
                name=path.relative_to(kit).as_posix()
                entry=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0))
                entry.compress_type=zipfile.ZIP_DEFLATED
                executable=name.endswith('.command') or name=='pilot-runtime/bin/mma-vision'
                entry.create_system=3
                entry.external_attr=(0o100755 if executable else 0o100644)<<16
                package.writestr(entry,path.read_bytes())
    sha=hashlib.sha256(zipped.read_bytes()).hexdigest()
    report={'sourceRevision':revision,'sourceWorktreeDirty':dirty,'platform':platform,
        'inventorySha256':checksum,'sha256':sha,'artifact':zipped.name,
        'modelFilesBundled':False,'packetsBundled':False,'publicDistributionReady':False,
        'signed':False,'cloudCalls':0,'actionsRuns':0,**launcher}
    (output/'pilot-kit-receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--native-dir',type=Path,required=True)
    parser.add_argument('--revision',required=True);parser.add_argument('--platform',default='windows-x86_64')
    parser.add_argument('--windows-reference-dir',type=Path)
    parser.add_argument('--readiness-dir',type=Path)
    args=parser.parse_args();print(json.dumps(build(args.output,args.native_dir,args.revision,args.platform,
        windows_reference_dir=args.windows_reference_dir,readiness_dir=args.readiness_dir)))
