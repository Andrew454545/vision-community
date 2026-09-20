import unittest

from community.rank import (
    accepts,
    cap_by_country,
    canonicalize_country,
    clamp_result_count,
    normalize_filters,
    prune_nearby,
)


class RankHelpersTest(unittest.TestCase):
    def test_all_generations_means_no_generation_filter(self):
        mode, countries, generations = normalize_filters(
            "all",
            ["Japan"],
            ["badcam", "gen1", "gen2", "gen3", "gen4", "trekker"],
        )
        self.assertEqual(mode, "all")
        self.assertEqual(countries, [])
        self.assertEqual(generations, [])

    def test_include_without_countries_stays_include(self):
        mode, countries, generations = normalize_filters("include", [], ["gen4"])
        self.assertEqual(mode, "include")
        self.assertEqual(countries, [])
        self.assertEqual(generations, ["gen4"])

    def test_accepts_country_and_generation(self):
        record = {"pose": {"country": "Japan", "cameraGeneration": "gen4"}}
        self.assertTrue(accepts(record, "include", ["Japan"], ["gen4"]))
        self.assertFalse(accepts(record, "include", ["Italy"], ["gen4"]))
        self.assertFalse(accepts(record, "exclude", ["Japan"], []))
        self.assertFalse(accepts(record, "all", [], ["gen3"]))

    def test_country_cap_keeps_highest_scores(self):
        hits = [
            {"score": 1.0, "pose": {"country": "USA"}},
            {"score": 0.9, "pose": {"country": "USA"}},
            {"score": 0.8, "pose": {"country": "Japan"}},
        ]
        capped = cap_by_country(hits, result_count=2, max_per_country=1)
        self.assertEqual([hit["pose"]["country"] for hit in capped], ["USA", "Japan"])
        self.assertEqual(clamp_result_count(0), 1)
        self.assertEqual(clamp_result_count(50_000), 10_000)

    def test_united_states_alias_matches_vision_usa_tag(self):
        self.assertEqual(canonicalize_country("United States"), "USA")
        mode, countries, _gens = normalize_filters("exclude", ["United States"], [])
        self.assertEqual(countries, ["USA"])
        self.assertFalse(accepts({"pose": {"country": "United States"}}, "exclude", countries, []))

    def test_nearby_duplicate_panoramas_are_pruned(self):
        hits = [
            {"score": 1.0, "pose": {"panoId": "a", "lat": 0, "lng": 0, "country": "USA"}},
            {"score": 0.9, "pose": {"panoId": "b", "lat": 0.0002, "lng": 0, "country": "USA"}},
            {"score": 0.8, "pose": {"panoId": "c", "lat": 1, "lng": 1, "country": "Canada"}},
        ]
        pruned = prune_nearby(hits)
        self.assertEqual([hit["pose"]["panoId"] for hit in pruned], ["a", "c"])


if __name__ == "__main__":
    unittest.main()
