import base64
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from community.admin import audit, backup, restore
from community.features import MODEL_ID, cosine, embedding_for, render_faces
from community.search import ranked_search
from community.segments import SegmentError, SegmentRegistry
from community.service import CommunityService, ServiceError
from community.source import SourceError, parse_catalog
from community.worker import ProcessingWorker, PACE


CATALOG = Path(__file__).resolve().parents[1] / "visual_catalog.json"


def visual_service(folder: Path, search_cost: int = 4) -> CommunityService:
    return CommunityService(
        folder / "community.sqlite",
        search_cost=search_cost,
        artifacts=folder / "artifacts",
        segment_capacity=100,
    )


class RightsAndImporterTest(unittest.TestCase):
    def test_google_and_incomplete_wikimedia_grants_are_rejected(self):
        with self.assertRaises(SourceError):
            parse_catalog({"source": "google", "locations": []})
        with self.assertRaises(SourceError):
            parse_catalog(
                {
                    "source": "wikimedia",
                    "locations": [
                        {
                            "assetId": "wikimedia:Q1",
                            "capture": "2020",
                            "lane": "scene",
                            "model": MODEL_ID,
                        }
                    ],
                },
                grant={"source": "wikimedia", "permits": ["fetch"], "attribution": "x"},
            )

    def test_wikimedia_rights_complete_still_does_not_ingest(self):
        grant = {
            "source": "wikimedia",
            "writtenEvidence": True,
            "attribution": "Wikimedia Commons contributors",
            "permits": [
                "fetch",
                "transform",
                "redistribute_to_workers",
                "retain_derived_index",
                "display_search_results",
            ],
        }
        document = {
            "source": "wikimedia",
            "locations": [
                {"assetId": "wikimedia:Q1", "capture": "2020", "lane": "scene", "model": MODEL_ID}
            ],
        }
        rows = parse_catalog(document, grant=grant)
        self.assertEqual(rows[0]["rights"], "granted")
        with tempfile.TemporaryDirectory() as folder:
            service = visual_service(Path(folder))
            with self.assertRaisesRegex(ServiceError, "ingest_not_started"):
                service.import_jobs(document, grant=grant)


class VisualPipelineTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.service = visual_service(self.folder)
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        imported = self.service.import_jobs(catalog)
        self.assertEqual(imported, 12)
        self.first = self.service.create_account()
        self.second = self.service.create_account()

    def test_worker_pace_controls_real_concurrency(self):
        self.assertEqual(PACE["slow"]["workers"], 1)
        self.assertGreaterEqual(PACE["max"]["workers"], PACE["medium"]["workers"])
        self.assertGreaterEqual(PACE["medium"]["workers"], 1)

    def test_forged_stale_and_replayed_visual_submissions_are_rejected(self):
        account = self.first["accountId"]
        lease = self.service.lease(account, "scene", 4, pace="slow")
        worker = ProcessingWorker("slow")
        valid = worker.process_lease(lease)
        forged = [dict(item) for item in valid]
        forged[0] = dict(forged[0])
        forged[0]["outputSha256"] = "0" * 64
        with self.assertRaisesRegex(ServiceError, "verification_failed"):
            self.service.submit(account, lease["leaseId"], forged)
        accepted = self.service.submit(account, lease["leaseId"], valid)
        self.assertEqual(accepted["unitsEarned"], 4)
        self.assertTrue(accepted["segments"])
        replay = self.service.submit(account, lease["leaseId"], valid)
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.service.status(account)["units"], 4)

        old = self.service.lease(self.first["accountId"], "object", 1, now=100, pace="max")
        new = self.service.lease(self.second["accountId"], "object", 1, now=100 + 30 * 60, pace="medium")
        self.assertEqual(old["items"][0]["locationId"], new["items"][0]["locationId"])
        with self.assertRaisesRegex(ServiceError, "expired_lease"):
            self.service.submit(self.first["accountId"], old["leaseId"], ProcessingWorker().process_lease(old), now=2000)
        result = self.service.submit(
            self.second["accountId"], new["leaseId"], ProcessingWorker().process_lease(new), now=2000
        )
        self.assertEqual(result["unitsEarned"], 10)

    def test_shared_visual_index_is_ranked_not_label_search(self):
        first_id = self.first["accountId"]
        second_id = self.second["accountId"]
        lease = self.service.lease(first_id, "scene", 8, pace="max")
        self.service.submit(first_id, lease["leaseId"], ProcessingWorker("max").process_lease(lease))
        query = render_faces("synthetic:visual:001", "2026-01", "scene", MODEL_ID)
        with self.assertRaisesRegex(ServiceError, "insufficient_credit"):
            self.service.search(second_id, None, "visual-second-001", query_faces=query)
        result = self.service.search(first_id, None, "visual-first-001", query_faces=query)
        self.assertFalse(result["demo"])
        self.assertEqual(result["results"][0]["locationId"], lease["items"][0]["locationId"])
        self.assertNotIn("label", result["results"][0])
        self.assertGreater(result["results"][0]["score"], 0.99)
        self.assertEqual(self.service.search(first_id, None, "visual-first-001", query_faces=query), result)
        self.assertEqual(self.service.status(first_id)["units"], 4)
        other_lease = self.service.lease(second_id, "object", 1)
        self.service.submit(second_id, other_lease["leaseId"], ProcessingWorker().process_lease(other_lease))
        other_query = render_faces("synthetic:visual:001", "2026-01", "scene", MODEL_ID)
        second_result = self.service.search(second_id, None, "visual-second-002", query_faces=other_query)
        self.assertEqual(second_result["results"][0]["locationId"], result["results"][0]["locationId"])

    def test_no_owner_bypass_or_index_dump(self):
        with self.assertRaises(ValueError):
            CommunityService(self.folder / "owner.sqlite", owner_account_id="anyone")
        account = self.service.create_account()
        with self.assertRaisesRegex(ServiceError, "insufficient_credit"):
            self.service.search(account["accountId"], "pine", "owner-bypass-001")
        status = self.service.status()
        self.assertFalse(status["operational"])
        self.assertFalse(status["ownerBypass"])
        self.assertTrue(status["r2"]["provisioned"])
        self.assertEqual(status["r2"]["bucket"], "vision-community")
        self.assertFalse(status["r2"]["publicAccess"])

    def test_recovery_restores_same_account_and_units(self):
        account = self.first
        lease = self.service.lease(account["accountId"], "scene", 4)
        self.service.submit(account["accountId"], lease["leaseId"], ProcessingWorker().process_lease(lease))
        restored = self.service.recover_account(account["recoveryCode"])
        self.assertEqual(restored["accountId"], account["accountId"])
        self.assertEqual(self.service.status(restored["accountId"])["units"], 4)
        with self.assertRaisesRegex(ServiceError, "unauthorized"):
            self.service.account_for_token(account["token"])
        self.assertEqual(self.service.account_for_token(restored["token"]), account["accountId"])

    def test_checksummed_registry_fails_closed_on_tamper(self):
        lease = self.service.lease(self.first["accountId"], "scene", 4)
        self.service.submit(self.first["accountId"], lease["leaseId"], ProcessingWorker().process_lease(lease))
        document = self.service.registry.load()
        self.assertTrue(document["sources"])
        shard = self.service.artifacts / "index" / document["sources"][0]["path"] / "embeddings.bin"
        data = bytearray(shard.read_bytes())
        data[0] ^= 0xFF
        shard.write_bytes(data)
        with self.assertRaises(SegmentError):
            self.service.registry.load()

    def test_backup_restore_and_spatial_duplicate_deferral(self):
        lease = self.service.lease(self.first["accountId"], "scene", 4)
        self.service.submit(self.first["accountId"], lease["leaseId"], ProcessingWorker().process_lease(lease))
        destination = self.folder / "backup.sqlite"
        restored = self.folder / "restored.sqlite"
        self.assertTrue(audit(self.service.database)["ok"])
        self.assertTrue(backup(self.service.database, destination)["ok"])
        self.assertTrue(restore(destination, restored)["ok"])
        near = {
            "source": "synthetic",
            "rights": "synthetic-test-data",
            "locations": [
                {
                    "assetId": "synthetic:visual:near",
                    "capture": "2026-01",
                    "lane": "scene",
                    "model": MODEL_ID,
                    "lat": 10.00001,
                    "lon": 10.00001,
                }
            ],
        }
        added = self.service.import_jobs(near)
        self.assertEqual(added, 1)
        with sqlite3.connect(self.service.database) as connection:
            state = connection.execute(
                "SELECT queue_state FROM locations WHERE asset_id=?", ("synthetic:visual:near",)
            ).fetchone()[0]
        self.assertEqual(state, "deferred")


class SegmentSearchParityTest(unittest.TestCase):
    def test_identical_query_ranks_the_source_location_first(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = SegmentRegistry(Path(folder), capacity=10)
            ids, blobs = [], []
            for index in range(8):
                asset = f"synthetic:visual:{index:03d}"
                faces = render_faces(asset, "2026-01", "scene", MODEL_ID)
                ids.append(index + 1)
                blobs.append(embedding_for("scene", faces))
            registry.publish(lane="scene", location_ids=ids, embeddings=b"".join(blobs))
            query = render_faces("synthetic:visual:003", "2026-01", "scene", MODEL_ID)
            hits = ranked_search(registry, "scene", query, limit=3)
            self.assertEqual(hits[0]["locationId"], 4)
            self.assertGreater(hits[0]["score"], hits[1]["score"])
            self.assertGreater(cosine(blobs[3], embedding_for("scene", query)), 0.99)


class ScaleSearchTest(unittest.TestCase):
    def test_topk_heap_scans_without_materializing_all_scores(self):
        from community.search import ranked_search_embedding

        count = 20_000
        with tempfile.TemporaryDirectory() as folder:
            registry = SegmentRegistry(Path(folder), capacity=count)
            ids = list(range(1, count + 1))
            blobs = [bytes([(index + dim) % 256 for dim in range(96)]) for index in range(count)]
            special = bytes([127] * 96)
            blobs[1233] = special
            poses = [
                {
                    "locationId": location_id,
                    "lat": 10.0,
                    "lng": 20.0,
                    "heading": 90,
                    "pitch": 0,
                    "zoom": 0,
                    "panoId": f"ScalePano{location_id:012d}",
                    "capture": "2020-06",
                    "country": "Italy",
                    "cameraGeneration": "gen4",
                }
                for location_id in ids
            ]
            registry.publish(lane="scene", location_ids=ids, embeddings=b"".join(blobs), poses=poses)
            hits = ranked_search_embedding(registry, "scene", special, limit=5)
            self.assertEqual(len(hits), 5)
            self.assertEqual(hits[0]["locationId"], 1234)
            self.assertEqual(hits[0]["scanned"], count)
            self.assertEqual(hits[0]["pose"]["panoId"], "ScalePano000000001234")
            self.assertGreater(hits[0]["score"], hits[-1]["score"])


if __name__ == "__main__":
    unittest.main()
