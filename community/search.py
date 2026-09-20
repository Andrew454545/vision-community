"""Ranked visual search over published Community segments.

Queries are embeddings, not labels. The full index never leaves this process.
"""

from __future__ import annotations

from .features import OBJECT_DIM, cosine, embedding_for, max_region_cosine, scene_embedding
from .segments import SegmentRegistry


def query_vector(lane: str, faces: bytes) -> bytes:
    if lane == "scene":
        return scene_embedding(faces)
    return embedding_for("object", faces)


def ranked_search_embedding(registry: SegmentRegistry, lane: str, query: bytes, *, limit: int = 25) -> list[dict]:
    scored = []
    for record in registry.iter_records(lane):
        if lane == "object":
            score = max_region_cosine(query[:OBJECT_DIM] if len(query) >= OBJECT_DIM else query, record["embedding"])
        else:
            score = cosine(query, record["embedding"])
        scored.append((score, record))
    scored.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, record in scored[:limit]:
        results.append(
            {
                "locationId": record["locationId"],
                "lane": record["lane"],
                "score": round(float(score), 6),
                "segmentId": record["segmentId"],
            }
        )
    return results


def ranked_search(registry: SegmentRegistry, lane: str, faces: bytes, *, limit: int = 25) -> list[dict]:
    return ranked_search_embedding(registry, lane, query_vector(lane, faces), limit=limit)
