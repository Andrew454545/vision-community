"""Trusted independent verification of volunteer outputs.

A client-reported digest is never enough. The server re-renders or re-fetches
the canonical source and recomputes the versioned embedding. Sampling is not
used; every credited Community-visual-v1 result is recomputed. That guarantee
does not extend to RF-DETR/OWLv2, which this project does not run.
"""

from __future__ import annotations

import hmac

from .features import (
    MODEL_ID,
    embedding_for,
    output_digest,
    render_faces,
    sha256_hex,
)
from .source import assert_not_google


class VerificationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def verify_output(row: dict, supplied: dict) -> bytes:
    assert_not_google(row["asset_id"])
    if row["model"] != MODEL_ID or supplied.get("model") not in (None, MODEL_ID):
        raise VerificationError("unsupported_model")
    faces = row.get("faces")
    if not isinstance(faces, (bytes, bytearray)):
        faces = render_faces(row["asset_id"], row["capture"], row["lane"], row["model"])
    embedding = embedding_for(row["lane"], bytes(faces))
    expected_digest = output_digest(
        row["asset_id"], row["capture"], row["lane"], row["model"], embedding
    )
    supplied_digest = supplied.get("outputSha256") or supplied.get("digest")
    supplied_embed_hash = supplied.get("embeddingSha256")
    supplied_embed = supplied.get("embedding")
    if isinstance(supplied_embed, str):
        raise VerificationError("embedding_must_be_bytes")
    if not isinstance(supplied_digest, str) or len(supplied_digest) != 64:
        raise VerificationError("verification_failed")
    if not hmac.compare_digest(supplied_digest, expected_digest):
        raise VerificationError("verification_failed")
    if supplied_embed_hash is not None and not hmac.compare_digest(supplied_embed_hash, sha256_hex(embedding)):
        raise VerificationError("verification_failed")
    if supplied_embed is not None and (not isinstance(supplied_embed, (bytes, bytearray)) or not hmac.compare_digest(bytes(supplied_embed), embedding)):
        raise VerificationError("verification_failed")
    return embedding
