"""Trusted qualification and quarantine; no client result can grant credit.

The injected verifier is an operator-controlled integration. It must enforce
the approved full-profile qualification and the canary/batch reference policy.
No permissive verifier or acceptance threshold ships with the application.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time

from .four_view import BYTES_PER_LOCATION, valid_four_view_record

CANARY_LOCATIONS = 112
MAX_QUALIFICATION_SECONDS = 30 * 86400


class ScenePipelineError(Exception):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code = code
        self.status = status


def migrate(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS scene_qualifications (
            id TEXT PRIMARY KEY, account_id TEXT NOT NULL, profile_id TEXT NOT NULL,
            policy_id TEXT NOT NULL, canary_sha256 TEXT NOT NULL,
            expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scene_candidates (
            lease_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
            qualification_id TEXT NOT NULL, policy_id TEXT NOT NULL,
            submission_sha256 TEXT NOT NULL, artifact_key TEXT NOT NULL,
            records_json TEXT NOT NULL, created_at INTEGER NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','published','rejected'))
        );
    """)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(leases)")}
    if "scene_qualification_id" not in columns:
        connection.execute("ALTER TABLE leases ADD COLUMN scene_qualification_id TEXT")


def configured(verifier):
    return (verifier is not None and isinstance(getattr(verifier, "policy_id", None), str)
            and bool(verifier.policy_id) and callable(getattr(verifier, "qualify", None))
            and callable(getattr(verifier, "audit", None)))


def active_qualification(connection, account_id, verifier, now, qualification_id=None, profile_id=None):
    if not configured(verifier):
        raise ScenePipelineError("scene_verification_unavailable", 503)
    row = connection.execute(
        """SELECT * FROM scene_qualifications WHERE account_id=? AND policy_id=?
           AND expires_at>? AND (? IS NULL OR id=?) AND (? IS NULL OR profile_id=?)
           ORDER BY created_at DESC, id DESC LIMIT 1""",
        (account_id, verifier.policy_id, now, qualification_id, qualification_id, profile_id, profile_id),
    ).fetchone()
    if row is None:
        raise ScenePipelineError("scene_device_qualification_required", 403)
    return row


def qualify(service, account_id, profile_id, canary, now=None):
    now = int(time.time()) if now is None else now
    verifier = service.scene_verifier
    if not configured(verifier):
        raise ScenePipelineError("scene_verification_unavailable", 503)
    if not isinstance(profile_id, str) or not re.fullmatch(r"[0-9a-f]{64}", profile_id):
        raise ScenePipelineError("invalid_profile_id")
    if not isinstance(canary, dict) or canary.get("locations") != CANARY_LOCATIONS:
        raise ScenePipelineError("invalid_scene_canary")
    try:
        records = canary.get("records")
        if not isinstance(records, list) or len(records) != CANARY_LOCATIONS:
            raise ValueError("invalid records")
        decoded = [base64.b64decode(record, validate=True) for record in records]
        if any(len(record) != BYTES_PER_LOCATION for record in decoded):
            raise ValueError("invalid record length")
        blob = b"".join(decoded)
    except (ValueError, TypeError):
        raise ScenePipelineError("invalid_scene_canary") from None
    if len(blob) != CANARY_LOCATIONS * BYTES_PER_LOCATION or any(
        not valid_four_view_record(blob[offset:offset + BYTES_PER_LOCATION])
        for offset in range(0, len(blob), BYTES_PER_LOCATION)
    ):
        raise ScenePipelineError("invalid_scene_canary")
    if canary.get("outputSha256") != hashlib.sha256(blob).hexdigest():
        raise ScenePipelineError("invalid_scene_canary")
    canary_hash = hashlib.sha256(json.dumps(canary, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    request = {"accountId": account_id, "profileId": profile_id, "policyId": verifier.policy_id,
               "canarySha256": canary_hash, "canary": canary}
    try:
        result = verifier.qualify(request)
    except Exception:
        raise ScenePipelineError("scene_verifier_unavailable", 503) from None
    if (not isinstance(result, dict) or result.get("approved") is not True
            or result.get("policyId") != verifier.policy_id or result.get("profileId") != profile_id
            or result.get("canarySha256") != canary_hash
            or type(result.get("expiresAt")) is not int
            or not now < result["expiresAt"] <= now + MAX_QUALIFICATION_SECONDS):
        raise ScenePipelineError("scene_device_not_qualified", 422)
    qualification_id = secrets.token_hex(16)
    with service._connection() as connection:
        connection.execute(
            "INSERT INTO scene_qualifications VALUES (?, ?, ?, ?, ?, ?, ?)",
            (qualification_id, account_id, profile_id, verifier.policy_id, canary_hash, result["expiresAt"], now),
        )
    return {"qualified": True, "qualificationId": qualification_id, "profileId": profile_id,
            "policyId": verifier.policy_id, "expiresAt": result["expiresAt"]}


def qualification_status(service, account_id, profile_id, now=None):
    """Return only the current account/profile approval; never grants one."""
    now = int(time.time()) if now is None else now
    verifier = service.scene_verifier
    if not configured(verifier):
        raise ScenePipelineError("scene_verification_unavailable", 503)
    if not isinstance(profile_id, str) or not re.fullmatch(r"[0-9a-f]{64}", profile_id):
        raise ScenePipelineError("invalid_profile_id")
    with service._connection() as connection:
        row = connection.execute(
            """SELECT * FROM scene_qualifications WHERE account_id=? AND policy_id=?
               AND profile_id=? AND expires_at>? ORDER BY created_at DESC, id DESC LIMIT 1""",
            (account_id, verifier.policy_id, profile_id, now),
        ).fetchone()
    if row is None:
        return {"qualified": False, "profileId": profile_id, "policyId": verifier.policy_id}
    return {"qualified": True, "qualificationId": row["id"], "profileId": row["profile_id"],
            "policyId": row["policy_id"], "expiresAt": row["expires_at"]}


def candidate_result(row):
    return {"accepted": 0, "unitsEarned": 0, "replayed": True,
            "pendingAudit": row["state"] == "pending", "rejected": row["state"] == "rejected",
            "submissionId": row["lease_id"], "segments": []}


def stage(service, connection, account_id, lease, items, verified, now):
    if not lease["scene_qualification_id"]:
        raise ScenePipelineError("scene_device_qualification_required", 403)
    qualification = active_qualification(connection, account_id, service.scene_verifier,
                                         now, lease["scene_qualification_id"])
    records = [{"locationId": row["id"], "assetId": row["asset_id"], "capture": row["capture"],
                "inputModel": row["model"], "lat": row["lat"], "lng": row["lon"],
                "heading": row["heading"], "pitch": row["pitch"], "zoom": row["zoom"],
                "outputSha256": verified[row["id"]]["digest"]} for row in items]
    blob = b"".join(verified[row["id"]]["four_view"] for row in items)
    metadata = json.dumps(records, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(metadata.encode() + b"\n" + blob).hexdigest()
    key = f"scene-quarantine/{lease['id']}/{digest}.i8"
    dest = service.artifacts / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    connection.execute("INSERT INTO scene_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                       (lease["id"], account_id, qualification["id"], qualification["policy_id"], digest, key, metadata, now))
    connection.execute("UPDATE leases SET state='submitted' WHERE id=?", (lease["id"],))
    connection.executemany("""UPDATE locations SET state='pending', active_lease=NULL,
                           lease_until=NULL, queue_state='quarantined' WHERE id=?""",
                           [(row["id"],) for row in items])
    return {"accepted": 0, "pending": len(items), "staged": len(items), "unitsEarned": 0, "replayed": False,
            "pendingAudit": True, "submissionId": lease["id"], "segments": []}


def audit(service, account_id, lease_id, now=None):
    now = int(time.time()) if now is None else now
    verifier = service.scene_verifier
    if not configured(verifier):
        raise ScenePipelineError("scene_verification_unavailable", 503)
    with service._connection() as connection:
        row = connection.execute("SELECT * FROM scene_candidates WHERE lease_id=? AND account_id=?",
                                 (lease_id, account_id)).fetchone()
        if row is None:
            raise ScenePipelineError("unknown_scene_submission", 404)
        if row["state"] != "pending":
            return candidate_result(row)
        if row["policy_id"] != verifier.policy_id:
            raise ScenePipelineError("scene_policy_changed", 409)
        qualification = connection.execute("SELECT * FROM scene_qualifications WHERE id=?",
                                           (row["qualification_id"],)).fetchone()
    blob = (service.artifacts / row["artifact_key"]).read_bytes()
    if hashlib.sha256(row["records_json"].encode() + b"\n" + blob).hexdigest() != row["submission_sha256"]:
        raise ScenePipelineError("scene_quarantine_corrupt", 500)
    request = {"accountId": account_id, "profileId": qualification["profile_id"],
               "policyId": row["policy_id"], "submissionSha256": row["submission_sha256"],
               "records": json.loads(row["records_json"]), "indexBase64": base64.b64encode(blob).decode("ascii")}
    try:
        result = verifier.audit(request)
    except Exception:
        return candidate_result(row)
    if (not isinstance(result, dict) or result.get("policyId") != row["policy_id"]
            or result.get("submissionSha256") != row["submission_sha256"]
            or result.get("decision") not in ("approved", "rejected")):
        return candidate_result(row)
    with service._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute("SELECT * FROM scene_candidates WHERE lease_id=?", (lease_id,)).fetchone()
        if current["state"] != "pending":
            return candidate_result(current)
        if result["decision"] == "rejected":
            connection.execute("UPDATE scene_candidates SET state='rejected' WHERE lease_id=?", (lease_id,))
            return {**candidate_result(current), "pendingAudit": False, "rejected": True}
        records = request["records"]
        for record in records:
            location = connection.execute("SELECT state, queue_state FROM locations WHERE id=?",
                                          (record["locationId"],)).fetchone()
            if location is None or location["state"] != "pending" or location["queue_state"] != "quarantined":
                raise ScenePipelineError("scene_submission_conflict", 409)
        key = f"four-view-v4/{lease_id}.i8"
        dest = service.artifacts / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        for record in records:
            connection.execute("""UPDATE locations SET state='published', queue_state='pending',
                               output_sha256=?, contributor_id=? WHERE id=?""",
                               (record["outputSha256"], account_id, record["locationId"]))
            connection.execute("""INSERT INTO published_index
                (location_id,index_text,output_sha256,published_at,embedding,four_view_sha256,four_view_key)
                VALUES (?, '', ?, ?, NULL, ?, ?)""",
                (record["locationId"], record["outputSha256"], now, record["outputSha256"], key))
        earned = len(records)
        connection.execute("UPDATE accounts SET units=units+? WHERE id=?", (earned, account_id))
        connection.execute("INSERT INTO ledger (account_id,units,reason,reference) VALUES (?,?,'verified_work',?)",
                           (account_id, earned, f"lease:{lease_id}"))
        connection.execute("UPDATE scene_candidates SET state='published' WHERE lease_id=?", (lease_id,))
    return {"accepted": earned, "unitsEarned": earned, "pendingAudit": False, "replayed": False, "segments": []}
