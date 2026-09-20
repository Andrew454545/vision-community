"""VISION-matching view geometry and integer downsample, without network I/O."""

from __future__ import annotations

import io
import math
import tempfile
import unittest
from pathlib import Path

from community.features import FACE_SIZE, FACES_BYTES, MODEL_ID, render_faces
from community.pano import (
    FACE_FOV,
    downsample_box,
    location_from_row,
    render_location_faces,
    thumbnail_fov,
    thumbnail_url,
    uses_street_views,
    view_plan,
    wrap_heading,
)


class ViewGeometryTest(unittest.TestCase):
    def test_scene_four_view_uses_pose_pitch_and_zoom_fov(self):
        plan = view_plan("scene", heading=270, pitch=8, zoom=1)
        self.assertEqual(len(plan), 6)
        self.assertEqual([view["yaw"] for view in plan[:4]], [270.0, 0.0, 90.0, 180.0])
        self.assertTrue(all(view["pitch"] == 8.0 for view in plan[:4]))
        self.assertAlmostEqual(plan[0]["fov"], thumbnail_fov(1), places=9)
        self.assertEqual(plan[4], {"yaw": 270.0, "pitch": 90.0, "fov": FACE_FOV})
        self.assertEqual(plan[5], {"yaw": 270.0, "pitch": -90.0, "fov": FACE_FOV})

    def test_object_cube_ignores_pose_pitch_and_uses_90_fov(self):
        plan = view_plan("object", heading=15, pitch=12, zoom=2)
        self.assertEqual([view["yaw"] for view in plan[:4]], [15.0, 105.0, 195.0, 285.0])
        self.assertTrue(all(view["pitch"] == 0.0 and view["fov"] == 90.0 for view in plan[:4]))
        self.assertEqual(plan[4]["pitch"], 90.0)
        self.assertEqual(plan[5]["pitch"], -90.0)

    def test_thumbnail_fov_matches_vision_formula_and_clamps(self):
        expected = (360.0 / math.pi) * math.atan(0.75 * 2.0)
        self.assertAlmostEqual(thumbnail_fov(0), min(120.0, max(30.0, expected)), places=12)
        self.assertEqual(thumbnail_fov(-10), 120.0)
        self.assertEqual(thumbnail_fov(8), 30.0)

    def test_thumbnail_url_negates_pitch_and_does_not_store_a_host_path(self):
        url = thumbnail_url("CAoSLEFGMVFpcE5realpano0001", 270, 8, 90)
        self.assertTrue(url.startswith("https://geo0.ggpht.com/cbk?"))
        self.assertIn("cb_client=apiv3", url)
        self.assertIn("output=thumbnail", url)
        self.assertIn("panoid=CAoSLEFGMVFpcE5realpano0001", url)
        self.assertIn("yaw=270", url)
        self.assertIn("pitch=-8", url)
        self.assertIn("thumbfov=90", url)
        self.assertIn("w=64", url)
        self.assertIn("h=64", url)
        zoom0 = thumbnail_url("CAoSLEFGMVFpcE5realpano0001", 106.92, 0, thumbnail_fov(0))
        self.assertIn("thumbfov=113", zoom0)

    def test_heading_wraps_like_euclidean_remainder(self):
        self.assertEqual(wrap_heading(-10), 350.0)
        self.assertEqual(wrap_heading(370), 10.0)

    def test_invented_ids_do_not_fetch_street_view(self):
        self.assertFalse(uses_street_views("PrototypeBerkeleyCA000001"))
        self.assertFalse(uses_street_views("CommunityPano000000000001"))
        self.assertFalse(uses_street_views("synthetic:visual:001"))
        self.assertFalse(uses_street_views("https://maps.googleapis.com/maps/api/streetview"))
        self.assertTrue(uses_street_views("CAoSLEFGMVFpcE5realpano0001"))


class DownsampleTest(unittest.TestCase):
    def test_box_filter_64_to_16_is_integer_mean(self):
        width = height = 64
        rgb = bytearray(width * height * 3)
        for y in range(height):
            for x in range(width):
                index = (y * width + x) * 3
                rgb[index] = x
                rgb[index + 1] = y
                rgb[index + 2] = (x + y) & 255
        face = downsample_box(bytes(rgb), width, height, FACE_SIZE)
        self.assertEqual(len(face), FACE_SIZE * FACE_SIZE * 3)
        # Top-left 4×4 block mean of x=0..3, y=0..3.
        self.assertEqual(face[0], (0 + 1 + 2 + 3) * 4 // 16)
        self.assertEqual(face[1], (0 + 1 + 2 + 3) * 4 // 16)


class InventedFallbackTest(unittest.TestCase):
    def test_render_location_faces_keeps_seed_for_prototype(self):
        location = location_from_row(
            {
                "asset_id": "PrototypeBerkeleyCA000001",
                "capture": "2019-06",
                "lane": "scene",
                "model": MODEL_ID,
                "heading": 270,
                "pitch": 0,
                "zoom": 0,
            }
        )
        faces = render_location_faces(location)
        self.assertEqual(len(faces), FACES_BYTES)
        self.assertEqual(faces, render_faces("PrototypeBerkeleyCA000001", "2019-06", "scene", MODEL_ID))

    def test_street_faces_use_fetcher_not_seed(self):
        from PIL import Image

        calls = []

        def fake_fetch(url: str) -> bytes:
            calls.append(url)
            image = Image.new("RGB", (64, 64), (len(calls) * 10, 20, 30))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=95)
            return buffer.getvalue()

        faces = render_location_faces(
            {
                "panoId": "CAoSLEFGMVFpcE5realpano0001",
                "capture": "2020-06",
                "lane": "scene",
                "model": MODEL_ID,
                "heading": 90,
                "pitch": 4,
                "zoom": 0,
            },
            fetch=fake_fetch,
        )
        self.assertEqual(len(calls), 6)
        self.assertEqual(len(faces), FACES_BYTES)
        self.assertNotEqual(faces, render_faces("CAoSLEFGMVFpcE5realpano0001", "2020-06", "scene", MODEL_ID))
        self.assertTrue(all("geo0.ggpht.com/cbk" in url for url in calls))
        self.assertIn("yaw=90", calls[0])
        self.assertIn("pitch=-4", calls[0])


    def test_views_returns_seed_faces_for_prototype(self):
        import base64
        from community.service import CommunityService

        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(Path(folder) / "db.sqlite", search_cost=4)
            account = service.create_account()
            result = service.views(
                account["accountId"],
                {
                    "pano": "PrototypeBerkeleyCA000001",
                    "capture": "2019-06",
                    "lane": "scene",
                    "heading": 270,
                    "pitch": 0,
                    "zoom": 0,
                },
            )
            self.assertEqual(result["viewStrategy"], "identity-seed")
            self.assertFalse(result["persistImagery"])
            self.assertEqual(
                base64.b64decode(result["faces"]),
                render_faces("PrototypeBerkeleyCA000001", "2019-06", "scene", MODEL_ID),
            )

    def test_views_rejects_imagery_urls(self):
        from community.service import CommunityService, ServiceError

        with tempfile.TemporaryDirectory() as folder:
            service = CommunityService(Path(folder) / "db.sqlite", search_cost=4)
            account = service.create_account()
            with self.assertRaisesRegex(ServiceError, "imagery_url_forbidden"):
                service.views(
                    account["accountId"],
                    {"pano": "https://maps.googleapis.com/maps/api/streetview", "lane": "scene"},
                )


if __name__ == "__main__":
    unittest.main()
