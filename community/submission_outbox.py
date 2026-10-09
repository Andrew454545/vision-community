"""Durable local delivery journal, scoped to an anonymous account and service.

The server remains authoritative for verification and credit. This journal
contains output data and responses, never account codes or bearer tokens.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time


MAX_PENDING_SUBMISSIONS = 64
LOST_LEASE_CODES = frozenset({"expired_lease", "lease_lost", "unknown_lease"})


def submission_result_state(lease_id, result, expected_count=None):
    """Only a coherent service acknowledgement may retire saved output."""
    if not isinstance(result, dict):
        raise ValueError("invalid_submission_result")
    if any(key in result and type(result[key]) is not bool for key in ("pendingAudit", "rejected", "replayed")):
        raise ValueError("invalid_submission_result")
    if any(key in result and (type(result[key]) is not int or not 0 <= result[key] <= 2**53 - 1)
           for key in ("accepted", "unitsEarned")):
        raise ValueError("invalid_submission_result")
    if "submissionId" in result and result["submissionId"] != lease_id:
        raise ValueError("invalid_submission_result")
    pending, rejected = result.get("pendingAudit", False), result.get("rejected", False)
    accepted, earned = result.get("accepted", 0), result.get("unitsEarned", 0)
    if pending and rejected or (pending or rejected) and (accepted or earned):
        raise ValueError("invalid_submission_result")
    if not pending and not rejected and ("accepted" not in result or earned and not accepted):
        raise ValueError("invalid_submission_result")
    if not pending and not rejected and expected_count is not None:
        # Each submitted batch is atomic. A partial/empty fresh acknowledgement
        # must never erase the only retryable copy of its remaining locations.
        # Scene audits may report zero for an already published replay; retain
        # that explicit protocol case without counting it as new earned work.
        if (type(expected_count) is not int or expected_count < 1
                or accepted != expected_count and not (accepted == 0 and result.get("replayed") is True)):
            raise ValueError("invalid_submission_result")
    return "pending" if pending else "rejected" if rejected else "accepted"


class SubmissionOutbox:
    def __init__(self, path, origin, account_id):
        if not isinstance(account_id, str) or not re.fullmatch(r"[0-9a-f]{32}", account_id):
            raise ValueError("invalid_account_id")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.origin, self.account_id = origin, account_id
        with self.connection() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS deliveries (
                origin TEXT NOT NULL, account_id TEXT NOT NULL, lease_id TEXT NOT NULL,
                payload_json TEXT, payload_sha256 TEXT NOT NULL, state TEXT NOT NULL,
                result_json TEXT, updated_at REAL NOT NULL DEFAULT 0,
                lane TEXT NOT NULL DEFAULT 'scene',
                PRIMARY KEY (origin, account_id, lease_id)
            )""")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(deliveries)")}
            if "updated_at" not in columns:
                connection.execute("ALTER TABLE deliveries ADD COLUMN updated_at REAL NOT NULL DEFAULT 0")
            if "lane" not in columns:
                connection.execute("ALTER TABLE deliveries ADD COLUMN lane TEXT NOT NULL DEFAULT 'scene'")
            # Months of accepted receipts must not slow each delivery recovery.
            # Keep the journal and failure evidence; index only actionable rows.
            connection.execute("""CREATE INDEX IF NOT EXISTS deliveries_pending
                ON deliveries(origin, account_id, updated_at)
                WHERE state IN ('ready','pending')""")
            connection.execute("""CREATE INDEX IF NOT EXISTS deliveries_lost
                ON deliveries(origin, account_id) WHERE state='lease_lost'""")

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous=FULL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def remember(self, lease_id, outputs):
        self._remember(lease_id, outputs, "scene")

    def remember_object(self, lease_id, outputs, object_index):
        if not isinstance(outputs, list) or not isinstance(object_index, dict):
            raise ValueError("invalid_saved_submission")
        self._remember(lease_id, {"outputs": outputs, "objectIndex": object_index}, "object")

    def _remember(self, lease_id, value, lane):
        if not isinstance(lease_id, str) or not re.fullmatch(r"[0-9a-f]{32}", lease_id):
            raise ValueError("invalid_lease")
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.connection() as connection:
            existing = connection.execute("SELECT payload_sha256,lane FROM deliveries WHERE origin=? AND account_id=? AND lease_id=?",
                                          (self.origin, self.account_id, lease_id)).fetchone()
            if existing and (existing["payload_sha256"] != digest or existing["lane"] != lane):
                raise ValueError("submission_payload_changed")
            connection.execute("""INSERT OR IGNORE INTO deliveries
                (origin,account_id,lease_id,payload_json,payload_sha256,state,result_json,lane)
                VALUES (?, ?, ?, ?, ?, 'ready', NULL, ?)""",
                               (self.origin, self.account_id, lease_id, payload, digest, lane))

    @staticmethod
    def decode_delivery(delivery):
        """Check the immutable bytes before retrying a saved submission."""
        try:
            payload, lane = delivery["payload_json"], delivery["lane"]
            if (not isinstance(payload, str) or lane not in {"scene", "object"}
                    or hashlib.sha256(payload.encode()).hexdigest() != delivery["payload_sha256"]):
                raise ValueError
            value = json.loads(payload)
            if lane == "object":
                if (not isinstance(value, dict) or set(value) != {"outputs", "objectIndex"}
                        or not isinstance(value["objectIndex"], dict)):
                    raise ValueError
                outputs = value["outputs"]
            else:
                outputs = value
            if not isinstance(outputs, list):
                raise ValueError
            return value
        except (KeyError, TypeError, ValueError):
            raise ValueError("invalid_saved_submission") from None

    def result(self, lease_id, result):
        state = submission_result_state(lease_id, result)
        with self.connection() as connection:
            saved = connection.execute("""SELECT payload_json,payload_sha256,lane FROM deliveries
                    WHERE origin=? AND account_id=? AND lease_id=? AND state IN ('ready','pending')""",
                    (self.origin, self.account_id, lease_id)).fetchone()
            if saved:
                payload = self.decode_delivery(saved)
                # Objects has no asynchronous audit protocol yet. Keep a
                # surprising pending reply ready for exact resubmission;
                # never route it to the Scene audit endpoint.
                if saved["lane"] == "object" and state == "pending":
                    raise ValueError("invalid_submission_result")
                if state == "accepted":
                    outputs = payload["outputs"] if saved["lane"] == "object" else payload
                    submission_result_state(lease_id, result, len(outputs))
            connection.execute("""UPDATE deliveries SET state=?, result_json=?, updated_at=?,
                payload_json=CASE WHEN ?='accepted' THEN NULL ELSE payload_json END
                WHERE origin=? AND account_id=? AND lease_id=? AND state IN ('ready','pending')""",
                (state, json.dumps(result), time.time(), state, self.origin, self.account_id, lease_id))

    def pending(self, limit=16, *, include_payload=True):
        fields = "lease_id,state,lane,payload_sha256" + (",payload_json" if include_payload else "")
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(f"""SELECT {fields} FROM deliveries
                WHERE origin=? AND account_id=? AND state IN ('ready','pending') ORDER BY updated_at, rowid LIMIT ?""",
                (self.origin, self.account_id, limit))]

    def pending_delivery(self, lease_id):
        with self.connection() as connection:
            row = connection.execute("""SELECT lease_id,state,lane,payload_sha256,payload_json FROM deliveries
                WHERE origin=? AND account_id=? AND lease_id=? AND state IN ('ready','pending')""",
                (self.origin, self.account_id, lease_id)).fetchone()
            return dict(row) if row else None

    def lose_lease(self, lease_id, code):
        """Retain completed output after a definitive server ownership refusal.

        A staged candidate remains pending audit even after its lease expires.
        Only an unacknowledged delivery may enter this terminal state.
        """
        if code not in LOST_LEASE_CODES:
            raise ValueError("invalid_lease_loss")
        result = {"accepted": 0, "unitsEarned": 0, "leaseLost": True, "code": code}
        with self.connection() as connection:
            changed = connection.execute("""UPDATE deliveries
                SET state='lease_lost', result_json=?, updated_at=?
                WHERE origin=? AND account_id=? AND lease_id=? AND state='ready'""",
                (json.dumps(result), time.time(), self.origin, self.account_id, lease_id))
            return changed.rowcount == 1

    def undelivered(self):
        with self.connection() as connection:
            return connection.execute("""SELECT COUNT(*) FROM deliveries
                WHERE origin=? AND account_id=? AND state='lease_lost'""",
                (self.origin, self.account_id)).fetchone()[0]

    def count(self):
        with self.connection() as connection:
            return connection.execute("""SELECT COUNT(*) FROM deliveries
                WHERE origin=? AND account_id=? AND state IN ('ready','pending')""",
                (self.origin, self.account_id)).fetchone()[0]

    def saved(self, lease_id):
        with self.connection() as connection:
            return connection.execute("""SELECT 1 FROM deliveries
                WHERE origin=? AND account_id=? AND lease_id=?""",
                (self.origin, self.account_id, lease_id)).fetchone() is not None
