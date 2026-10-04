"""Server-owned approval of scene outputs; a client checksum is not proof.

This deliberately has no similarity threshold. An operator must independently
audit each allowed output against Andrew's reference before listing its digest.
The approval is tied to the source, capture, pose and both model identities.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from .four_view import VISION_FOUR_VIEW_MODEL


class SceneQualityError(ValueError):
    pass


class ApprovedSceneReferences:
    def __init__(self, manifest: dict):
        if (not isinstance(manifest, dict) or manifest.get("version") != 1
                or manifest.get("outputModel") != VISION_FOUR_VIEW_MODEL
                or not isinstance(manifest.get("inputModel"), str) or not manifest["inputModel"]
                or not isinstance(manifest.get("policyId"), str) or not manifest["policyId"]
                or not isinstance(manifest.get("references"), list) or not manifest["references"]):
            raise SceneQualityError("invalid_scene_reference_policy")
        self.policy_id = manifest["policyId"]
        self.input_model = manifest["inputModel"]
        self._approved = {}
        for entry in manifest["references"]:
            if not isinstance(entry, dict):
                raise SceneQualityError("invalid_scene_reference_policy")
            if any(not isinstance(entry.get(k), str) or not entry[k] for k in ("assetId", "capture")):
                raise SceneQualityError("invalid_scene_reference_policy")
            pose = tuple(entry.get(k) for k in ("lat", "lng", "heading", "pitch", "zoom"))
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in pose):
                raise SceneQualityError("invalid_scene_reference_policy")
            hashes = entry.get("approvedSha256")
            if not isinstance(hashes, list) or not hashes or any(
                not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes
            ):
                raise SceneQualityError("invalid_scene_reference_policy")
            key = (entry["assetId"], entry["capture"], *pose)
            if key in self._approved:
                raise SceneQualityError("duplicate_scene_reference")
            self._approved[key] = frozenset(hashes)

    @classmethod
    def load(cls, path: Path, expected_sha256: str) -> "ApprovedSceneReferences":
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise SceneQualityError("scene_reference_checksum_mismatch")
        return cls(json.loads(raw))

    def _key(self, row):
        if row["lane"] != "scene" or row["model"] != self.input_model:
            return None
        return (row["asset_id"], row["capture"], row["lat"], row["lon"],
                row["heading"], row["pitch"], row["zoom"])

    def covers(self, row) -> bool:
        return self._key(row) in self._approved

    def verify(self, row, output_sha256: str) -> bool:
        return output_sha256 in self._approved.get(self._key(row), ())


def scene_capabilities(references: ApprovedSceneReferences | None) -> dict:
    return {"version": 1, "sceneContributions": {
        "ready": references is not None,
        "reason": None if references is not None else "scene_verification_unavailable",
        "model": VISION_FOUR_VIEW_MODEL,
        "policyId": references.policy_id if references is not None else None,
        "verification": "independently-approved-output-digests",
        "scope": "preapproved-locations-only",
    }}
