"""Local and browser-equivalent processing worker.

slow, medium, and max change concurrent jobs and process niceness. They never
change credits, model identity, or which locations are assigned.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from .features import embedding_for, output_digest, render_faces, sha256_hex


PACE = {
    "slow": {"workers": 1, "nice": 15},
    "medium": {"workers": max(1, (os.cpu_count() or 2) // 2), "nice": 5},
    "max": {"workers": os.cpu_count() or 2, "nice": 0},
}


class WorkerPaused(Exception):
    pass


class ProcessingWorker:
    def __init__(self, pace: str = "medium"):
        if pace not in PACE:
            raise ValueError("invalid_pace")
        self.pace = pace
        self._pause = threading.Event()
        self._pause.set()

    def resource_budget(self) -> dict:
        budget = dict(PACE[self.pace])
        budget["pace"] = self.pace
        budget["model"] = "community-visual-v1"
        return budget

    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    def _maybe_pause(self) -> None:
        if not self._pause.wait(timeout=30):
            raise WorkerPaused()

    def process_item(self, item: dict) -> dict:
        self._maybe_pause()
        faces = render_faces(item["assetId"], item["capture"], item["lane"], item["model"])
        expected = item.get("facesSha256")
        if expected and sha256_hex(faces) != expected:
            raise ValueError("faces_identity_mismatch")
        embedding = embedding_for(item["lane"], bytes(faces))
        return {
            "locationId": item["locationId"],
            "model": item["model"],
            "embeddingSha256": sha256_hex(embedding),
            "outputSha256": output_digest(
                item["assetId"], item["capture"], item["lane"], item["model"], embedding
            ),
            "embedding": embedding,
        }

    def process_lease(self, lease: dict) -> list[dict]:
        items = lease["items"]
        workers = min(PACE[self.pace]["workers"], len(items) or 1)
        if workers <= 1:
            return [self.process_item(item) for item in items]
        outputs = [None] * len(items)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.process_item, item): index for index, item in enumerate(items)}
            for future in as_completed(futures):
                outputs[futures[future]] = future.result()
        return outputs
