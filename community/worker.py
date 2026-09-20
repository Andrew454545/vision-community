"""Local and browser-equivalent processing worker.

slow, medium, and max change concurrent jobs and process niceness. They never
change credits, model identity, or which locations are assigned.
"""

from __future__ import annotations

import base64
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from .features import embedding_for, output_digest, sha256_hex
from .pano import ViewError, render_location_faces, uses_street_views


PACE = {
    "slow": {"workers": 1, "nice": 15},
    "medium": {"workers": max(1, (os.cpu_count() or 2) // 2), "nice": 5},
    "max": {"workers": os.cpu_count() or 2, "nice": 0},
}


class WorkerPaused(Exception):
    pass


class ProcessingWorker:
    def __init__(self, pace: str = "medium", *, views=None):
        if pace not in PACE:
            raise ValueError("invalid_pace")
        self.pace = pace
        self.views = views
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
        pano_id = item.get("panoId") or item["assetId"]
        if uses_street_views(pano_id) and self.views is not None:
            faces = self.views(item)
        else:
            try:
                faces = render_location_faces(item)
            except ViewError as error:
                raise ValueError(error.code) from error
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

    def as_submission(self, outputs: list[dict]) -> list[dict]:
        encoded = []
        for item in outputs:
            payload = dict(item)
            embedding = payload.get("embedding")
            if isinstance(embedding, (bytes, bytearray)):
                payload["embedding"] = base64.b64encode(bytes(embedding)).decode("ascii")
            encoded.append(payload)
        return encoded

    def process_lease(self, lease: dict, *, progress=None) -> list[dict]:
        items = lease["items"]
        total = len(items)

        def run(index: int, item: dict) -> dict:
            if progress is not None:
                progress(index + 1, total, item)
            return self.process_item(item)

        workers = min(PACE[self.pace]["workers"], len(items) or 1)
        if workers <= 1:
            return [run(index, item) for index, item in enumerate(items)]
        outputs = [None] * len(items)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run, index, item): index for index, item in enumerate(items)}
            for future in as_completed(futures):
                outputs[futures[future]] = future.result()
        return outputs
