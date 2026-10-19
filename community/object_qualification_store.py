"""Offline owned sample delivery and pinned private job lookup; no inference.

An operator supplies the destination-specific approval and catalog pins. Neither
is an uploader assertion or created by this module. Nothing is downloaded,
published, credited, deleted or automatically added to the trusted catalog.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import time

from .native_scene_search import strict_json
from .object_canary import fingerprint, regular, relative
from .object_index_qualification import ObjectIndexQualifier
from .object_qualification import checksum, integer, require, ObjectQualificationError
from .object_qualification_evidence import SavedObjectQualificationEvidence, ID
from .owner_search_agent import _exclusive
from .search_snapshot import digest, encoded, pinned_read

MAX_DOCUMENT = 65536
MAX_FILES = 96
MAX_BYTES = 40 * 1024**2
MAX_JOBS = 32
MAX_SECONDS = 65
CHECKOUT = Path(__file__).absolute().parent.parent


def private_directory(path):
    path = regular(path, directory=True)
    require(not path.is_relative_to(CHECKOUT), 'object_sample_private_directory_required')
    return path


def path_identity(path):
    return fingerprint({'absolutePath': os.path.normcase(str(Path(path).absolute()))})


def job_identity(value):
    return fingerprint({k: value[k] for k in ('accountId', 'requestId', 'profileId', 'artifactSetSha256')})


def identity(value):
    return all(isinstance(value.get(k), str) and ID.fullmatch(value[k]) for k in ('accountId', 'requestId')) \
        and all(checksum(value.get(k)) for k in ('profileId', 'artifactSetSha256', 'policySha256'))


def read(path, sha256, limit=MAX_DOCUMENT):
    return strict_json(pinned_read(regular(path), sha256, limit))


def safe_name(value):
    # Case-folded collisions, Windows devices and alternate data streams must
    # have the same meaning on both supported platforms.
    return relative(value) and all(not re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?', p, re.I)
        for p in value.split('/'))


def inventory(root, entries):
    require(isinstance(entries, list) and 1 <= len(entries) <= MAX_FILES, 'invalid_object_sample_delivery')
    result, used, names = {}, 0, set()
    for entry in entries:
        require(isinstance(entry, dict) and set(entry) == {'path', 'bytes', 'sha256'} and safe_name(entry['path'])
            and entry['path'].casefold() not in ('package.json', 'delivery.json')
            and integer(entry['bytes'], 0, MAX_BYTES) and checksum(entry['sha256']), 'invalid_object_sample_delivery')
        name = entry['path'].casefold()
        require(name not in names and not any(name.startswith(n + '/') or n.startswith(name + '/') for n in names),
            'invalid_object_sample_delivery')
        names.add(name)
        used += entry['bytes']
        require(used <= MAX_BYTES, 'object_sample_delivery_limit')
        path = regular(root / entry['path'])
        require(path.stat().st_size == entry['bytes'], 'object_sample_delivery_changed')
        pinned_read(path, entry['sha256'], entry['bytes'])
        result[entry['path']] = entry
    return result


def closed_artifacts(root, doc, files):
    pin = doc['artifacts']
    require(isinstance(pin, dict) and set(pin) == {'path', 'bytes', 'sha256'} and files.get(pin['path']) == pin
        and pin['sha256'] == doc['artifactSetSha256'], 'invalid_object_sample_artifacts')
    artifacts = read(root / pin['path'], pin['sha256'], 16384)
    require(isinstance(artifacts, dict) and set(artifacts) == {'version', 'scope', 'accountId', 'requestId',
        'profileId', 'scoreRequest', 'indexManifest', 'executionReceipt'} and type(artifacts['version']) is int
        and artifacts['version'] == 1 and artifacts['scope'] == 'trusted-owned-object-sample-artifacts-v1'
        and all(artifacts[k] == doc[k] for k in ('accountId', 'requestId', 'profileId')), 'invalid_object_sample_artifacts')
    parent = Path(pin['path']).parent
    expected = {pin['path']}
    for name, maximum in (('scoreRequest', 8 * 1024**2), ('indexManifest', 1024**2), ('executionReceipt', 16384)):
        entry = artifacts[name]
        require(isinstance(entry, dict) and set(entry) == {'path', 'bytes', 'sha256'} and safe_name(entry['path'])
            and integer(entry['bytes'], 1, maximum) and checksum(entry['sha256']), 'invalid_object_sample_artifacts')
        path = (parent / entry['path']).as_posix()
        require(files.get(path) == {**entry, 'path': path} and path not in expected, 'incomplete_object_sample_delivery')
        expected.add(path)
    index_pin = artifacts['indexManifest']
    index_path = parent / index_pin['path']
    index = read(root / index_path, index_pin['sha256'], 1024**2)
    require(isinstance(index, dict) and isinstance(index.get('classes'), list) and len(index['classes']) == 80
        and isinstance(index.get('hotConcepts'), list) and len(index['hotConcepts']) == 2, 'invalid_object_sample_artifacts')
    for entry in [index.get(k) for k in ('offsets', 'metadata', 'globalIds', 'semantic', 'viewQuality')] \
            + index['classes'] + index['hotConcepts']:
        require(isinstance(entry, dict) and safe_name(entry.get('file')) and integer(entry.get('bytes'), 0, MAX_BYTES)
            and checksum(entry.get('sha256')), 'invalid_object_sample_artifacts')
        path = (index_path.parent / entry['file']).as_posix()
        require(files.get(path) == {'path': path, 'bytes': entry['bytes'], 'sha256': entry['sha256']}
            and path not in expected, 'incomplete_object_sample_delivery')
        expected.add(path)
    require(set(files) == expected, 'unrelated_object_sample_delivery_files')


def paused(root):
    require(not (root / 'PAUSE').exists() and not (root / 'PAUSE').is_symlink(), 'object_sample_host_paused')


def deliver_owned_sample(package, package_sha256, approval, approval_sha256, destination, *, now=None):
    """Copy only a finite sealed local package, after an independent approval.

    The caller must already have legitimate transfer consent. Approval records
    are trusted operator inputs, not a mechanism for granting that consent.
    A failed partial copy is retained and blocks automatic retry/overwrite.
    """
    try:
        root = private_directory(destination)
        with _exclusive(root, name='service.lock'):
            return _deliver(package, package_sha256, approval, approval_sha256, root, now=now)
    except ObjectQualificationError:
        raise
    except Exception:
        raise ObjectQualificationError('object_sample_delivery_unavailable') from None


def _deliver(package, package_sha256, approval, approval_sha256, destination, *, now):
    try:
        started = time.monotonic()
        current = int(time.time()) if now is None else now
        require(integer(current, 0, 8640000000000), 'invalid_object_sample_delivery')
        root = private_directory(destination)
        source = private_directory(Path(package).absolute().parent)
        require(not root.is_relative_to(source) and not source.is_relative_to(root), 'object_sample_delivery_overlap')
        paused(root)
        raw = pinned_read(regular(package), package_sha256, MAX_DOCUMENT)
        doc = strict_json(raw)
        require(isinstance(doc, dict) and set(doc) == {'version', 'scope', 'accountId', 'requestId', 'profileId',
            'artifactSetSha256', 'policySha256', 'artifacts', 'files'} and type(doc['version']) is int and doc['version'] == 1
            and doc['scope'] == 'sealed-owned-object-sample-delivery-v1' and identity(doc), 'invalid_object_sample_delivery')
        consent = read(approval, approval_sha256, 16384)
        keys = {'version', 'scope', 'accountId', 'requestId', 'profileId', 'artifactSetSha256', 'policySha256',
            'packageSha256', 'sourceRootSha256', 'destinationRootSha256', 'validFrom', 'validUntil'}
        require(isinstance(consent, dict) and set(consent) == keys and type(consent['version']) is int and consent['version'] == 1
            and consent['scope'] == 'operator-approved-private-object-sample-delivery-v1'
            and all(consent[k] == doc[k] for k in ('accountId', 'requestId', 'profileId', 'artifactSetSha256', 'policySha256'))
            and consent['packageSha256'] == package_sha256 and consent['sourceRootSha256'] == path_identity(source)
            and consent['destinationRootSha256'] == path_identity(root)
            and integer(consent['validFrom'], 0, current) and integer(consent['validUntil'], current + 1, consent['validFrom'] + 30 * 86400),
            'object_sample_delivery_approval_required')
        files = inventory(source, doc['files'])
        closed_artifacts(source, doc, files)
        job = job_identity(doc)
        target, partial = root / job, root / ('.partial-' + job)
        require(not target.exists() and not partial.exists(), 'object_sample_delivery_exists')
        require(len([p for p in root.iterdir() if p.name != 'service.lock']) < MAX_JOBS, 'object_sample_store_full')
        # No recursive deletion, no existing file mutation, no uploader-chosen
        # destination. Atomic rename makes only a fully checked package visible.
        partial.mkdir(mode=0o700)
        for entry in files.values():
            target_file = partial / entry['path']
            target_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            payload = pinned_read(regular(source / entry['path']), entry['sha256'], entry['bytes'])
            with target_file.open('xb') as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        with (partial / 'package.json').open('xb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        inventory(partial, doc['files'])
        require(pinned_read(regular(package), package_sha256, MAX_DOCUMENT) == raw
            and read(approval, approval_sha256, 16384) == consent, 'object_sample_delivery_changed')
        paused(root)
        require(time.monotonic() - started < MAX_SECONDS
            and current + int(time.monotonic() - started) < consent['validUntil'], 'object_sample_delivery_timeout')
        receipt = {'version': 1, 'scope': 'delivered-owned-object-sample-v1', 'jobId': job,
            'accountId': doc['accountId'], 'requestId': doc['requestId'], 'profileId': doc['profileId'],
            'artifactSetSha256': doc['artifactSetSha256'], 'policySha256': doc['policySha256'],
            'packageSha256': package_sha256, 'approvalSha256': approval_sha256,
            'destinationRootSha256': path_identity(root), 'deliveredAt': current, 'expiresAt': consent['validUntil']}
        value = encoded(receipt)
        with (partial / 'delivery.json').open('xb') as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        require(not target.exists(), 'object_sample_delivery_exists')
        partial.rename(target)
        # This pin is only for a separately installed operator catalog. It is
        # not an account qualification or a saved execution identity receipt.
        return {'jobId': job, 'receipt': {'path': job + '/delivery.json', 'bytes': len(value), 'sha256': digest(value)}}
    except ObjectQualificationError:
        raise
    except Exception:
        raise ObjectQualificationError('object_sample_delivery_unavailable') from None


class OwnedObjectQualificationStore:
    """Read-only lookup under a pinned, bounded trusted operator catalog."""
    def __init__(self, comparator, root, catalog, catalog_sha256):
        require(isinstance(comparator, ObjectIndexQualifier), 'invalid_object_sample_comparator')
        self.comparator, self.root = comparator, private_directory(root)
        self.catalog, self.catalog_sha256 = regular(catalog), catalog_sha256
        require(not self.catalog.is_relative_to(self.root) and not self.catalog.is_relative_to(CHECKOUT),
            'object_sample_private_catalog_required')
        self._catalog(int(time.time()), check_time=False)

    def _catalog(self, now, *, check_time=True):
        paused(self.root)
        doc = read(self.catalog, self.catalog_sha256)
        p = self.comparator
        require(isinstance(doc, dict) and set(doc) == {'version', 'scope', 'rootSha256', 'policySha256', 'resource', 'jobs'}
            and type(doc['version']) is int and doc['version'] == 1 and doc['scope'] == 'trusted-owned-object-sample-jobs-v1'
            and doc['rootSha256'] == path_identity(self.root) and doc['policySha256'] == p.policy_sha256
            and doc['resource'] == p.scores.policy['resource'] and isinstance(doc['jobs'], list)
            and len(doc['jobs']) <= MAX_JOBS, 'invalid_object_sample_catalog')
        seen = set()
        for entry in doc['jobs']:
            pin = entry.get('receipt') if isinstance(entry, dict) else None
            require(isinstance(entry, dict) and set(entry) == {'jobId', 'receipt'} and checksum(entry['jobId'])
                and entry['jobId'] not in seen and isinstance(pin, dict) and set(pin) == {'path', 'bytes', 'sha256'}
                and pin['path'] == entry['jobId'] + '/delivery.json' and integer(pin['bytes'], 1, 16384)
                and checksum(pin['sha256']), 'invalid_object_sample_catalog')
            seen.add(entry['jobId'])
        if check_time:
            require(p.scores.policy['validFrom'] <= now < p.scores.policy['validUntil'], 'object_sample_policy_expired')
        return doc

    def evidence(self, request, *, now=None):
        try:
            started = time.monotonic()
            current = int(time.time()) if now is None else now
            require(integer(current, 0, 8640000000000) and isinstance(request, dict) and set(request) == {
                'version', 'accountId', 'requestId', 'challenge', 'profileId', 'artifactSetSha256', 'policyId', 'policySha256'}
                and type(request['version']) is int and request['version'] == 1 and identity(request)
                and isinstance(request['challenge'], str) and ID.fullmatch(request['challenge'])
                and request['policyId'] == self.comparator.policy['policyId']
                and request['policySha256'] == self.comparator.policy_sha256
                and request['profileId'] in self.comparator.scores.policy['profiles'], 'invalid_object_sample_request')
            catalog = self._catalog(current)
            job = job_identity(request)
            entry = next((j for j in catalog['jobs'] if j['jobId'] == job), None)
            require(entry is not None, 'object_sample_job_unavailable')
            pin = entry['receipt']
            folder = regular(self.root / job, directory=True)
            receipt_path = regular(self.root / pin['path'])
            require(receipt_path.stat().st_size == pin['bytes'], 'object_sample_delivery_changed')
            receipt = read(receipt_path, pin['sha256'], 16384)
            require(isinstance(receipt, dict) and set(receipt) == {'version', 'scope', 'jobId', 'accountId', 'requestId',
                'profileId', 'artifactSetSha256', 'policySha256', 'packageSha256', 'approvalSha256', 'destinationRootSha256',
                'deliveredAt', 'expiresAt'} and type(receipt['version']) is int and receipt['version'] == 1
                and receipt['scope'] == 'delivered-owned-object-sample-v1' and receipt['jobId'] == job
                and all(receipt[k] == request[k] for k in ('accountId', 'requestId', 'profileId', 'artifactSetSha256', 'policySha256'))
                and checksum(receipt['packageSha256']) and checksum(receipt['approvalSha256'])
                and receipt['destinationRootSha256'] == path_identity(self.root)
                and integer(receipt['deliveredAt'], 0, current)
                and integer(receipt['expiresAt'], current + 1, receipt['deliveredAt'] + 30 * 86400), 'object_sample_delivery_expired')
            package = read(folder / 'package.json', receipt['packageSha256'])
            require(isinstance(package, dict) and package.get('scope') == 'sealed-owned-object-sample-delivery-v1'
                and all(package.get(k) == request[k] for k in ('accountId', 'requestId', 'profileId', 'artifactSetSha256', 'policySha256')),
                'object_sample_delivery_changed')
            files = inventory(folder, package['files'])
            closed_artifacts(folder, package, files)
            adapter = SavedObjectQualificationEvidence(self.comparator, folder / package['artifacts']['path'], request['artifactSetSha256'])
            value = adapter.evidence(request, now=current + int(time.monotonic() - started))
            inventory(folder, package['files'])
            elapsed = time.monotonic() - started
            require(elapsed < MAX_SECONDS and self._catalog(current + int(elapsed)) == catalog
                and read(receipt_path, pin['sha256'], 16384) == receipt
                and read(folder / 'package.json', receipt['packageSha256']) == package
                and current + int(elapsed) < value['expiresAt'], 'object_sample_authority_changed')
            return value
        except ObjectQualificationError:
            raise
        except Exception:
            raise ObjectQualificationError('object_sample_host_unavailable') from None
