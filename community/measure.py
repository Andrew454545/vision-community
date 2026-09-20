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
    imagery_500kb_gb = VISION_SCENE_CORPUS * 500 * 1024 / (1024**3)

    def r2_storage_cost(gb: float) -> float:
        billable = max(0.0, gb - R2_FREE_GB)
        return round(billable * R2_STANDARD_GB_MONTH, 4)

    return {
        "model": identity,
        "measured": samples,
        "bytes": {
            "communityScenePerLocation": scene_bytes,
            "communityObjectPerLocation": object_bytes,
            "communityFacesRawPerLocation": FACES_BYTES,
            "visionScenePerLocation": VISION_SCENE_BYTES_PER_LOCATION,
            "syntheticSourceImageNotStored": True,
        },
        "projections": {
            "visionCorpusLocations": VISION_SCENE_CORPUS,
            "localSealedSegmentDirGiB": LOCAL_SEALED_SEGMENT_GB,
            "localApplicationSupportGiB": LOCAL_APP_SUPPORT_GB,
            "visionInt8IndexGiB": round(vision_index_gb, 2),
            "communityVisualIndexGiB": round(community_index_gb, 3),
            "rawImageryIf500KiBEachGiB": round(imagery_500kb_gb, 1),
            "r2StorageUsdIfCommunityIndexOnly": r2_storage_cost(community_index_gb),
            "r2StorageUsdIfVisionIndexCopied": r2_storage_cost(vision_index_gb),
            "r2StorageUsdIfRawImageryStored": r2_storage_cost(imagery_500kb_gb),
            "r2ClassAUsdAfterFree": 0.0,
            "notes": (
                "Copying the local VISION index or Google imagery is forbidden. "
                "Community index size assumes the same location count with community-visual-v1."
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
                "Keep leases, credits, and search authorization on trusted server code. "
                "Store sealed segments durably (R2 later, local disk now). Run ranked search "
                "on a dedicated process with the index in RAM or on local NVMe. Workers Free "
                "cannot hold or scan a multi-million-location index within 10 ms and 128 MB. "
                "Vectorize Free stores under 10,000 512-d vectors. Do not create an R2 bucket "
                "until a rights-cleared corpus and a search host are approved."
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
