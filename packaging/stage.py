"""Stage only the public guided client; never copy a checkout or worker folder."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from community.mac_starter import regular, source_inventory


def source_state(revision, *, signing=False):
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    if revision != head:
        raise ValueError('package_revision_does_not_match_checkout')
    dirty = bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=all'],cwd=REPO,text=True).strip())
    if signing and dirty:
        raise ValueError('signed_package_requires_clean_source')
    return dirty


def inventory(root, revision):
    files = {}
    for path in sorted(root.rglob('*')):
        regular(path, directory=path.is_dir())
        if path.is_file() and path.name != 'release-inventory.json':
            body = path.read_bytes()
            files[path.relative_to(root).as_posix()] = {'bytes':len(body), 'sha256':hashlib.sha256(body).hexdigest()}
    body = (json.dumps({'version':1, 'sourceRevision':revision, 'files':files}, sort_keys=True) + '\n').encode()
    (root / 'release-inventory.json').write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def stage(destination, platform, revision, *, source=REPO):
    if platform not in {'mac', 'windows'} or not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('invalid_package_request')
    destination = regular(destination, directory=True, missing=True)
    if destination.exists():
        raise ValueError('package_output_exists')
    source = regular(source, directory=True)
    files = set(source_inventory(source))
    files |= {'START-HERE.md'}
    if platform == 'mac':
        files.add('macos/Start-Vision.command')
        files.add('macos/Remove-Vision.command')
    else:
        files |= {'windows/Start-Vision.ps1', 'windows/Background-Control.ps1', 'windows/Install-Background.ps1',
                  'packaging/windows/Remove-Vision.ps1'}
    # Validate every input before creating an output tree.
    for name in files:
        regular(source / name)
    destination.mkdir()
    for name in sorted(files):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / name).read_bytes())
    return inventory(destination, revision)


def archive(root, output):
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as package:
        for path in sorted(root.rglob('*')):
            if path.is_file():
                regular(path)
                entry = zipfile.ZipInfo(path.relative_to(root).as_posix(), date_time=(2026,1,1,0,0,0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                package.writestr(entry, path.read_bytes())
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=('mac','windows'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    print(stage(args.output, args.platform, args.revision))

if __name__ == '__main__':
    main()
