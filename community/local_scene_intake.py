"""Owner: turn a private compatibility ZIP into a reviewed personal queue.

One local command; no cloud, arbitrary archive extraction or native inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import zipfile

from .local_scene_campaign import allocate_campaign, campaign_connection, export_campaign_zip, MAX_LOCATIONS
from .local_scene_packets import canonical
from .local_scene_pilot import immutable
from .local_scene_qualification import approve, fixed_policy
from .local_scene_readiness import load_readiness
from .mac_starter import regular


def read_check_zip(path):
    path = regular(path)
    if path.stat().st_size > 8 * 1024**2:
        raise ValueError('check_archive_too_large')
    raw = path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        allowed = {'installation.json', *(f'threads-{n}/canary-report.json' for n in (1, 2, 4))}
        if (not 2 <= len(entries) <= 4 or len(names) != len(set(names))
                or 'installation.json' not in names or not set(names) <= allowed
                or sum(e.file_size for e in entries) > 7 * 1024**2
                or any(e.file_size > 2 * 1024**2 or e.flag_bits & 1
                    or e.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or stat.S_IFMT(e.external_attr >> 16) not in (0, stat.S_IFREG) for e in entries)):
            raise ValueError('invalid_check_archive')
        documents = {e.filename: archive.read(e) for e in entries}
    installation = json.loads(documents.pop('installation.json'))
    if (set(installation) != {'installationId', 'scope'}
            or installation['scope'] != 'OWNER_REVIEW_REQUIRED'
            or not re.fullmatch('[a-f0-9]{64}', str(installation['installationId']))):
        raise ValueError('invalid_check_installation')
    return raw, installation['installationId'], documents


def intake(check_zip, policies_root, gold, destination):
    """Recompute each successful profile; a failing faster profile cannot block CPU1."""
    raw, installation, documents = read_check_zip(check_zip)
    checksum = hashlib.sha256(raw).hexdigest()
    root = regular(destination, directory=True, missing=True) / checksum
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    immutable(root / 'original-check.zip', raw)
    policies_root = regular(policies_root, directory=True)
    descriptors = ([policies_root / 'Check this computer.json'] if
        (policies_root / 'Check this computer.json').exists() else
        [policies_root / platform / 'Check this computer.json' for platform in ('darwin-arm64', 'windows-x86_64')
         if (policies_root / platform / 'Check this computer.json').exists()])
    trusted = {}
    for descriptor in descriptors:
        for entry in load_readiness(descriptor)['policies']:
            path = descriptor.parent / entry['path']
            policy = fixed_policy(path, entry['sha256'])
            trusted[(entry['threads'], policy.document['runtimeProfileSha256'])] = (path, entry['sha256'])
    if not trusted:
        raise ValueError('trusted_readiness_policies_required')
    approvals, failures = [], []
    for name, body in sorted(documents.items()):
        threads = int(name.split('/')[0].split('-')[1])
        immutable(root / name, body)
        try:
            report = json.loads(body)
            key = (threads, report.get('runtimeProfile', {}).get('sha256'))
            if key not in trusted:
                raise ValueError('unapproved_runtime_profile')
            policy_path, pin = trusted[key]
            receipt = approve(root / name, policy_path, pin, gold, installation)
            if receipt['inferenceThreads'] != threads:
                raise ValueError('reported_thread_profile_changed')
            approvals.append(receipt)
        except (ValueError, KeyError, TypeError) as error:
            failures.append({'threads': threads, 'errorClass': type(error).__name__})
    summary = {'contract': 'vision-local-scene-intake-v1', 'installationId': installation,
        'inputSha256': checksum, 'approvedThreads': sorted(a['inferenceThreads'] for a in approvals),
        'rejectedProfiles': failures, 'baselineApproved': any(a['inferenceThreads'] == 1 for a in approvals),
        'scope': 'LOCAL_PROCESSING_ONLY', 'cloudCalls': 0}
    immutable(root / 'review.json', canonical(summary) + b'\n')
    immutable(root / 'approvals.json', canonical(approvals) + b'\n')
    return root, summary, approvals


def prepare_delivery(check_zip, policies_root, gold, registry, participant, destination, *, count=MAX_LOCATIONS):
    if not isinstance(participant, str) or not re.fullmatch('[A-Za-z0-9_-]{1,48}', participant):
        raise ValueError('invalid_participant')
    destination = regular(destination, directory=True, missing=True)
    review_root, summary, approvals = intake(check_zip, policies_root, gold, destination / 'private-review')
    if not summary['baselineApproved']:
        raise ValueError('cpu1_check_must_pass_before_assignment')
    # A ZIP's timestamps/compression, or repeating the computer check, must not
    # silently grant another five million rows to the same installation.
    allocation = participant + '-' + summary['installationId'][:16] + '-' + str(count)
    with campaign_connection(registry) as db:
        prior = db.execute('SELECT participant,locations,body FROM campaigns WHERE id=?', (allocation,)).fetchone()
    if prior:
        retained = json.loads(prior[2])
        current = {(a['inferenceThreads'], a['runtimeProfile']['sha256'], a['policySha256'], a['referenceSha256']) for a in approvals}
        original = {(a['inferenceThreads'], a['runtimeProfile']['sha256'], a['policySha256'], a['referenceSha256']) for a in retained['approvals']}
        if (prior[:2] != (participant, count) or not original <= current
                or {a['installationId'] for a in retained['approvals']} != {summary['installationId']}):
            raise ValueError('existing_campaign_requires_explicit_profile_update')
        approvals = retained['approvals']
    manifest = allocate_campaign(registry, participant, count, allocation, approvals)
    delivery = export_campaign_zip(registry, allocation, destination / f'{participant}-{count}-locations.zip')
    immutable(review_root / f'delivery-{count}.json', canonical(delivery) + b'\n')
    return {**delivery, 'approvedThreads': summary['approvedThreads'], 'scope': 'LOCAL_PROCESSING_ONLY'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-zip', type=Path, required=True)
    parser.add_argument('--policies', type=Path, required=True)
    parser.add_argument('--gold', type=Path, required=True)
    parser.add_argument('--registry', type=Path)
    parser.add_argument('--participant')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=MAX_LOCATIONS)
    parser.add_argument('--review-only', action='store_true')
    args = parser.parse_args()
    if args.review_only:
        _root, result, _approvals = intake(args.check_zip, args.policies, args.gold, args.output)
    else:
        if not args.registry or not args.participant:
            parser.error('--registry and --participant required for delivery')
        result = prepare_delivery(args.check_zip, args.policies, args.gold, args.registry,
                                  args.participant, args.output, count=args.count)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
