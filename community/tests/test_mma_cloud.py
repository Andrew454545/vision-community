import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from community.mma import MMAError
from community.mma_cloud import (
    CloudError,
    add_map_locations,
    cloud_locations,
    create_map,
    list_maps,
    send_map,
)


class FakeMMA(BaseHTTPRequestHandler):
    maps = []
    created = []
    edits = []

    def log_message(self, format, *args):
        return

    def _read(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Authorization") != "API test-key":
            return self._send(401, {"message": "Login required"})
        if urlparse(self.path).path == "/api/maps":
            return self._send(200, {"maps": self.maps})
        return self._send(404, {"message": "not found"})

    def do_POST(self):
        if self.headers.get("Authorization") != "API test-key":
            return self._send(401, {"message": "Login required"})
        path = urlparse(self.path).path
        body = self._read()
        if path == "/api/maps":
            created = {"id": "map-new", "name": body.get("name") or "Untitled"}
            self.created.append(created)
            return self._send(200, created)
        if path.endswith("/locations"):
            self.edits.append(body)
            return self._send(200, {"ok": True})
        return self._send(404, {"message": "not found"})


class MapMakingCloudTest(unittest.TestCase):
    def setUp(self):
        FakeMMA.maps = [{"id": "map-1", "name": "Keepers"}]
        FakeMMA.created = []
        FakeMMA.edits = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeMMA)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.origin = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_cloud_locations_keep_country_tags_and_pano_flag(self):
        rows = cloud_locations(
            {
                "name": "Red barns",
                "customCoordinates": [
                    {
                        "lat": 1.5,
                        "lng": 2.5,
                        "heading": 90,
                        "pitch": 1,
                        "zoom": 0,
                        "panoId": "PanoKeepCountry001",
                        "extra": {"tags": ["Italy"], "visionRank": 1},
                    }
                ],
            }
        )
        self.assertEqual(rows[0]["panoId"], "PanoKeepCountry001")
        self.assertEqual(rows[0]["flags"], 1)
        self.assertEqual(rows[0]["location"], {"lat": 1.5, "lng": 2.5})
        self.assertEqual(rows[0]["tags"], ["Italy"])
        self.assertEqual(rows[0]["extra"]["visionRank"], 1)

    def test_send_creates_map_and_posts_location_edits(self):
        document = {
            "name": "Community barns",
            "customCoordinates": [
                {"lat": 10, "lng": 20, "heading": 0, "pitch": 0, "zoom": 0, "panoId": "PanoSend001", "extra": {"tags": ["USA"]}}
            ],
        }
        listed = list_maps("test-key", origin=self.origin)
        self.assertEqual(listed, [{"id": "map-1", "name": "Keepers"}])
        created = create_map("test-key", "Community barns", origin=self.origin)
        self.assertEqual(created["id"], "map-new")
        result = add_map_locations("test-key", "map-1", document, origin=self.origin)
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["url"], f"{self.origin}/maps/map-1")
        edit = FakeMMA.edits[0]["edits"][0]
        self.assertEqual(edit["action"]["type"], 4)
        self.assertEqual(edit["create"][0]["panoId"], "PanoSend001")
        sent = send_map(document, api_key="test-key", new_map=True, origin=self.origin)
        self.assertEqual(sent["added"], 1)
        self.assertEqual(sent["mapId"], "map-new")
        with self.assertRaises(CloudError):
            list_maps("", origin=self.origin)
        with self.assertRaises(MMAError):
            cloud_locations({"name": "Empty", "customCoordinates": []})

    def test_web_offers_map_app_connect(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        app = (root / "web" / "app.js").read_text(encoding="utf-8")
        script = (root / "web" / "mma.js").read_text(encoding="utf-8")
        self.assertIn('id="mma-api-key"', html)
        self.assertIn('id="send-mma"', html)
        self.assertIn('id="copy-mma"', html)
        self.assertIn("Connect a map app", html)
        self.assertIn("sendToMapMaking", app)
        self.assertIn("copyForLocalMma", app)
        self.assertIn("localStorage", script)
        self.assertIn("https://map-making.app", script)
        self.assertNotIn("/api/mma", app)
        self.assertNotIn("/api/mma", script)
        worker = (Path(__file__).resolve().parents[2] / "deploy" / "cloudflare" / "src" / "worker.js").read_text(encoding="utf-8")
        server = (Path(__file__).resolve().parents[2] / "community" / "server.py").read_text(encoding="utf-8")
        self.assertIn("connect-src 'self' https://map-making.app", worker)
        self.assertIn("connect-src 'self' https://map-making.app", server)


if __name__ == "__main__":
    unittest.main()
