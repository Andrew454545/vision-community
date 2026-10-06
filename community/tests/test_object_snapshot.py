import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from community.object_index import (OBJECT_INDEX_MODEL, RUNTIME_IDENTITY, global_id_record)
from community.object_snapshot import (VALIDATOR, build_object_snapshot, cache_directory,
                                       load_bundle, row_member, verify_object_snapshot)
from community.search_snapshot import (CONFIRMED_RESOURCE, CONFIRMED_STAGING_RESOURCE, SnapshotError, digest, encoded)
from community.tests.test_object_index import contract_bundle
from community.vision_index import VisionIndexError


class ObjectSnapshotTest(unittest.TestCase):
    def test_retired_timeline_coverage_cannot_be_reused_for_search(self):
        self.rows[0]['coverage_validator'] = 'official-gen4-historical-v1'
        with self.assertRaises(SnapshotError):
            self.build('retired-coverage')
        self.assertFalse((self.root / 'retired-coverage/snapshot.json').exists())

    def test_staging_object_snapshot_is_explicit_and_cannot_be_used_as_production(self):
        self.inventory["resource"] = CONFIRMED_STAGING_RESOURCE
        with self.assertRaisesRegex(SnapshotError, "invalid_community_inventory"):
            self.build("implicit-staging")
        report = self.build("staging", environment="staging")
        document = verify_object_snapshot(self.root / "staging", report["snapshotSha256"], environment="staging")
        self.assertEqual(document["resource"], CONFIRMED_STAGING_RESOURCE)
        with self.assertRaisesRegex(SnapshotError, "snapshot_environment_mismatch"):
            verify_object_snapshot(self.root / "staging", report["snapshotSha256"], environment="production")

    def test_object_snapshot_history_cannot_cross_resource_pairs_with_matching_members(self):
        previous = self.build("production")
        self.inventory["resource"] = CONFIRMED_STAGING_RESOURCE
        with self.assertRaisesRegex(SnapshotError, "snapshot_environment_mismatch"):
            self.build("mixed", environment="staging", previous=self.root / "production",
                       previous_sha256=previous["snapshotSha256"])
        self.assertFalse((self.root / "mixed/snapshot.json").exists())

    def test_staging_still_requires_trusted_gen4_evidence_and_feature_approval(self):
        self.inventory["resource"] = CONFIRMED_STAGING_RESOURCE
        self.rows[0]["camera_generation"] = "gen3"
        with self.assertRaises(SnapshotError):
            self.build("untrusted-staging", environment="staging")
        self.assertFalse((self.root / "untrusted-staging/snapshot.json").exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.rows = []
        self.policy = {"version": 1, "policyId": "synthetic-object-audit-only",
                       "inputModel": "input-model", "outputModel": OBJECT_INDEX_MODEL,
                       "verification": "independently-audited-object-inference",
                       "runtimeIdentity": RUNTIME_IDENTITY, "coverageValidator": VALIDATOR, "artifacts": []}
        self.add_bundle("a" * 32, [3, 10])
        self.add_bundle("b" * 32, [20])
        self.inventory = {"version": 1, "resource": CONFIRMED_RESOURCE, "rows": self.rows}

    def add_bundle(self, lease, ids):
        key = f"object-index-v4/{lease}/"
        rows = [{"id": number, "asset_id": f"synthetic-{number}", "capture": "2026-09", "lane": "object",
                 "model": "input-model", "state": "published", "contributor_id": "private-account-id",
                 "lat": number, "lon": 20, "heading": 90, "pitch": 0, "zoom": 0, "country": "Italy",
                 "camera_generation": "gen4", "coverage_validator": VALIDATOR,
                 "coverage_evidence_sha256": "c" * 64, "object_index_key": key,
                 "output_sha256": digest(global_id_record(offset)),
                 "location_output_sha256": digest(global_id_record(offset))} for offset, number in enumerate(ids)]
        items = [{"locationId": row["id"], "panoId": row["asset_id"], "lat": row["lat"], "lng": row["lon"],
                  "heading": 90, "country": "Italy", "cameraGeneration": "gen4",
                  "mapId": "private-source-map-label", "roadName": "private-road-label"} for row in rows]
        manifest, files, source = contract_bundle(items, lease, self.root / "private-local-path.tsv")
        manifest["privateExtension"] = {"account": "private-account-id", "path": str(self.root)}
        manifest["classes"][0]["privateNote"] = "private-account-id"
        manifest["offsets"]["name"] = "private-account-id"
        folder = cache_directory(self.cache, key)
        folder.mkdir()
        (folder / "manifest.json").write_bytes(encoded(manifest))
        (folder / "locations.tsv").write_bytes(source)
        for name, raw in files.items():
            (folder / name).write_bytes(raw)
        for row in rows:
            row["object_index_sha256"] = digest(source)
        _, _, _, artifact_sha = load_bundle(folder, key, rows)
        self.policy["artifacts"].append({"keySha256": digest(key.encode()), "bundleSha256": artifact_sha,
                                         "members": [row_member(row, "input-model") for row in rows]})
        self.rows.extend(rows)
        return key

    def build(self, name="snapshot", **options):
        inventory, policy = encoded(self.inventory), encoded(self.policy)
        inventory_path, policy_path = self.root / "inventory.json", self.root / "policy.json"
        inventory_path.write_bytes(inventory)
        policy_path.write_bytes(policy)
        return build_object_snapshot(inventory_path, options.pop("inventory_pin", digest(inventory)), policy_path,
                                     options.pop("policy_pin", digest(policy)), self.cache, self.root / name, **options)

    def failed(self, reason):
        with self.assertRaisesRegex((SnapshotError, VisionIndexError), reason):
            self.build()
        self.assertFalse((self.root / "snapshot/snapshot.json").exists())
        report = json.loads((self.root / "snapshot/failure-report.json").read_text())
        self.assertFalse(report["sealed"])
        self.assertNotIn("private", report["error"])

    def test_seals_complete_audited_gen4_bundles_without_private_metadata(self):
        report = self.build()
        manifest = verify_object_snapshot(self.root / "snapshot", report["snapshotSha256"])
        self.assertEqual((manifest["locations"], len(manifest["bundles"])), (3, 2))
        members = json.loads((self.root / "snapshot/members.json").read_text())
        self.assertEqual([(row["sourceIndex"], row["locationId"], row["bundleIndex"], row["localIndex"])
                          for row in members], [(0, 3, 0, 0), (1, 10, 0, 1), (2, 20, 1, 0)])
        for file in (self.root / "snapshot").rglob("*"):
            if file.is_file():
                raw = file.read_bytes()
                for private in (b"private-account-id", b"private-source-map-label", b"private-road-label", str(self.root).encode()):
                    self.assertNotIn(private, raw)
        self.assertEqual(manifest["roadNameAuthority"], "unavailable")
        self.assertEqual(self.build("second")["snapshotSha256"], report["snapshotSha256"])

    def test_prototype_uncredited_pending_and_uncovered_locations_are_denied(self):
        original = copy.deepcopy(self.rows[0])
        for index, change in enumerate(({"contributor_id": ""}, {"state": "pending"}, {"lane": "scene"},
                                      {"model": "unreviewed"}, {"camera_generation": "gen3"},
                                      {"coverage_validator": "client-supplied-label"}, {"coverage_evidence_sha256": ""},
                                      {"location_output_sha256": "f" * 64})):
            self.rows[0] = {**original, **change}
            with self.subTest(change=change), self.assertRaisesRegex(SnapshotError, "not_a_covered_contributed_object"):
                self.build(f"denied-{index}")
        self.rows[0] = original
        self.rows[0]["coverage_evidence_sha256"] = "d" * 64
        self.failed("object_artifact_not_independently_approved")

    def test_global_id_checksum_does_not_approve_modified_semantic_features(self):
        key = self.rows[0]["object_index_key"]
        folder = cache_directory(self.cache, key)
        raw = (folder / "semantic-pq128.bin").read_bytes()
        changed = b"\x01" + raw[1:]
        (folder / "semantic-pq128.bin").write_bytes(changed)
        manifest = json.loads((folder / "manifest.json").read_bytes())
        manifest["semantic"]["sha256"] = digest(changed)
        (folder / "manifest.json").write_bytes(encoded(manifest))
        # Structural validation and published ID hashes still pass; the trusted
        # whole-bundle audit must reject the self-consistent feature alteration.
        load_bundle(folder, key, self.rows[:2])
        self.failed("object_artifact_not_independently_approved")

    def test_common_hot_and_semantic_file_corruption_is_rejected(self):
        folder = cache_directory(self.cache, self.rows[0]["object_index_key"])
        for index, filename in enumerate(("class-01-person.bin", "hot-00-bird-nest.bin", "semantic-pq128.bin")):
            file = folder / filename
            original = file.read_bytes()
            file.write_bytes(b"broken-feature")
            with self.subTest(filename=filename), self.assertRaises(VisionIndexError):
                self.build(f"corrupt-{index}")
            self.assertFalse((self.root / f"corrupt-{index}/snapshot.json").exists())
            file.write_bytes(original)

    def test_partial_batch_cannot_copy_unapproved_or_unpublished_neighbors(self):
        self.inventory["rows"] = [self.rows[0], self.rows[2]]
        self.failed("verification_failed")

    def test_pose_and_source_tsv_are_bound_to_database_and_auditor(self):
        folder = cache_directory(self.cache, self.rows[0]["object_index_key"])
        source = (folder / "locations.tsv").read_text()
        source = source.replace("\t90\t", "\t91\t", 1).encode()
        (folder / "locations.tsv").write_bytes(source)
        manifest = json.loads((folder / "manifest.json").read_bytes())
        manifest["sourceSha256"] = digest(source)
        manifest["sourceBytes"] = len(source)
        (folder / "manifest.json").write_bytes(encoded(manifest))
        for row in self.rows[:2]:
            row["object_index_sha256"] = digest(source)
        self.failed("object_source_pose_mismatch")

    def test_trusted_resource_inventory_and_policy_pins_are_required(self):
        for index, pin in enumerate(("inventory_pin", "policy_pin")):
            with self.assertRaisesRegex(SnapshotError, "input_checksum_mismatch"):
                self.build(f"pin-{index}", **{pin: "f" * 64})
        self.inventory["resource"] = {**CONFIRMED_RESOURCE, "bucket": "unconfirmed-bucket"}
        self.failed("invalid_community_inventory")

    def test_invalid_policy_duplicate_locations_path_escape_and_missing_files_never_seal(self):
        original_policy, original_inventory = copy.deepcopy(self.policy), copy.deepcopy(self.inventory)
        cases = [("invalid_object_approval_policy", lambda: self.policy.update(verification="client-checksums")),
                 ("duplicate_location_id", lambda: self.inventory["rows"].append(copy.deepcopy(self.rows[0]))),
                 ("invalid_object_artifact_key", lambda: self.inventory["rows"][0].update(object_index_key="object-index-v4/../secret/"))]
        for index, (reason, change) in enumerate(cases):
            self.policy, self.inventory = copy.deepcopy(original_policy), copy.deepcopy(original_inventory)
            change()
            with self.subTest(reason=reason), self.assertRaisesRegex(SnapshotError, reason):
                self.build(f"invalid-{index}")
            self.assertFalse((self.root / f"invalid-{index}/snapshot.json").exists())
        self.policy, self.inventory = original_policy, original_inventory
        folder = cache_directory(self.cache, self.rows[0]["object_index_key"])
        (folder / "global-location-ids.bin").unlink()
        with self.assertRaises(FileNotFoundError):
            self.build("missing")
        self.assertEqual(json.loads((self.root / "missing/failure-report.json").read_text()),
                         {"sealed": False, "error": "object_snapshot_build_failed"})

    def test_completed_output_is_immutable_and_pins_detect_payload_tampering(self):
        report = self.build()
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertFalse((self.root / "snapshot/failure-report.json").exists())
        folder = self.root / "snapshot" / "objects" / digest(self.rows[0]["object_index_key"].encode())
        (folder / "semantic-pq128.bin").write_bytes(b"bad")
        with self.assertRaisesRegex(SnapshotError, "input_checksum_mismatch"):
            verify_object_snapshot(self.root / "snapshot", report["snapshotSha256"])
        with self.assertRaisesRegex(SnapshotError, "input_checksum_mismatch"):
            verify_object_snapshot(self.root / "snapshot", "f" * 64)

    def test_new_batches_append_without_renumbering_and_removed_history_is_denied(self):
        first = self.build()
        self.add_bundle("e" * 32, [1])
        self.inventory["rows"] = self.rows
        second = self.build("next", previous=self.root / "snapshot", previous_sha256=first["snapshotSha256"])
        verify_object_snapshot(self.root / "next", second["snapshotSha256"])
        members = json.loads((self.root / "next/members.json").read_text())
        self.assertEqual([(row["sourceIndex"], row["locationId"], row["bundleIndex"])
                          for row in members], [(0, 3, 0), (1, 10, 0), (2, 20, 1), (3, 1, 2)])
        self.inventory["rows"] = [self.rows[-1]]
        with self.assertRaisesRegex(SnapshotError, "snapshot_history_changed"):
            self.build("removed", previous=self.root / "next", previous_sha256=second["snapshotSha256"])
        with self.assertRaisesRegex(SnapshotError, "previous_snapshot_pin_required"):
            self.build("unpinned", previous=self.root / "snapshot")

    def test_snapshot_budget_failure_preserves_report_without_publishing_marker(self):
        with patch("community.object_snapshot.MAX_SNAPSHOT_BYTES", 100):
            self.failed("object_snapshot_too_large")

    def test_sealer_refuses_metadata_larger_than_its_verifier_can_read(self):
        self.build("sized")
        member_bytes = (self.root / "sized/members.json").stat().st_size
        self.assertGreater((self.root / "sized/snapshot.json").stat().st_size, member_bytes)
        for name, limit in (("large-members", 1), ("large-manifest", member_bytes)):
            with self.subTest(name=name), patch("community.object_snapshot.MAX_SNAPSHOT_METADATA_BYTES", limit):
                with self.assertRaisesRegex(SnapshotError, "object_snapshot_metadata_too_large"):
                    self.build(name)
            self.assertFalse((self.root / name / "snapshot.json").exists())
            self.assertEqual(json.loads((self.root / name / "failure-report.json").read_text()),
                             {"sealed": False, "error": "object_snapshot_metadata_too_large"})

    def test_free_form_manifest_counters_cannot_leak_private_metadata(self):
        folder = cache_directory(self.cache, self.rows[0]["object_index_key"])
        manifest = json.loads((folder / "manifest.json").read_bytes())
        manifest["fetchErrors"] = "private-account-id"
        (folder / "manifest.json").write_bytes(encoded(manifest))
        self.failed("invalid_object_artifact")

    def test_append_update_cannot_replace_existing_features_even_with_new_audit(self):
        first = self.build()
        key = self.rows[0]["object_index_key"]
        folder = cache_directory(self.cache, key)
        file = folder / "semantic-pq128.bin"
        changed = b"\x01" + file.read_bytes()[1:]
        file.write_bytes(changed)
        manifest = json.loads((folder / "manifest.json").read_bytes())
        manifest["semantic"]["sha256"] = digest(changed)
        (folder / "manifest.json").write_bytes(encoded(manifest))
        _, _, _, new_digest = load_bundle(folder, key, self.rows[:2])
        self.policy["artifacts"][0]["bundleSha256"] = new_digest
        with self.assertRaisesRegex(SnapshotError, "snapshot_history_changed"):
            self.build("changed-history", previous=self.root / "snapshot", previous_sha256=first["snapshotSha256"])
        self.assertFalse((self.root / "changed-history/snapshot.json").exists())

    def add_quality(self):
        key = self.rows[0]["object_index_key"]
        folder = cache_directory(self.cache, key)
        raw = b"\x0f\x00\x00\x00\x00\x00\x00\x00" * 2
        (folder / "view-quality.bin").write_bytes(raw)
        manifest = json.loads((folder / "manifest.json").read_bytes())
        manifest["viewQuality"] = {"file": "view-quality.bin", "recordBytes": 8, "records": 2,
            "bytes": len(raw), "sha256": digest(raw), "policy": "vision-per-view-quality-v1",
            "implementationIdentity": "d" * 64, "viewCount": 6, "blurAreaFractionExclusive": 0.5,
            "tileGrid": 8, "tunnelVisionProbabilityInclusive": 0.85,
            "tunnelEvidencePolicy": "none-darkness-never-rejects-v1", "keptViews": 12,
            "blurRejectedViews": 0, "darkTunnelRejectedViews": 0, "fullyRejectedLocations": 0,
            "protectedAuthorityManifest": str(self.root / "private-authority.json"),
            "protectedAuthorityManifestSha256": "e" * 64}
        (folder / "manifest.json").write_bytes(encoded(manifest))
        _, _, _, new_digest = load_bundle(folder, key, self.rows[:2])
        self.policy["artifacts"][0]["bundleSha256"] = new_digest
        return folder, manifest

    def test_reference_view_quality_semantics_and_hashes_survive_without_local_paths(self):
        self.add_quality()
        report = self.build()
        snapshot = verify_object_snapshot(self.root / "snapshot", report["snapshotSha256"])
        folder = self.root / "snapshot" / snapshot["bundles"][0]["path"]
        exported = json.loads((folder / "manifest.json").read_bytes())["viewQuality"]
        self.assertEqual(exported["implementationIdentity"], "d" * 64)
        self.assertEqual(exported["protectedAuthorityManifestSha256"], "e" * 64)
        self.assertEqual(exported["keptViews"], 12)
        self.assertNotIn("protectedAuthorityManifest", exported)
        self.assertNotIn(str(self.root), (folder / "manifest.json").read_text())

    def test_invalid_view_quality_accounting_and_post_normalization_size_never_seal(self):
        folder, manifest = self.add_quality()
        manifest["viewQuality"]["keptViews"] = 11
        (folder / "manifest.json").write_bytes(encoded(manifest))
        self.failed("invalid_object_view_quality")
        manifest["viewQuality"]["keptViews"] = 12
        (folder / "manifest.json").write_bytes(encoded(manifest))
        with patch("community.object_snapshot.normalized_source", return_value=b"x" * (1024 * 1024 + 1)):
            with self.assertRaisesRegex(SnapshotError, "object_artifact_too_large"):
                self.build("expanded")
        self.assertFalse((self.root / "expanded/snapshot.json").exists())

    def test_self_consistent_envelope_cannot_escape_paths_or_forge_member_ordinals(self):
        report = self.build()
        root = self.root / "snapshot"
        manifest = json.loads((root / "snapshot.json").read_bytes())
        members = json.loads((root / "members.json").read_bytes())
        members[0]["sourceIndex"] = True
        raw = encoded(members)
        (root / "members.json").write_bytes(raw)
        manifest["files"]["members.json"] = {"bytes": len(raw), "sha256": digest(raw)}
        raw = encoded(manifest)
        (root / "snapshot.json").write_bytes(raw)
        with self.assertRaisesRegex(SnapshotError, "invalid_snapshot_members"):
            verify_object_snapshot(root, digest(raw))
        members[0]["sourceIndex"] = 0
        raw = encoded(members)
        (root / "members.json").write_bytes(raw)
        manifest["files"]["members.json"] = {"bytes": len(raw), "sha256": digest(raw)}
        manifest["bundles"][0]["path"] = "../outside"
        raw = encoded(manifest)
        (root / "snapshot.json").write_bytes(raw)
        with self.assertRaisesRegex(SnapshotError, "invalid_snapshot_manifest"):
            verify_object_snapshot(root, digest(raw))


if __name__ == "__main__":
    unittest.main()
