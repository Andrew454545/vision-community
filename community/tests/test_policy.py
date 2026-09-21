import tempfile
import unittest
from pathlib import Path

from community.service import CommunityService, ServiceError, UNITS_PER_LOCATION


ROOT = Path(__file__).resolve().parents[2]
WORKER_MODEL = ROOT / "deploy" / "cloudflare" / "src" / "model.js"


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
            self.assertEqual(live.status()["searchCost"], 100_000)
            self.assertFalse(live.status()["ownerBypass"])
            self.assertEqual(UNITS_PER_LOCATION, {"scene": 1, "object": 10})
            with self.assertRaisesRegex(ServiceError, "insufficient_credit"):
                service.search(account, "pine", "first-search-001")
            operational_account = live.create_account()["accountId"]
            with self.assertRaisesRegex(ServiceError, "insufficient_credit"):
                live.search(operational_account, "pine", "operational-search-001")

    def test_hosted_worker_search_cost_is_one_hundred_thousand(self):
        source = WORKER_MODEL.read_text(encoding="utf-8")
        self.assertIn("export const SEARCH_COST = 100000;", source)
        self.assertIn("export const SITE_SEARCH_CAP = 2000;", source)
        self.assertNotIn("export const SEARCH_COST = 4;", source)
        self.assertIn("scene: 1", source)
        self.assertIn("object: 10", source)


class PublicSurfaceIdentityTest(unittest.TestCase):
    def test_public_web_does_not_link_a_personal_github_user(self):
        import re

        web = ROOT / "community" / "web"
        for path in web.rglob("*"):
            if not path.is_file() or path.suffix not in {".html", ".js", ".css", ".json", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"github\.com/[A-Za-z0-9_-]+", text),
                msg=str(path),
            )
            self.assertNotIn("/Users/", text)
            self.assertNotIn("\\Users\\", text)

    def test_hosted_worker_tags_each_hit_with_country_name(self):
        source = (ROOT / "deploy" / "cloudflare" / "src" / "worker.js").read_text(encoding="utf-8")
        self.assertIn("tags: [canonicalizeCountry(hit.country || \"\")]", source)
        self.assertNotIn("tags: hit.country ? [hit.country] : []", source)
        self.assertIn('body.execute === "local"', source)
        self.assertIn("search_on_computer", source)


if __name__ == "__main__":
    unittest.main()

