"""Offline Scene membership seals from independently pinned contributions.

This is not an approval authority. It verifies an existing contributed snapshot
and builds a bounded Merkle tree; the coordinator's separately trusted root is
what authorizes proofs. No account keys, uploader approvals, cloud or activation.
"""
from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path
import re

from .native_scene_search import plain_path, strict_json
from .search_snapshot import (MAX_INVENTORY_BYTES, MAX_LOCATIONS, bounded_read, digest,
                              encoded, pinned_read, resource_for_environment, verify_snapshot, write_file)

SCOPE = 'operator-sealed-scene-membership-v1'
CONTEXT = 'vision-contributed-scene-member-v1'
HEX = re.compile(r'[0-9a-f]{64}\Z')
POLICY = re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')
MAX_MEMBER_BYTES = 8192
MAX_PROOF_HITS = 64
HEADER_KEYS = {'version', 'scope', 'lane', 'environment', 'resource', 'policyId',
               'runtimeSha256', 'snapshotSha256', 'locations', 'rootSha256'}


class SceneMembershipError(ValueError):
    pass


def require(value):
    if not value:
        raise SceneMembershipError('scene_membership_invalid')


def validate_header(doc):
    require(isinstance(doc, dict) and set(doc) == HEADER_KEYS
            and type(doc['version']) is int and doc['version'] == 1 and doc['scope'] == SCOPE
            and doc['lane'] == 'scene' and doc['environment'] in ('staging', 'production')
            and doc['resource'] == resource_for_environment(doc['environment'])
            and isinstance(doc['policyId'], str) and POLICY.fullmatch(doc['policyId'])
            and (not doc['policyId'].startswith('staging.') or doc['environment'] == 'staging')
            and all(isinstance(doc[k], str) and HEX.fullmatch(doc[k]) for k in
                    ('runtimeSha256', 'snapshotSha256', 'rootSha256'))
            and type(doc['locations']) is int and 1 <= doc['locations'] <= MAX_LOCATIONS)
    return doc


def context(doc):
    # Fixed ASCII array avoids cross-language object-key/float serialization.
    return encoded([CONTEXT, doc['environment'], 'scene', doc['policyId'],
                    doc['runtimeSha256'], doc['snapshotSha256'], doc['locations']]).rstrip(b'\n')


def member_bytes(member, ordinal):
    require(isinstance(member, dict) and set(member) == {'sourceIndex', 'locationId', 'outputSha256', 'pose'}
            and type(member['sourceIndex']) is int and member['sourceIndex'] == ordinal
            and type(member['locationId']) is int and 0 < member['locationId'] < 2**53
            and isinstance(member['outputSha256'], str) and HEX.fullmatch(member['outputSha256']))
    pose = member['pose']
    require(isinstance(pose, dict) and set(pose) == {'lat', 'lng', 'heading', 'pitch', 'zoom',
                                                   'panoId', 'capture', 'country', 'cameraGeneration'})
    for key, low, high in (('lat', -90, 90), ('lng', -180, 180), ('heading', 0, 360),
                            ('pitch', -90, 90), ('zoom', 0, 5)):
        require(type(pose[key]) in (int, float) and math.isfinite(pose[key]) and low <= pose[key] <= high)
    for key, minimum, maximum in (('panoId', 1, 1000), ('capture', 1, 1000),
                                   ('country', 0, 100), ('cameraGeneration', 0, 64)):
        value = pose[key]
        require(isinstance(value, str) and minimum <= len(value) <= maximum
                and not any(ord(c) < 32 or ord(c) == 127 for c in value))
    raw = encoded(member).rstrip(b'\n')
    require(len(raw) <= MAX_MEMBER_BYTES)
    return raw


def tree_for(members, header):
    require(isinstance(members, list) and len(members) == header['locations'])
    prefix = b'\0' + context(header) + b'\n'
    raw_members = [member_bytes(m, i) for i, m in enumerate(members)]
    require(len({m['locationId'] for m in members}) == len(members))
    levels = [[hashlib.sha256(prefix + raw).digest() for raw in raw_members]]
    while len(levels[-1]) > 1:
        prior = levels[-1]
        levels.append([hashlib.sha256(b'\1' + prior[i] + prior[min(i+1, len(prior)-1)]).digest()
                       for i in range(0, len(prior), 2)])
    return raw_members, levels


def snapshot_members(snapshot, snapshot_pin, environment):
    snapshot = plain_path(Path(snapshot), directory=True)
    doc = verify_snapshot(snapshot, snapshot_pin, environment=environment)
    raw = bounded_read(plain_path(snapshot/'members.json'), MAX_INVENTORY_BYTES)
    members = strict_json(raw)
    # Bracket membership reads with the original sealed snapshot checks.
    require(digest(raw) == doc['files']['members.json']['sha256'])
    return snapshot, doc, members


def build_membership(snapshot, snapshot_pin, destination, *, environment, policy_id, runtime_sha256):
    """Only an operator's independently pinned contributed snapshot is accepted.

    The runtime/policy pin must be approved separately. This does not approve a
    runtime, establish earnings or publish the resulting root/configuration.
    """
    snapshot, doc, members = snapshot_members(snapshot, snapshot_pin, environment)
    header = {'version': 1, 'scope': SCOPE, 'lane': 'scene', 'environment': environment,
        'resource': resource_for_environment(environment), 'policyId': policy_id,
        'runtimeSha256': runtime_sha256, 'snapshotSha256': snapshot_pin,
        'locations': doc['locations'], 'rootSha256': '0'*64}
    validate_header(header)
    _, levels = tree_for(members, header)
    header['rootSha256'] = levels[-1][0].hex()
    destination = Path(destination).absolute()
    require(not (destination == snapshot or snapshot in destination.parents or destination in snapshot.parents))
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    destination = plain_path(destination, directory=True)
    # No member/account database copy is needed: tree nodes are just digests.
    tree = b''.join(node for level in levels for node in level)
    geometry = write_file(destination/'tree.bin', tree)
    validate_header(header)
    manifest = {**header, 'files': {'tree.bin': geometry}}
    verify_snapshot(snapshot, snapshot_pin, environment=environment)
    temporary = destination/'membership.pending'
    write_file(temporary, encoded(manifest))
    temporary.replace(destination/'membership.json')
    return {'locations': len(members), 'rootSha256': header['rootSha256'],
            'membershipSha256': digest(encoded(manifest)), 'coordinatorBinding': header}


class SceneMembershipProofs:
    def __init__(self, snapshot, snapshot_pin, membership, membership_pin, *, environment, policy_id, runtime_sha256):
        self.path = plain_path(Path(membership))
        self.membership_pin = membership_pin
        self.document = strict_json(pinned_read(self.path, membership_pin, 4096))
        require(isinstance(self.document, dict) and set(self.document) == HEADER_KEYS | {'files'})
        self.header = validate_header({k: v for k, v in self.document.items() if k != 'files'})
        require(self.header['environment'] == environment and self.header['policyId'] == policy_id
                and self.header['runtimeSha256'] == runtime_sha256 and self.header['snapshotSha256'] == snapshot_pin)
        self.snapshot, _, members = snapshot_members(snapshot, snapshot_pin, environment)
        self.members = members
        self.raw_members, self.levels = tree_for(members, self.header)
        require(self.levels[-1][0].hex() == self.header['rootSha256'])
        self.tree = b''.join(node for level in self.levels for node in level)
        require(self.document['files'] == {'tree.bin': {'bytes': len(self.tree), 'sha256': digest(self.tree)}})
        self.verify_inputs()

    def verify_inputs(self):
        require(strict_json(pinned_read(self.path, self.membership_pin, 4096)) == self.document)
        retained = bounded_read(plain_path(self.path.parent/'tree.bin'), 2 * MAX_LOCATIONS * 32 + 1024)
        require(retained == self.tree)
        verify_snapshot(self.snapshot, self.header['snapshotSha256'], environment=self.header['environment'])

    def proof(self, ordinal):
        require(type(ordinal) is int and 0 <= ordinal < len(self.members))
        siblings, index = [], ordinal
        for level in self.levels[:-1]:
            siblings.append(level[min(index ^ 1, len(level)-1)].hex())
            index //= 2
        return {'memberJson': self.raw_members[ordinal].decode('utf-8'), 'siblings': siblings}


class SceneMembershipEngine:
    """Existing native engine plus bounded membership, never a new approver."""
    def __init__(self, engine, proofs):
        self.engine, self.proofs = engine, proofs

    def search(self, request, *, raw_query):
        require(isinstance(request.get('query'), dict)
                and type(request['query'].get('resultCount')) is int
                and 1 <= request['query']['resultCount'] <= MAX_PROOF_HITS)
        self.proofs.verify_inputs()
        result = self.engine.search(request, raw_query=raw_query)
        header = self.proofs.header
        require(isinstance(result, dict) and type(result.get('processedLocations')) is int
                and result['processedLocations'] == header['locations']
                and all(result.get(k) == header[k] for k in ('policyId', 'runtimeSha256', 'snapshotSha256'))
                and isinstance(result.get('hits'), list) and len(result['hits']) <= request['query']['resultCount'])
        proofs = []
        for hit in result['hits']:
            require(isinstance(hit, dict))
            ordinal = hit.get('sourceIndex')
            proof = self.proofs.proof(ordinal)
            member = self.proofs.members[ordinal]
            require(hit.get('locationId') == member['locationId'] and hit.get('outputSha256') == member['outputSha256'])
            proofs.append(proof)
        self.proofs.verify_inputs()
        return {**result, 'membership': proofs}


def main():
    parser = argparse.ArgumentParser(description='Offline operator-only Scene membership sealing; no activation.')
    for key in ('snapshot', 'snapshot-sha256', 'destination', 'environment', 'policy-id', 'runtime-sha256'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    try:
        report = build_membership(args.snapshot, args.snapshot_sha256, args.destination,
            environment=args.environment, policy_id=args.policy_id, runtime_sha256=args.runtime_sha256)
    except Exception:
        report = {'sealed': False, 'error': 'scene_membership_seal_failed'}
    print(encoded(report).decode(), end='')
    return 1 if report.get('sealed') is False else 0


if __name__ == '__main__':
    raise SystemExit(main())
