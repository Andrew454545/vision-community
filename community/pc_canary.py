"""One local 112-location readiness screen, after owner runtime qualification.

The result is not a server credential. No accounts, submissions, or automatic
approval thresholds exist here. An owner-approved, hash-pinned policy is needed
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
import sys
import time

from calibration.quality import decoded_difference
from calibration.run_windows import FIXTURE, verify_fixture
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
                                         "imageEncoderSessions", "dutyCyclePercent", "thermalStateLimit")}
    profile = {"version": 1, "platform": sys.platform, "assets": assets,
               "settings": settings,
               "threads": {key: str(inference_threads) for key in THREAD_ENVIRONMENT_KEYS},
               "pipeline": {name: sha(Path(__file__).with_name(name)) for name in ("vision_index.py", "four_view.py")}}
    return {"sha256": fingerprint(profile), "profile": profile}


def canary_reference():
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
        if not isinstance(document, dict) or document.get("version") != 1:
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
        self.document = json.loads(json.dumps(document))

    @classmethod
    def load(cls, path, expected_sha256):
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("canary_policy_checksum_mismatch")
        return cls(json.loads(raw))

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
        reference, identity = canary_reference()
        profile = runtime_profile(binary, model_dir, inference_threads=inference_threads)
        report.update(identity=identity, runtimeProfile=profile)
        active = indexer or index_locations_tsv
        active(FIXTURE / "canary-112.tsv", index_dir=work / "index", checkpoint=work / "checkpoint.json",
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
