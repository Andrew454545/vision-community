"""Audit one Street View location per lease; invented panos always recompute."""

import hmac
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from community.features import MODEL_ID, embedding_for, output_digest, render_faces, sha256_hex
from community.pano import CLI_LEASE_CAP, STREET_LEASE_CAP, lease_cap
from community.service import CommunityService
from community.verify import locations_to_recompute, verify_output


class LeaseCapTest(unittest.TestCase):
    def test_cli_batches_are_larger_than_browser_proxy_caps(self):
        self.assertEqual(lease_cap("scene", "medium", "browser"), STREET_LEASE_CAP["scene"]["medium"])
        self.assertEqual(lease_cap("scene", "medium", "cli"), CLI_LEASE_CAP["scene"]["medium"])
        self.assertGreater(lease_cap("scene", "max", "cli"), lease_cap("scene", "max", "browser"))
        self.assertGreater(lease_cap("object", "medium", "cli"), lease_cap("object", "medium", "browser"))


class AuditSelectionTest(unittest.TestCase):
    def test_invented_and_first_street_location_are_recomputed(self):
        rows = [
            {"id": 10, "asset_id": "iCpOERm3I_1uyE8VFk40eA"},
            {"id": 11, "asset_id": "AbCdEfGhIjKlMnOpQrStUV"},
            {"id": 12, "asset_id": "synthetic:visual:001"},
            {"id": 13, "asset_id": "CommunityPano000000000001"},
        ]
        self.assertEqual(locations_to_recompute(rows), {10, 12, 13})

    def test_all_invented_rows_are_recomputed(self):
        rows = [
            {"id": 1, "asset_id": "synthetic:a"},
            {"id": 2, "asset_id": "PrototypeBerkeleyCA000001"},
        ]
        self.assertEqual(locations_to_recompute(rows), {1, 2})


class AcceptClientEmbeddingTest(unittest.TestCase):
    def test_skip_recompute_requires_matching_embedding_bytes(self):
        faces = render_faces("iCpOERm3I_1uyE8VFk40eA", "2019-06", "scene", MODEL_ID)
        embedding = embedding_for("scene", faces)
        row = {
            "asset_id": "iCpOERm3I_1uyE8VFk40eA",
            "capture": "2019-06",
            "lane": "scene",
            "model": MODEL_ID,
        }
        supplied = {
            "digest": output_digest("iCpOERm3I_1uyE8VFk40eA", "2019-06", "scene", MODEL_ID, embedding),
            "embedding": embedding,
            "model": MODEL_ID,
        }
        with patch("community.verify.render_location_faces") as fetch:
            accepted = verify_output(row, supplied, recompute=False)
            fetch.assert_not_called()
        self.assertTrue(hmac.compare_digest(accepted, embedding))


class StreetAuditServiceTest(unittest.TestCase):
    def test_only_the_first_street_location_is_refetched(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=4,
                artifacts=Path(folder) / "artifacts",
                segment_capacity=20,
            )
            account = service.create_account()["accountId"]
            with service._connection() as connection:
                connection.executemany(
                    """INSERT INTO locations (asset_id, capture, lane, model, label, state, lat, lon, heading, pitch, zoom, source, rights)
                       VALUES (?, '2019-06', 'scene', ?, '', 'pending', 0, 0, 0, 0, 0, 'synthetic', 'synthetic-test-data')""",
                    [
                        ("StreetAuditPanoAAAAAAA", MODEL_ID),
                        ("StreetAuditPanoBBBBBBB", MODEL_ID),
                    ],
                )
            lease = service.lease(account, "scene", 2, pace="slow")
            calls = []

            def fake_faces(location, *, fetch=None):
                calls.append(location.get("panoId") or location.get("assetId"))
                pano = location.get("panoId") or location.get("assetId")
                return render_faces(pano, location.get("capture") or "2019-06", "scene", MODEL_ID)

            outputs = []
            for item in lease["items"]:
                faces = render_faces(item["panoId"], item["capture"], item["lane"], item["model"])
                embedding = embedding_for(item["lane"], faces)
                outputs.append(
                    {
                        "locationId": item["locationId"],
                        "model": item["model"],
                        "embedding": embedding,
                        "embeddingSha256": sha256_hex(embedding),
                        "outputSha256": output_digest(
                            item["assetId"], item["capture"], item["lane"], item["model"], embedding
                        ),
                    }
                )
            with patch("community.verify.render_location_faces", side_effect=fake_faces):
                result = service.submit(account, lease["leaseId"], outputs)
            self.assertEqual(result["accepted"], 2)
            self.assertEqual(result["unitsEarned"], 2)
            self.assertEqual(calls, [lease["items"][0]["panoId"]])


if __name__ == "__main__":
    unittest.main()
