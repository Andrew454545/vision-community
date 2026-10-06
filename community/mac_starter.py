"""Private Mac source snapshot and guided application entrypoint.

The shell verifies the entire private Python before this program executes.
No native runtime, account or imagery is used by snapshot-only checks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys

MODULES = ('__init__ admin all_locations_full all_locations_tail background bootstrap catalog '
    'contribute delivery desktop features four_view indexed_local local_search measure mma mma_cloud '
    'object_index pano parts pc_canary prompt rank scene_pipeline scene_quality search mac_launch_agent mac_launch_guard mac_starter mac_runtime mac_worker mac_background mac_background_control '
    'mac_remove seal_index segments send_mma server service source store submission_outbox verify '
    'vision_handoff vision_index process_owner work_plan worker').split()
FILES = tuple('community/'+name+'.py' for name in MODULES) + (
    'community/runtime_manifest.json', 'community/country-names.txt',
    'community/desktop_web/index.html', 'community/desktop_web/style.css', 'community/desktop_web/app.js',
    'calibration/run_windows.py', 'calibration/quality.py', 'calibration/synthetic_canary.py',
    'community/background_web/index.html', 'community/background_web/style.css', 'community/background_web/app.js',
    'macos/python-arm64-inventory.json', 'macos/verify-python.pl', 'macos/verify-source.pl') + tuple(
    'calibration/gen4-v1/'+name for name in ('checksums.json', 'canary-112.tsv', 'fixture-1024.tsv',
        'fixture-manifest.json', 'generation-evidence.json', 'historical-reference.i8',
        'local-vision-observation.json', 'record-hashes.json'))
REQUIRED = {'community/desktop.py', 'community/work_plan.py', 'community/object_index.py', 'community/bootstrap.py', 'community/vision_index.py',
    'community/process_owner.py', 'community/runtime_manifest.json', 'community/submission_outbox.py', 'community/delivery.py',
    'community/desktop_web/index.html', 'calibration/run_windows.py', 'calibration/quality.py',
    'calibration/synthetic_canary.py', 'calibration/gen4-v1/checksums.json', 'community/mac_worker.py',
    'community/mac_background.py', 'community/mac_background_control.py', 'community/mac_remove.py', 'community/background_web/index.html',
    'community/background_web/app.js', 'community/background_web/style.css',
    'macos/python-arm64-inventory.json', 'macos/verify-python.pl', 'macos/verify-source.pl'}

class SnapshotError(ValueError):
    pass

def regular(path, *, directory=False, missing=False):
    path=Path(path).absolute()
    if '..' in path.parts:raise SnapshotError('unsafe_private_path')
    for parent in reversed(path.parents):
        try:
            item=parent.lstat()
            if not stat.S_ISDIR(item.st_mode) or getattr(item,'st_file_attributes',0)&0x400:
                raise SnapshotError('linked_private_path')
        except FileNotFoundError:
            if not missing:raise SnapshotError('private_parent_missing')
    try:item=path.lstat()
    except FileNotFoundError:
        if missing:return path
        raise
    if not (stat.S_ISDIR if directory else stat.S_ISREG)(item.st_mode) or getattr(item,'st_file_attributes',0)&0x400:
        raise SnapshotError('linked_private_path')
    return path

def pin(path):
    path=regular(path)
    with path.open('rb') as body:return {'bytes':path.stat().st_size,'sha256':hashlib.file_digest(body,'sha256').hexdigest()}

def source_inventory(source):
    source=regular(source,directory=True)
    files={}
    for name in sorted(FILES):
        path=source/name
        if not path.exists() and not path.is_symlink():
            if name in REQUIRED:raise SnapshotError('source_download_incomplete')
            continue
        files[name]=pin(path)
    return files

def verify_snapshot(target,files,metadata):
    regular(target,directory=True)
    expected={*files,'source-inventory.json'}
    expected_dirs={p.as_posix() for name in files for p in Path(name).parents if p!=Path('.')}
    seen=set()
    for folder,dirs,names in os.walk(target,followlinks=False):
        for name in dirs:
            path=regular(Path(folder)/name,directory=True)
            if path.relative_to(target).as_posix() not in expected_dirs:
                raise SnapshotError('unexpected_snapshot_directory')
        for name in names:
            path=regular(Path(folder)/name);relative=path.relative_to(target).as_posix()
            if relative not in expected:raise SnapshotError('unexpected_snapshot_file')
            seen.add(relative)
    if seen!=expected:raise SnapshotError('snapshot_inventory_changed')
    for name,value in files.items():
        if pin(target/name)!=value:raise SnapshotError('snapshot_file_changed')
    if (target/'source-inventory.json').read_bytes()!=metadata:raise SnapshotError('snapshot_receipt_changed')

def copy_source(source,root):
    files=source_inventory(source)
    metadata=(json.dumps({'version':1,'files':files},sort_keys=True,separators=(',',':'))+'\n').encode()
    digest=hashlib.sha256(metadata).hexdigest()
    apps=regular(Path(root)/'apps',directory=True,missing=True);apps.mkdir(parents=True,exist_ok=True)
    target=regular(apps/digest,directory=True,missing=True)
    if not target.exists():
        stage=apps/('staging-'+secrets.token_hex(16));stage.mkdir()
        for name,value in files.items():
            origin=regular(Path(source)/name);destination=stage/name
            destination.parent.mkdir(parents=True,exist_ok=True)
            with destination.open('xb') as output:output.write(origin.read_bytes())
            if pin(destination)!=value:raise SnapshotError('source_changed_during_copy')
        (stage/'source-inventory.json').write_bytes(metadata)
        verify_snapshot(stage,files,metadata)
        stage.rename(target)
    verify_snapshot(target,files,metadata)
    return target,digest

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--snapshot-only',action='store_true')
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--background-controls',action='store_true')
    args=parser.parse_args()
    root=regular(args.root,directory=True,missing=True);root.mkdir(parents=True,exist_ok=True)
    try:
        if sys.platform!='darwin':raise SnapshotError('mac_required')
        source=Path(__file__).resolve().parents[1]
        app,digest=copy_source(source,root)
        if args.snapshot_only:
            with (root/'mac-source-check.json').open('x',encoding='utf-8') as output:
                json.dump({'status':'PRIVATE_SOURCE_VERIFIED','sourceSha256':digest,
                    'accountsCreated':0,'imageryRetrieved':False,'productionQualified':False},output)
            print('Private VISION source verified. No account or imagery used.')
            return 0
        entry='mac_background_control.py' if args.background_controls else 'desktop.py'
        arguments=[sys.executable,'-I','-B',str(app/'community'/entry),'--root',str(root)]
        if not args.background_controls:
            if args.prepare_only:arguments+=['--prepare-only']
            # Only the installed native app carries a sealed release inventory.
            if (source/'release-inventory.json').is_file():arguments+=['--native-app']
        return subprocess.run(arguments,check=False).returncode
    except Exception as error:
        report={'status':'INCOMPLETE','code':str(error) if isinstance(error,SnapshotError) else type(error).__name__,
            'productionQualified':False}
        folder=root/'setup-failures';regular(folder,directory=True,missing=True);folder.mkdir(exist_ok=True)
        with (folder/(secrets.token_hex(16)+'.json')).open('x',encoding='utf-8') as output:json.dump(report,output)
        print('VISION could not start. Your private report and existing files were kept.')
        return 1

if __name__=='__main__':raise SystemExit(main())
