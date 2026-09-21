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
        worker = (ROOT / "deploy" / "cloudflare" / "src" / "worker.js").read_text(encoding="utf-8")
        self.assertIn("reason='search' AND units<0", worker)
        self.assertIn("UPDATE accounts SET units=units-? WHERE id=? AND units>=?", worker)


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

    def test_public_web_uses_vision_saved_pan_labels(self):
        html = (ROOT / "community" / "web" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "community" / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("Saved pan (0°)", html)
        self.assertIn("Opposite saved pan (180°)", html)
        self.assertIn("Saved pan (0°)", app)
        worker = (ROOT / "deploy" / "cloudflare" / "src" / "worker.js").read_text(encoding="utf-8")
        self.assertIn("cameraGeneration: parts[9] || \"\"", worker)
        self.assertIn("heading: Number(parts[4]) || 0", worker)
        self.assertIn("catalog/all-locations-tail-v1/", worker)
        self.assertIn("assignee=?", worker)
        self.assertIn("separateParts: true", worker)

    def test_hosted_worker_tags_each_hit_with_country_name(self):
        source = (ROOT / "deploy" / "cloudflare" / "src" / "worker.js").read_text(encoding="utf-8")
        self.assertIn("tags: [canonicalizeCountry(hit.country || \"\")]", source)
        self.assertNotIn("tags: hit.country ? [hit.country] : []", source)
        self.assertIn('body.execute === "local"', source)
        self.assertIn("search_on_computer", source)

    def test_app_offers_scene_and_object_processing(self):
        html = (ROOT / "community" / "web" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "community" / "web" / "app.js").read_text(encoding="utf-8")
        worker = (ROOT / "deploy" / "cloudflare" / "src" / "worker.js").read_text(encoding="utf-8")
        process_at = html.index('id="process-lane"')
        speed_at = html.index("Speed and batch number")
        self.assertLess(process_at, speed_at)
        self.assertIn('value="scene"', html[process_at:speed_at])
        self.assertIn('value="object"', html[process_at:speed_at])
        self.assertIn('value="both"', html[process_at:speed_at])
        self.assertNotIn("Places or objects, and speed", html)
        self.assertIn("selectedProcessLanes", app)
        self.assertIn('choice === "both"', app)
        self.assertIn("workByLane", app)
        self.assertIn("workByLane", worker)
        html = (ROOT / "community" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="prompt"', html)
        self.assertIn('name="description-weight"', html)
        self.assertIn("What to search with", html)
        self.assertIn("descriptionEmbedding", worker)
        self.assertIn("mixEmbeddings", worker)

    def test_indexing_avoids_full_status_on_every_batch(self):
        app = (ROOT / "community" / "web" / "app.js").read_text(encoding="utf-8")
        worker = (ROOT / "deploy" / "cloudflare" / "src" / "worker.js").read_text(encoding="utf-8")
        self.assertIn("applyCredit", app)
        self.assertIn("holdWakeLock", app)
        self.assertIn("/api/me?lite=1", app)
        self.assertIn("vision-community-jobs", app)
        self.assertIn("REFRESH_EVERY_BATCHES", app)
        self.assertIn('lite: url.searchParams.get("lite") === "1"', worker)
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(Path(folder) / "lite.sqlite", operational=True)
            account = service.create_account()["accountId"]
            full = service.status(account)
            lite = service.status(account, lite=True)
            self.assertEqual(lite["searchCost"], 100_000)
            self.assertEqual(lite["units"], full["units"])
            self.assertEqual(lite["countries"], [])
            self.assertNotIn("workByLane", lite)
            self.assertIn("workByLane", full)


if __name__ == "__main__":
    unittest.main()

