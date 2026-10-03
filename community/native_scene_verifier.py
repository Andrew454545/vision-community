"""Private scene qualification and complete native recomputation auditing.

An independently pinned operator policy supplies measured bounds and admitted
runtime profiles. This service cannot invent approval from a client report.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import json
import math
import os
import re
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from calibration.quality import decoded_difference
from . import native_scene_search as native
from .four_view import BYTES_PER_LOCATION, SHARD_LOCATIONS, valid_four_view_record
from .pc_canary import CanaryPolicy
from .vision_index import VisionIndexError, require_scene_execution
from .search_snapshot import bounded_read, digest, encoded, file_digest, pinned_read, write_file

MAX_REQUEST = 6 * 1024 * 1024
MAX_LOCATIONS = 128
CANARY_LOCATIONS = 112


class VerificationError(ValueError):
    def __init__(self, code, status=503):
        super().__init__(code)
        self.status = status


def source_pins():
    root = Path(__file__).parent.parent
    return {p.relative_to(root).as_posix(): {"bytes": native.plain_path(p).stat().st_size, "sha256": file_digest(p)}
            for folder in (root / 'community', root / 'calibration') for p in sorted(folder.glob('*.py'))}


def field_bytes(raw, name):
    # JSON.stringify's Unicode/order/exponent bytes must survive qualification
    # and submission fingerprints. strict_json separately rejects duplicate keys.
    source = raw.decode('utf-8')
    decoder = json.JSONDecoder()
    position = source.index('{') + 1
    while True:
        while source[position].isspace() or source[position] == ',':
            position += 1
        if source[position] == '}':
            raise VerificationError('invalid_request', 400)
        key, position = decoder.raw_decode(source, position)
        while source[position].isspace():
            position += 1
        if source[position] != ':':
            raise VerificationError('invalid_request', 400)
        position += 1
        while source[position].isspace():
            position += 1
        start = position
        _, position = decoder.raw_decode(source, position)
        if key == name:
            return source[start:position].encode('utf-8')


def decode(value, size):
    if not isinstance(value, str) or len(value) > ((size + 2) // 3) * 4:
        raise VerificationError('invalid_submission', 422)
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise VerificationError('invalid_submission', 422) from None
    if len(result) != size or any(not valid_four_view_record(result[i:i+BYTES_PER_LOCATION])
                                 for i in range(0, size, BYTES_PER_LOCATION)):
        raise VerificationError('invalid_submission', 422)
    return result


def thresholds(value):
    if (not isinstance(value, dict) or set(value) != {'minimumViewCosine', 'maximumViewRelativeL2'}
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value.values())
            or not -1 <= value['minimumViewCosine'] <= 1 or value['maximumViewRelativeL2'] < 0):
        raise VerificationError('invalid_operator_thresholds')
    return value


def within(candidate, reference, bounds):
    measured = decoded_difference(candidate, reference)
    return (measured['cosine_similarity']['min'] >= bounds['minimumViewCosine']
            and measured['relative_l2_error']['max'] <= bounds['maximumViewRelativeL2'])


class NativeSceneVerifier:
    def __init__(self, runtime, runtime_sha256, policy, policy_sha256, work, *, timeout=50):
        if type(timeout) not in (int, float) or not 0 < timeout <= 50:
            raise VerificationError('invalid_audit_timeout')
        self.runtime = native.NativeSceneRuntime(runtime, runtime_sha256)
        self.policy_path = native.plain_path(policy)
        self.policy_sha256 = policy_sha256
        self.work = native.plain_path(work, directory=True)
        if any(root == self.work or root in self.work.parents
               for root in (self.runtime.runtime_root, self.policy_path.parent)):
            raise VerificationError('audit_work_overlaps_input')
        self.timeout = timeout
        self.busy = threading.BoundedSemaphore(1)
        policy = native.strict_json(pinned_read(self.policy_path, policy_sha256, 1024 * 1024))
        if (not isinstance(policy, dict) or policy.get('version') != 1
                or policy.get('scope') != 'trusted-native-scene-audit'
                or not isinstance(policy.get('policyId'), str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', policy['policyId'])
                or policy.get('runtimeSha256') != runtime_sha256
                or policy.get('sourceFiles') != source_pins()
                or not isinstance(policy.get('profiles'), list) or not 1 <= len(policy['profiles']) <= 16):
            raise VerificationError('invalid_operator_policy')
        self.document, self.policy_id = policy, policy['policyId']
        self.diagnostic_metrics = policy.get('diagnosticMetrics', False)
        if (type(self.diagnostic_metrics) is not bool or self.diagnostic_metrics and
                (not self.policy_id.startswith('staging.') or policy.get('deploymentEnvironment') != 'staging')):
            raise VerificationError('invalid_operator_diagnostics')
        self.bounds = thresholds(policy.get('auditThresholds'))
        self.max_locations = policy.get('maxAuditLocations', 8)
        if type(self.max_locations) is not int or not 1 <= self.max_locations <= MAX_LOCATIONS:
            raise VerificationError('invalid_audit_batch_limit')
        self.profiles = {}
        for definition in policy['profiles']:
            admitted = CanaryPolicy(definition)
            if definition['policyId'] != self.policy_id or definition['runtimeProfileSha256'] in self.profiles:
                raise VerificationError('invalid_operator_profiles')
            if ('expiresInSeconds' in definition and (type(definition['expiresInSeconds']) is not int
                    or not 0 < definition['expiresInSeconds'] <= 30 * 86400)):
                raise VerificationError('invalid_operator_profiles')
            thresholds(definition['thresholds'])
            self.profiles[definition['runtimeProfileSha256']] = admitted.document
        references = {v['referenceSha256'] for v in self.profiles.values()}
        if len(references) != 1:
            raise VerificationError('inconsistent_operator_references')
        self.reference_path = native.relative_file(self.policy_path.parent, 'canary-reference.i8')
        self.reference_sha256 = next(iter(references))
        self.reference = pinned_read(self.reference_path, self.reference_sha256, CANARY_LOCATIONS * BYTES_PER_LOCATION)
        # Reject damaged operator vectors at startup as service failure.
        try:
            decoded_difference(self.reference, self.reference)
        except ValueError:
            raise VerificationError('invalid_operator_reference') from None
        if len(self.reference) != CANARY_LOCATIONS * BYTES_PER_LOCATION:
            raise VerificationError('invalid_operator_reference')

    def verify_inputs(self):
        self.runtime.verify_runtime()
        if (file_digest(self.policy_path) != self.policy_sha256 or source_pins() != self.document['sourceFiles']
                or file_digest(self.reference_path) != self.reference_sha256):
            raise VerificationError('operator_inputs_changed')

    def qualify(self, body, raw_canary):
        self.verify_inputs()
        definition = self.profiles.get(body.get('profileId'))
        canary = body.get('canary')
        if (body.get('policyId') != self.policy_id or not definition or not isinstance(canary, dict)
                or any(canary.get(k) != definition[k] for k in ('fixtureSha256', 'referenceSha256'))
                or canary.get('locations') != CANARY_LOCATIONS or not isinstance(canary.get('records'), list)
                or len(canary['records']) != CANARY_LOCATIONS or digest(raw_canary) != body.get('canarySha256')):
            raise VerificationError('scene_device_not_qualified', 422)
        candidate = b''.join(decode(value, BYTES_PER_LOCATION) for value in canary['records'])
        try:
            approved = digest(candidate) == canary.get('outputSha256') and within(candidate, self.reference, definition['thresholds'])
        except ValueError:
            approved = False
        if not approved:
            raise VerificationError('scene_device_not_qualified', 422)
        self.verify_inputs()
        return {'approved': True, 'policyId': self.policy_id, 'profileId': body['profileId'],
                'canarySha256': body['canarySha256'],
                'expiresAt': int(time.time()) + definition.get('expiresInSeconds', 7 * 86400)}

    def validate_audit(self, body, raw_records):
        if (body.get('policyId') != self.policy_id or body.get('profileId') not in self.profiles
                or not isinstance(body.get('submissionSha256'), str)
                or not native.HEX.fullmatch(body['submissionSha256'])):
            raise VerificationError('invalid_submission', 422)
        records = body.get('records')
        if not isinstance(records, list) or not 1 <= len(records) <= self.max_locations:
            raise VerificationError('invalid_submission', 422)
        blob = decode(body.get('indexBase64'), len(records) * BYTES_PER_LOCATION)
        if digest(raw_records + b'\n' + blob) != body['submissionSha256']:
            raise VerificationError('invalid_submission', 422)
        try:
            decoded_difference(blob, blob)
        except ValueError:
            raise VerificationError('invalid_submission', 422) from None
        ids = set()
        for i, r in enumerate(records):
            if (not isinstance(r, dict) or type(r.get('locationId')) is not int or not 0 < r['locationId'] < 2**53
                    or r['locationId'] in ids or any(not isinstance(r.get(k), str) or not r[k]
                         or len(r[k]) > 1000 or any(ord(c) < 32 for c in r[k]) for k in ('assetId', 'capture', 'inputModel'))
                    or digest(blob[i*BYTES_PER_LOCATION:(i+1)*BYTES_PER_LOCATION]) != r.get('outputSha256')):
                raise VerificationError('invalid_submission', 422)
            try:
                native.validate_pose({**r, 'panoId': r['assetId']}, self.runtime.countries, member=True)
            except ValueError:
                raise VerificationError('invalid_submission', 422) from None
            ids.add(r['locationId'])
        return records, blob

    def audit(self, body, raw_records):
        self.verify_inputs()
        try:
            records, candidate = self.validate_audit(body, raw_records)
        except VerificationError as error:
            if error.status != 422:
                raise
            # A permanently invalid candidate must leave quarantine rejected,
            # rather than waiting forever as though native hosting is offline.
            result = {'policyId': self.policy_id, 'submissionSha256': body.get('submissionSha256'),
                      'decision': 'rejected'}
            if self.diagnostic_metrics:
                result['auditEvidence'] = {'version': 1, 'scope': 'private-staging-audit-measurements',
                                           'reason': 'invalid_submission'}
            return result
        if not self.busy.acquire(blocking=False):
            raise VerificationError('scene_auditor_busy')
        try:
            with tempfile.TemporaryDirectory(prefix='native-audit-', dir=self.work) as temporary:
                job = Path(temporary)
                reference = self.recompute(records, job)
                self.verify_inputs()
                measured = decoded_difference(candidate, reference)
                approved = (measured['cosine_similarity']['min'] >= self.bounds['minimumViewCosine']
                            and measured['relative_l2_error']['max'] <= self.bounds['maximumViewRelativeL2'])
            result = {'policyId': self.policy_id, 'submissionSha256': body['submissionSha256'],
                      'decision': 'approved' if approved else 'rejected'}
            if self.diagnostic_metrics:
                # Private operator evidence, without locations, pixels, tensors,
                # account details or native stderr. Changing live inputs remain
                # an explicit limit; these numbers cannot infer input identity.
                result['auditEvidence'] = {'version': 1, 'scope': 'private-staging-audit-measurements',
                    'reason': 'within_bounds' if approved else 'outside_bounds',
                    'inputIdentity': 'SOURCE_PIXELS_NOT_FROZEN', 'locations': len(records),
                    'views': len(records) * 4, 'nativeReferenceSha256': digest(reference),
                    'minimumViewCosine': measured['cosine_similarity']['min'],
                    'maximumViewRelativeL2': measured['relative_l2_error']['max']}
            return result
        except Exception:
            # Keep a fixed failure marker; never persist request/account/imagery
            # or inherited credentials. Native temporaries are always removed.
            marker = self.work / 'first-audit-failure.json'
            if not marker.exists():
                try:
                    write_file(marker, encoded({'ready': False, 'error': 'native_audit_unavailable'}))
                except FileExistsError:
                    pass
            raise
        finally:
            self.busy.release()

    def recompute(self, records, job):
        lines = ['\t'.join(str(v) for v in ('community-audit', r['locationId'], r['lat'], r['lng'],
                   r['heading'], r['pitch'], r['zoom'], r['assetId'], r['country'], r['cameraGeneration'], 'false')) + '\n' for r in records]
        source = job / 'locations.tsv'
        write_file(source, ''.join(lines).encode('utf-8'))
        spec = {'version': 1, 'runId': 'trusted-community-audit', 'totalLocations': len(records),
                'topK': 1, 'resultPruneMeters': 100, 'chunkSize': 16, 'concurrency': 8,
                'checkpointEvery': len(records), 'shardLocations': SHARD_LOCATIONS,
                'queries': [{'name': 'audit', 'query': 'a street view panorama', 'mode': 'textOnly',
                             'minSimilarity': .01, 'examples': []}],
                'embeddingBatchSize': 16, 'imageEncoderSessions': 1,
                'dutyCyclePercent': 100, 'thermalStateLimit': None, 'seedResults': None, 'sceneFp32': True}
        write_file(job / 'input.json', encoded(spec))
        index = job / 'index'
        command = [str(self.runtime.binary), 'index-four-views', '--input', str(job/'input.json'),
                   '--model-dir', str(self.runtime.models), '--locations-tsv', str(source),
                   '--index-dir', str(index), '--checkpoint', str(job/'checkpoint.json'), '--output', str(job/'output.json')]
        native.run_native(command, job, self.timeout)
        # A successful exit is insufficient when old binaries ignore sceneFp32.
        # This pinned host must actually use the requested graph and CPU pool.
        try:
            require_scene_execution(bounded_read(native.plain_path(job/'stderr.log'), 1024*1024).decode('utf-8'), 1)
        except VisionIndexError:
            raise VerificationError('native_audit_runtime_unavailable') from None
        checkpoint = native.strict_json(bounded_read(native.plain_path(job/'checkpoint.json'), native.MAX_NATIVE_OUTPUT))
        manifest = native.strict_json(bounded_read(native.plain_path(index/'manifest.json'), 1024*1024))
        if (any(checkpoint.get(k) != v for k, v in {'version': 4, 'totalLocations': len(records),
                'nextLocationIndex': len(records), 'completed': True, 'fetchErrors': 0,
                'inferenceErrors': 0, 'incompleteLocations': 0, 'sourceBytes': source.stat().st_size,
                'sourcePrefixHash': native.fnv_file(source), 'modelIdentity': native.model_identity(self.runtime.models)}.items())
                or any(manifest.get(k) != v for k, v in {'version': 4, 'totalLocations': len(records),
                       'indexedLocations': len(records), 'viewsPerLocation': 4, 'bytesPerLocation': BYTES_PER_LOCATION,
                       'completed': True, 'sourcePrefixHash': native.fnv_file(source),
                       'modelIdentity': native.model_identity(self.runtime.models)}.items())):
            raise VerificationError('native_audit_incomplete')
        mask = bounded_read(native.plain_path(index/'shard-000000.mask'), len(records))
        reference = bounded_read(native.plain_path(index/'shard-000000.i8'), len(records) * BYTES_PER_LOCATION)
        if mask != bytes([15]) * len(records) or len(reference) != len(records) * BYTES_PER_LOCATION:
            raise VerificationError('native_audit_incomplete')
        return reference


def make_server(verifier, secret, *, port=0):
    if not isinstance(secret, str) or not re.fullmatch(r'[\x21-\x7e]{32,256}', secret):
        raise VerificationError('private_verifier_secret_required')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def setup(self):
            super().setup()
            self.connection.settimeout(5)
        def reply(self, status, value):
            raw = encoded(value)
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + secret).encode()):
                native.discard_small_body(self)
                self.reply(401, {'error': 'unauthorized'})
                return
            if self.path not in ('/qualify', '/audit'):
                native.discard_small_body(self)
                self.reply(404, {'error': 'not_found'})
                return
            lengths = self.headers.get_all('Content-Length', [])
            if (len(lengths) != 1 or not re.fullmatch(r'[0-9]+', lengths[0]) or not 0 < int(lengths[0]) <= MAX_REQUEST
                    or self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'):
                self.reply(400, {'error': 'invalid_request'})
                return
            try:
                raw = self.rfile.read(int(lengths[0]))
                if len(raw) != int(lengths[0]):
                    raise VerificationError('invalid_request', 400)
                body = native.strict_json(raw)
                if not isinstance(body, dict):
                    raise VerificationError('invalid_request', 400)
                value = (verifier.qualify(body, field_bytes(raw, 'canary')) if self.path == '/qualify'
                         else verifier.audit(body, field_bytes(raw, 'records')))
                self.reply(200, value)
            except VerificationError as error:
                self.reply(error.status, {'error': str(error)})
            except (OSError, ValueError, KeyError, TypeError):
                self.reply(503, {'error': 'scene_verifier_unavailable'})
    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 8
        def __init__(self, *args):
            self.slots = threading.BoundedSemaphore(8)
            super().__init__(*args)
        def process_request(self, request, address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, address)
            except Exception:
                self.slots.release()
                raise
        def process_request_thread(self, request, address):
            try:
                super().process_request_thread(request, address)
            finally:
                self.slots.release()
    return Server(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime', 'policy', 'work'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('runtime-sha256', 'policy-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    args.work.mkdir(mode=0o700, parents=True, exist_ok=False)
    server = None
    try:
        verifier = NativeSceneVerifier(args.runtime, args.runtime_sha256, args.policy, args.policy_sha256, args.work)
        server = make_server(verifier, os.environ.get('VISION_SCENE_VERIFIER_SECRET', ''), port=args.port)
        print(encoded({'ready': True, 'bind': '127.0.0.1', 'port': server.server_port,
                       'scope': 'private-native-scene-verifier'}).decode(), flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception:
        print(encoded({'ready': False, 'error': 'private_verifier_start_failed'}).decode(), flush=True)
        return 1
    finally:
        if server is not None:
            server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
