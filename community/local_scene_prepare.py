"""Maintainer-only preparation of pinned offline compatibility checks.

No inference, cloud request, model download or device approval happens here.
Existing owner-reviewed full-runtime evidence is an explicit input.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re

from .bootstrap import files_for_platform
from .local_scene_packets import canonical
from .local_scene_pilot import MANIFEST, immutable
from .local_scene_qualification import fixed_policy, read_document
from .local_scene_readiness import load_readiness
from .mac_starter import regular
from .pc_canary import runtime_profile
from .vision_index import file_identity


def prepare(template, template_sha256, binary, models, platform, evidence, destination):
    source = fixed_policy(template, template_sha256)
    inputs = source.pinned_inputs()
    if platform not in ('windows-x86_64', 'darwin-arm64'):
        raise ValueError('unsupported_platform')
    if (not isinstance(evidence, list) or not 1 <= len(evidence) <= 3
            or len({e.get('threads') for e in evidence}) != len(evidence)
            or not any(e.get('threads') == 1 for e in evidence)):
        raise ValueError('reviewed_full_runtime_evidence_required')
    binary, models = regular(binary), regular(models, directory=True)
    for item in files_for_platform(read_document(MANIFEST), platform, lane='scene'):
        path = binary.parent / Path(item['path']).name if item['path'].startswith('bin/') else models / Path(item['path']).name
        if file_identity(regular(path)) != {'bytes': item['bytes'], 'sha256': item['sha256']}:
            raise ValueError('pilot_runtime_mismatch')
    destination = regular(destination, directory=True, missing=True)
    destination.mkdir(parents=True, exist_ok=True)
    immutable(destination / 'locations.tsv', inputs['fixtureBytes'])
    immutable(destination / 'reference.i8', inputs['referenceBytes'])
    descriptor = {'contract': 'vision-local-scene-readiness-v1', 'policies': []}
    for entry in sorted(evidence, key=lambda e: e['threads']):
        if (set(entry) != {'threads', 'approved', 'locations', 'repetitions', 'evidenceSha256'}
                or type(entry['threads']) is not int or entry['threads'] not in (1, 2, 4)
                or entry['approved'] is not True or entry['locations'] != 1024
                or type(entry['repetitions']) is not int or entry['repetitions'] < 3
                or not re.fullmatch('[a-f0-9]{64}', str(entry['evidenceSha256']))):
            raise ValueError('reviewed_full_runtime_evidence_required')
        profile = runtime_profile(binary, models, inference_threads=entry['threads'],
                                  platform_name='win32' if platform.startswith('windows') else 'darwin')
        policy = copy.deepcopy(source.document)
        policy['policyId'] = f"vision-local-fixed112-{platform}-cpu{entry['threads']}-v1"
        policy['runtimeProfileSha256'] = profile['sha256']
        policy['fullCalibration'] = {k: v for k, v in entry.items() if k != 'threads'}
        policy['dataset']['fixture']['path'] = 'locations.tsv'
        policy['dataset']['reference']['path'] = 'reference.i8'
        name = f"threads-{entry['threads']}.json"
        body = canonical(policy) + b'\n'
        immutable(destination / name, body)
        descriptor['policies'].append({'path': name, 'sha256': hashlib.sha256(body).hexdigest(),
                                       'threads': entry['threads']})
    immutable(destination / 'Check this computer.json', canonical(descriptor) + b'\n')
    load_readiness(destination / 'Check this computer.json')
    return descriptor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--template-sha256', required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--platform', choices=('windows-x86_64', 'darwin-arm64'), required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.template, args.template_sha256, args.binary, args.models,
                             args.platform, read_document(args.evidence)['profiles'], args.output)))


if __name__ == '__main__':
    main()
