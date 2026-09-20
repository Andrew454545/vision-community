"""Verification of volunteer outputs without putting Street View on the owner bill.

Invented test panos are always recomputed (no network). Street View batches
re-fetch one location per lease as an audit; the rest must include embedding
bytes whose digest matches. That keeps indexing compute on volunteer machines.
This does not prove RF-DETR/YOLOE/OWLv2.
"""

from __future__ import annotations

import hmac

from .features import (
    MODEL_ID,
    embedding_for,
    output_digest,
    record_bytes,
    sha256_hex,
)
from .pano import ViewError, location_from_row, render_location_faces, uses_street_views
from .source import assert_not_google


class VerificationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def locations_to_recompute(rows) -> set[int]:
    """Recompute every invented pano and the first Street View pano in a lease."""
    audit: set[int] = set()
    street_audit = None
    for row in rows:
        asset = row["asset_id"]
        location_id = int(row["id"])
        if uses_street_views(asset):
            if street_audit is None:
                street_audit = location_id
        else:
            audit.add(location_id)
    if street_audit is not None:
        audit.add(street_audit)
    return audit


def _supplied_embedding(supplied: dict, lane: str) -> bytes:
    embedding = supplied.get("embedding")
    if not isinstance(embedding, (bytes, bytearray)):
        raise VerificationError("verification_failed")
    expected_len = record_bytes(lane)
    if len(embedding) != expected_len:
        raise VerificationError("verification_failed")
    return bytes(embedding)


def _check_digests(row: dict, supplied: dict, embedding: bytes) -> None:
    expected_digest = output_digest(
        row["asset_id"], row["capture"], row["lane"], row["model"], embedding
    )
    supplied_digest = supplied.get("outputSha256") or supplied.get("digest")
    supplied_embed_hash = supplied.get("embeddingSha256")
    if not isinstance(supplied_digest, str) or len(supplied_digest) != 64:
        raise VerificationError("verification_failed")
    if not hmac.compare_digest(supplied_digest, expected_digest):
        raise VerificationError("verification_failed")
    if supplied_embed_hash is not None and not hmac.compare_digest(supplied_embed_hash, sha256_hex(embedding)):
        raise VerificationError("verification_failed")


def verify_output(row: dict, supplied: dict, *, recompute: bool = True) -> bytes:
    assert_not_google(row["asset_id"])
    if row["model"] != MODEL_ID or supplied.get("model") not in (None, MODEL_ID):
        raise VerificationError("unsupported_model")
    if not recompute:
        embedding = _supplied_embedding(supplied, row["lane"])
        _check_digests(row, supplied, embedding)
        return embedding
    faces = row.get("faces")
    if not isinstance(faces, (bytes, bytearray)):
        try:
            faces = render_location_faces(location_from_row(row))
        except ViewError as error:
            raise VerificationError(error.code) from error
    embedding = embedding_for(row["lane"], bytes(faces))
    _check_digests(row, supplied, embedding)
    supplied_embed = supplied.get("embedding")
    if isinstance(supplied_embed, str):
        raise VerificationError("embedding_must_be_bytes")
    if supplied_embed is not None and (
        not isinstance(supplied_embed, (bytes, bytearray))
        or not hmac.compare_digest(bytes(supplied_embed), embedding)
    ):
        raise VerificationError("verification_failed")
    return embedding
