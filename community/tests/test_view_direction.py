"""Saved pan, cross-axis, and other VISION view-direction search modes."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from community.features import (
    MODEL_ID,
    SCENE_FACE_DIM,
    VIEW_DIRECTION_OFFSETS,
    best_scene_view,
    embedding_for,
    render_faces,
    wrap_heading,
)
from community.search import ranked_search_embedding
from community.segments import SegmentRegistry
from community.service import CommunityService
from community.worker import ProcessingWorker


STREET = Path(__file__).resolve().parents[1] / "street_catalog.json"


class ViewDirectionHelpersTest(unittest.TestCase):
    def test_offsets_match_local_vision(self):
        self.assertEqual(VIEW_DIRECTION_OFFSETS["original"], (0,))
        self.assertEqual(VIEW_DIRECTION_OFFSETS["right"], (1,))
        self.assertEqual(VIEW_DIRECTION_OFFSETS["opposite"], (2,))
        self.assertEqual(VIEW_DIRECTION_OFFSETS["left"], (3,))
        self.assertEqual(VIEW_DIRECTION_OFFSETS["originalAxis"], (0, 2))
        self.assertEqual(VIEW_DIRECTION_OFFSETS["sideAxis"], (1, 3))
        self.assertEqual(wrap_heading(450), 90)
        self.assertEqual(wrap_heading(-90), 270)

    def test_opposite_and_cross_axis_select_the_matching_compass_face(self):
        query = embedding_for("scene", render_faces("synthetic:view:q", "2026-01", "scene", MODEL_ID))
        opposite = bytearray(embedding_for("scene", render_faces("synthetic:view:opp", "2026-01", "scene", MODEL_ID)))
        opposite[2 * SCENE_FACE_DIM : 3 * SCENE_FACE_DIM] = query[:SCENE_FACE_DIM]
        score, offset = best_scene_view(query, bytes(opposite), VIEW_DIRECTION_OFFSETS["opposite"])
        self.assertEqual(offset, 2)
        self.assertGreater(score, 0.99)

        side = bytearray(embedding_for("scene", render_faces("synthetic:view:side", "2026-01", "scene", MODEL_ID)))
        side[SCENE_FACE_DIM : 2 * SCENE_FACE_DIM] = query[:SCENE_FACE_DIM]
        score, offset = best_scene_view(query, bytes(side), VIEW_DIRECTION_OFFSETS["sideAxis"])
        self.assertEqual(offset, 1)
        self.assertGreater(score, 0.99)

        saved, saved_offset = best_scene_view(query, bytes(side), VIEW_DIRECTION_OFFSETS["original"])
        self.assertEqual(saved_offset, 0)
        self.assertLess(saved, score)

    def test_ranked_search_opposite_prefers_the_180_face(self):
        query = embedding_for("scene", render_faces("synthetic:view:q", "2026-01", "scene", MODEL_ID))
        original = embedding_for("scene", render_faces("synthetic:view:orig", "2026-01", "scene", MODEL_ID))
        opposite = bytearray(embedding_for("scene", render_faces("synthetic:view:opp", "2026-01", "scene", MODEL_ID)))
        opposite[2 * SCENE_FACE_DIM : 3 * SCENE_FACE_DIM] = query[:SCENE_FACE_DIM]
        with tempfile.TemporaryDirectory() as folder:
            registry = SegmentRegistry(Path(folder), capacity=10)
            registry.publish(
                lane="scene",
                location_ids=[1, 2],
                embeddings=original + bytes(opposite),
                poses=[
                    {
                        "locationId": 1,
                        "panoId": "orig",
                        "lat": 0,
                        "lng": 0,
                        "heading": 10,
                        "pitch": 0,
                        "zoom": 0,
                    },
                    {
                        "locationId": 2,
                        "panoId": "opp",
                        "lat": 1,
                        "lng": 1,
                        "heading": 10,
                        "pitch": 0,
                        "zoom": 0,
                    },
                ],
            )
            saved = ranked_search_embedding(registry, "scene", query, limit=2, view_direction="original")
            flipped = ranked_search_embedding(registry, "scene", query, limit=2, view_direction="opposite")
        self.assertEqual(flipped[0]["locationId"], 2)
        self.assertEqual(flipped[0]["viewOffset"], 2)
        self.assertNotEqual(saved[0]["locationId"], flipped[0]["locationId"])


class ViewDirectionSearchTest(unittest.TestCase):
    def test_search_writes_heading_offset_and_can_exclude_a_previous_map(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(
                Path(folder) / "db.sqlite",
                search_cost=1,
                artifacts=Path(folder) / "artifacts",
                segment_capacity=20,
            )
            catalog = json.loads(STREET.read_text(encoding="utf-8"))
            service.import_jobs(catalog)
            account = service.create_account()
            lease = service.lease(account["accountId"], "scene", 4)
            service.submit(account["accountId"], lease["leaseId"], ProcessingWorker().process_lease(lease))
            query_map = {
                "name": "Reference",
                "customCoordinates": [
                    {
                        "lat": 41.9,
                        "lng": 12.5,
                        "heading": 90,
                        "pitch": 0,
                        "zoom": 0,
                        "panoId": "CommunityPano000000000001",
                    }
                ],
            }
            saved = service.search(
                account["accountId"],
                None,
                "view-original",
                query_map=query_map,
                view_direction="original",
            )
            first = saved["map"]["customCoordinates"][0]
            self.assertEqual(first["extra"]["visionHeadingOffset"], 0)
            self.assertAlmostEqual(first["heading"], 90)

            opposite = service.search(
                account["accountId"],
                None,
                "view-opposite",
                query_map=query_map,
                view_direction="opposite",
            )
            flipped = opposite["map"]["customCoordinates"][0]
            self.assertEqual(flipped["extra"]["visionHeadingOffset"], 180)
            self.assertGreaterEqual(flipped["heading"], 0)
            self.assertLess(flipped["heading"], 360)

            excluded = service.search(
                account["accountId"],
                None,
                "view-exclude",
                query_map=query_map,
                view_direction="original",
                exclude_map={"customCoordinates": [first]},
            )
            remaining = [hit["panoId"] for hit in excluded["map"]["customCoordinates"]]
            self.assertNotIn(first["panoId"], remaining)


if __name__ == "__main__":
    unittest.main()
