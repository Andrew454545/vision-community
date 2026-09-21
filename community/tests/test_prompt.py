import tempfile
import unittest
from pathlib import Path

from community.features import embedding_for, render_faces
from community.prompt import (
    description_embedding,
    mix_embeddings,
    parse_prompt,
    snap_description_weight,
)
from community.service import CommunityService, ServiceError
from community.worker import ProcessingWorker


ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype_catalog.json"
QUERY = ROOT / "web" / "prototype-query.json"


class DescriptionQueryTest(unittest.TestCase):
    def test_weight_follows_vision_json_and_description_rules(self):
        self.assertEqual(snap_description_weight(50, has_json=False, has_prompt=True), 100)
        self.assertEqual(snap_description_weight(50, has_json=True, has_prompt=False), 0)
        self.assertEqual(snap_description_weight(40, has_json=True, has_prompt=True), 50)
        self.assertEqual(parse_prompt("  Red   Barn  "), "red barn")

    def test_mix_zero_is_json_and_hundred_is_description(self):
        visual = embedding_for("scene", render_faces("synthetic:mix:visual", "2026-01", "scene", "community-visual-v1"))
        textual = description_embedding("red barn in snow", "scene")
        self.assertEqual(mix_embeddings(visual, textual, 0), visual)
        self.assertEqual(mix_embeddings(visual, textual, 100), textual)
        mixed = mix_embeddings(visual, textual, 50)
        self.assertEqual(len(mixed), len(visual))
        self.assertNotEqual(mixed, visual)
        self.assertNotEqual(mixed, textual)
        self.assertNotEqual(
            description_embedding("red barn", "scene"),
            description_embedding("blue ocean", "scene"),
        )

    def test_search_accepts_description_json_or_both(self):
        import json

        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=4,
                artifacts=Path(folder) / "artifacts",
                segment_capacity=50,
            )
            service.import_jobs(json.loads(PROTOTYPE.read_text(encoding="utf-8")))
            account = service.create_account()["accountId"]
            lease = service.lease(account, "scene", 12)
            service.submit(account, lease["leaseId"], ProcessingWorker().process_lease(lease))
            query = json.loads(QUERY.read_text(encoding="utf-8"))
            unpaid = service.create_account()["accountId"]
            with self.assertRaisesRegex(ServiceError, "insufficient_credit"):
                service.search(unpaid, None, "unpaid-desc-001", prompt="red barn")
            described = service.search(account, None, "desc-only-001", prompt="red barn")
            self.assertTrue(described["results"])
            json_only = service.search(account, None, "json-only-001", query_map=query, description_weight=0)
            self.assertTrue(json_only["results"])
            mixed = service.search(
                account,
                None,
                "mixed-001",
                query_map=query,
                prompt="red barn in snow",
                description_weight=50,
            )
            self.assertTrue(mixed["results"])
            with self.assertRaisesRegex(ServiceError, "invalid_query"):
                service.search(account, None, "empty-001")


if __name__ == "__main__":
    unittest.main()
