import base64
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from community.four_view import VISION_FOUR_VIEW_MODEL
from community.scene_pipeline import CANARY_LOCATIONS, ScenePipelineError
from community.service import CommunityService


PROTOTYPE = Path(__file__).resolve().parents[1] / "prototype_catalog.json"


def record(fill=7):
    return (b"\x00\x3c" + bytes([fill]) * 768) * 4


class FakeVerifier:
    policy_id = "policy-test-v1"

    def __init__(self, decision="approved"):
        self.decision = decision
        self.qualify_calls = []
        self.audit_calls = []

    def qualify(self, request):
        self.qualify_calls.append(request)
        return {
            "approved": True,
            "policyId": request["policyId"],
            "profileId": request["profileId"],
            "canarySha256": request["canarySha256"],
            "expiresAt": int(time.time()) + 3600,
        }

    def audit(self, request):
        self.audit_calls.append(request)
        return {
            "decision": self.decision,
            "policyId": request["policyId"],
            "submissionSha256": request["submissionSha256"],
        }


class ScenePipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.verifier = FakeVerifier()
        self.service = CommunityService(
            Path(self.temp.name) / "db.sqlite",
            operational=True,
            scene_verifier=self.verifier,
        )
        self.service.import_jobs(json.loads(PROTOTYPE.read_text(encoding="utf-8")))
        self.account = self.service.create_account()["accountId"]
        self.profile = "a" * 64

    def canary(self):
        item = base64.b64encode(record()).decode("ascii")
        blob = record() * CANARY_LOCATIONS
        return {
            "locations": CANARY_LOCATIONS,
            "records": [item] * CANARY_LOCATIONS,
            "outputSha256": hashlib.sha256(blob).hexdigest(),
        }

    def qualify(self):
        result = self.service.qualify_scene_device(self.account, self.profile, self.canary())
        self.assertTrue(result["qualified"])
        self.assertEqual(result["policyId"], self.verifier.policy_id)

    def output(self, item, data=None):
        data = record() if data is None else data
        return {
            "locationId": item["locationId"],
            "model": VISION_FOUR_VIEW_MODEL,
            "outputSha256": hashlib.sha256(data).hexdigest(),
            "embedding": base64.b64encode(data).decode("ascii"),
        }

    def test_qualification_binds_profile_and_stages_before_audit(self):
        self.qualify()
        lease = self.service.lease(self.account, "scene", 1, profile_id=self.profile)
        result = self.service.submit(self.account, lease["leaseId"], [self.output(lease["items"][0])])

        self.assertEqual(result["accepted"], 0)
        self.assertTrue(result["pendingAudit"])
        self.assertEqual(result["unitsEarned"], 0)
        self.assertEqual(self.service.status(self.account)["units"], 0)
        with self.service._connection() as connection:
            candidate = connection.execute("SELECT state FROM scene_candidates").fetchone()
            location = connection.execute("SELECT state, queue_state FROM locations WHERE id=?",
                                          (lease["items"][0]["locationId"],)).fetchone()
        self.assertEqual(candidate["state"], "pending")
        self.assertEqual(tuple(location), ("pending", "quarantined"))

        audited = self.service.audit_scene_submission(self.account, lease["leaseId"])
        self.assertEqual(audited["accepted"], 1)
        self.assertEqual(audited["unitsEarned"], 1)
        self.assertFalse(audited["pendingAudit"])
        self.assertEqual(self.service.status(self.account)["units"], 1)
        self.assertEqual(len(self.verifier.audit_calls), 1)

        replay = self.service.audit_scene_submission(self.account, lease["leaseId"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["unitsEarned"], 0)
        with self.service._connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM published_index").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ledger").fetchone()[0], 1)

    def test_unqualified_or_wrong_profile_cannot_lease_scene_work(self):
        with self.assertRaisesRegex(ScenePipelineError, "scene_device_qualification_required"):
            self.service.lease(self.account, "scene", 1, profile_id=self.profile)
        self.qualify()
        with self.assertRaisesRegex(ScenePipelineError, "scene_device_qualification_required"):
            self.service.lease(self.account, "scene", 1, profile_id="b" * 64)

    def test_rejected_audit_keeps_work_out_of_index_and_ledger(self):
        self.verifier.decision = "rejected"
        self.qualify()
        lease = self.service.lease(self.account, "scene", 1, profile_id=self.profile)
        staged = self.service.submit(self.account, lease["leaseId"], [self.output(lease["items"][0])])
        self.assertTrue(staged["pendingAudit"])

        rejected = self.service.audit_scene_submission(self.account, lease["leaseId"])
        self.assertTrue(rejected["rejected"])
        self.assertFalse(rejected["pendingAudit"])
        self.assertEqual(rejected["unitsEarned"], 0)
        with self.service._connection() as connection:
            candidate = connection.execute("SELECT state FROM scene_candidates").fetchone()
            self.assertEqual(candidate["state"], "rejected")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM published_index").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ledger").fetchone()[0], 0)

    def test_invalid_canary_is_rejected_before_qualification_record(self):
        canary = self.canary()
        canary["records"][0] = base64.b64encode(b"bad").decode("ascii")
        with self.assertRaisesRegex(ScenePipelineError, "invalid_scene_canary"):
            self.service.qualify_scene_device(self.account, self.profile, canary)
        with self.service._connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM scene_qualifications").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
