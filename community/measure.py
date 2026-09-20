"""Cost, storage, and search-resource measurements. No network, no R2."""

from __future__ import annotations

import json
import os
import resource
import tempfile
import time
from pathlib import Path

from .features import (
    FACES_BYTES,
    MODEL_ID,
    OBJECT_RECORD_BYTES,
    SCENE_RECORD_BYTES,
    embedding_for,
    model_identity,
    render_faces,
)
from .search import ranked_search
from .segments import SegmentRegistry


R2_STANDARD_GB_MONTH = 0.015
R2_FREE_GB = 10
R2_CLASS_A_PER_MILLION = 4.50
R2_CLASS_B_PER_MILLION = 0.36
R2_FREE_CLASS_A = 1_000_000
R2_FREE_CLASS_B = 10_000_000
VISION_SCENE_BYTES_PER_LOCATION = 3080
VISION_SCENE_CORPUS = 20_955_444
TARGET_CORPUS = 200_000_000
METADATA_BYTES_PER_LOCATION = 80
LOCAL_SEALED_SEGMENT_GB = 20
LOCAL_APP_SUPPORT_GB = 76


def _rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports kilobytes.
    if usage > 10_000_000:
        return usage / (1024 * 1024)
    return usage / 1024


def measure(location_counts: tuple[int, ...] = (200, 2_000, 10_000)) -> dict:
    identity = model_identity()
    scene_bytes = SCENE_RECORD_BYTES
    object_bytes = OBJECT_RECORD_BYTES
    samples = []
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        for count in location_counts:
            registry = SegmentRegistry(root / f"n{count}", capacity=max(count, 1))
            ids = []
            blobs = []
            t0 = time.perf_counter()
            for index in range(count):
                asset = f"synthetic:measure:{index:06d}"
                faces = render_faces(asset, "2026-01", "scene", MODEL_ID)
                embedding = embedding_for("scene", faces)
                ids.append(index + 1)
                blobs.append(embedding)
            embed_s = time.perf_counter() - t0
            packed = b"".join(blobs)
            t1 = time.perf_counter()
            registry.publish(lane="scene", location_ids=ids, embeddings=packed)
            publish_s = time.perf_counter() - t1
            query_faces = render_faces("synthetic:measure:000000", "2026-01", "scene", MODEL_ID)
            t2 = time.perf_counter()
            hits = ranked_search(registry, "scene", query_faces, limit=25)
            search_s = time.perf_counter() - t2
            samples.append(
                {
                    "locations": count,
                    "indexBytes": len(packed),
                    "bytesPerLocation": scene_bytes,
                    "embedSeconds": round(embed_s, 4),
                    "publishSeconds": round(publish_s, 4),
                    "searchSeconds": round(search_s, 4),
                    "searchRssMb": round(_rss_mb(), 2),
                    "topLocationId": hits[0]["locationId"] if hits else None,
                    "topScore": hits[0]["score"] if hits else None,
                }
            )
    vision_index_gb = VISION_SCENE_CORPUS * VISION_SCENE_BYTES_PER_LOCATION / (1024**3)
    community_index_gb = VISION_SCENE_CORPUS * scene_bytes / (1024**3)
    community_200m_gb = TARGET_CORPUS * (scene_bytes + METADATA_BYTES_PER_LOCATION) / (1024**3)
    vision_200m_gb = TARGET_CORPUS * (VISION_SCENE_BYTES_PER_LOCATION + METADATA_BYTES_PER_LOCATION) / (1024**3)
    imagery_500kb_gb = TARGET_CORPUS * 500 * 1024 / (1024**3)

    def r2_storage_cost(gb: float) -> float:
        billable = max(0.0, gb - R2_FREE_GB)
        return round(billable * R2_STANDARD_GB_MONTH, 4)

    return {
        "model": identity,
        "measured": samples,
        "bytes": {
            "communityScenePerLocation": scene_bytes,
            "communityObjectPerLocation": object_bytes,
            "metadataPerLocation": METADATA_BYTES_PER_LOCATION,
            "ephemeralFacesBytesNotStored": FACES_BYTES,
            "visionScenePerLocation": VISION_SCENE_BYTES_PER_LOCATION,
            "imageryPersisted": False,
        },
        "projections": {
            "currentIndexedLocations": VISION_SCENE_CORPUS,
            "targetCorpusLocations": TARGET_CORPUS,
            "localSealedSegmentDirGiB": LOCAL_SEALED_SEGMENT_GB,
            "localApplicationSupportGiB": LOCAL_APP_SUPPORT_GB,
            "communityIndexAtCurrentGiB": round(community_index_gb, 3),
            "communityIndexPlusMetadataAt200MGiB": round(community_200m_gb, 2),
            "visionInt8IndexAtCurrentGiB": round(vision_index_gb, 2),
            "visionInt8PlusMetadataAt200MGiB": round(vision_200m_gb, 1),
            "r2StorageUsdCommunity200M": r2_storage_cost(community_200m_gb),
            "r2StorageUsdVisionScale200M": r2_storage_cost(vision_200m_gb),
            "rawImageryIfStoredGiB": round(imagery_500kb_gb, 1),
            "r2StorageUsdIfImageryStored": r2_storage_cost(imagery_500kb_gb),
            "notes": (
                "Imagery is not stored. 200M locations of community-visual-v1 embeddings "
                "plus pano/pose metadata fit well under a $20 R2 storage budget. "
                "VISION-scale 3080-byte embeddings at 200M are about $9/month storage. "
                "Search CPU still needs a dedicated host; Workers Free cannot scan 200M vectors."
            ),
        },
        "cloudflareFreeTier": {
            "r2StorageGiB": R2_FREE_GB,
            "r2ClassA": R2_FREE_CLASS_A,
            "r2ClassB": R2_FREE_CLASS_B,
            "workersCpuMs": 10,
            "workersMemoryMiB": 128,
            "workersRequestsPerDay": 100_000,
            "d1StorageGiB": 5,
            "d1RowsReadPerDay": 5_000_000,
            "d1RowsWrittenPerDay": 100_000,
            "vectorizeStoredDimensions": 5_000_000,
        },
        "verdict": {
            "fastSearchAndStrictGateAndOnlyR2": False,
            "smallestTradeoff": (
                "Store only embeddings and panorama metadata (no imagery). R2 storage for a "
                "200M community-visual-v1 index is a few dollars or less. Fast gated search "
                "still needs a dedicated process with the index on local disk or RAM. "
                "Workers Free cannot do that scan."
            ),
            "verificationGuarantee": (
                "Every credited community-visual-v1 embedding is independently recomputed. "
                "That is not a guarantee for RF-DETR/OWLv2. Sampling those models would not "
                "be an absolute guarantee either."
            ),
        },
        "r2PricesUsd": {
            "storagePerGiBMonth": R2_STANDARD_GB_MONTH,
            "classAPerMillion": R2_CLASS_A_PER_MILLION,
            "classBPerMillion": R2_CLASS_B_PER_MILLION,
        },
        "cpuCount": os.cpu_count(),
    }


def main():
    report = measure()
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
