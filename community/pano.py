"""Street View view geometry matching VISION.app, without copying its models.

Scene processing uses the four-view compass (heading + 0/90/180/270) at the
saved pose pitch and thumbnail FOV from zoom. Object processing uses the
six-face cube (those four headings at pitch 0, plus zenith and nadir) at 90°
FOV. Community still downsamples each view to a 16×16 integer face so the
existing community-visual-v1 descriptor can be recomputed. Imagery is fetched
ephemerally and never written to disk, D1, or R2.

Invented catalog IDs (Prototype, CommunityPano, synthetic, wikimedia) keep the
identity-seed extractor so local tests do not hit the network.
"""

from __future__ import annotations

import io
import math
import time
import urllib.error
import urllib.parse
import urllib.request

from .features import FACE_COUNT, FACE_SIZE, FACES_BYTES, render_faces


THUMB_SIZE = 64
FACE_FOV = 90.0
THUMBNAIL_ENDPOINT = "https://geo0.ggpht.com/cbk"
VIEW_USER_AGENT = "VISION-Community-view/1"
INVENTED_PREFIXES = ("synthetic:", "Prototype", "CommunityPano", "wikimedia:")
QUERY_VIEW_CAP = 4
# Browser processing proxies thumbnails through the Worker (CORS), so leases stay small.
STREET_LEASE_CAP = {
    "scene": {"slow": 1, "medium": 4, "max": 8},
    "object": {"slow": 1, "medium": 2, "max": 4},
}
# CLI fetches Street View on the volunteer machine; larger exclusive batches are safe.
CLI_LEASE_CAP = {
    "scene": {"slow": 16, "medium": 64, "max": 128},
    "object": {"slow": 8, "medium": 32, "max": 64},
}


def lease_cap(lane: str, pace: str, client: str = "browser") -> int:
    table = CLI_LEASE_CAP if client == "cli" else STREET_LEASE_CAP
    caps = table.get(lane) or table["scene"]
    return int(caps.get(pace) or caps["medium"])


class ViewError(Exception):
    def __init__(self, code: str = "view_unavailable"):
        super().__init__(code)
        self.code = code


def uses_street_views(pano_id: str | None) -> bool:
    if not isinstance(pano_id, str) or not pano_id.strip():
        return False
    identity = pano_id.strip()
    if "maps.googleapis.com" in identity or identity.startswith("http"):
        return False
    return not identity.startswith(INVENTED_PREFIXES)


def wrap_heading(heading: float) -> float:
    return float(heading) % 360.0


def thumbnail_fov(zoom: float) -> float:
    try:
        zoom_value = float(zoom)
    except (TypeError, ValueError):
        zoom_value = 0.0
    if not math.isfinite(zoom_value):
        zoom_value = 0.0
    fov = (360.0 / math.pi) * math.atan(0.75 * (2.0 ** (1.0 - zoom_value)))
    return min(120.0, max(30.0, fov))


def view_plan(lane: str, heading: float = 0, pitch: float = 0, zoom: float = 0) -> list[dict]:
    """Return the six faces stored in a community-visual-v1 buffer.

    Scene compass views follow VISION four-view (pose pitch + zoom FOV).
    Object compass views follow the VISION object cube (pitch 0, FOV 90).
    Faces 4 and 5 are zenith and nadir at FOV 90 for both lanes so the
    six-face descriptor stays fully populated from real pixels.
    """
    base_heading = wrap_heading(heading or 0)
    pose_pitch = float(pitch or 0)
    pose_zoom = float(zoom or 0)
    if lane == "object":
        ring_pitch = 0.0
        ring_fov = FACE_FOV
    else:
        ring_pitch = pose_pitch
        ring_fov = thumbnail_fov(pose_zoom)
    views = []
    for offset in range(4):
        views.append(
            {
                "yaw": wrap_heading(base_heading + offset * 90.0),
                "pitch": ring_pitch,
                "fov": ring_fov,
            }
        )
    views.append({"yaw": base_heading, "pitch": 90.0, "fov": FACE_FOV})
    views.append({"yaw": base_heading, "pitch": -90.0, "fov": FACE_FOV})
    if len(views) != FACE_COUNT:
        raise RuntimeError("view_count")
    return views


def thumbnail_url(pano_id: str, yaw: float, pitch: float, fov: float, *, width: int = THUMB_SIZE, height: int = THUMB_SIZE) -> str:
    query = urllib.parse.urlencode(
        {
            "cb_client": "apiv3",
            "output": "thumbnail",
            "panoid": pano_id,
            "w": str(width),
            "h": str(height),
            "yaw": _query_number(yaw),
            "pitch": _query_number(-float(pitch)),
            "thumbfov": str(int(round(min(120.0, max(30.0, float(fov)))))),
        }
    )
    return f"{THUMBNAIL_ENDPOINT}?{query}"


def _query_number(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.6g}"


def downsample_box(rgb: bytes, width: int, height: int, size: int = FACE_SIZE) -> bytes:
    if width <= 0 or height <= 0 or len(rgb) < width * height * 3:
        raise ViewError("invalid_thumbnail")
    if width == size and height == size:
        return bytes(rgb[: size * size * 3])
    out = bytearray(size * size * 3)
    for y in range(size):
        y0 = y * height // size
        y1 = (y + 1) * height // size
        if y1 <= y0:
            y1 = y0 + 1
        for x in range(size):
            x0 = x * width // size
            x1 = (x + 1) * width // size
            if x1 <= x0:
                x1 = x0 + 1
            count = (y1 - y0) * (x1 - x0)
            sum_r = sum_g = sum_b = 0
            for py in range(y0, y1):
                row = py * width * 3
                for px in range(x0, x1):
                    index = row + px * 3
                    sum_r += rgb[index]
                    sum_g += rgb[index + 1]
                    sum_b += rgb[index + 2]
            dest = (y * size + x) * 3
            out[dest] = sum_r // count
            out[dest + 1] = sum_g // count
            out[dest + 2] = sum_b // count
    return bytes(out)


def decode_jpeg_rgb(payload: bytes) -> tuple[bytes, int, int]:
    try:
        from PIL import Image
    except ImportError as error:
        raise ViewError("jpeg_decoder_missing") from error
    try:
        image = Image.open(io.BytesIO(payload)).convert("RGB")
    except Exception as error:
        raise ViewError("invalid_thumbnail") from error
    return image.tobytes(), image.width, image.height


def fetch_thumbnail(url: str, *, attempts: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        request = urllib.request.Request(url, headers={"User-Agent": VIEW_USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read()
                if getattr(response, "status", 200) != 200 or not payload:
                    raise ViewError("view_unavailable")
                return payload
        except ViewError as error:
            last_error = error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
        if attempt + 1 < attempts:
            time.sleep(0.4 * (attempt + 1))
    raise ViewError("view_unavailable") from last_error


def render_street_faces(location: dict, *, fetch=fetch_thumbnail) -> bytes:
    pano_id = location.get("panoId") or location.get("assetId") or location.get("asset_id")
    if not uses_street_views(pano_id):
        raise ViewError("not_a_street_pano")
    lane = location.get("lane") or "scene"
    faces = bytearray()
    for view in view_plan(lane, location.get("heading") or 0, location.get("pitch") or 0, location.get("zoom") or 0):
        payload = fetch(thumbnail_url(pano_id, view["yaw"], view["pitch"], view["fov"]))
        rgb, width, height = decode_jpeg_rgb(payload)
        faces.extend(downsample_box(rgb, width, height))
    if len(faces) != FACES_BYTES:
        raise ViewError("invalid_thumbnail")
    return bytes(faces)


def render_location_faces(location: dict, *, fetch=fetch_thumbnail) -> bytes:
    pano_id = location.get("panoId") or location.get("assetId") or location.get("asset_id")
    capture = location.get("capture") or "unknown"
    lane = location.get("lane") or "scene"
    model = location.get("model") or "community-visual-v1"
    if uses_street_views(pano_id):
        return render_street_faces(location, fetch=fetch)
    return render_faces(pano_id, capture, lane, model)


def location_from_row(row) -> dict:
    if isinstance(row, dict):
        mapping = row
    else:
        mapping = {key: row[key] for key in row.keys()}
    return {
        "panoId": mapping.get("asset_id") or mapping.get("panoId") or mapping.get("assetId"),
        "assetId": mapping.get("asset_id") or mapping.get("assetId") or mapping.get("panoId"),
        "capture": mapping.get("capture") or "unknown",
        "lane": mapping.get("lane") or "scene",
        "model": mapping.get("model") or "community-visual-v1",
        "heading": mapping.get("heading") or 0,
        "pitch": mapping.get("pitch") or 0,
        "zoom": mapping.get("zoom") or 0,
    }
