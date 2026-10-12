"""Explicitly activated owner runner. Importing it never starts work.

No startup registration, credential provisioning, downloads or cloud changes.
The current operational cost hold forbids real activation. The local activation
file is an accidental-start guard, not proof of budget or release authority.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading

from .native_scene_search import plain_path, strict_json
from .owner_search_agent import HTTPSCoordinator, OwnerSearchAgent, OwnerSearchError, _exclusive
from .owner_search_credentials import canonical_origin
from .owner_search_supervisor import OwnerSearchSupervisor
from .search_snapshot import bounded_read, encoded, pinned_read, resource_for_environment

MAX_CONFIG = 16384
SCOPE = 'vision-owner-search-service-v1'
ACTIVATION = 'ACTIVATE.private.json'
HEX = re.compile(r'[0-9a-f]{64}\Z')
POLICY = re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')


class OwnerServiceError(ValueError):
    """Fixed error only; paths, keys, native diagnostics and prompts stay private."""


def require(value, code='owner_service_configuration_required'):
    if not value:
        raise OwnerServiceError(code)


def absolute_path(value):
    require(isinstance(value, str) and 0 < len(value) <= 2000
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))
    path = Path(value)
    require(path.is_absolute() and '..' not in path.parts)
    return path.absolute()


def overlaps(left, right):
    return left == right or left in right.parents or right in left.parents


def _load_configuration(path, checksum):
    """Validate only configuration, not native assets or OS credentials.

    Exact saved completion replay must remain possible with unavailable native
    assets. Full runtime, source, resource and snapshot checks run before the
    first new native search; stale pins can never be retargeted.
    """
    require(isinstance(checksum, str) and HEX.fullmatch(checksum))
    path = plain_path(absolute_path(str(path)))
    doc = strict_json(pinned_read(path, checksum, MAX_CONFIG))
    require(isinstance(doc, dict) and set(doc) == {'version', 'scope', 'origin', 'environment', 'state', 'lanes'}
            and type(doc['version']) is int and doc['version'] == 1 and doc['scope'] == SCOPE
            and doc['environment'] in {'staging', 'production'}
            and isinstance(doc['lanes'], dict) and 1 <= len(doc['lanes']) <= 2
            and not set(doc['lanes']) - {'scene', 'object'})
    require(canonical_origin(doc['origin']) == doc['origin'])
    state = plain_path(absolute_path(doc['state']), directory=True)
    source = Path(__file__).absolute().parents[1]
    require(not overlaps(state, source), 'owner_service_private_state_required')
    require(state not in path.parents and path != state, 'owner_service_configuration_overlaps_state')
    for lane, definition in doc['lanes'].items():
        keys = {'policyId', 'runtime', 'runtimeSha256', 'snapshot', 'snapshotSha256'}
        if lane == 'object': keys |= {'binary', 'models'}
        require(isinstance(definition, dict) and set(definition) == keys
                and isinstance(definition['policyId'], str) and POLICY.fullmatch(definition['policyId'])
                and all(isinstance(definition[k], str) and HEX.fullmatch(definition[k])
                        for k in ('runtimeSha256', 'snapshotSha256'))
                and (not definition['policyId'].startswith('staging.') or doc['environment'] == 'staging'))
        for key in ('runtime', 'snapshot', *(['binary', 'models'] if lane == 'object' else [])):
            item = absolute_path(definition[key])
            root = item.parent if key in {'runtime', 'binary'} else item
            require(not overlaps(state, root), 'owner_service_state_overlaps_input')
    return doc


def load_configuration(path, checksum):
    try:
        return _load_configuration(path, checksum)
    except OwnerServiceError:
        raise
    except Exception:
        raise OwnerServiceError('owner_service_configuration_required') from None


def check_activation(path, checksum, config):
    # This file must be deliberately created by an authorized future operator.
    # There is no activation command and no implicit marker/template writer.
    pinned_read(plain_path(path), checksum, MAX_CONFIG)
    state = plain_path(absolute_path(config['state']), directory=True)
    try:
        approved = strict_json(bounded_read(plain_path(state / ACTIVATION), 4096))
    except (OSError, ValueError):
        raise OwnerServiceError('owner_service_activation_required') from None
    require(approved == {'version': 1, 'scope': 'explicit-owner-search-activation', 'approved': True,
                         'configSha256': checksum, 'origin': config['origin'], 'environment': config['environment']}
            and type(approved.get('version')) is int and type(approved.get('approved')) is bool,
            'owner_service_activation_required')


class LazyCoordinator:
    def __init__(self, origin, guard):
        self.origin, self.guard, self.connection = origin, guard, None

    def post(self, action, body):
        self.guard()
        if self.connection is None:
            self.connection = HTTPSCoordinator.from_os_credentials(self.origin)
        self.guard()
        return self.connection.post(action, body)


class LazyEngine:
    def __init__(self, lane, definition, state, environment, guard):
        self.lane, self.definition, self.state, self.environment = lane, definition, state, environment
        self.guard, self.engine = guard, None

    def search(self, request, *, raw_query):
        self.guard()
        if self.engine is None:
            d = self.definition
            runtime = plain_path(Path(d['runtime']))
            snapshot = plain_path(Path(d['snapshot']), directory=True)
            config = strict_json(pinned_read(runtime, d['runtimeSha256'], 1024 * 1024))
            manifest = strict_json(pinned_read(plain_path(snapshot / 'snapshot.json'), d['snapshotSha256'], 1024 * 1024))
            require(isinstance(config, dict) and config.get('policyId') == d['policyId']
                    and type(config.get('contractVersion')) is int and config['contractVersion'] == 2
                    and isinstance(manifest, dict) and manifest.get('resource') == resource_for_environment(self.environment))
            if self.lane == 'object':
                require(config.get('environment') == self.environment
                        and config.get('resource') == resource_for_environment(self.environment))
            work = self.state / ('native-' + self.lane)
            try: work.mkdir(mode=0o700)
            except FileExistsError: pass
            plain_path(work, directory=True)
            if self.lane == 'scene':
                from .native_scene_search import NativeSceneEngine
                self.engine = NativeSceneEngine(runtime, d['runtimeSha256'], snapshot, d['snapshotSha256'],
                                                work, reuse_mount=True)
            else:
                from .native_object_search import NativeObjectSearchEngine
                self.engine = NativeObjectSearchEngine(Path(d['binary']), Path(d['models']), runtime,
                    d['runtimeSha256'], snapshot, d['snapshotSha256'], work)
        return self.engine.search(request, raw_query=raw_query)


class GuardedAgent:
    def __init__(self, agent, path, checksum, config):
        self.agent, self.state = agent, agent.state
        self.path, self.checksum, self.config = path, checksum, config

    def run_once(self):
        check_activation(self.path, self.checksum, self.config)
        return self.agent.run_once()


def failure_receipt(state):
    # First failure only, with no arbitrary exception detail or growing log.
    try:
        plain_path(state, directory=True)
        descriptor = os.open(state / 'owner-service.failure.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encoded({'success': False, 'error': 'owner_service_operator_required'}))
            stream.flush(); os.fsync(stream.fileno())
    except FileExistsError:
        pass
    except OSError:
        raise OwnerServiceError('owner_service_storage_unavailable') from None


def run_service(path, checksum, *, once=False, stop_event=None):
    """Future approved invocation only. The current cost hold forbids activation."""
    state = None
    try:
        require(type(once) is bool)
        config = load_configuration(path, checksum)
        state = plain_path(Path(config['state']), directory=True)
        if any((state / marker).exists() for marker in ('PAUSE', 'STOP')):
            return {'status': 'stopped' if (state / 'STOP').exists() else 'paused'}
        with _exclusive(state, name='service.lock'):
            check_activation(path, checksum, config)
            guard = lambda: check_activation(path, checksum, config)
            engines = {lane: LazyEngine(lane, definition, state, config['environment'], guard)
                       for lane, definition in config['lanes'].items()}
            bindings = {lane: {'contractVersion': 2, **{k: definition[k]
                         for k in ('policyId', 'runtimeSha256', 'snapshotSha256')}}
                        for lane, definition in config['lanes'].items()}
            agent = OwnerSearchAgent(LazyCoordinator(config['origin'], guard), engines, state, bindings=bindings)
            supervisor = OwnerSearchSupervisor(GuardedAgent(agent, path, checksum, config))
            return supervisor.step() if once else supervisor.run(stop_event or threading.Event())
    except OwnerSearchError as error:
        if error.code == 'owner_agent_busy':
            return {'status': 'busy'}
        if state is not None: failure_receipt(state)
        raise OwnerServiceError('owner_service_operator_required') from None
    except Exception:
        if state is not None: failure_receipt(state)
        raise OwnerServiceError('owner_service_operator_required') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description='Private owner search runner; requires explicit approved activation.')
    parser.add_argument('--config', required=True)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    stop, previous = threading.Event(), {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, lambda *_: stop.set())
        result = run_service(args.config, args.config_sha256, once=args.once, stop_event=stop)
        status = 2 if result['status'] == 'operator_required' else 0
    except (Exception, KeyboardInterrupt):
        result, status = {'status': 'operator_required', 'error': 'owner_service_operator_required'}, 1
    finally:
        for signum, handler in previous.items(): signal.signal(signum, handler)
    if sys.stdout is not None:
        sys.stdout.write(json.dumps(result) + '\n')
    return status
