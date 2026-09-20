import tempfile
import unittest
from pathlib import Path

from community.service import CommunityService, ServiceError, UNITS_PER_LOCATION


class PublicCreditPolicyTest(unittest.TestCase):
    def test_new_account_has_no_search_and_public_rate_is_exact(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(Path(folder) / "policy.sqlite")
            account = service.create_account()["accountId"]
            state = service.status(account)
            self.assertEqual(state["searchCost"], 100_000)
            self.assertEqual(state["units"], 0)
            self.assertEqual(state["searchesAvailable"], 0)
            self.assertFalse(state["operational"])
            self.assertFalse(state["ownerBypass"])
            live = CommunityService(Path(folder) / "live.sqlite", operational=True)
            self.assertTrue(live.status()["operational"])
            self.assertEqual(UNITS_PER_LOCATION, {"scene": 1, "object": 10})
            with self.assertRaisesRegex(ServiceError, "insufficient_credit"):
                service.search(account, "pine", "first-search-001")


if __name__ == "__main__":
    unittest.main()
