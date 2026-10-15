"""Provision only local Scene files. No service account, upload or inference."""
import argparse
import json
from pathlib import Path
import os
import sys

REPO=Path(os.path.abspath(__file__)).parents[1]
if str(REPO) not in sys.path:sys.path.insert(0,str(REPO))
from community.bootstrap import RELEASE, download_file, files_for_platform, runtime_platform
from community.local_scene_pilot import MANIFEST, immutable, verify_runtime
from community.mac_starter import regular
from community.vision_index import file_identity


def setup_runtime(kit_runtime, destination, *, download_models=False, downloader=download_file):
    destination=regular(destination,directory=True,missing=True)
    kit_runtime=regular(kit_runtime,directory=True)
    manifest=json.loads(MANIFEST.read_text())
    entries=files_for_platform(manifest,runtime_platform(),lane='scene')
    # Verify all bundled native files before copying or downloading anything.
    for item in entries:
        if item['path'].startswith('bin/'):
            source=regular(kit_runtime/item['path'])
            if file_identity(source)!={'bytes':item['bytes'],'sha256':item['sha256']}:
                raise ValueError('pilot_kit_runtime_mismatch')
    for item in entries:
        target=regular(destination/item['path'],missing=True)
        if item['path'].startswith('bin/'):
            immutable(target,(kit_runtime/item['path']).read_bytes())
            if item.get('executable'):
                target.chmod(0o755)
        elif file_identity(target)!={'bytes':item['bytes'],'sha256':item['sha256']}:
            if not download_models:raise ValueError('pilot_models_download_consent_required')
            target.parent.mkdir(parents=True,exist_ok=True)
            partial=regular(target.with_name(target.name+'.partial'),missing=True)
            downloader(RELEASE+'/'+item['asset'],partial,item)
            if file_identity(partial)!={'bytes':item['bytes'],'sha256':item['sha256']}:
                raise ValueError('pilot_model_mismatch')
            os.replace(partial,target)
    return verify_runtime(destination)[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit-runtime',required=True,type=Path)
    parser.add_argument('--runtime-root',required=True,type=Path)
    parser.add_argument('--download-models',action='store_true')
    args=parser.parse_args()
    setup_runtime(args.kit_runtime,args.runtime_root,download_models=args.download_models)
    print('Local Scene processing files verified. Nothing was processed or uploaded.')


if __name__=='__main__':main()
