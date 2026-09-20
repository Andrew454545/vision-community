"""Ranked visual search over published Community segments.

Queries are embeddings, not labels. A bounded heap keeps only the top hits so
a 200M scan does not materialize 200M Python score tuples. The full index never
leaves this process.
"""

from __future__ import annotations

import heapq

from .features import OBJECT_DIM, cosine, embedding_for, max_region_cosine, scene_embedding
from .segments import SegmentRegistry


def query_vector(lane: str, faces: bytes) -> bytes:
    if lane == "scene":
        return scene_embedding(faces)
    return embedding_for("object", faces)


def _score(lane: str, query: bytes, embedding: bytes) -> float:
    if lane == "object":
        return max_region_cosine(query[:OBJECT_DIM] if len(query) >= OBJECT_DIM else query, embedding)
    return cosine(query, embedding)


def ranked_search_embedding(registry: SegmentRegistry, lane: str, query: bytes, *, limit: int = 25) -> list[dict]:
    if limit < 1:
        return []
    heap: list[tuple[float, int]] = []
    payloads: dict[int, dict] = {}
    scanned = 0
    for record in registry.iter_records(lane, verify=False):
        score = _score(lane, query, record["embedding"])
        scanned += 1
        location_id = record["locationId"]
        payload = {
            "locationId": location_id,
            "lane": record["lane"],
            "score": round(float(score), 6),
            "segmentId": record["segmentId"],
            "pose": record.get("pose"),
        }
        if len(heap) < limit:
            heapq.heappush(heap, (score, -location_id))
            payloads[location_id] = payload
        elif score > heap[0][0]:
            _old_score, old_neg = heapq.heapreplace(heap, (score, -location_id))
            payloads.pop(-old_neg, None)
            payloads[location_id] = payload
    ordered = sorted(heap, key=lambda item: item[0], reverse=True)
    results = [payloads[-neg_id] for _score, neg_id in ordered]
    if results:
        results[0] = {**results[0], "scanned": scanned}
    return results


def ranked_search(registry: SegmentRegistry, lane: str, faces: bytes, *, limit: int = 25) -> list[dict]:
    return ranked_search_embedding(registry, lane, query_vector(lane, faces), limit=limit)
