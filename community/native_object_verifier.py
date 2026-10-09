"""Operator-only, bounded native recomputation of a quarantined Object batch.

The assignment, policy and runtime pins must come from trusted operator state,
never from the uploader. This module has no account, publication or credit API.
It does not qualify a device or turn a diagnostic frozen replay into work.
"""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import re
import subprocess
import time

from calibration import compare_object_indexes as comparison
from . import native_scene_search as native
from .native_scene_verifier import source_pins
from .object_canary import runtime_profile, THREAD_MARKER, regular
from .object_index import (manifest_file_names, object_tsv_lines, source_id_for,
                           validate_object_index, verify_arguments, COMMON_MODEL_SHA256,
                           RUNTIME_IDENTITY, CODEBOOK_SHA256)
from .object_snapshot import VALIDATOR, public_manifest
from .process_owner import run_owned
from .protected_reference import ProtectedReference
from .search_snapshot import digest, encoded, file_digest, pinned_read, resource_for_environment
from .vision_index import THREAD_ENVIRONMENT_KEYS

MAX_MANIFEST = 1024 * 1024
MAX_FILES = 32_000_000
MAX_PROTECTED_SNAPSHOT = 64 * 1024 * 1024
# A 16-location Windows replay exceeded 900 seconds. Audit small batches under
# that same finite budget; do not silently extend a failed experiment's limit.
MAX_LOCATIONS = 4
MAX_SECONDS = 900
LANE_LIMITS = {
    'maximumScoreDifference': .001, 'maximumConfidenceDifference': .001,
    'maximumHeadingDegrees': .05, 'maximumPitchDegrees': .05,
    'maximumZoomDifference': .001, 'maximumAreaDifference': .001,
}
SEMANTIC_LIMITS = {
    'maximumBoxDifference': 2 / 65535,
    'maximumLogitShiftDifference': .01, 'maximumLogitScaleDifference': .01,
}


class ObjectAuditError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ObjectAuditError(code)


def read_json(path, pin):
    return native.strict_json(pinned_read(regular(path), pin, MAX_MANIFEST))


def bounds(document):
    require(isinstance(document, dict) and set(document) == {'lanes', 'semantic'}, 'invalid_object_audit_bounds')
    for group, ceilings in (('lanes', LANE_LIMITS), ('semantic', SEMANTIC_LIMITS)):
        values = document[group]
        require(isinstance(values, dict) and set(values) == set(ceilings), 'invalid_object_audit_bounds')
        require(all(type(values[k]) in (int, float) and math.isfinite(values[k])
                    and 0 <= values[k] <= maximum for k, maximum in ceilings.items()), 'invalid_object_audit_bounds')
    return document


def within(report, limits):
    """No missing hits, changed selections, quality masks or changed PQ codes.

    Only the explicitly named numerical fields may differ. In particular,
    bytewise PQ equality cannot be replaced by a loose average cosine score.
    """
    if report['viewQualityDifferences']:
        return False
    for entries in report['lanes'].values():
        for row in entries:
            if any(row[k] for k in ('missingRecords', 'extraRecords', 'discreteDifferences')):
                return False
            if any(row[k] > limit for k, limit in limits['lanes'].items()):
                return False
    semantic = report['semantic']
    return (not semantic['differentCodeBytes'] and not semantic['differentFaces']
            and all(semantic[k] <= limit for k, limit in limits['semantic'].items()))


def overlaps(left, right):
    return left == right or left in right.parents or right in left.parents


class NativeObjectVerifier:
    def __init__(self, binary, models, policy, policy_sha256):
        self.binary, self.models = regular(binary), regular(models, directory=True)
        self.policy_path, self.policy_sha256 = regular(policy), policy_sha256
        self.document = doc = read_json(self.policy_path, policy_sha256)
        require(isinstance(doc, dict) and doc.get('version') == 1
                and doc.get('scope') == 'trusted-native-object-audit'
                and isinstance(doc.get('policyId'), str)
                and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', doc['policyId'])
                and doc.get('sourceFiles') == source_pins(), 'invalid_object_audit_policy')
        environment = doc.get('environment')
        require(environment in ('staging', 'production')
                and doc.get('resource') == resource_for_environment(environment)
                and (not doc['policyId'].startswith('staging.') or environment == 'staging'),
                'object_audit_resource_mismatch')
        self.profile = runtime_profile(self.binary, self.models)
        require(doc.get('runtimeProfileSha256') == self.profile['sha256'], 'object_audit_runtime_mismatch')
        self.validate_model_paths()
        profiles = doc.get('profiles')
        require(isinstance(profiles, list) and 1 <= len(profiles) <= 16
                and all(isinstance(v, str) and native.HEX.fullmatch(v) for v in profiles)
                and len(set(profiles)) == len(profiles), 'invalid_object_audit_profiles')
        require(isinstance(doc.get('qualityImplementationIdentity'), str)
                and native.HEX.fullmatch(doc['qualityImplementationIdentity']), 'invalid_object_audit_quality')
        self.limits = bounds(doc.get('auditThresholds'))
        require(type(doc.get('maxLocations')) is int and 1 <= doc['maxLocations'] <= MAX_LOCATIONS
                and type(doc.get('timeoutSeconds')) is int and 1 <= doc['timeoutSeconds'] <= MAX_SECONDS,
                'invalid_object_audit_budget')
        authority = doc.get('protectedAuthority')
        require(isinstance(authority, dict) and set(authority) == {'path', 'bytes', 'sha256'}
                and isinstance(authority['path'], str) and Path(authority['path']).is_absolute()
                and type(authority['bytes']) is int and 0 < authority['bytes'] <= MAX_MANIFEST,
                'invalid_object_audit_authority')
        self.authority_path = regular(authority['path'])
        raw = pinned_read(self.authority_path, authority['sha256'], MAX_MANIFEST)
        require(len(raw) == authority['bytes'], 'invalid_object_audit_authority')
        authority_doc = native.strict_json(raw)
        # The native program also checks these database fingerprints before,
        # during and after inference. Keep independently supplied authority;
        # never invent a protected MMA database to make a fixture pass.
        require(isinstance(authority_doc, dict)
                and authority_doc.get('contract') == 'vision-gen4-inline-object-import-v1'
                and authority_doc.get('inlineQualityFilterRequired') is True
                and authority_doc.get('runtimeLiveProtectedFilterRequired') is True
                and isinstance(authority_doc.get('invariants'), dict)
                and isinstance(authority_doc.get('quality'), dict)
                and authority_doc.get('invariants', {}).get('protectedDatabaseFingerprintSealed') is True
                and authority_doc.get('quality', {}).get('currentTunnelEvidence') == 'none-darkness-never-rejects-v1',
                'unsupported_object_audit_authority')
        # External tunnel evidence needs its own independently sealed transport.
        # This first adapter supports blur filtering and always keeps darkness.
        require(authority_doc['quality'].get('tunnelEvidenceManifest') is None,
                'unsupported_object_audit_authority')
        self.authority_doc = authority_doc
        snapshot = authority_doc.get('protectedSnapshot')
        require(isinstance(snapshot, dict) and isinstance(snapshot.get('path'), str)
                and Path(snapshot['path']).is_absolute()
                and type(snapshot.get('bytes')) is int and 0 < snapshot['bytes'] <= MAX_PROTECTED_SNAPSHOT
                and isinstance(snapshot.get('sha256'), str) and native.HEX.fullmatch(snapshot['sha256']),
                'invalid_object_audit_protected_snapshot')
        self.snapshot_path = regular(snapshot['path'])
        self.verify_inputs()

    def validate_model_paths(self):
        # A pinned manifest must not redirect native reads to an unpinned file.
        doc = native.strict_json(comparison.read(self.models / 'hybrid-object-runtime.json', MAX_MANIFEST))
        expected = {'pq': {'file': ('owlv2-pq128-codebook.bin', 'sha256')},
            'owlv2': {key: (name, key.replace('File', 'SHA256')) for key, name in (
                ('visionFile', 'owlv2-vision-proposals.onnx'), ('textFile', 'owlv2-text-encoder.onnx'),
                ('tokenizerFile', 'owlv2-tokenizer.json'), ('vocabFile', 'owlv2-vocab.json'),
                ('mergesFile', 'owlv2-merges.txt'))},
            'yoloe': {'modelFile': ('yoloe-26l-hot.onnx', 'modelSHA256'),
                      'promptEmbeddingsFile': ('yoloe-26l-hot-prompts.npz', 'promptEmbeddingsSHA256')}}
        for group, fields in expected.items():
            require(isinstance(doc.get(group), dict), 'invalid_object_audit_models')
            for key, (filename, pin_key) in fields.items():
                require(doc[group].get(key) == filename and doc[group].get(pin_key)
                        == self.profile['profile']['assets']['models/' + filename], 'invalid_object_audit_models')
        require(self.profile['profile']['assets']['models/rfdetr-medium-576-b4.onnx'] == COMMON_MODEL_SHA256
                and doc['pq'].get('sha256') == CODEBOOK_SHA256, 'invalid_object_audit_models')

    def verify_inputs(self):
        require(read_json(self.policy_path, self.policy_sha256) == self.document
                and source_pins() == self.document['sourceFiles'], 'object_audit_policy_changed')
        require(runtime_profile(self.binary, self.models) == self.profile, 'object_audit_runtime_changed')
        authority = self.document['protectedAuthority']
        require(read_json(self.authority_path, authority['sha256']) == self.authority_doc,
                'object_audit_authority_changed')
        database = self.authority_doc.get('protectedDatabase')
        require(isinstance(database, dict) and set(database) == {'main', 'wal'}, 'invalid_object_audit_authority')
        require(isinstance(database['main'], dict) and database['main'].get('exists') is True,
                'invalid_object_audit_authority')
        for entry in database.values():
            require(isinstance(entry, dict) and isinstance(entry.get('path'), str)
                    and Path(entry['path']).is_absolute() and type(entry.get('exists')) is bool,
                    'invalid_object_audit_authority')
            path = Path(entry['path'])
            if not entry['exists']:
                regular(path.parent, directory=True)
                require(not path.exists() and not path.is_symlink(), 'object_audit_authority_changed')
                continue
            path = regular(path)
            require(path.stat().st_size == entry.get('bytes')
                    and path.stat().st_mtime_ns // 1_000_000 == entry.get('modifiedUnixMillis')
                    and file_digest(path) == entry.get('sha256'), 'object_audit_authority_changed')
        require(database['wal']['path'] == database['main']['path'] + '-wal', 'invalid_object_audit_authority')
        snapshot = self.authority_doc['protectedSnapshot']
        raw = pinned_read(regular(self.snapshot_path), snapshot['sha256'], MAX_PROTECTED_SNAPSHOT)
        require(len(raw) == snapshot['bytes'], 'object_audit_protected_snapshot_changed')
        self.protected = ProtectedReference(native.strict_json(raw), database=database['main']['path'])
        require(snapshot.get('generatedAt') == self.protected.generated_at,
                'invalid_object_audit_protected_snapshot')
        # The native inline-pool sealer permits one second because exporter
        # timestamps have second precision. Do not let a newer MMA fingerprint
        # bless an older coordinate snapshot.
        require(all(not entry['exists'] or entry['modifiedUnixMillis'] <= self.protected.generated_unix_millis + 1000
                    for entry in database.values()), 'object_audit_protected_snapshot_stale')

    def assignment(self, path, pin, source):
        doc = read_json(path, pin)
        require(isinstance(doc, dict) and doc.get('version') == 1
                and doc.get('scope') == 'trusted-object-assignment'
                and doc.get('policyId') == self.document['policyId']
                and doc.get('resource') == self.document['resource']
                and doc.get('profileId') in self.document['profiles']
                and isinstance(doc.get('leaseId'), str) and re.fullmatch('[0-9a-f]{32}', doc['leaseId'])
                and doc.get('sourceSha256') == digest(source), 'invalid_object_audit_assignment')
        rows = doc.get('records')
        require(isinstance(rows, list) and 1 <= len(rows) <= self.document['maxLocations'],
                'invalid_object_audit_assignment')
        ids = set()
        for row in rows:
            require(isinstance(row, dict) and type(row.get('locationId')) is int
                    and 0 < row['locationId'] < 2**53 and row['locationId'] not in ids
                    and row.get('cameraGeneration') == 'gen4' and row.get('coverageValidator') == VALIDATOR
                    and isinstance(row.get('coverageEvidenceSha256'), str)
                    and native.HEX.fullmatch(row['coverageEvidenceSha256']), 'invalid_object_audit_assignment')
            native.validate_pose(row, {row.get('country')}, member=True)
            require(not self.protected.contains(row['lat'], row['lng']), 'object_audit_protected_assignment')
            require(isinstance(row.get('country'), str) and 0 < len(row['country']) <= 100,
                    'invalid_object_audit_assignment')
            ids.add(row['locationId'])
        # Bind every TSV column, exact pose and binary64 spelling, road flags,
        # country/camera metadata and local/global allocation to trusted state.
        expected = ('\n'.join(object_tsv_lines(rows)) + '\n').encode('utf-8')
        require(source.replace(b'\r\n', b'\n') == expected, 'object_audit_assignment_source_mismatch')
        return doc

    def validate_index(self, directory, manifest_pin, source, assignment):
        directory = regular(directory, directory=True)
        doc = read_json(directory / 'manifest.json', manifest_pin)
        require(isinstance(doc, dict) and 'frozenViewsManifestSha256' not in doc, 'diagnostic_object_artifact')
        manifest = public_manifest(doc)
        quality = manifest.get('viewQuality')
        require(isinstance(quality, dict)
                and quality.get('implementationIdentity') == self.document['qualityImplementationIdentity']
                and quality.get('protectedAuthorityManifestSha256') == self.document['protectedAuthority']['sha256']
                and quality.get('tunnelEvidencePolicy') == 'none-darkness-never-rejects-v1', 'object_audit_quality_mismatch')
        require(all(doc.get(k, 0) == 0 for k in ('fetchErrors', 'inferenceErrors', 'permanentlyInvalidLocations')),
                'object_audit_incomplete_index')
        names = manifest_file_names(manifest)
        require(len(names) <= 87 and len(set(names)) == len(names), 'invalid_object_audit_index')
        files, remaining = {}, MAX_FILES
        for name in names:
            require(isinstance(name, str) and re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.bin', name),
                    'invalid_object_audit_index')
            files[name] = comparison.read(directory / name, remaining)
            remaining -= len(files[name])
        validate_object_index(manifest, files, source, assignment['records'], lease_id=assignment['leaseId'])
        return doc

    def run(self, command, job, timeout):
        job.mkdir(mode=0o700)
        environment = {k: v for k, v in os.environ.items() if k.upper() in ('SYSTEMROOT', 'WINDIR')}
        system_path = str(Path(os.environ.get('SYSTEMROOT', 'C:/Windows')) / 'System32') if os.name == 'nt' else '/usr/bin:/bin'
        environment.update(PATH=str(self.binary.parent) + os.pathsep + system_path,
                           HOME=str(job), TEMP=str(job), TMP=str(job), TMPDIR=str(job))
        environment.update({key: '1' for key in THREAD_ENVIRONMENT_KEYS})
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 0
        receipt = {'status': 'STARTED', 'timeoutSeconds': timeout,
                   'processOwnership': 'windows-job' if os.name == 'nt' else 'parent-pipe-session'}
        def save():
            temporary = job / 'exit.next'
            with temporary.open('xb') as stream:
                stream.write(encoded(receipt)); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, job / 'exit.json')
        save()
        started = time.monotonic()
        try:
            with (job / 'stdout.log').open('xb') as stdout, (job / 'stderr.log').open('xb') as stderr:
                result = run_owned(command, env=environment, cwd=job, stdout=stdout, stderr=stderr,
                                   timeout=timeout, creationflags=flags)
            receipt.update(status='EXITED', exitCode=result.returncode)
        except BaseException as error:
            receipt.update(status='FAILED', errorType=type(error).__name__)
            raise
        finally:
            receipt['wallSeconds'] = time.monotonic() - started
            save()
        require(result.returncode == 0, 'object_audit_native_failed')
        log = comparison.read(job / 'stderr.log', MAX_MANIFEST).decode('utf-8', errors='replace')
        require(THREAD_MARKER in log.splitlines(), 'object_audit_shared_pool_unconfirmed')
        return comparison.read(job / 'stdout.log', MAX_MANIFEST)

    def audit(self, *, assignment, assignment_sha256, source, candidate, candidate_sha256, out):
        out = Path(out).absolute()
        regular(out.parent, directory=True)
        inputs = [self.binary.parent, self.models, self.policy_path.parent, self.authority_path.parent,
                  self.snapshot_path.parent,
                  regular(assignment).parent, regular(source).parent, regular(candidate, directory=True)]
        inputs += [Path(v['path']).parent for v in self.authority_doc['protectedDatabase'].values()]
        require(not any(overlaps(out, root) for root in inputs), 'object_audit_output_overlaps_input')
        out.mkdir(mode=0o700, exist_ok=False)
        regular(out, directory=True)
        report = {'version': 1, 'scope': 'trusted-native-object-audit', 'status': 'INCOMPLETE',
                  'decision': 'pending', 'serverAuthorization': False, 'productionQualified': False,
                  'acceptedContributions': 0, 'searchCreditsCreated': 0, 'rawDataUploaded': False}
        started = time.monotonic()
        def save():
            path = out / 'audit-report.json'
            if path.exists() or path.is_symlink():
                regular(path)
            temporary = out / 'audit-report.next'
            with temporary.open('xb') as stream:
                stream.write(encoded(report)); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
        def remaining():
            value = self.document['timeoutSeconds'] - (time.monotonic() - started)
            require(value > 0, 'object_audit_timeout')
            return value
        try:
            save()
            self.verify_inputs()
            original_source = comparison.read(source, MAX_MANIFEST)
            trusted = self.assignment(assignment, assignment_sha256, original_source)
            self.validate_index(candidate, candidate_sha256, original_source, trusted)
            local_source = out / 'locations.tsv'
            local_source.write_bytes(original_source)
            target, cache = out / 'reference', out / 'cache'
            cache.mkdir(mode=0o700)
            total = len(trusted['records'])
            identity = source_id_for(trusted['leaseId'])
            info = native.strict_json(self.run([str(self.binary), 'runtime-info', '--model',
                str(self.models / 'rfdetr-medium-576-b4.onnx'), '--model-manifest',
                str(self.models / 'object-model.json'), '--runtime-manifest',
                str(self.models / 'hybrid-object-runtime.json')], out / 'runtime-check', remaining()))
            require(isinstance(info, dict) and info.get('valid') is True
                    and info.get('indexContractVersion') == 4 and info.get('searchContractVersion') == 2
                    and info.get('commonModelSHA256') == COMMON_MODEL_SHA256
                    and info.get('runtimeIdentity') == RUNTIME_IDENTITY
                    and info.get('viewQualityImplementationIdentity') == self.document['qualityImplementationIdentity'],
                    'object_audit_runtime_contract_mismatch')
            # All model paths and switches are selected here, not by a client.
            command = [str(self.binary), 'index-segment', '--model', str(self.models / 'rfdetr-medium-576-b4.onnx'),
                       '--model-manifest', str(self.models / 'object-model.json'), '--runtime-manifest',
                       str(self.models / 'hybrid-object-runtime.json'), '--source-tsv', str(local_source),
                       '--output-dir', str(target), '--source-id', identity, '--total-locations', str(total),
                       '--global-start', '0', '--cpu', '--quality-filter', '--protected-authority-manifest',
                       str(self.authority_path), '--duty-cycle-percent', '100', '--checkpoint-every', '1',
                       '--model-cache', str(cache)]
            self.run(command, out / 'inference', remaining())
            reference_pin = file_digest(regular(target / 'manifest.json'))
            self.validate_index(target, reference_pin, original_source, trusted)
            for label in ('verify-before', 'verify-after'):
                result = native.strict_json(self.run([str(self.binary), *verify_arguments(source_tsv=local_source,
                    output_dir=target, source_id=identity, total=total, global_start=0, full=True)],
                    out / label, remaining()))
                require(isinstance(result, dict) and result.get('valid') is True
                        and result.get('full') is True and result.get('indexVersion') == 4,
                        'object_audit_native_verification_failed')
                if label == 'verify-before':
                    measured = comparison.compare(target / 'manifest.json', reference_pin,
                        Path(candidate) / 'manifest.json', candidate_sha256, local_source)
            # Recheck independently pinned state and candidate after all native
            # work. A timeout, changed authority or partial output stays pending.
            self.verify_inputs()
            require(self.assignment(assignment, assignment_sha256, comparison.read(source, MAX_MANIFEST)) == trusted
                    and comparison.read(source, MAX_MANIFEST) == original_source, 'object_audit_inputs_changed')
            self.validate_index(candidate, candidate_sha256, original_source, trusted)
            self.validate_index(target, reference_pin, original_source, trusted)
            remaining()
            report.update(status='COMPLETE', decision='approved' if within(measured, self.limits) else 'rejected',
                          policyId=self.document['policyId'], policySha256=self.policy_sha256,
                          runtimeProfileSha256=self.profile['sha256'], sourceSha256=digest(original_source),
                          nativeReferenceRecomputed=True, assignmentSha256=assignment_sha256,
                          protectedSnapshotSha256=self.authority_doc['protectedSnapshot']['sha256'],
                          protectedAssignmentsChecked=True,
                          candidateManifestSha256=candidate_sha256, referenceManifestSha256=reference_pin,
                          locations=total, inputIdentity='LIVE_RETRIEVAL_NOT_FROZEN', comparison=measured)
        except (Exception, KeyboardInterrupt) as error:
            report.update(status='FAILED', decision='pending', errorType=type(error).__name__,
                          error=str(error) if isinstance(error, ObjectAuditError) else 'object_audit_unavailable')
        finally:
            report['wallSeconds'] = time.monotonic() - started
            save()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'models', 'policy', 'assignment', 'source', 'candidate', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('policy-sha256', 'assignment-sha256', 'candidate-sha256'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        verifier = NativeObjectVerifier(args.binary, args.models, args.policy, args.policy_sha256)
        result = verifier.audit(assignment=args.assignment, assignment_sha256=args.assignment_sha256,
            source=args.source, candidate=args.candidate, candidate_sha256=args.candidate_sha256, out=args.out)
    except (OSError, ValueError, KeyError, TypeError):
        print(encoded({'status': 'FAILED', 'decision': 'pending', 'error': 'object_audit_setup_failed'}).decode(), end='')
        return 1
    print(encoded(result).decode(), end='')
    return 0 if result['status'] == 'COMPLETE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
