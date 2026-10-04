"""One local 112-location readiness screen, after release runtime qualification.

The result is not a server credential. No accounts, submissions, or automatic
approval thresholds exist here. A release-approved, hash-pinned policy is needed
before a complete diagnostic screen can become local readiness approval.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import sys
import time

from calibration.quality import decoded_difference
from calibration.run_windows import FIXTURE, verify_fixture
from .bootstrap import files_for_platform
from .four_view import BYTES_PER_LOCATION
from .vision_index import (REQUIRED_MODEL_FILES, THREAD_ENVIRONMENT_KEYS,
                           four_view_input, index_locations_tsv, require_complete_index)

LOCATIONS = 112
DLLS = ("DirectML.dll", "msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def runtime_profile(binary: Path, model_dir: Path, *, inference_threads=1):
    if type(inference_threads) is not int or inference_threads not in (1, 2, 4):
        raise ValueError("invalid_inference_threads")
    binary, model_dir = Path(binary), Path(model_dir)
    assets = {"binary": sha(binary)}
    for name in REQUIRED_MODEL_FILES:
        assets["models/" + name] = sha(model_dir / name)
    if sys.platform == "win32":
        for name in DLLS:
            assets["bin/" + name] = sha(binary.parent / name)
    spec = four_view_input(total=LOCATIONS, pace="slow", run_id="canary")
    settings = {key: spec[key] for key in ("chunkSize", "concurrency", "embeddingBatchSize",
                                         "imageEncoderSessions", "dutyCyclePercent", "thermalStateLimit", "sceneFp32")}
    profile = {"version": 1, "platform": sys.platform, "assets": assets,
               "settings": settings,
               "threads": {key: str(inference_threads) for key in THREAD_ENVIRONMENT_KEYS},
               "pipeline": {name: sha(Path(__file__).with_name(name))
                            for name in ("vision_index.py", "four_view.py", "process_owner.py")}}
    return {"sha256": fingerprint(profile), "profile": profile}


def canary_reference(policy=None):
    if policy is not None and policy.document['version'] == 2:
        inputs = policy.pinned_inputs()
        return inputs['referenceBytes'], {
            'fixtureSha256': policy.document['fixtureSha256'],
            'referenceSha256': policy.document['referenceSha256'],
            'parentReferenceSha256': policy.document['dataset']['parentReferenceSha256']}
    inventory = verify_fixture()
    manifest = json.loads((FIXTURE / "fixture-manifest.json").read_text())
    full = (FIXTURE / "historical-reference.i8").read_bytes()
    ordinals = manifest["canary_parent_ordinals_zero_based"]
    if len(ordinals) != LOCATIONS or len(set(ordinals)) != LOCATIONS:
        raise ValueError("invalid_canary_geometry")
    reference = b"".join(full[i * BYTES_PER_LOCATION:(i + 1) * BYTES_PER_LOCATION] for i in ordinals)
    return reference, {"fixtureSha256": inventory["canary-112.tsv"],
                       "referenceSha256": hashlib.sha256(reference).hexdigest(),
                       "parentReferenceSha256": inventory["historical-reference.i8"]}


class CanaryPolicy:
    """Caller must obtain this policy's expected hash from a trusted release."""
    def __init__(self, document):
        if (not isinstance(document, dict) or type(document.get("version")) is not int
                or document["version"] not in (1, 2)):
            raise ValueError("invalid_canary_policy")
        required_hashes = ("runtimeProfileSha256", "fixtureSha256", "referenceSha256")
        if any(not isinstance(document.get(key), str) or not re.fullmatch(r"[a-f0-9]{64}", document[key]) for key in required_hashes):
            raise ValueError("invalid_canary_policy")
        if not isinstance(document.get("policyId"), str) or not document["policyId"].strip():
            raise ValueError("invalid_canary_policy")
        qualification = document.get("fullCalibration", {})
        if (not isinstance(qualification, dict) or qualification.get("approved") is not True
                or qualification.get("locations") != 1024
                or type(qualification.get("repetitions")) is not int or qualification["repetitions"] < 3
                or not isinstance(qualification.get("evidenceSha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", qualification["evidenceSha256"])):
            raise ValueError("full_runtime_qualification_required")
        bounds = document.get("thresholds", {})
        if not isinstance(bounds, dict) or set(bounds) != {"minimumViewCosine", "maximumViewRelativeL2"}:
            raise ValueError("explicit_canary_thresholds_required")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds.values()):
            raise ValueError("invalid_canary_thresholds")
        if not -1 <= bounds["minimumViewCosine"] <= 1 or bounds["maximumViewRelativeL2"] < 0:
            raise ValueError("invalid_canary_thresholds")
        if document['version'] == 2:
            dataset = document.get('dataset')
            if (not isinstance(dataset, dict) or set(dataset) != {'fixture', 'reference', 'parentReferenceSha256'}
                    or not isinstance(dataset['parentReferenceSha256'], str)
                    or not re.fullmatch(r'[a-f0-9]{64}', dataset['parentReferenceSha256'])):
                raise ValueError('invalid_canary_dataset')
            for name in ('fixture', 'reference'):
                entry = dataset[name]
                if (not isinstance(entry, dict) or set(entry) != {'path', 'bytes', 'sha256'}
                        or not isinstance(entry['path'], str) or not entry['path']
                        or any(part in ('', '.', '..') or ':' in part or '\\' in part for part in entry['path'].split('/'))
                        or type(entry['bytes']) is not int or not 1 <= entry['bytes'] <= 512 * 1024
                        or entry['sha256'] != document[name + 'Sha256']):
                    raise ValueError('invalid_canary_dataset')
            if dataset['reference']['bytes'] != LOCATIONS * BYTES_PER_LOCATION:
                raise ValueError('invalid_canary_dataset')
        self.document = json.loads(json.dumps(document))
        self._source_root = None

    @classmethod
    def load(cls, path, expected_sha256):
        source = Path(path).absolute()
        if source.is_symlink() or getattr(source.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('linked_canary_policy')
        if not source.is_file() or source.stat().st_size > 1024 * 1024:
            raise ValueError('invalid_canary_policy_file')
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("canary_policy_checksum_mismatch")
        policy = cls(json.loads(raw))
        policy._source_root = source.parent
        return policy

    def pinned_inputs(self):
        """Read a release dataset with independent byte pins; never repair it.

        V2 may refresh source/reference without rewriting the historical fixture.
        It still fetches live imagery; it does not establish identical pixels.
        """
        if self.document['version'] != 2 or self._source_root is None:
            raise ValueError('canary_dataset_requires_pinned_policy_load')
        data = {}
        for name in ('fixture', 'reference'):
            entry = self.document['dataset'][name]
            path = self._source_root
            for part in (self._source_root, *[self._source_root.joinpath(*entry['path'].split('/')[:i])
                         for i in range(1, len(entry['path'].split('/')) + 1)]):
                info = part.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('linked_canary_dataset')
            path = path.joinpath(*entry['path'].split('/'))
            if not path.is_file() or path.stat().st_size != entry['bytes']:
                raise ValueError('canary_dataset_size_mismatch')
            raw = path.read_bytes()
            if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise ValueError('canary_dataset_checksum_mismatch')
            data[name + 'Bytes'] = raw
        rows = data['fixtureBytes'].splitlines()
        if (len(rows) != LOCATIONS or any(len(row.split(b'\t')) != 11 for row in rows)
                or len({row.split(b'\t')[7] for row in rows}) != LOCATIONS):
            raise ValueError('invalid_canary_dataset_geometry')
        decoded_difference(data['referenceBytes'], data['referenceBytes'])
        return data

    def evaluate(self, profile_sha256, identity, metrics):
        doc = self.document
        if doc["runtimeProfileSha256"] != profile_sha256:
            return False, "RUNTIME_PROFILE_NOT_QUALIFIED"
        if any(doc[key] != identity[key] for key in ("fixtureSha256", "referenceSha256")):
            return False, "CANARY_REFERENCE_NOT_QUALIFIED"
        bounds = doc["thresholds"]
        passed = (metrics["cosine_similarity"]["min"] >= bounds["minimumViewCosine"]
                  and metrics["relative_l2_error"]["max"] <= bounds["maximumViewRelativeL2"])
        return passed, "LOCAL_CANARY_PASSED" if passed else "OUTSIDE_OWNER_CANARY_BOUNDS"


def released_canary_policy(manifest, runtime_root):
    """Use only a policy/dataset pinned in the starter's trusted release manifest.

    No service-provided URL or locally supplied approval is used. An absent
    release entry keeps the legacy diagnostic; an invalid entry must fail.
    This optional manifest field is for the Windows guided starter.
    """
    if 'pcCanaryPolicy' not in manifest:
        return None
    entry = manifest['pcCanaryPolicy']
    if (not isinstance(entry, dict) or set(entry) != {'path', 'sha256'}
            or not isinstance(entry['path'], str) or not entry['path']
            or any(part in ('', '.', '..') or ':' in part or '\\' in part
                   for part in entry['path'].split('/'))
            or not isinstance(entry['sha256'], str)
            or not re.fullmatch(r'[a-f0-9]{64}', entry['sha256'])):
        raise ValueError('invalid_release_canary_policy')
    files = files_for_platform(manifest, 'windows-x86_64', lane='scene')
    def asset(path, checksum, size=None):
        matching = [v for v in files if v.get('path') == path]
        if (len(matching) != 1 or matching[0].get('sha256') != checksum
                or matching[0].get('executable')
                or type(matching[0].get('bytes')) is not int
                or not 0 < matching[0]['bytes'] <= 1024 * 1024
                or size is not None and matching[0]['bytes'] != size):
            raise ValueError('release_canary_asset_not_pinned')
        return matching[0]
    declared = asset(entry['path'], entry['sha256'])
    root = Path(runtime_root).absolute()
    # Reject linked roots and policy-parent directories before reading anything.
    parts = entry['path'].split('/')
    for path in (root, *[root.joinpath(*parts[:i]) for i in range(1, len(parts) + 1)]):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('linked_canary_policy')
    path = root.joinpath(*parts)
    if path.stat().st_size != declared['bytes']:
        raise ValueError('canary_policy_size_mismatch')
    policy = CanaryPolicy.load(path, entry['sha256'])
    if policy.document['version'] != 2:
        raise ValueError('release_canary_dataset_required')
    for name in ('fixture', 'reference'):
        value = policy.document['dataset'][name]
        relative = '/'.join(parts[:-1] + value['path'].split('/'))
        asset(relative, value['sha256'], value['bytes'])
    policy.pinned_inputs()
    return policy


def run_canary(work_dir: Path, *, binary: Path, model_dir: Path,
               policy: CanaryPolicy | None = None, inference_threads=1,
               progress_callback=None, indexer=None):
    """Write a fresh complete report, retaining failures; does not upload.

    Pass a new work_dir for each attempt. An absent policy still permits the
    user-requested diagnostic screen, but its result cannot enable indexing.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=False)
    report = {"version": 1, "status": "INCOMPLETE", "qualified": False,
              "locations": LOCATIONS, "views": LOCATIONS * 4,
              "reference": "HISTORICAL_REFERENCE_ONLY", "inputIdentity": "SOURCE_PIXELS_NOT_FROZEN",
              "serverAuthorization": False, "policyId": policy.document["policyId"] if policy else None}
    started = time.perf_counter()
    try:
        source_tsv = FIXTURE / 'canary-112.tsv'
        input_data = None
        if policy is not None and policy.document['version'] == 2:
            input_data = policy.pinned_inputs()
            # Index the already checked bytes in this attempt's private folder.
            # A later change to the release source cannot redirect native input.
            source_tsv = work / 'release-canary-112.tsv'
            source_tsv.write_bytes(input_data['fixtureBytes'])
            report['reference'] = 'RELEASE_PINNED_REFERENCE_LIVE_SOURCE_PIXELS'
        reference, identity = canary_reference(policy)
        profile = runtime_profile(binary, model_dir, inference_threads=inference_threads)
        report.update(identity=identity, runtimeProfile=profile)
        active = indexer or index_locations_tsv
        active(source_tsv, index_dir=work / "index", checkpoint=work / "checkpoint.json",
               output=work / "output.json", binary=binary, model_dir=model_dir, pace="slow",
               inference_threads=inference_threads, run_id="vision-user-canary-v1",
               progress_callback=progress_callback, use_nice=False)
        require_complete_index(work / "checkpoint.json", work / "index", LOCATIONS)
        blob = (work / "index/shard-000000.i8").read_bytes()
        if len(blob) != LOCATIONS * BYTES_PER_LOCATION:
            raise ValueError("invalid_canary_geometry")
        metrics = decoded_difference(blob, reference)
        report.update(status="COMPLETE", complete=True, payloadSha256=hashlib.sha256(blob).hexdigest(),
                      byteIdentical=blob == reference, decoded=metrics,
                      locationSha256=[hashlib.sha256(blob[i:i + BYTES_PER_LOCATION]).hexdigest()
                                      for i in range(0, len(blob), BYTES_PER_LOCATION)])
        # Explicit opt-in callers may submit this to the trusted qualification
        # endpoint. This module itself never transmits the packet.
        report["submission"] = {"profileId": profile["sha256"], "canary": {
            "version": 1, "locations": LOCATIONS, "views": LOCATIONS * 4,
            **identity, "runtimeProfile": profile, "outputSha256": report["payloadSha256"],
            "records": [base64.b64encode(blob[i:i + BYTES_PER_LOCATION]).decode("ascii")
                        for i in range(0, len(blob), BYTES_PER_LOCATION)]}}
        # Detect modifications while the test was running, before qualifying it.
        if runtime_profile(binary, model_dir, inference_threads=inference_threads) != profile:
            raise ValueError("runtime_changed_during_canary")
        if input_data is not None and (source_tsv.read_bytes() != input_data['fixtureBytes']
                                      or policy.pinned_inputs() != input_data):
            raise ValueError('canary_dataset_changed_during_check')
        if policy is None:
            report["decision"] = "OWNER_QUALIFICATION_POLICY_REQUIRED"
        else:
            report["qualified"], report["decision"] = policy.evaluate(profile["sha256"], identity, metrics)
    except (Exception, KeyboardInterrupt) as error:
        report.update(status="FAILED", qualified=False, error=getattr(error, "code", str(error)) or type(error).__name__)
        report.pop("submission", None)
    finally:
        report["wallSeconds"] = time.perf_counter() - started
        (work / "canary-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def canary_profile_matches(report, *, binary, model_dir, inference_threads=1):
    """Only freshness/completeness; server authorization is a separate check."""
    if not isinstance(report, dict) or report.get("status") != "COMPLETE":
        return False
    try:
        return report.get("runtimeProfile") == runtime_profile(binary, model_dir, inference_threads=inference_threads)
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description="One private 112-location PC canary; never uploads results")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--allow-live-imagery", action="store_true")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--policy-sha256")
    args = parser.parse_args()
    if not args.allow_live_imagery:
        parser.error("The 112-location test requires explicit live-imagery consent.")
    if bool(args.policy) != bool(args.policy_sha256):
        parser.error("A policy path and trusted policy SHA-256 must be supplied together.")
    policy = CanaryPolicy.load(args.policy, args.policy_sha256) if args.policy else None
    report = run_canary(args.root, binary=args.binary, model_dir=args.model_dir, policy=policy)
    print(json.dumps({key: report.get(key) for key in ("status", "qualified", "decision", "error")}, indent=2))
    print("Local report:", args.root / "canary-report.json")
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
