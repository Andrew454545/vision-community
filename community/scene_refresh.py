"""Private operator refresh of native-audited staging publications.

Uses existing credentials through a pinned Wrangler adapter, not volunteer
authority. No account/credit writes, public admission, model downloads or deploys.
The caller must serialize this work with any staging shutdown controller.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import zipfile

from .background import atomic_json, single_instance
from .process_owner import run_owned
from .scene_publication_snapshot import document, seal_publications, strict_json
from .search_snapshot import (HEX, MAX_INVENTORY_BYTES, bounded_read, cache_file, digest,
                              encoded, pinned_read, resource_for_environment, verify_snapshot, write_file)


class RefreshError(RuntimeError):
    pass


class AdapterUnavailable(RuntimeError):
    pass


class WranglerAdapter:
    def __init__(self, settings, scratch):
        self.settings, self.scratch, self.number = settings, Path(scratch), 0

    def call(self, operation, **values):
        self.number += 1
        prefix = self.scratch / (str(self.number).zfill(4) + '-' + operation)
        request = prefix.with_suffix('.request.private.json')
        result = prefix.with_suffix('.result.private.json')
        write_file(request, encoded({**values, 'operation': operation, 'result': str(result),
                                     'proxyConfig': self.settings['proxyConfig'], 'wrangler': self.settings['wrangler']}))
        temporary = Path(self.settings.get('temporaryDirectory', self.scratch))
        temporary.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, XDG_CONFIG_HOME=self.settings['authDirectory'], WRANGLER_SEND_METRICS='false',
                   TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
        try:
            with prefix.with_suffix('.stdout.private.log').open('xb') as stdout, prefix.with_suffix('.stderr.private.log').open('xb') as stderr:
                child = run_owned([self.settings['node'], self.settings['helper'], str(request)], env=env,
                                  cwd=self.scratch, stdout=stdout, stderr=stderr, timeout=180)
            reply = strict_json(bounded_read(result, 2 * MAX_INVENTORY_BYTES))
            if child.returncode != 0 or reply.get('ok') is not True:
                raise AdapterUnavailable('refresh_adapter_unavailable')
            return reply['result']
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            raise AdapterUnavailable('refresh_adapter_unavailable') from error


def canonical_capture(value, resource):
    if not isinstance(value, dict) or set(value) != {'inventory', 'control'}:
        raise RefreshError('invalid_refresh_export')
    result = {}
    orders = {'rows': 'id', 'candidates': 'lease_id', 'qualifications': 'id', 'accounts': 'id', 'ledger': 'reference', 'deletions': 'account_id'}
    for name, expected in [('inventory', {'rows'}), ('control', set(orders) - {'rows', 'deletions'})]:
        doc = value[name]
        if name == 'control' and isinstance(doc, dict) and 'deletions' in doc:
            expected = expected | {'deletions'}
        if not isinstance(doc, dict) or set(doc) != expected | {'version', 'resource'} or doc['version'] != 1 or doc['resource'] != resource:
            raise RefreshError('invalid_refresh_export')
        copied = dict(doc)
        for key in expected:
            if not isinstance(doc[key], list):
                raise RefreshError('invalid_refresh_export')
            copied[key] = sorted(doc[key], key=lambda row: row[orders[key]])
        result[name] = copied
    return result


def capture_pin(value):
    return digest(encoded(value))


def bundle_descriptor(path):
    raw = Path(path).read_bytes()
    pin = digest(raw)
    if not 0 < len(raw) <= 384 * 1024**2:
        raise RefreshError('refresh_bundle_too_large')
    return {'version': 1, 'key': 'native-host/bundles/' + pin + '.zip', 'sha256': pin, 'bytes': len(raw)}


def checked_current(value):
    if not isinstance(value, dict) or not {'snapshot', 'snapshotSha256', 'bundle'} <= value.keys():
        raise RefreshError('invalid_refresh_state')
    bundle = value['bundle']
    if (not isinstance(value['snapshot'], str) or not isinstance(value['snapshotSha256'], str)
            or not HEX.fullmatch(value['snapshotSha256']) or not isinstance(bundle, dict)
            or set(bundle) != {'version', 'key', 'sha256', 'bytes'} or type(bundle['version']) is not int
            or bundle['version'] != 1 or not isinstance(bundle['sha256'], str)
            or not HEX.fullmatch(bundle['sha256'])
            or bundle['key'] != 'native-host/bundles/' + bundle['sha256'] + '.zip'
            or type(bundle['bytes']) is not int or not 0 < bundle['bytes'] <= 384 * 1024**2):
        raise RefreshError('invalid_refresh_state')
    return value


def pack_bundle(template, snapshot, snapshot_pin, output):
    files = {}
    for name, pin in template['files'].items():
        if name not in {'manifest.json', 'policy/policy.json', 'policy/canary-reference.i8'}:
            raise RefreshError('invalid_refresh_template')
        files[name] = pinned_read(Path(template['root']) / name, pin, 4 * 1024**2)
    if set(files) != {'manifest.json', 'policy/policy.json', 'policy/canary-reference.i8'}:
        raise RefreshError('invalid_refresh_template')
    manifest = strict_json(files['manifest.json'])
    if set(manifest) != {'version', 'policySha256', 'runtimeSha256', 'snapshotSha256'} or manifest['version'] != 1:
        raise RefreshError('invalid_refresh_template')
    if digest(files['policy/policy.json']) != manifest['policySha256']:
        raise RefreshError('refresh_template_policy_changed')
    manifest['snapshotSha256'] = snapshot_pin
    files['manifest.json'] = encoded(manifest)
    for name in ('snapshot.json', 'members.json', 'scene-records.i8'):
        files['snapshot/' + name] = bounded_read(Path(snapshot) / name, 384 * 1024**2)
    # Stable metadata makes identical retries content-address to the same object.
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(files.items()):
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o600 << 16
            archive.writestr(item, raw)
    return bundle_descriptor(output)


class SceneRefresher:
    def __init__(self, root, settings, adapter):
        self.root, self.settings, self.adapter = Path(root), settings, adapter
        self.resource = resource_for_environment('staging')
        if settings.get('version') != 1 or settings.get('environment') != 'staging' or settings.get('resource') != self.resource:
            raise RefreshError('unconfirmed_refresh_resources')
        if type(settings.get('reserveNativeStarts', 4)) is not int or not 0 <= settings.get('reserveNativeStarts', 4) <= 12:
            raise RefreshError('invalid_refresh_allowance')
        self.authority_path = Path(settings['authority']['path'])
        self.authority = document(self.authority_path, settings['authority']['sha256'], self.resource)
        self.policies = [row['policyId'] for row in self.authority['policies']]
        if (not HEX.fullmatch(settings.get('runtimeSha256', '')) or not settings.get('searchPolicyId')
                or any(row['runtimeSha256'] != settings['runtimeSha256'] for row in self.authority['policies'])):
            raise RefreshError('refresh_runtime_mismatch')
        manifest = strict_json(pinned_read(Path(settings['template']['root']) / 'manifest.json',
            settings['template']['files']['manifest.json'], 4096))
        if manifest['runtimeSha256'] != settings['runtimeSha256']:
            raise RefreshError('refresh_runtime_mismatch')
        self.state_path = self.root / 'state.private.json'

    def head_matches(self, response, current):
        return response.get('httpStatus') == 200 and response.get('body') == {
            'policyId': self.settings['searchPolicyId'], 'runtimeSha256': self.settings['runtimeSha256'],
            'snapshotSha256': current['snapshotSha256'], 'bundleSha256': current['bundle']['sha256']}

    def capture(self, directory, label):
        value = canonical_capture(self.adapter.call('capture', policies=self.policies), self.resource)
        paths = {}
        for name, doc in value.items():
            path = directory / (label + '-' + name + '.private.json')
            write_file(path, encoded(doc)); paths[name] = path
        return value, paths

    def finish(self, state, directory):
        pending, current = checked_current(state['pending']), checked_current(state['current'])
        verify_snapshot(Path(pending['snapshot']), pending['snapshotSha256'], environment='staging')
        if bundle_descriptor(pending['archive']) != pending['bundle']:
            raise RefreshError('refresh_prepared_bytes_changed')
        head = self.adapter.call('head')
        if not self.head_matches(head, pending):
            if not self.head_matches(head, current):
                raise RefreshError('refresh_active_pointer_changed')
            fresh, _ = self.capture(directory, 'activation-recheck')
            if capture_pin(fresh) != pending['captureSha256']:
                state['pending'] = None; atomic_json(self.state_path, state)
                return {'status': 'SOURCE_CHANGED_RETRY', 'activated': False}
            status = self.adapter.call('status')
            budget = status.get('body', {}).get('computeBudget', {})
            if (status.get('httpStatus') != 200 or budget.get('configured') is not True
                    or type(budget.get('requestsRemaining')) is not int or budget['requestsRemaining'] < 2
                    or type(budget.get('startsRemaining')) is not int
                    or budget['startsRemaining'] <= self.settings.get('reserveNativeStarts', 4)):
                return {'status': 'DEFERRED_NATIVE_ALLOWANCE', 'activated': False}
            self.adapter.call('upload', descriptor=pending['bundle'], archive=pending['archive'])
            # Capture again after upload: never activate a stale membership proof.
            rechecked, _ = self.capture(directory, 'post-upload-recheck')
            if capture_pin(rechecked) != pending['captureSha256']:
                state['pending'] = None; atomic_json(self.state_path, state)
                return {'status': 'SOURCE_CHANGED_RETRY', 'activated': False}
            response = self.adapter.call('activate', request={'bundle': pending['bundle'],
                'expectedBundleSha256': current['bundle']['sha256'], 'search': {
                'policyId': self.settings['searchPolicyId'], 'runtimeSha256': self.settings['runtimeSha256'],
                'snapshotSha256': pending['snapshotSha256']}})
            if response.get('httpStatus') == 503:
                return {'status': 'DEFERRED_NATIVE_UNAVAILABLE', 'activated': False}
            if response.get('httpStatus') != 200:
                raise RefreshError('refresh_activation_conflict')
            if not self.head_matches(self.adapter.call('head'), pending):
                raise RefreshError('refresh_activation_readback_failed')
        # Exact durable head is the acknowledgement of a previous activation.
        # Later accepted work must not turn a lost reply into a terminal failure;
        # the next cycle revalidates and appends it without reactivating this seal.
        state.update(current={key: pending[key] for key in ('snapshot', 'snapshotSha256', 'bundle')}, pending=None)
        atomic_json(self.state_path, state)
        return {'status': 'NATIVE_AUDITED_SCENE_REFRESHED', 'activated': True,
                'snapshotSha256': pending['snapshotSha256'], 'locations': pending['locations']}

    def once(self, directory):
        directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
        try:
            state = strict_json(bounded_read(self.state_path, 65536)) if self.state_path.exists() else {
                'version': 1, 'current': self.settings['seed'], 'pending': None}
            if state.get('version') != 1:
                raise RefreshError('invalid_refresh_state')
            current = checked_current(state['current'])
            previous = verify_snapshot(Path(current['snapshot']), current['snapshotSha256'], environment='staging')
            if state['pending']:
                result = self.finish(state, directory)
            else:
                if not self.head_matches(self.adapter.call('head'), current):
                    raise RefreshError('refresh_active_pointer_changed')
                capture, paths = self.capture(directory, 'source')
                cache = directory / 'artifact-cache'; cache.mkdir()
                for row in capture['control']['candidates']:
                    key = 'four-view-v4/' + row['lease_id'] + '.i8'
                    target = cache_file(cache, key)
                    self.adapter.call('artifact', key=key, destination=str(target))
                sealed = seal_publications(paths['inventory'], digest(paths['inventory'].read_bytes()),
                    paths['control'], digest(paths['control'].read_bytes()), self.authority_path,
                    self.settings['authority']['sha256'], cache, directory / 'seal', environment='staging',
                    previous=Path(current['snapshot']), previous_sha256=current['snapshotSha256'])
                snapshot = directory / 'seal/snapshot'
                manifest = verify_snapshot(snapshot, sealed['snapshotSha256'], environment='staging')
                if manifest['files'] == previous['files']:
                    result = {'status': 'CURRENT_NO_CHANGE', 'activated': False, 'locations': manifest['locations'],
                              'snapshotSha256': current['snapshotSha256']}
                else:
                    archive = directory / 'bundle.private.zip'
                    descriptor = pack_bundle(self.settings['template'], snapshot, sealed['snapshotSha256'], archive)
                    state['pending'] = {'snapshot': str(snapshot), 'snapshotSha256': sealed['snapshotSha256'],
                        'bundle': descriptor, 'archive': str(archive), 'captureSha256': capture_pin(capture),
                        'locations': manifest['locations']}
                    # Persist the exact next operation before any remote mutation.
                    atomic_json(self.state_path, state)
                    result = self.finish(state, directory)
            write_file(directory / 'receipt.json', encoded({**result, 'environment': 'staging',
                'newCreditGranted': 0, 'productionApproved': False}))
            return result
        except AdapterUnavailable:
            write_file(directory / 'failure-report.json', encoded({'error': 'refresh_adapter_unavailable', 'retryable': True}))
            return {'status': 'DEFERRED_ADAPTER_UNAVAILABLE', 'activated': False}
        except Exception as failure:
            code = str(failure) if isinstance(failure, RefreshError) else 'scene_refresh_failed'
            write_file(directory / 'failure-report.json', encoded({'error': code, 'retryable': False}))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    settings = strict_json(pinned_read(args.config, args.config_sha256, 65536))
    root = args.root.resolve(); root.mkdir(parents=True, exist_ok=True)
    run = root / 'runs' / (str(int(time.time())) + '-' + secrets.token_hex(4))
    scratch = root / 'temporary'; scratch.mkdir(exist_ok=True)
    # Every adapter gets a fresh exclusive request/log directory.
    adapter_dir = scratch / run.name; adapter_dir.mkdir()
    with single_instance(root):
        report = SceneRefresher(root, settings, WranglerAdapter(settings['adapter'], adapter_dir)).once(run)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
