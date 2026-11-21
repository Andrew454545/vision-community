"""Maintainer-only inventory of the independently pinned standalone archive.

Writes hashes and relative names only. Does not extract or execute Python.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

ARCHIVE_BYTES = 26798928
ARCHIVE_SHA256 = 'd15291f940cfecd2e54010d5e37d2e03aa192f076a65d26ab741372fff2dabfe'

def inventory(archive):
    if archive.is_symlink() or archive.stat().st_size != ARCHIVE_BYTES:
        raise ValueError('archive_size_mismatch')
    with archive.open('rb') as body:
        if hashlib.file_digest(body, 'sha256').hexdigest() != ARCHIVE_SHA256:
            raise ValueError('archive_pin_mismatch')
    files, links, seen, directories = {}, {}, set(), {'python'}
    with tarfile.open(archive, 'r:gz') as source:
        for item in source:
            path = PurePosixPath(item.name)
            if (not re.fullmatch(r'python/[A-Za-z0-9_./+-]+', item.name)
                    or '..' in path.parts or item.name in seen):
                raise ValueError('unsafe_archive_member')
            seen.add(item.name)
            directories.update(str(p) for p in path.parents if str(p) != '.')
            if item.isfile():
                with source.extractfile(item) as body:
                    files[item.name] = {'bytes': item.size,
                        'sha256': hashlib.file_digest(body, 'sha256').hexdigest(),
                        'executable': bool(item.mode & 0o111)}
            elif item.issym():
                if not re.fullmatch(r'[A-Za-z0-9_.+-]+', item.linkname):
                    raise ValueError('unsafe_archive_link')
                links[item.name] = item.linkname
            elif item.isdir():
                directories.add(item.name.rstrip('/'))
            else:
                raise ValueError('unsupported_archive_member')
    for name, target in links.items():
        if str(PurePosixPath(name).parent / target) not in files:
            raise ValueError('link_target_not_pinned_regular_file')
    return {'version': 1, 'platform': 'darwin-arm64', 'archiveBytes': ARCHIVE_BYTES,
        'archiveSha256': ARCHIVE_SHA256, 'files': dict(sorted(files.items())),
        'links': dict(sorted(links.items())), 'directories': sorted(directories)}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path); parser.add_argument('out', type=Path)
    args = parser.parse_args()
    result = inventory(args.archive)
    with args.out.open('x', encoding='utf-8', newline='\n') as destination:
        json.dump(result, destination, sort_keys=True, separators=(',', ':')); destination.write('\n')
    print(json.dumps({'files': len(result['files']), 'links': len(result['links']),
        'manifestSha256': hashlib.sha256(args.out.read_bytes()).hexdigest()}))
