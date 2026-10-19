import json
from pathlib import Path
import tempfile
import unittest

from community.service import CommunityService, ServiceError
from community.worker import ProcessingWorker

FIXTURES = Path(__file__).resolve().parents[1]


class PublicationAccessTest(unittest.TestCase):
    def test_paid_search_cannot_download_unpublished_or_uncontributed_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = CommunityService(root / "db.sqlite", artifacts=root / "artifacts", search_cost=1)
            service.import_jobs(json.loads((FIXTURES / "prototype_catalog.json").read_text()))
            account = service.create_account()["accountId"]
            lease = service.lease(account, "scene", 2)
            service.submit(account, lease["leaseId"], ProcessingWorker().process_lease(lease))
            # Banked credits survive a fresh service instance.
            service = CommunityService(root / "db.sqlite", artifacts=root / "artifacts", search_cost=1)
            self.assertEqual(service.status(account)["searchesAvailable"], 2)
            query = json.loads((FIXTURES / "web/prototype-query.json").read_text())
            search = service.search(account, None, "publication-paid-001", query_map=query, execute="local")
            search_id = search["searchId"]
            self.assertEqual(service.status(account)["searchesAvailable"], 1)
            orphan = "a" * 32
            scene_key = f"four-view-v4/{orphan}.i8"
            object_key = f"object-index-v4/{orphan}/manifest.json"
            for key in (scene_key, object_key):
                path = service.artifacts / key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"unpublished data")
            self.assertEqual(service.list_object_indexes(account, search_id), {"indexes": []})
            for download, key in ((service.scene_index_bytes, scene_key), (service.object_index_bytes, object_key)):
                with self.assertRaisesRegex(ServiceError, "not_found"):
                    download(account, search_id, key)
            location_id = lease["items"][0]["locationId"]
            with service._connection() as connection:
                connection.execute("UPDATE published_index SET four_view_key=? WHERE location_id=?", (scene_key, location_id))
            self.assertEqual(service.scene_index_bytes(account, search_id, scene_key), b"unpublished data")
            with service._connection() as connection:
                connection.execute("UPDATE locations SET contributor_id=NULL WHERE id=?", (location_id,))
            self.assertEqual(service.list_scene_indexes(account, search_id), {"indexes": []})
            with self.assertRaisesRegex(ServiceError, "not_found"):
                service.scene_index_bytes(account, search_id, scene_key)


if __name__ == "__main__":
    unittest.main()
