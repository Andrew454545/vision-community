import json
import tempfile
import unittest
from pathlib import Path

from community.seal_index import seal_catalog
from community.store import (
    FORBIDDEN_R2_BUCKETS,
    R2_BUCKET_NAME,
    R2ArtifactStore,
    assert_community_bucket,
    r2_public_status,
)


ROOT = Path(__file__).resolve().parents[1]


class R2StoreTest(unittest.TestCase):
    def test_refuses_unrelated_bucket(self):
        self.assertIn("geonections-images", FORBIDDEN_R2_BUCKETS)
        with self.assertRaisesRegex(RuntimeError, "refusing_unrelated_bucket"):
            assert_community_bucket("geonections-images")
        with self.assertRaisesRegex(RuntimeError, "unknown_r2_bucket"):
            assert_community_bucket("some-other-bucket")
        self.assertEqual(assert_community_bucket(R2_BUCKET_NAME), "vision-community")

    def test_status_names_the_private_community_bucket(self):
        status = r2_public_status()
        self.assertTrue(status["provisioned"])
        self.assertEqual(status["bucket"], "vision-community")
        self.assertEqual(status["binding"], "INDEX")
        self.assertFalse(status["publicAccess"])
        self.assertNotIn("geonections-images", json.dumps(status))

    def test_r2_store_does_not_use_browser_credentials(self):
        store = R2ArtifactStore({"bucket": "vision-community"})
        self.assertEqual(store.backend(), "r2")
        with self.assertRaisesRegex(RuntimeError, "r2_use_worker_binding"):
            store.put("registry.json", b"{}")

    def test_prototype_catalog_seals_without_imagery(self):
        catalog = json.loads((ROOT / "prototype_catalog.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder:
            document = seal_catalog(catalog, Path(folder))
            self.assertFalse(document["persistImagery"])
            self.assertEqual(sum(source["count"] for source in document["sources"]), 28)
            lanes = {source["lane"] for source in document["sources"]}
            self.assertEqual(lanes, {"scene", "object"})


if __name__ == "__main__":
    unittest.main()
