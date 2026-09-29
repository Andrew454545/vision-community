import base64
import hashlib
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from community.features import MODEL_ID
from community.catalog import parse_indexer_line
from community.four_view import VISION_FOUR_VIEW_MODEL
from community.scene_quality import ApprovedSceneReferences, SceneQualityError
from community.server import handler_for
from community.service import CommunityService, ServiceError


PROTOTYPE = Path(__file__).resolve().parents[1] / "prototype_catalog.json"


def reference_policy(record, jobs=None):
    if jobs is None:
        jobs = json.loads(PROTOTYPE.read_text(encoding="utf-8"))["locations"]
    return {"version": 1, "policyId": "unit-test-only", "inputModel": MODEL_ID,
            "outputModel": VISION_FOUR_VIEW_MODEL, "references": [
                {"assetId": item["panoId"], "capture": item["capture"],
                 **{key: item[key] for key in ("lat", "lng", "heading", "pitch", "zoom")},
                 "approvedSha256": [hashlib.sha256(record).hexdigest()]}
                for item in jobs if item["lane"] == "scene"
            ]}


def record(fill=7):
    return (b"\x00\x3c" + bytes([fill]) * 768) * 4


def references_from_fixture_lines(lines):
    jobs = [parse_indexer_line(line) for line in lines if line.strip()]
    return ApprovedSceneReferences(reference_policy(record(), [
        {**job, "lng": job["lon"]} for job in jobs
    ]))


class SceneQualityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = CommunityService(Path(self.temp.name) / "db.sqlite", operational=True)
        self.service.import_jobs(json.loads(PROTOTYPE.read_text(encoding="utf-8")))
        self.account = self.service.create_account()["accountId"]

    def approve(self):
        self.service.scene_references = ApprovedSceneReferences(reference_policy(record()))

    def output(self, item, data):
        return {"locationId": item["locationId"], "model": VISION_FOUR_VIEW_MODEL,
                "outputSha256": hashlib.sha256(data).hexdigest(),
                "embedding": base64.b64encode(data).decode("ascii")}

    def assert_unpublished(self):
        self.assertEqual(self.service.status(self.account)["units"], 0)
        with self.service._connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM published_index").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ledger").fetchone()[0], 0)

    def test_missing_policy_rejects_before_allocating_lease(self):
        with self.assertRaisesRegex(ServiceError, "scene_verification_unavailable"):
            self.service.lease(self.account, "scene", 1)
        with self.service._connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM leases").fetchone()[0], 0)
        self.assert_unpublished()

    def test_uncovered_pose_rejects_before_allocating_lease(self):
        self.approve()
        with self.service._connection() as connection:
            connection.execute("UPDATE locations SET heading=heading+1 WHERE lane='scene'")
        with self.assertRaisesRegex(ServiceError, "scene_reference_not_approved"):
            self.service.lease(self.account, "scene", 1)
        with self.service._connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM leases").fetchone()[0], 0)

    def test_fabricated_vector_and_model_downgrade_earn_nothing(self):
        self.approve()
        lease = self.service.lease(self.account, "scene", 1)
        forged = self.output(lease["items"][0], record(8))
        with self.assertRaisesRegex(ServiceError, "scene_reference_not_approved"):
            self.service.submit(self.account, lease["leaseId"], [forged])
        forged["model"] = MODEL_ID
        with self.assertRaisesRegex(ServiceError, "unsupported_model"):
            self.service.submit(self.account, lease["leaseId"], [forged])
        self.assert_unpublished()

    def test_policy_revocation_rejects_active_lease(self):
        self.approve()
        lease = self.service.lease(self.account, "scene", 1)
        self.service.scene_references = None
        with self.assertRaisesRegex(ServiceError, "scene_verification_unavailable"):
            self.service.submit(self.account, lease["leaseId"], [self.output(lease["items"][0], record())])
        self.assert_unpublished()

    def test_approved_output_credits_once(self):
        self.approve()
        lease = self.service.lease(self.account, "scene", 1)
        output = self.output(lease["items"][0], record())
        result = self.service.submit(self.account, lease["leaseId"], [output])
        self.assertEqual(result["unitsEarned"], 1)
        replay = self.service.submit(self.account, lease["leaseId"], [output])
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["unitsEarned"], 0)

    def test_checksum_pins_operator_manifest(self):
        path = Path(self.temp.name) / "references.json"
        path.write_text(json.dumps(reference_policy(record())), encoding="utf-8")
        with self.assertRaisesRegex(SceneQualityError, "checksum_mismatch"):
            ApprovedSceneReferences.load(path, "0" * 64)
        approved = ApprovedSceneReferences.load(path, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(approved.policy_id, "unit-test-only")

    def test_capabilities_are_read_only_and_do_not_require_account(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.service))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/capabilities") as response:
                result = json.load(response)
            self.assertFalse(result["sceneContributions"]["ready"])
            self.assertEqual(result["sceneContributions"]["reason"], "scene_verification_unavailable")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
