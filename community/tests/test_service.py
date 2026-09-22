import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from community.admin import audit, backup
from community.service import CommunityService, ServiceError, fixture_index_text, fixture_output


FIXTURE = Path(__file__).resolve().parents[1] / "demo_catalog.json"


def outputs_for(lease):
    return [
        {
            "locationId": item["locationId"],
            "indexText": fixture_index_text(item["label"]),
            "outputSha256": fixture_output(
                item["assetId"], item["capture"], item["lane"], item["model"],
                fixture_index_text(item["label"]),
            ),
        }
        for item in lease["items"]
    ]


class CommunityServiceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.service = CommunityService(Path(self.temporary.name) / "community.sqlite", search_cost=4)
        self.records = json.loads(FIXTURE.read_text(encoding="utf-8"))["locations"]
        self.assertEqual(self.service.import_synthetic(self.records), 12)
        self.first = self.service.create_account()
        self.second = self.service.create_account()

    def test_import_deduplicates_canonical_asset_capture_lane_and_model(self):
        self.assertEqual(self.service.import_synthetic(self.records), 0)
        alternate_capture = dict(self.records[0], capture="2025-12")
        alternate_lane = dict(self.records[0], lane="object")
        self.assertEqual(self.service.import_synthetic([alternate_capture, alternate_lane]), 2)

    def test_simultaneous_accounts_receive_disjoint_work(self):
        barrier = threading.Barrier(2)
        results = []

        def claim(account):
            barrier.wait()
            results.append(self.service.lease(account["accountId"], "scene", 4))

        threads = [threading.Thread(target=claim, args=(account,)) for account in (self.first, self.second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 2)
        self.assertTrue(
            {item["locationId"] for item in results[0]["items"]}.isdisjoint(
                {item["locationId"] for item in results[1]["items"]}
            )
        )

    def test_only_verified_complete_work_is_published_and_credited_once(self):
        account = self.first["accountId"]
        lease = self.service.lease(account, "scene", 4)
        valid = outputs_for(lease)
        bad = [dict(item) for item in valid]
        bad[0]["outputSha256"] = "0" * 64
        with self.assertRaisesRegex(ServiceError, "verification_failed"):
            self.service.submit(account, lease["leaseId"], bad)
        bad_text = [dict(item) for item in valid]
        bad_text[0]["indexText"] = "forged search text"
        with self.assertRaisesRegex(ServiceError, "verification_failed"):
            self.service.submit(account, lease["leaseId"], bad_text)
        self.assertEqual(self.service.status(account)["units"], 0)
        with self.assertRaisesRegex(ServiceError, "incomplete_submission"):
            self.service.submit(account, lease["leaseId"], valid[:-1])
        with sqlite3.connect(self.service.database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM published_index").fetchone()[0], 0)
        accepted = self.service.submit(account, lease["leaseId"], valid)
        self.assertEqual(accepted["unitsEarned"], 4)
        with sqlite3.connect(self.service.database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM published_index").fetchone()[0], 4)
        replay = self.service.submit(account, lease["leaseId"], valid)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["unitsEarned"], 0)
        self.assertEqual(self.service.status(account)["units"], 4)

    def test_expired_work_can_be_reassigned_but_old_lease_cannot_publish(self):
        old = self.service.lease(self.first["accountId"], "scene", 1, now=100)
        new = self.service.lease(self.second["accountId"], "scene", 1, now=100 + 30 * 60)
        self.assertEqual(old["items"][0]["locationId"], new["items"][0]["locationId"])
        with self.assertRaisesRegex(ServiceError, "expired_lease"):
            self.service.submit(self.first["accountId"], old["leaseId"], outputs_for(old), now=2000)
        result = self.service.submit(self.second["accountId"], new["leaseId"], outputs_for(new), now=2000)
        self.assertEqual(result["unitsEarned"], 1)

    def test_shared_index_requires_search_credit_for_every_account(self):
        first_id = self.first["accountId"]
        second_id = self.second["accountId"]
        lease = self.service.lease(first_id, "scene", 4)
        self.service.submit(first_id, lease["leaseId"], outputs_for(lease))
        with self.assertRaisesRegex(ServiceError, "insufficient_credit"):
            self.service.search(second_id, "pine", "request-second-001")
        result = self.service.search(first_id, "pine", "request-first-001")
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(self.service.search(first_id, "pine", "request-first-001"), result)
        with self.assertRaisesRegex(ServiceError, "idempotency_conflict"):
            self.service.search(first_id, "bridge", "request-first-001")
        self.assertEqual(self.service.status(first_id)["units"], 0)
        with self.assertRaisesRegex(ServiceError, "insufficient_credit"):
            self.service.search(first_id, "pine", "request-first-002")
        own_lease = self.service.lease(second_id, "scene", 4)
        self.service.submit(second_id, own_lease["leaseId"], outputs_for(own_lease))
        second_result = self.service.search(second_id, "pine", "request-second-002")
        self.assertEqual(len(second_result["results"]), 3)

    def test_concurrent_searches_cannot_spend_one_balance_twice(self):
        account = self.first["accountId"]
        lease = self.service.lease(account, "scene", 4)
        self.service.submit(account, lease["leaseId"], outputs_for(lease))
        barrier = threading.Barrier(2)
        outcomes = []

        def search(key):
            barrier.wait()
            try:
                outcomes.append(self.service.search(account, "pine", key))
            except ServiceError as error:
                outcomes.append(error.code)

        threads = [threading.Thread(target=search, args=(f"request-{i:03d}",)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(isinstance(result, dict) for result in outcomes), 1)
        self.assertIn("insufficient_credit", outcomes)
        self.assertEqual(self.service.status(account)["units"], 0)

    def test_token_is_required_and_other_account_cannot_submit_lease(self):
        with self.assertRaisesRegex(ServiceError, "unauthorized"):
            self.service.account_for_token("invalid")
        lease = self.service.lease(self.first["accountId"], "scene", 1)
        with self.assertRaisesRegex(ServiceError, "unknown_lease"):
            self.service.submit(self.second["accountId"], lease["leaseId"], outputs_for(lease))

    def test_audit_and_consistent_backup_include_published_work_and_credits(self):
        lease = self.service.lease(self.first["accountId"], "scene", 4)
        self.service.submit(self.first["accountId"], lease["leaseId"], outputs_for(lease))
        destination = Path(self.temporary.name) / "backup.sqlite"
        self.assertTrue(audit(self.service.database)["ok"])
        self.assertTrue(backup(self.service.database, destination)["ok"])
        self.assertEqual(audit(destination)["counts"]["published_index"], 4)

    def test_audit_detects_credit_drift(self):
        with sqlite3.connect(self.service.database) as connection:
            connection.execute("UPDATE accounts SET units=units+1 WHERE id=?", (self.first["accountId"],))
        self.assertIn("credit_ledger_mismatch", audit(self.service.database)["issues"])

    def test_second_lease_resumes_the_active_batch(self):
        first = self.service.lease(self.first["accountId"], "scene", 4)
        second = self.service.lease(self.first["accountId"], "scene", 4)
        self.assertEqual(first["leaseId"], second["leaseId"])
        self.assertTrue(second.get("resumed"))
        self.assertEqual(
            {item["locationId"] for item in first["items"]},
            {item["locationId"] for item in second["items"]},
        )

    def test_release_returns_unsubmitted_work(self):
        lease = self.service.lease(self.first["accountId"], "scene", 4)
        released = self.service.release_lease(self.first["accountId"], lease["leaseId"])
        self.assertEqual(released["released"], 4)
        again = self.service.lease(self.second["accountId"], "scene", 4)
        self.assertEqual(
            {item["locationId"] for item in lease["items"]},
            {item["locationId"] for item in again["items"]},
        )


class PoseCatalogLeaseTest(unittest.TestCase):
    def test_lease_reads_shards_instead_of_preloading_sqlite(self):
        from community.all_locations_tail import split_shards

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "tail.tsv"
            lines = []
            for index in range(4):
                lines.append(
                    "\t".join(
                        (
                            "map",
                            str(index),
                            "10.0",
                            "20.0",
                            "90",
                            "0",
                            "0",
                            f"CatalogPano{index:016d}",
                            "Italy",
                            "gen4",
                            "no road name",
                        )
                    )
                )
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            shards = root / "shards"
            manifest = split_shards(source, shards, rows_per_shard=2, row_start=1000)
            service = CommunityService(root / "db.sqlite", search_cost=4, artifacts=root / "artifacts")
            report = service.install_pose_catalog(manifest, source_dir=shards)
            self.assertEqual(report["rows"], 4)
            status = service.status()
            self.assertEqual(status["counts"]["scene"]["pending"], 4)
            self.assertEqual(status["counts"]["scene"]["catalogRemaining"], 4)
            account = service.create_account()
            lease = service.lease(account["accountId"], "scene", 3)
            self.assertEqual(len(lease["items"]), 3)
            self.assertTrue(all(item["assetId"].startswith("CatalogPano") for item in lease["items"]))
            after = service.status()
            self.assertEqual(after["counts"]["scene"]["catalogRemaining"], 1)
            self.assertEqual(after["counts"]["scene"]["pending"], 4)


if __name__ == "__main__":
    unittest.main()
