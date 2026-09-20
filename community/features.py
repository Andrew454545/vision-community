"""Versioned, independently recomputable Community visual extractor.

This is not RF-DETR, YOLOE, or OWLv2. It is a deterministic six-face visual
descriptor so a trusted server can recompute every credited result. Integer
arithmetic keeps Python and browser workers bit-identical.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Iterable


MODEL_ID = "community-visual-v1"
MODEL_VERSION = 1
FACE_COUNT = 6
FACE_SIZE = 16
BYTES_PER_FACE = FACE_SIZE * FACE_SIZE * 3
FACES_BYTES = FACE_COUNT * BYTES_PER_FACE
SCENE_DIM = 96
SCENE_FACE_DIM = 16
COMPASS_FACE_COUNT = 4
OBJECT_PROPOSALS = 16
OBJECT_DIM = 8
# Quarter-turns from each map's saved pan, matching VISION.app VisionViewDirection.
VIEW_DIRECTION_OFFSETS = {
    "bestOfFour": (0, 1, 2, 3),
    "original": (0,),
    "right": (1,),
    "opposite": (2,),
    "left": (3,),
    "originalAxis": (0, 2),
    "sideAxis": (1, 3),
}
DEFAULT_VIEW_DIRECTION = "bestOfFour"
OBJECT_VECTOR_BYTES = OBJECT_PROPOSALS * OBJECT_DIM
SCENE_RECORD_BYTES = SCENE_DIM
OBJECT_RECORD_BYTES = OBJECT_VECTOR_BYTES

MODEL_MANIFEST = {
    "id": MODEL_ID,
    "version": MODEL_VERSION,
    "architecture": "VISION Community: six-face integer descriptors from Street View views",
    "faceCount": FACE_COUNT,
    "faceSize": FACE_SIZE,
    "sceneDimensions": SCENE_DIM,
    "objectProposalsPerLocation": OBJECT_PROPOSALS,
    "objectDimensions": OBJECT_DIM,
    "codec": "int8",
    "viewsPerLocation": FACE_COUNT,
    "sceneViewStrategy": "four-view-compass plus zenith/nadir",
    "objectViewStrategy": "six-face-cube",
    "notes": (
        "Scene compass views use heading+0/90/180/270 at the saved pitch and "
        "thumbnail FOV from zoom. Object views use the six-face cube at 90°. "
        "Each thumbnail is downsampled to 16×16. Independent recomputation "
        "fetches the same views ephemerally. This is not RF-DETR, YOLOE, or OWLv2."
    ),
}


def model_identity() -> dict:
    payload = canonical_json(MODEL_MANIFEST)
    return {
        **MODEL_MANIFEST,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def canonical_json(value: dict) -> bytes:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_faces(asset_id: str, capture: str, lane: str, model: str) -> bytes:
    """Deterministic six-face RGB payload used when no rights-cleared image exists."""
    seed = hashlib.sha256(f"{asset_id}\n{capture}\n{lane}\n{model}".encode("utf-8")).digest()
    out = bytearray(FACES_BYTES)
    # Expand the seed with a 64-bit xorshift so every asset has a distinct texture.
    state = int.from_bytes(seed[:8], "little") or 1
    for face in range(FACE_COUNT):
        face_bias = (state >> (face % 8)) & 255
        for y in range(FACE_SIZE):
            for x in range(FACE_SIZE):
                state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
                state ^= state >> 7
                state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
                idx = (face * FACE_SIZE * FACE_SIZE + y * FACE_SIZE + x) * 3
                radial = (x - 7) * (x - 7) + (y - 7) * (y - 7)
                out[idx] = (state + face_bias + x * 13 + radial) & 255
                out[idx + 1] = ((state >> 8) + y * 17 + face * 41) & 255
                out[idx + 2] = ((state >> 16) + (x * y) + face_bias * 3) & 255
    return bytes(out)


def _mean_int8(total: int, count: int) -> int:
    return max(-127, min(127, total // count - 128))


def scene_embedding(faces: bytes) -> bytes:
    if len(faces) != FACES_BYTES:
        raise ValueError("faces_bytes")
    dims = []
    for face in range(FACE_COUNT):
        base = face * BYTES_PER_FACE
        for qy in range(2):
            for qx in range(2):
                sum_r = sum_g = sum_b = sum_dx = 0
                for y in range(8):
                    prev_r = None
                    for x in range(8):
                        px = qx * 8 + x
                        py = qy * 8 + y
                        i = base + (py * FACE_SIZE + px) * 3
                        r, g, b = faces[i], faces[i + 1], faces[i + 2]
                        sum_r += r
                        sum_g += g
                        sum_b += b
                        if prev_r is not None:
                            sum_dx += abs(r - prev_r)
                        prev_r = r
                dims.extend(
                    [
                        _mean_int8(sum_r, 64),
                        _mean_int8(sum_g, 64),
                        _mean_int8(sum_b, 64),
                        _mean_int8(sum_dx, 56),
                    ]
                )
    packed = bytes((d + 256) % 256 if d < 0 else d for d in dims)
    if len(packed) != SCENE_DIM:
        raise RuntimeError("scene_dim")
    return packed


def object_embedding(faces: bytes) -> bytes:
    if len(faces) != FACES_BYTES:
        raise ValueError("faces_bytes")
    base = 0  # front face, analogous to a single object view
    dims = []
    for cy in range(4):
        for cx in range(4):
            sum_r = sum_g = sum_b = 0
            gray_min, gray_max = 255, 0
            sum_dx = sum_dy = 0
            for y in range(4):
                for x in range(4):
                    px = cx * 4 + x
                    py = cy * 4 + y
                    i = base + (py * FACE_SIZE + px) * 3
                    r, g, b = faces[i], faces[i + 1], faces[i + 2]
                    sum_r += r
                    sum_g += g
                    sum_b += b
                    gray = (r + g + b) // 3
                    gray_min = min(gray_min, gray)
                    gray_max = max(gray_max, gray)
                    if x:
                        left = base + (py * FACE_SIZE + px - 1) * 3
                        sum_dx += abs(r - faces[left])
                    if y:
                        up = base + ((py - 1) * FACE_SIZE + px) * 3
                        sum_dy += abs(r - faces[up])
            dims.extend(
                [
                    _mean_int8(sum_r, 16),
                    _mean_int8(sum_g, 16),
                    _mean_int8(sum_b, 16),
                    _mean_int8((gray_min + gray_max) * 8, 16),
                    _mean_int8(gray_max - gray_min, 1),
                    _mean_int8(sum_dx, 12),
                    _mean_int8(sum_dy, 12),
                    max(-127, min(127, (cx + cy * 4) * 8 - 60)),
                ]
            )
    packed = bytes((d + 256) % 256 if d < 0 else d for d in dims)
    if len(packed) != OBJECT_VECTOR_BYTES:
        raise RuntimeError("object_dim")
    return packed


def embedding_for(lane: str, faces: bytes) -> bytes:
    if lane == "scene":
        return scene_embedding(faces)
    if lane == "object":
        return object_embedding(faces)
    raise ValueError("lane")


def record_bytes(lane: str) -> int:
    return SCENE_RECORD_BYTES if lane == "scene" else OBJECT_RECORD_BYTES


def signed_int8(data: bytes) -> list[int]:
    return [b - 256 if b > 127 else b for b in data]


def normalize_view_direction(value, lane: str = "scene") -> str:
    if lane != "scene":
        return DEFAULT_VIEW_DIRECTION
    if value in VIEW_DIRECTION_OFFSETS:
        return value
    return DEFAULT_VIEW_DIRECTION


def view_offsets_for(direction, lane: str = "scene") -> tuple[int, ...]:
    return VIEW_DIRECTION_OFFSETS[normalize_view_direction(direction, lane)]


def scene_face(embedding: bytes, offset: int) -> bytes:
    start = int(offset) * SCENE_FACE_DIM
    end = start + SCENE_FACE_DIM
    if start < 0 or len(embedding) < end:
        return b""
    return embedding[start:end]


def query_saved_pan(embedding: bytes) -> bytes:
    """Face 0 is the query map's saved pan."""
    if len(embedding) >= SCENE_FACE_DIM:
        return embedding[:SCENE_FACE_DIM]
    return embedding


def best_scene_view(query: bytes, embedding: bytes, offsets) -> tuple[float, int]:
    query_face = query_saved_pan(query)
    allowed = tuple(offsets) if offsets else VIEW_DIRECTION_OFFSETS[DEFAULT_VIEW_DIRECTION]
    best_score = -1.0
    best_offset = allowed[0] if allowed else 0
    for offset in allowed:
        score = cosine(query_face, scene_face(embedding, offset))
        if score > best_score:
            best_score = score
            best_offset = int(offset)
    return best_score, best_offset


def wrap_heading(heading: float) -> float:
    value = float(heading) % 360.0
    return value + 360.0 if value < 0 else value


def cosine(a: bytes, b: bytes) -> float:
    if len(a) != len(b) or not a:
        return -1.0
    sa, sb = signed_int8(a), signed_int8(b)
    dot = sum(x * y for x, y in zip(sa, sb))
    na = math.sqrt(sum(x * x for x in sa))
    nb = math.sqrt(sum(y * y for y in sb))
    if na == 0 or nb == 0:
        return -1.0
    return dot / (na * nb)


def max_region_cosine(query: bytes, packed_regions: bytes) -> float:
    """Rank an object location by its best region-to-query cosine."""
    if len(query) != OBJECT_DIM:
        # A full object vector may be passed; use the first region as the query crop.
        if len(query) == OBJECT_VECTOR_BYTES:
            best = -1.0
            for offset in range(0, OBJECT_VECTOR_BYTES, OBJECT_DIM):
                best = max(best, max_region_cosine(query[offset : offset + OBJECT_DIM], packed_regions))
            return best
        return -1.0
    best = -1.0
    for offset in range(0, len(packed_regions), OBJECT_DIM):
        best = max(best, cosine(query, packed_regions[offset : offset + OBJECT_DIM]))
    return best


def output_digest(asset_id: str, capture: str, lane: str, model: str, embedding: bytes) -> str:
    return sha256_hex(
        f"{MODEL_ID}\n{asset_id}\n{capture}\n{lane}\n{model}\n".encode("utf-8") + embedding
    )


def mean_embeddings(vectors: list[bytes]) -> bytes:
    if not vectors:
        raise ValueError("empty_query")
    width = len(vectors[0])
    totals = [0] * width
    for vector in vectors:
        if len(vector) != width:
            raise ValueError("query_width")
        for index, value in enumerate(signed_int8(vector)):
            totals[index] += value
    count = len(vectors)
    dims = [max(-127, min(127, total // count)) for total in totals]
    return bytes((d + 256) % 256 if d < 0 else d for d in dims)


def pack_ids(ids: Iterable[int]) -> bytes:
    return b"".join(struct.pack("<Q", int(location_id)) for location_id in ids)
