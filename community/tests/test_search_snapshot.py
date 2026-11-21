import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from community.search_snapshot import (CONFIRMED_RESOURCE, CONFIRMED_STAGING_RESOURCE, SnapshotError, build_snapshot,
                                       cache_file, encoded, verify_snapshot)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def record(value):
    return (b"\x00\x3c" + bytes([value]) * 768) * 4


class SearchSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.key = "four-view-v4/synthetic-test-only.i8"
        self.blob = record(7) + record(9)
        cache_file(self.cache, self.key).write_bytes(self.blob)
        self.rows = [self.row(10, 9), self.row(3, 7)]  # IDs/order differ from artifact record order.
        self.inventory = {"version": 1, "resource": CONFIRMED_RESOURCE, "rows": self.rows}
        self.policy = {"version": 1, "policyId": "synthetic-test-only", "inputModel": "input-model",
                       "outputModel": "vision-four-view-v4", "references": [
                           {"assetId": row["asset_id"], "capture": row["capture"], "lat": row["lat"], "lng": row["lon"],
                            "heading": row["heading"], "pitch": row["pitch"], "zoom": row["zoom"],
                            "approvedSha256": [row["output_sha256"]]} for row in self.rows]}
        self.inventory_path = self.root / "inventory.json"
        self.policy_path = self.root / "policy.json"

    def row(self, location, value):
        return {"id": location, "asset_id": f"synthetic-{location}", "capture": "2026-09", "lane": "scene",
                "model": "input-model", "state": "published", "contributor_id": "private-anonymous-account-id",
                "lat": location, "lon": 20, "heading": 90, "pitch": 0, "zoom": 0, "country": "Italy",
                "camera_generation": "gen4", "output_sha256": sha(record(value)), "four_view_sha256": sha(record(value)),
                "location_output_sha256": sha(record(value)), "four_view_key": self.key}

    def build(self, destination="snapshot", inventory_pin=None, policy_pin=None, **options):
        raw_inventory, raw_policy = encoded(self.inventory), encoded(self.policy)
        self.inventory_path.write_bytes(raw_inventory)
        self.policy_path.write_bytes(raw_policy)
        return build_snapshot(self.inventory_path, inventory_pin or sha(raw_inventory), self.policy_path,
                              policy_pin or sha(raw_policy), self.cache, self.root / destination, **options)

    def assert_failure(self, reason):
        with self.assertRaisesRegex(SnapshotError, reason):
            self.build()
        self.assertFalse((self.root / "snapshot/snapshot.json").exists())
        self.assertEqual(json.loads((self.root / "snapshot/failure-report.json").read_text()),
                         {"sealed": False, "error": reason})

    def test_only_reviewed_contributions_are_sealed_in_stable_order_without_account_ids(self):
        report = self.build()
        document = verify_snapshot(self.root / "snapshot", report["snapshotSha256"])
        self.assertEqual(document["locations"], 2)
        self.assertEqual((self.root / "snapshot/scene-records.i8").read_bytes(), record(7) + record(9))
        members = json.loads((self.root / "snapshot/members.json").read_text())
        self.assertEqual([(row["sourceIndex"], row["locationId"]) for row in members], [(0, 3), (1, 10)])
        self.assertEqual(members[1]["pose"]["panoId"], "synthetic-10")
        for path in (self.root / "snapshot").iterdir():
            self.assertNotIn(b"private-anonymous-account-id", path.read_bytes())
            self.assertNotIn(str(self.root).encode(), path.read_bytes())
        second = self.build("second")
        self.assertEqual(second["snapshotSha256"], report["snapshotSha256"])
        self.assertEqual(document["roadNameAuthority"], "unavailable")

    def test_staging_requires_explicit_selection_and_seals_the_confirmed_resource_pair(self):
        self.inventory["resource"] = CONFIRMED_STAGING_RESOURCE
        with self.assertRaisesRegex(SnapshotError, "invalid_community_inventory"):
            self.build("implicit-staging")
        report = self.build("staging", environment="staging")
        document = verify_snapshot(self.root / "staging", report["snapshotSha256"], environment="staging")
        self.assertEqual(document["resource"], CONFIRMED_STAGING_RESOURCE)
        with self.assertRaisesRegex(SnapshotError, "snapshot_environment_mismatch"):
            verify_snapshot(self.root / "staging", report["snapshotSha256"], environment="production")

    def test_snapshot_updates_cannot_mix_environments_even_when_member_ids_and_hashes_match(self):
        previous = self.build("production")
        self.inventory["resource"] = CONFIRMED_STAGING_RESOURCE
        with self.assertRaisesRegex(SnapshotError, "snapshot_environment_mismatch"):
            self.build("mixed", environment="staging", previous=self.root / "production",
                       previous_sha256=previous["snapshotSha256"])
        self.assertFalse((self.root / "mixed/snapshot.json").exists())
        self.assertTrue((self.root / "mixed/failure-report.json").exists())

    def test_confirmed_resources_cannot_be_recombined_or_replaced_with_other_buckets(self):
        for resource in ({**CONFIRMED_STAGING_RESOURCE, "databaseId": CONFIRMED_RESOURCE["databaseId"]},
                         {**CONFIRMED_STAGING_RESOURCE, "bucket": "geonections-images"},
                         {**CONFIRMED_STAGING_RESOURCE, "accountId": "another-account"}):
            self.inventory["resource"] = resource
            with self.assertRaisesRegex(SnapshotError, "invalid_community_inventory"):
                self.build("bad-resource-" + str(len(list(self.root.iterdir()))), environment="staging")

    def test_legacy_snapshot_remains_production_only_and_unknown_environment_preserves_failure(self):
        report = self.build()
        folder = self.root / "snapshot"
        document = json.loads((folder / "snapshot.json").read_bytes())
        del document["resource"]
        raw = encoded(document)
        (folder / "snapshot.json").write_bytes(raw)
        verify_snapshot(folder, sha(raw), environment="production")
        with self.assertRaisesRegex(SnapshotError, "snapshot_environment_mismatch"):
            verify_snapshot(folder, sha(raw), environment="staging")
        with self.assertRaisesRegex(SnapshotError, "invalid_snapshot_environment"):
            self.build("unknown-environment", environment="unconfirmed")
        self.assertFalse((self.root / "unknown-environment/snapshot.json").exists())

    def test_uncredited_unpublished_changed_publications_and_objects_are_denied(self):
        for changed in [{"contributor_id": ""}, {"contributor_id": None}, {"state": "pending"}, {"lane": "object"},
                        {"four_view_sha256": "f" * 64}, {"location_output_sha256": "f" * 64}]:
            with self.subTest(changed=changed):
                self.inventory["rows"] = [{**self.rows[0], **changed}]
                with self.assertRaisesRegex(SnapshotError, "not_a_contributed_scene_publication"):
                    self.build("denied-" + str(len(list(self.root.iterdir()))))

    def test_changed_pose_or_vector_cannot_be_approved_from_a_contributor_checksum(self):
        self.inventory["rows"] = [{**self.rows[0], "heading": 91}]
        self.assert_failure("publication_not_independently_approved")

    def test_trusted_inventory_and_policy_pins_and_resource_are_required(self):
        for pin in ["inventory", "policy"]:
            with self.assertRaisesRegex(SnapshotError, "input_checksum_mismatch"):
                self.build(pin, inventory_pin="f" * 64 if pin == "inventory" else None,
                           policy_pin="f" * 64 if pin == "policy" else None)
        self.inventory["resource"] = {**CONFIRMED_RESOURCE, "bucket": "unconfirmed-bucket"}
        self.assert_failure("invalid_community_inventory")

    def test_duplicates_path_escape_and_missing_or_corrupt_artifacts_never_seal(self):
        cases = [("duplicate_location_id", lambda: self.inventory.update(rows=[self.rows[0], self.rows[0]])),
                 ("invalid_artifact_key", lambda: self.inventory.update(rows=[{**self.rows[0], "four_view_key": "four-view-v4/../secret.i8"}])),
                 ("published_record_missing_from_artifact", lambda: cache_file(self.cache, self.key).write_bytes(record(6))),
                 ("invalid_scene_artifact", lambda: cache_file(self.cache, self.key).write_bytes(self.blob[:-1])),
                 ("invalid_scene_artifact", lambda: cache_file(self.cache, self.key).write_bytes((b"\x00\x3c" + b"\0" * 768) * 4))]
        original = copy.deepcopy(self.inventory)
        for index, (reason, change) in enumerate(cases):
            self.inventory = copy.deepcopy(original)
            cache_file(self.cache, self.key).write_bytes(self.blob)
            change()
            with self.subTest(reason=reason), self.assertRaisesRegex(SnapshotError, reason):
                self.build("failed-" + str(index))
            self.assertFalse((self.root / f"failed-{index}/snapshot.json").exists())
        self.inventory = original
        cache_file(self.cache, self.key).unlink()
        with self.assertRaises(FileNotFoundError):
            self.build("missing")
        self.assertEqual(json.loads((self.root / "missing/failure-report.json").read_text())["error"], "snapshot_build_failed")

    def test_tampered_snapshot_is_unusable_and_completed_directory_cannot_be_overwritten(self):
        report = self.build()
        with self.assertRaises(FileExistsError):
            self.build()
        (self.root / "snapshot/scene-records.i8").write_bytes(record(8) + record(9))
        with self.assertRaisesRegex(SnapshotError, "snapshot_file_checksum_mismatch"):
            verify_snapshot(self.root / "snapshot", report["snapshotSha256"])
        good = self.build("good")
        (self.root / "good/members.json").write_bytes(b"[]")
        with self.assertRaisesRegex(SnapshotError, "snapshot_file_checksum_mismatch"):
            verify_snapshot(self.root / "good", good["snapshotSha256"])
        with self.assertRaisesRegex(SnapshotError, "input_checksum_mismatch"):
            verify_snapshot(self.root / "good", "f" * 64)

    def test_new_locations_append_without_renumbering_and_changed_history_is_denied(self):
        first = self.build()
        new_row = self.row(1, 11)
        self.inventory["rows"] = [new_row, *self.rows]
        self.policy["references"].append({"assetId": new_row["asset_id"], "capture": new_row["capture"],
            "lat": 1, "lng": 20, "heading": 90, "pitch": 0, "zoom": 0, "approvedSha256": [new_row["output_sha256"]]})
        cache_file(self.cache, self.key).write_bytes(record(11) + self.blob)
        second = self.build("next", previous=self.root / "snapshot", previous_sha256=first["snapshotSha256"])
        verify_snapshot(self.root / "next", second["snapshotSha256"])
        members = json.loads((self.root / "next/members.json").read_text())
        self.assertEqual([(row["sourceIndex"], row["locationId"]) for row in members], [(0, 3), (1, 10), (2, 1)])
        self.inventory["rows"] = [new_row]
        with self.assertRaisesRegex(SnapshotError, "snapshot_history_changed"):
            self.build("removed", previous=self.root / "next", previous_sha256=second["snapshotSha256"])
        self.inventory["rows"] = [new_row, *self.rows]
        self.rows[0]["country"] = "USA"
        with self.assertRaisesRegex(SnapshotError, "snapshot_history_changed"):
            self.build("changed", previous=self.root / "next", previous_sha256=second["snapshotSha256"])
        with self.assertRaisesRegex(SnapshotError, "previous_snapshot_pin_required"):
            self.build("unpinned", previous=self.root / "snapshot")


if __name__ == "__main__":
    unittest.main()
