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
                PRIMARY KEY (origin, account_id, lease_id)
            )""")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(deliveries)")}
            if "updated_at" not in columns:
                connection.execute("ALTER TABLE deliveries ADD COLUMN updated_at REAL NOT NULL DEFAULT 0")

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
        if not isinstance(lease_id, str) or not re.fullmatch(r"[0-9a-f]{32}", lease_id):
            raise ValueError("invalid_lease")
        payload = json.dumps(outputs, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.connection() as connection:
            existing = connection.execute("SELECT payload_sha256 FROM deliveries WHERE origin=? AND account_id=? AND lease_id=?",
                                          (self.origin, self.account_id, lease_id)).fetchone()
            if existing and existing["payload_sha256"] != digest:
                raise ValueError("submission_payload_changed")
            connection.execute("""INSERT OR IGNORE INTO deliveries
                (origin,account_id,lease_id,payload_json,payload_sha256,state,result_json)
                VALUES (?, ?, ?, ?, ?, 'ready', NULL)""",
                               (self.origin, self.account_id, lease_id, payload, digest))

    def result(self, lease_id, result):
        if not isinstance(result, dict) or not (result.get("pendingAudit") is True
                or result.get("rejected") is True or type(result.get("accepted")) is int):
            raise ValueError("invalid_submission_result")
        state = "pending" if result.get("pendingAudit") else "rejected" if result.get("rejected") else "accepted"
        with self.connection() as connection:
            connection.execute("""UPDATE deliveries SET state=?, result_json=?, updated_at=?,
                payload_json=CASE WHEN ?='accepted' THEN NULL ELSE payload_json END
                WHERE origin=? AND account_id=? AND lease_id=? AND state IN ('ready','pending')""",
                (state, json.dumps(result), time.time(), state, self.origin, self.account_id, lease_id))

    def pending(self, limit=16):
        with self.connection() as connection:
            return [dict(row) for row in connection.execute("""SELECT lease_id, state, payload_json FROM deliveries
                WHERE origin=? AND account_id=? AND state IN ('ready','pending') ORDER BY updated_at, rowid LIMIT ?""",
                (self.origin, self.account_id, limit))]

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
