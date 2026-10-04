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
import shutil
import stat
import sys
import time

from calibration.quality import decoded_difference
from calibration.run_windows import FIXTURE, verify_fixture
from .bootstrap import files_for_platform
from .four_view import BYTES_PER_LOCATION
from .vision_index import (REQUIRED_MODEL_FILES, THREAD_ENVIRONMENT_KEYS,
                           default_runner, inference_environment,
                           four_view_input, index_locations_tsv, require_complete_index)

LOCATIONS = 112
DLLS = ("DirectML.dll", "msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll")
SYNTHETIC_GENERATOR = Path(__file__).resolve().parents[1] / 'calibration/synthetic_canary.py'


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
    if policy is not None and policy.document['version'] in (2, 3):
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
                or document["version"] not in (1, 2, 3)):
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
        if document['version'] in (2, 3):
            dataset = document.get('dataset')
            expected = {'fixture', 'reference', 'parentReferenceSha256'}
            if document['version'] == 3:
                expected.add('syntheticInputs')
            if (not isinstance(dataset, dict) or set(dataset) != expected
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
            if document['version'] == 3:
                synthetic = dataset['syntheticInputs']
                if (not isinstance(synthetic, dict)
                        or set(synthetic) != {'generatorVersion', 'generatorSha256', 'manifestSha256'}
                        or type(synthetic['generatorVersion']) is not int or synthetic['generatorVersion'] != 1
                        or any(not isinstance(synthetic[k], str) or not re.fullmatch(r'[a-f0-9]{64}', synthetic[k])
                               for k in ('generatorSha256', 'manifestSha256'))):
                    raise ValueError('invalid_synthetic_canary_policy')
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
        It still fetches live imagery; V3 pins generated RGB inputs as well.
        """
        if self.document['version'] not in (2, 3) or self._source_root is None:
            raise ValueError('canary_dataset_requires_pinned_policy_load')
        if self.document['version'] == 3:
            info = SYNTHETIC_GENERATOR.lstat()
            if (not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
                    or sha(SYNTHETIC_GENERATOR) != self.document['dataset']['syntheticInputs']['generatorSha256']):
                raise ValueError('synthetic_canary_generator_not_pinned')
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
    if policy.document['version'] not in (2, 3):
        raise ValueError('release_canary_dataset_required')
    for name in ('fixture', 'reference'):
        value = policy.document['dataset'][name]
        relative = '/'.join(parts[:-1] + value['path'].split('/'))
        asset(relative, value['sha256'], value['bytes'])
    policy.pinned_inputs()
    return policy


def index_synthetic_canary(source_tsv, *, index_dir, checkpoint, output, binary, model_dir,
                           inference_threads, run_id, sealed_rgb, sealed_sha256,
                           progress_callback=None, **unused):
    """Run only the private fixed readiness input, through the existing owner.

    This does not replace the ordinary contribution fetch path or query ranker.
    """
    work = Path(index_dir).parent
    spec = four_view_input(total=LOCATIONS, pace='slow', run_id=run_id)
    input_path = work/'synthetic-input.json'
    input_path.write_text(json.dumps(spec,indent=2)+'\n',encoding='utf-8')
    if progress_callback:
        progress_callback({'event':'indexing','completedLocations':0,'totalLocations':LOCATIONS})
    argv = [str(binary), 'study-four-views', '--input', str(input_path), '--model-dir', str(model_dir),
            '--locations-tsv', str(source_tsv), '--index-dir', str(index_dir), '--checkpoint', str(checkpoint),
            '--output', str(output), '--evidence-dir', str(work/'synthetic-evidence'),
            '--evidence-budget-mib', '384', '--scene-fp32', '--sealed-rgb', str(sealed_rgb),
            '--sealed-sha256', sealed_sha256]
    code, _stdout, stderr = default_runner(argv,inference_environment(work,inference_threads),work)
    if code:
        raise ValueError('synthetic_canary_native_failed')
    # study-four-views reports its graph in structured evidence. Its stderr
    # omits the ordinary index command's explicit-input graph message.
    witness = work/'synthetic-evidence/scene-evidence.json'
    if witness.stat().st_size > 1024**2:
        raise ValueError('synthetic_canary_native_witness_invalid')
    evidence = json.loads(witness.read_text(encoding='utf-8'))
    shapes = {'pixel-values':[3,224,224],'pooler-output':[768],'normalized':[768]}
    expected_models = [{'name':name,'bytes':(Path(model_dir)/name).stat().st_size,'sha256':sha(Path(model_dir)/name)}
                       for name in ('text_model.onnx','tokenizer.json','vision_model.onnx','vision_model_fp32.onnx')]
    expected_source = {'name':'locations.tsv','bytes':Path(source_tsv).stat().st_size,'sha256':sha(source_tsv)}
    frames = json.loads((sealed_rgb/'manifest.json').read_text(encoding='utf-8'))['frames']
    tensors = evidence.get('tensors',[])
    if (f'[vision] ONNX Runtime global threads: {inference_threads}, spinning disabled' not in stderr.splitlines()
            or evidence.get('schemaVersion') != 1 or evidence.get('status') != 'NATIVE_SCENE_STUDY_COMPLETED_UNQUALIFIED'
            or evidence.get('selectedImageGraph') != 'vision_model_fp32.onnx'
            or evidence.get('modelFiles') != expected_models or evidence.get('sourceTsv') != expected_source
            or evidence.get('frames') != frames or len(frames) != LOCATIONS*4 or len(tensors) != LOCATIONS*12
            or any(t.get('event') not in shapes or t.get('shape') != shapes[t['event']]
                   or t.get('dtype') != 'float32-little-endian' for t in tensors)
            or {(t['ordinal'],t['view'],t['event']) for t in tensors} !=
               {(i,v,event) for i in range(LOCATIONS) for v in range(4) for event in shapes}):
        raise ValueError('synthetic_canary_native_witness_invalid')
    result = json.loads(Path(output).read_text(encoding='utf-8'))
    if (result.get('completed') is not True or result.get('nextLocationIndex') != LOCATIONS
            or result.get('totalLocations') != LOCATIONS
            or any(result.get(k) != 0 for k in ('fetchErrors','inferenceErrors','incompleteLocations'))):
        raise ValueError('synthetic_canary_incomplete')
    if progress_callback:
        progress_callback({'event':'complete','completedLocations':LOCATIONS,'totalLocations':LOCATIONS})


def verify_synthetic_inputs(root, expected_sha256):
    """Require the complete fixed RGB inventory before and after native use."""
    manifest_path = root/'manifest.json'
    for path, kind in ((root,stat.S_ISDIR),(manifest_path,stat.S_ISREG)):
        info = path.lstat()
        if not kind(info.st_mode) or getattr(info,'st_file_attributes',0) & 0x400:
            raise ValueError('linked_synthetic_canary_inputs')
    if sha(manifest_path) != expected_sha256:
        raise ValueError('synthetic_canary_manifest_changed_during_check')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    expected = {'manifest.json'}
    frames = manifest.get('frames', [])
    seen = set()
    for frame in frames:
        ordinal,view = frame['ordinal'],frame['view']
        name = f'scene-{ordinal:04}-view-{view}.rgb'
        entry = frame['rgb']
        if (type(ordinal) is not int or type(view) is not int or ordinal not in range(LOCATIONS)
                or view not in range(4) or (ordinal,view) in seen
                or entry['name'] != name or entry['bytes'] != 224*224*3):
            raise ValueError('invalid_synthetic_canary_inventory')
        seen.add((ordinal,view))
        expected.add(name)
        path = root/name
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or getattr(info,'st_file_attributes',0) & 0x400
                or info.st_size != entry['bytes'] or sha(path) != entry['sha256']):
            raise ValueError('synthetic_canary_rgb_changed_during_check')
    if len(seen) != LOCATIONS*4 or {path.name for path in root.iterdir()} != expected:
        raise ValueError('invalid_synthetic_canary_inventory')


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
        if policy is not None and policy.document['version'] in (2, 3):
            input_data = policy.pinned_inputs()
            # Index the already checked bytes in this attempt's private folder.
            # A later change to the release source cannot redirect native input.
            source_tsv = work / 'release-canary-112.tsv'
            source_tsv.write_bytes(input_data['fixtureBytes'])
            report['reference'] = 'RELEASE_PINNED_REFERENCE_LIVE_SOURCE_PIXELS'
        reference, identity = canary_reference(policy)
        profile = runtime_profile(binary, model_dir, inference_threads=inference_threads)
        report.update(identity=identity, runtimeProfile=profile)
        frozen_args = {}
        if policy is not None and policy.document['version'] == 3:
            if shutil.disk_usage(work).free < 1024**3:
                raise ValueError('synthetic_canary_storage_required')
            from calibration.synthetic_canary import create_sealed_inputs, MODELS
            entries = [{'name':name,'bytes':(Path(model_dir)/name).stat().st_size,
                        'sha256':profile['profile']['assets']['models/'+name]} for name in MODELS]
            frozen = work/'synthetic-rgb'
            generated = create_sealed_inputs(frozen,input_data['fixtureBytes'],entries,
                                            expected_fixture_sha256=identity['fixtureSha256'])
            expected = policy.document['dataset']['syntheticInputs']
            if generated['manifestSha256'] != expected['manifestSha256']:
                raise ValueError('synthetic_canary_manifest_not_pinned')
            verify_synthetic_inputs(frozen,expected['manifestSha256'])
            frozen_args = {'sealed_rgb':frozen,'sealed_sha256':expected['manifestSha256']}
            report.update(reference='RELEASE_PINNED_SYNTHETIC_REFERENCE',inputIdentity='SEALED_SYNTHETIC_RGB_BYTES',
                          syntheticInputs=expected)
        active = indexer or (index_synthetic_canary if frozen_args else index_locations_tsv)
        active(source_tsv, index_dir=work / "index", checkpoint=work / "checkpoint.json",
               output=work / "output.json", binary=binary, model_dir=model_dir, pace="slow",
               inference_threads=inference_threads, run_id="vision-user-canary-v1",
               progress_callback=progress_callback, use_nice=False, **frozen_args)
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
        if frozen_args:
            verify_synthetic_inputs(frozen_args['sealed_rgb'],frozen_args['sealed_sha256'])
        if policy is None:
            report["decision"] = "OWNER_QUALIFICATION_POLICY_REQUIRED"
        else:
            report["qualified"], report["decision"] = policy.evaluate(profile["sha256"], identity, metrics)
    except (Exception, KeyboardInterrupt) as error:
        report.update(status="FAILED", complete=False, qualified=False, error=getattr(error, "code", str(error)) or type(error).__name__)
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
    if bool(args.policy) != bool(args.policy_sha256):
        parser.error("A policy path and trusted policy SHA-256 must be supplied together.")
    policy = CanaryPolicy.load(args.policy, args.policy_sha256) if args.policy else None
    if not args.allow_live_imagery and (policy is None or policy.document['version'] != 3):
        parser.error("The live 112-location test requires explicit live-imagery consent.")
    report = run_canary(args.root, binary=args.binary, model_dir=args.model_dir, policy=policy)
    print(json.dumps({key: report.get(key) for key in ("status", "qualified", "decision", "error")}, indent=2))
    print("Local report:", args.root / "canary-report.json")
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
