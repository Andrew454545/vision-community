"""Build a local maintainer pilot kit; no models, packets, credentials or cloud."""
import argparse
import json
from pathlib import Path
import sys
import hashlib
import zipfile

sys.path.insert(0,str(Path(__file__).parent))
from stage import REPO, regular, inventory, source_state
from community.mac_starter import source_inventory
from community.vision_index import file_identity
from community.bootstrap import files_for_platform


def build(output, native_dir, revision, platform='windows-x86_64'):
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
    output.mkdir();project=output/'VISION Local Scenes';project.mkdir()
    for name in sorted(names):
        target=project/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((REPO/name).read_bytes())
    for item in native:
        target=project/'pilot-runtime'/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((native_dir/Path(item['path']).name).read_bytes())
        if item.get('executable'):target.chmod(0o755)
    checksum=inventory(project,revision)
    zipped=output/f'VISION-Local-Scenes-{platform}-MAINTAINER.zip'
    # The shared native-app archive stores resources as regular data. This kit
    # exposes .command starters directly, so retain their executable Unix mode.
    with zipfile.ZipFile(zipped,'x',compression=zipfile.ZIP_DEFLATED) as package:
        for path in sorted(project.rglob('*')):
            if path.is_file():
                regular(path)
                name=path.relative_to(project).as_posix()
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
        'signed':False,'cloudCalls':0,'actionsRuns':0}
    (output/'pilot-kit-receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--native-dir',type=Path,required=True)
    parser.add_argument('--revision',required=True);parser.add_argument('--platform',default='windows-x86_64')
    args=parser.parse_args();print(json.dumps(build(args.output,args.native_dir,args.revision,args.platform)))
