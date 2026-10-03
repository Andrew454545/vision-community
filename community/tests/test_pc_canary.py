import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from community import pc_canary as canary


class CanaryTests(unittest.TestCase):
    def test_process_owner_change_invalidates_the_admitted_runtime_profile(self):
        helper_hash = ["a" * 64]
        def source_hash(path):
            return helper_hash[0] if Path(path).name == "process_owner.py" else "b" * 64
        with patch.object(canary, "sha", side_effect=source_hash):
            before = canary.runtime_profile(Path("binary"), Path("models"))
            helper_hash[0] = "c" * 64
            after = canary.runtime_profile(Path("binary"), Path("models"))
        self.assertEqual(before["profile"]["assets"], after["profile"]["assets"])
        self.assertEqual(before["profile"]["pipeline"]["process_owner.py"], "a" * 64)
        self.assertEqual(after["profile"]["pipeline"]["process_owner.py"], "c" * 64)
        self.assertNotEqual(before["sha256"], after["sha256"])

    def test_reference_subset_is_bound_to_sealed_full_fixture(self):
        blob, identity = canary.canary_reference()
        self.assertEqual(len(blob), 112 * 3080)
        self.assertEqual(identity["referenceSha256"], hashlib.sha256(blob).hexdigest())
        rows = (canary.FIXTURE / "canary-112.tsv").read_bytes()
        self.assertEqual(identity["fixtureSha256"], hashlib.sha256(rows).hexdigest())

    def test_explicit_owner_policy_checks_full_qualification_identity_and_every_view(self):
        document = {"version": 1, "policyId": "synthetic-test-only",
                    "runtimeProfileSha256": "a" * 64, "fixtureSha256": "b" * 64, "referenceSha256": "c" * 64,
                    "fullCalibration": {"approved": True, "locations": 1024, "repetitions": 3, "evidenceSha256": "d" * 64},
                    "thresholds": {"minimumViewCosine": 0.9, "maximumViewRelativeL2": 0.2}}
        policy = canary.CanaryPolicy(document)
        identity = {key: document[key] for key in ("fixtureSha256", "referenceSha256")}
        metrics = {"cosine_similarity": {"min": 0.95}, "relative_l2_error": {"max": 0.1}}
        self.assertTrue(policy.evaluate("a" * 64, identity, metrics)[0])
        self.assertFalse(policy.evaluate("f" * 64, identity, metrics)[0])
        self.assertFalse(policy.evaluate("a" * 64, {**identity, "fixtureSha256": "e" * 64}, metrics)[0])
        metrics["cosine_similarity"]["min"] = 0.89
        self.assertFalse(policy.evaluate("a" * 64, identity, metrics)[0])
        metrics["cosine_similarity"]["min"] = 1
        metrics["relative_l2_error"]["max"] = 0.21
        self.assertFalse(policy.evaluate("a" * 64, identity, metrics)[0])
        for changed in ({"fullCalibration": {"approved": False}}, {"thresholds": {}},
                        {"thresholds": {"minimumViewCosine": float("nan"), "maximumViewRelativeL2": 1}}):
            with self.assertRaises(ValueError):
                canary.CanaryPolicy({**document, **changed})

    def test_policy_file_requires_trusted_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "policy.json"
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "canary_policy_checksum_mismatch"):
                canary.CanaryPolicy.load(path, "0" * 64)

    def test_complete_diagnostic_does_not_self_approve_and_packet_contains_all_records(self):
        reference, _ = canary.canary_reference()
        profile = {"sha256": canary.fingerprint({"test": True}), "profile": {"test": True}}

        def indexer(tsv, **kwargs):
            self.assertEqual(tsv.name, "canary-112.tsv")
            self.assertEqual(kwargs["inference_threads"], 1)
            index = kwargs["index_dir"]
            index.mkdir()
            (index / "shard-000000.i8").write_bytes(reference)

        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp) / "canary"
            with patch.object(canary, "runtime_profile", return_value=profile), \
                 patch.object(canary, "require_complete_index") as completeness:
                report = canary.run_canary(work, binary=Path("test"), model_dir=Path("test"), indexer=indexer)
            self.assertEqual(report["status"], "COMPLETE")
            self.assertFalse(report["qualified"])
            self.assertFalse(report["serverAuthorization"])
            self.assertEqual(report["decision"], "OWNER_QUALIFICATION_POLICY_REQUIRED")
            self.assertEqual(completeness.call_args.args[2], 112)
            packet = report["submission"]
            self.assertEqual(packet["profileId"], profile["sha256"])
            self.assertEqual(packet["profileId"], canary.fingerprint(packet["canary"]["runtimeProfile"]["profile"]))
            self.assertEqual(packet["canary"]["fixtureSha256"], canary.sha(canary.FIXTURE / "canary-112.tsv"))
            self.assertEqual(packet["canary"]["referenceSha256"], hashlib.sha256(reference).hexdigest())
            self.assertEqual(len(packet["canary"]["records"]), 112)
            decoded = b"".join(base64.b64decode(record) for record in packet["canary"]["records"])
            self.assertEqual(decoded, reference)
            self.assertEqual(packet["canary"]["outputSha256"], hashlib.sha256(decoded).hexdigest())
            self.assertEqual(json.loads((work / "canary-report.json").read_text())["status"], "COMPLETE")

    def test_runtime_change_during_check_cannot_leave_a_submission_packet(self):
        reference, _ = canary.canary_reference()

        def indexer(_tsv, **kwargs):
            kwargs["index_dir"].mkdir()
            (kwargs["index_dir"] / "shard-000000.i8").write_bytes(reference)

        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp) / "canary"
            with patch.object(canary, "runtime_profile", side_effect=[{"sha256": "a" * 64}, {"sha256": "b" * 64}]), \
                 patch.object(canary, "require_complete_index"):
                report = canary.run_canary(work, binary=Path("test"), model_dir=Path("test"), indexer=indexer)
            self.assertEqual(report["status"], "FAILED")
            self.assertFalse(report["qualified"])
            self.assertEqual(report["error"], "runtime_changed_during_canary")
            self.assertNotIn("submission", report)

    def test_failure_preserves_report_and_no_submission(self):
        def fails(*_args, **_kwargs):
            raise RuntimeError("synthetic_failure")

        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp) / "canary"
            with patch.object(canary, "runtime_profile", return_value={"sha256": "a" * 64}):
                report = canary.run_canary(work, binary=Path("test"), model_dir=Path("test"), indexer=fails)
            self.assertEqual(report["status"], "FAILED")
            self.assertFalse(report["qualified"])
            self.assertNotIn("submission", report)
            self.assertTrue((work / "canary-report.json").is_file())

    def test_runtime_assets_and_settings_change_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "mma-vision.exe"
            binary.write_bytes(b"runtime")
            for name in (*canary.REQUIRED_MODEL_FILES, *canary.DLLS):
                (root / name).write_bytes(name.encode())
            original = canary.runtime_profile(binary, root)
            report = {"status": "COMPLETE", "runtimeProfile": copy.deepcopy(original)}
            self.assertTrue(canary.canary_profile_matches(report, binary=binary, model_dir=root))
            self.assertNotEqual(canary.runtime_profile(binary, root, inference_threads=2), original)
            (root / canary.REQUIRED_MODEL_FILES[0]).write_bytes(b"changed-model")
            self.assertFalse(canary.canary_profile_matches(report, binary=binary, model_dir=root))


if __name__ == "__main__":
    unittest.main()
