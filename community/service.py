"""Transactional queue, credit ledger, and visual publication gate."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .catalog import file_sha256, iter_jobs_from_path, load_jobs
from .features import MODEL_ID, embedding_for, mean_embeddings, render_faces, sha256_hex
from .mma import MMAError, build_map, location_record, parse_map
from .rank import (
    accepts,
    cap_by_country,
    candidate_result_count,
    canonicalize_country,
    clamp_max_per_country,
    clamp_result_count,
    normalize_filters,
    prune_nearby,
)
from .search import ranked_search, ranked_search_embedding
from .segments import SegmentRegistry
from .source import haversine_meters
from .store import r2_public_status
from .verify import VerificationError, verify_output


DEFAULT_SEARCH_COST = 100_000
MAX_LEASE_SIZE = 1_000
LEASE_SECONDS = 30 * 60
UNITS_PER_LOCATION = {"scene": 1, "object": 10}
RECOVERY_PEPPER_HEADER = "VISION-COMMUNITY-RECOVERY-V1"


class ServiceError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def fixture_index_text(label: str) -> str:
    return " ".join(label.casefold().split())


def fixture_output(asset_id: str, capture: str, lane: str, model: str, index_text: str) -> str:
    message = f"VISION-FIXTURE-V2\n{asset_id}\n{capture}\n{lane}\n{model}\n{index_text}"
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


class CommunityService:
    def __init__(
        self,
        database: Path,
        *,
        search_cost: int = DEFAULT_SEARCH_COST,
        artifacts: Path | None = None,
        segment_capacity: int = 500_000,
        owner_account_id: str | None = None,
        operational: bool = False,
    ):
        if not isinstance(search_cost, int) or search_cost < 1:
            raise ValueError("search_cost must be a positive integer")
        if owner_account_id is not None:
            raise ValueError("owner roles are not implemented and cannot bypass search credit")
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.search_cost = search_cost
        self.operational = operational
        self.artifacts = Path(artifacts) if artifacts is not None else self.database.parent / "artifacts"
        self.registry = SegmentRegistry(self.artifacts / "index", capacity=segment_capacity)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    units INTEGER NOT NULL DEFAULT 0 CHECK (units >= 0),
                    recovery_hash TEXT UNIQUE
                );
                CREATE TABLE IF NOT EXISTS locations (
                    id INTEGER PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    capture TEXT NOT NULL,
                    lane TEXT NOT NULL CHECK (lane IN ('scene', 'object')),
                    model TEXT NOT NULL,
                    label TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending'
                        CHECK (state IN ('pending', 'leased', 'published')),
                    active_lease TEXT,
                    lease_until INTEGER,
                    output_sha256 TEXT,
                    contributor_id TEXT,
                    UNIQUE (asset_id, capture, lane, model)
                );
                CREATE INDEX IF NOT EXISTS locations_queue
                    ON locations (lane, state, lease_until, id);
                CREATE TABLE IF NOT EXISTS leases (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    lane TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('active', 'submitted', 'expired'))
                );
                CREATE TABLE IF NOT EXISTS lease_items (
                    lease_id TEXT NOT NULL REFERENCES leases(id),
                    location_id INTEGER NOT NULL REFERENCES locations(id),
                    PRIMARY KEY (lease_id, location_id)
                );
                CREATE TABLE IF NOT EXISTS published_index (
                    location_id INTEGER PRIMARY KEY REFERENCES locations(id),
                    index_text TEXT NOT NULL,
                    output_sha256 TEXT NOT NULL,
                    published_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    units INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    reference TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS searches (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    idempotency_key TEXT NOT NULL,
                    query TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    UNIQUE (account_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS catalog_shards (
                    sha256 TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    imported INTEGER NOT NULL,
                    imported_at INTEGER NOT NULL
                );
                """
            )
            self._migrate(connection)

    def _migrate(self, connection: sqlite3.Connection) -> None:
        location_cols = {row[1] for row in connection.execute("PRAGMA table_info(locations)")}
        additions = {
            "source": "TEXT",
            "rights": "TEXT",
            "attribution": "TEXT",
            "image_sha256": "TEXT",
            "lat": "REAL",
            "lon": "REAL",
            "generation": "INTEGER NOT NULL DEFAULT 0",
            "queue_state": "TEXT NOT NULL DEFAULT 'pending'",
            "heading": "REAL NOT NULL DEFAULT 0",
            "pitch": "REAL NOT NULL DEFAULT 0",
            "zoom": "REAL NOT NULL DEFAULT 0",
            "country": "TEXT",
            "camera_generation": "TEXT",
        }
        for name, decl in additions.items():
            if name not in location_cols:
                connection.execute(f"ALTER TABLE locations ADD COLUMN {name} {decl}")
        account_cols = {row[1] for row in connection.execute("PRAGMA table_info(accounts)")}
        if "recovery_hash" not in account_cols:
            connection.execute("ALTER TABLE accounts ADD COLUMN recovery_hash TEXT")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS accounts_recovery_hash ON accounts(recovery_hash)"
            )
        index_cols = {row[1] for row in connection.execute("PRAGMA table_info(published_index)")}
        if "embedding" not in index_cols:
            connection.execute("ALTER TABLE published_index ADD COLUMN embedding BLOB")
        if "segment_id" not in index_cols:
            connection.execute("ALTER TABLE published_index ADD COLUMN segment_id TEXT")
        lease_cols = {row[1] for row in connection.execute("PRAGMA table_info(leases)")}
        if "generation" not in lease_cols:
            connection.execute("ALTER TABLE leases ADD COLUMN generation INTEGER")
        if "pace" not in lease_cols:
            connection.execute("ALTER TABLE leases ADD COLUMN pace TEXT")
        connection.execute(
            """CREATE INDEX IF NOT EXISTS locations_spatial
               ON locations (lane, capture, model, lat, lon)"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS catalog_shards (
                    sha256 TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    imported INTEGER NOT NULL,
                    imported_at INTEGER NOT NULL
               )"""
        )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(str(self.database), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def import_synthetic(self, records: list[dict]) -> int:
        """Admit only test records, with one canonical identity per lane/version."""
        if not isinstance(records, list) or len(records) > 100_000:
            raise ServiceError("invalid_fixture")
        checked = []
        for record in records:
            if not isinstance(record, dict):
                raise ServiceError("invalid_fixture")
            fields = [record.get(key) for key in ("assetId", "capture", "lane", "model", "label")]
            if any(not isinstance(field, str) or not field or len(field) > 200 for field in fields):
                raise ServiceError("invalid_fixture")
            if fields[2] not in UNITS_PER_LOCATION or not fields[0].startswith("synthetic:"):
                raise ServiceError("real_source_not_enabled")
            checked.append(tuple(fields))
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            before = connection.total_changes
            connection.executemany(
                """INSERT OR IGNORE INTO locations
                   (asset_id, capture, lane, model, label) VALUES (?, ?, ?, ?, ?)""",
                checked,
            )
            return connection.total_changes - before

    def _recovery_hash(self, recovery_code: str) -> str:
        return hashlib.sha256(f"{RECOVERY_PEPPER_HEADER}\n{recovery_code}".encode("utf-8")).hexdigest()

    def create_account(self) -> dict:
        token = secrets.token_urlsafe(32)
        account_id = secrets.token_hex(16)
        recovery = secrets.token_urlsafe(24)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO accounts (id, token_hash, recovery_hash) VALUES (?, ?, ?)",
                (account_id, token_hash, self._recovery_hash(recovery)),
            )
        return {"accountId": account_id, "token": token, "recoveryCode": recovery}

    def recover_account(self, recovery_code: str) -> dict:
        if not isinstance(recovery_code, str) or not 16 <= len(recovery_code) <= 80:
            raise ServiceError("invalid_recovery", 401)
        recovery_hash = self._recovery_hash(recovery_code)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM accounts WHERE recovery_hash=?", (recovery_hash,)
            ).fetchone()
            if row is None:
                raise ServiceError("invalid_recovery", 401)
            connection.execute(
                "UPDATE accounts SET token_hash=? WHERE id=?", (token_hash, row["id"])
            )
        return {"accountId": row["id"], "token": token}

    def account_for_token(self, token: str) -> str:
        if not isinstance(token, str) or len(token) > 100 or not token:
            raise ServiceError("unauthorized", 401)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, token_hash FROM accounts WHERE token_hash=?", (token_hash,)
            ).fetchone()
        if row is None or not hmac.compare_digest(row["token_hash"], token_hash):
            raise ServiceError("unauthorized", 401)
        return row["id"]

    def status(self, account_id: str | None = None) -> dict:
        with self._connection() as connection:
            counts = {
                row["lane"]: {"pending": row["pending"], "published": row["published"]}
                for row in connection.execute(
                    """SELECT lane,
                         SUM(CASE WHEN state='published' THEN 0 ELSE 1 END) AS pending,
                         SUM(CASE WHEN state='published' THEN 1 ELSE 0 END) AS published
                       FROM locations GROUP BY lane"""
                )
            }
            visual_published = connection.execute(
                "SELECT COUNT(*) FROM published_index WHERE embedding IS NOT NULL"
            ).fetchone()[0]
            countries = sorted({
                canonicalize_country(row[0])
                for row in connection.execute(
                    """SELECT DISTINCT country FROM locations
                       WHERE country IS NOT NULL AND country != ''"""
                )
                if row[0]
            })
            generations = [
                row[0]
                for row in connection.execute(
                    """SELECT DISTINCT camera_generation FROM locations
                       WHERE camera_generation IS NOT NULL AND camera_generation != ''
                       ORDER BY camera_generation"""
                )
            ]
            result = {
                "counts": counts,
                "countries": countries,
                "cameraGenerations": generations,
                "searchCost": self.search_cost,
                "demo": False,
                "operational": self.operational,
                "ownerBypass": False,
                "searchBackend": "local-sealed-segments",
                "r2": r2_public_status(),
                "model": MODEL_ID,
                "visualPublished": visual_published,
                "publicCorpus": False,
                "persistImagery": False,
                "output": "map-making.app JSON",
                "corpusTarget": 200_000_000,
            }
            if account_id is not None:
                row = connection.execute(
                    "SELECT units FROM accounts WHERE id=?", (account_id,)
                ).fetchone()
                if row is None:
                    raise ServiceError("unauthorized", 401)
                result["accountId"] = account_id
                result["units"] = row["units"]
                result["searchesAvailable"] = row["units"] // self.search_cost
            return result

    def _nearby_duplicate(self, connection: sqlite3.Connection, row: dict, *, meters: float = 25.0) -> bool:
        lat, lon = row["lat"], row["lon"]
        dlat = meters / 111_320.0
        cos_lat = math.cos(math.radians(lat))
        dlng = meters / max(1.0, 111_320.0 * abs(cos_lat))
        candidates = connection.execute(
            """SELECT asset_id, lat, lon FROM locations
               WHERE lane=? AND capture=? AND model=?
                 AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?""",
            (row["lane"], row["capture"], row["model"], lat - dlat, lat + dlat, lon - dlng, lon + dlng),
        )
        for other in candidates:
            if other["asset_id"] != row["assetId"] and haversine_meters(lat, lon, other["lat"], other["lon"]) <= meters:
                return True
        return False

    def _queue_states(self, connection: sqlite3.Connection, rows: list[dict]) -> list[dict]:
        prepared = []
        indexed = []
        for row in rows:
            deferred = self._nearby_duplicate(connection, row)
            if not deferred:
                for other in indexed:
                    if (
                        other["lane"] == row["lane"]
                        and other["capture"] == row["capture"]
                        and other["model"] == row["model"]
                        and other["assetId"] != row["assetId"]
                        and haversine_meters(row["lat"], row["lon"], other["lat"], other["lon"]) <= 25.0
                    ):
                        deferred = True
                        break
            item = dict(row)
            item["queueState"] = "deferred" if deferred else "pending"
            prepared.append(item)
            indexed.append(item)
        return prepared

    def _insert_jobs(self, rows: list[dict]) -> int:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prepared = self._queue_states(connection, rows)
            before = connection.total_changes
            connection.executemany(
                """INSERT OR IGNORE INTO locations
                   (asset_id, capture, lane, model, label, source, rights, attribution,
                    lat, lon, heading, pitch, zoom, country, camera_generation, queue_state)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        row["assetId"],
                        row["capture"],
                        row["lane"],
                        row["model"],
                        row.get("label") or "",
                        row["source"],
                        row["rights"],
                        row["attribution"],
                        row["lat"],
                        row["lon"],
                        row.get("heading") or 0,
                        row.get("pitch") or 0,
                        row.get("zoom") or 0,
                        row.get("country") or "",
                        row.get("cameraGeneration") or "",
                        row["queueState"],
                    )
                    for row in prepared
                    if row["queueState"] == "pending"
                ],
            )
            connection.executemany(
                """INSERT OR IGNORE INTO locations
                   (asset_id, capture, lane, model, label, source, rights, attribution,
                    lat, lon, heading, pitch, zoom, country, camera_generation, queue_state, state)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'deferred', 'pending')""",
                [
                    (
                        row["assetId"],
                        row["capture"],
                        row["lane"],
                        row["model"],
                        row.get("label") or "",
                        row["source"],
                        row["rights"],
                        row["attribution"],
                        row["lat"],
                        row["lon"],
                        row.get("heading") or 0,
                        row.get("pitch") or 0,
                        row.get("zoom") or 0,
                        row.get("country") or "",
                        row.get("cameraGeneration") or "",
                    )
                    for row in prepared
                    if row["queueState"] == "deferred"
                ],
            )
            return connection.total_changes - before

    def import_jobs(self, document: dict, *, grant: dict | None = None, ingest: bool = False) -> int:
        rows = load_jobs(document, grant=grant)
        if document.get("source") == "wikimedia" and not ingest:
            raise ServiceError("ingest_not_started")
        return self._insert_jobs(rows)

    def import_shard(self, path: Path, *, lane: str = "scene", batch_size: int = 500, limit: int | None = None) -> dict:
        path = Path(path)
        if batch_size < 1:
            raise ServiceError("invalid_batch")
        digest = file_sha256(path)
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT imported FROM catalog_shards WHERE sha256=?", (digest,)
            ).fetchone()
            if existing is not None:
                return {"imported": 0, "sha256": digest, "skipped": True, "alreadyImported": existing["imported"]}
        total = 0
        batch: list[dict] = []
        for job in iter_jobs_from_path(path, lane=lane):
            batch.append(job)
            if len(batch) >= batch_size:
                total += self._insert_jobs(batch)
                batch = []
                if limit is not None and total >= limit:
                    break
        if batch and (limit is None or total < limit):
            if limit is not None:
                batch = batch[: max(0, limit - total)]
            if batch:
                total += self._insert_jobs(batch)
        if limit is None:
            with self._connection() as connection:
                connection.execute(
                    """INSERT OR IGNORE INTO catalog_shards (sha256, path, imported, imported_at)
                       VALUES (?, ?, ?, ?)""",
                    (digest, str(path), total, int(time.time())),
                )
        return {"imported": total, "sha256": digest, "skipped": False}

    def lease(
        self,
        account_id: str,
        lane: str,
        count: int,
        *,
        now: int | None = None,
        pace: str | None = None,
    ) -> dict:
        if lane not in UNITS_PER_LOCATION or type(count) is not int or not 1 <= count <= MAX_LEASE_SIZE:
            raise ServiceError("invalid_lease_request")
        if pace is not None and pace not in {"slow", "medium", "max"}:
            raise ServiceError("invalid_pace")
        now = int(time.time()) if now is None else now
        expires_at = now + LEASE_SECONDS
        lease_id = secrets.token_hex(16)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # An expired lease loses its claim before any task can be reassigned.
            connection.execute(
                "UPDATE leases SET state='expired' WHERE state='active' AND expires_at<=?", (now,)
            )
            rows = connection.execute(
                """SELECT id, asset_id, capture, lane, model, label, generation, source, rights, attribution,
                          lat, lon, heading, pitch, zoom, country, camera_generation
                   FROM locations WHERE lane=? AND COALESCE(queue_state, 'pending')='pending' AND
                     (state='pending' OR (state='leased' AND lease_until<=?))
                   ORDER BY id LIMIT ?""",
                (lane, now, count),
            ).fetchall()
            if not rows:
                raise ServiceError("no_available_work", 409)
            generations = []
            for row in rows:
                next_generation = int(row["generation"] or 0) + 1
                generations.append((next_generation, row["id"]))
            connection.execute(
                """INSERT INTO leases (id, account_id, lane, expires_at, state, generation, pace)
                   VALUES (?, ?, ?, ?, 'active', ?, ?)""",
                (lease_id, account_id, lane, expires_at, generations[0][0], pace),
            )
            connection.executemany(
                "INSERT INTO lease_items (lease_id, location_id) VALUES (?, ?)",
                [(lease_id, row["id"]) for row in rows],
            )
            connection.executemany(
                """UPDATE locations SET state='leased', active_lease=?, lease_until=?, generation=? WHERE id=?""",
                [(lease_id, expires_at, generation, location_id) for generation, location_id in generations],
            )
            generation_by_id = {location_id: generation for generation, location_id in generations}
        items = []
        for row in rows:
            item = {
                "locationId": row["id"],
                "assetId": row["asset_id"],
                "panoId": row["asset_id"],
                "capture": row["capture"],
                "lane": row["lane"],
                "model": row["model"],
                "label": row["label"],
                "generation": generation_by_id[row["id"]],
                "attribution": row["attribution"],
                "lat": row["lat"],
                "lng": row["lon"],
                "heading": row["heading"] or 0,
                "pitch": row["pitch"] or 0,
                "zoom": row["zoom"] or 0,
                "country": row["country"] or "",
                "cameraGeneration": row["camera_generation"] or "",
                "persistImagery": False,
            }
            if row["model"] == MODEL_ID:
                # Identity checksum only. Pixels stay on the worker; they are not sent or stored.
                faces = render_faces(row["asset_id"], row["capture"], row["lane"], row["model"])
                item["facesSha256"] = sha256_hex(faces)
            items.append(item)
        return {
            "leaseId": lease_id,
            "expiresAt": expires_at,
            "pace": pace,
            "resourceBudget": {"slow": 1, "medium": "cpu/2", "max": "all-cores"}.get(pace or "medium"),
            "items": items,
        }

    def submit(self, account_id: str, lease_id: str, outputs: list[dict], *, now: int | None = None) -> dict:
        if not isinstance(lease_id, str) or not isinstance(outputs, list) or len(outputs) > MAX_LEASE_SIZE:
            raise ServiceError("invalid_submission")
        now = int(time.time()) if now is None else now
        supplied = {}
        for output in outputs:
            if not isinstance(output, dict) or type(output.get("locationId")) is not int:
                raise ServiceError("invalid_submission")
            location_id = output["locationId"]
            digest = output.get("outputSha256")
            if location_id in supplied or not isinstance(digest, str) or len(digest) != 64:
                raise ServiceError("invalid_submission")
            embedding = output.get("embedding")
            if isinstance(embedding, str):
                try:
                    embedding = base64.b64decode(embedding)
                except (ValueError, TypeError):
                    raise ServiceError("invalid_submission")
            index_text = output.get("indexText")
            if embedding is None:
                if not isinstance(index_text, str) or not 1 <= len(index_text) <= 200:
                    raise ServiceError("invalid_submission")
            elif not isinstance(embedding, (bytes, bytearray)) or not 1 <= len(embedding) <= 4096:
                raise ServiceError("invalid_submission")
            supplied[location_id] = {
                "digest": digest,
                "index_text": index_text if isinstance(index_text, str) else "",
                "embedding": bytes(embedding) if embedding is not None else None,
                "embeddingSha256": output.get("embeddingSha256"),
                "model": output.get("model"),
            }
        embeddings_to_seal: dict[str, list] = {"scene": [], "object": []}
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            lease = connection.execute(
                "SELECT * FROM leases WHERE id=? AND account_id=?", (lease_id, account_id)
            ).fetchone()
            if lease is None:
                raise ServiceError("unknown_lease", 404)
            if lease["state"] == "submitted":
                accepted = connection.execute(
                    "SELECT COUNT(*) FROM lease_items WHERE lease_id=?", (lease_id,)
                ).fetchone()[0]
                return {"accepted": accepted, "unitsEarned": 0, "replayed": True}
            if lease["state"] != "active" or lease["expires_at"] <= now:
                raise ServiceError("expired_lease", 409)
            items = connection.execute(
                """SELECT l.* FROM locations l JOIN lease_items i ON i.location_id=l.id
                   WHERE i.lease_id=? ORDER BY l.id""",
                (lease_id,),
            ).fetchall()
            if set(supplied) != {row["id"] for row in items}:
                raise ServiceError("incomplete_submission")
            verified = {}
            for row in items:
                if row["state"] != "leased" or row["active_lease"] != lease_id:
                    raise ServiceError("lease_lost", 409)
                payload = supplied[row["id"]]
                if row["model"] == MODEL_ID:
                    try:
                        embedding = verify_output({key: row[key] for key in row.keys()}, payload)
                    except VerificationError as error:
                        raise ServiceError(error.code, 422) from error
                    verified[row["id"]] = {
                        "digest": payload["digest"],
                        "index_text": "",
                        "embedding": embedding,
                    }
                    embeddings_to_seal[row["lane"]].append(
                        (
                            row["id"],
                            embedding,
                            {
                                "locationId": row["id"],
                                "lat": row["lat"] or 0,
                                "lng": row["lon"] or 0,
                                "heading": row["heading"] or 0,
                                "pitch": row["pitch"] or 0,
                                "zoom": row["zoom"] or 0,
                                "panoId": row["asset_id"],
                                "capture": row["capture"],
                                "country": row["country"] or "",
                                "cameraGeneration": row["camera_generation"] or "",
                            },
                        )
                    )
                else:
                    expected_text = fixture_index_text(row["label"])
                    expected = fixture_output(
                        row["asset_id"], row["capture"], row["lane"], row["model"], expected_text
                    )
                    if payload["index_text"] != expected_text or not hmac.compare_digest(payload["digest"], expected):
                        raise ServiceError("verification_failed", 422)
                    verified[row["id"]] = {
                        "digest": payload["digest"],
                        "index_text": payload["index_text"],
                        "embedding": None,
                    }
            earned = sum(UNITS_PER_LOCATION[row["lane"]] for row in items)
            connection.executemany(
                """UPDATE locations SET state='published', active_lease=NULL,
                   lease_until=NULL, output_sha256=?, contributor_id=? WHERE id=?""",
                [(verified[row["id"]]["digest"], account_id, row["id"]) for row in items],
            )
            connection.executemany(
                """INSERT INTO published_index
                   (location_id, index_text, output_sha256, published_at, embedding)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        row["id"],
                        verified[row["id"]]["index_text"],
                        verified[row["id"]]["digest"],
                        now,
                        verified[row["id"]]["embedding"],
                    )
                    for row in items
                ],
            )
            connection.execute("UPDATE leases SET state='submitted' WHERE id=?", (lease_id,))
            connection.execute("UPDATE accounts SET units=units+? WHERE id=?", (earned, account_id))
            connection.execute(
                "INSERT INTO ledger (account_id, units, reason, reference) VALUES (?, ?, 'verified_work', ?)",
                (account_id, earned, f"lease:{lease_id}"),
            )
        sealed = []
        for lane, records in embeddings_to_seal.items():
            if not records:
                continue
            published = self.registry.publish(
                lane=lane,
                location_ids=[item[0] for item in records],
                embeddings=b"".join(item[1] for item in records),
                poses=[item[2] for item in records],
            )
            sealed.append(published)
            with self._connection() as connection:
                connection.executemany(
                    "UPDATE published_index SET segment_id=? WHERE location_id=?",
                    [(published["id"], location_id) for location_id, _embed, _pose in records],
                )
        return {"accepted": len(items), "unitsEarned": earned, "replayed": False, "segments": sealed}

    def _mma_map(self, connection, hits: list[dict], *, query_name: str, lane: str) -> dict:
        processed = connection.execute(
            "SELECT COUNT(*) FROM published_index WHERE embedding IS NOT NULL"
        ).fetchone()[0]
        coordinates = []
        min_score = hits[-1]["score"] if hits else 0.0
        for rank, hit in enumerate(hits, start=1):
            pose = hit.get("pose") or {}
            if pose.get("panoId"):
                lat, lng = pose.get("lat") or 0, pose.get("lng") or 0
                heading, pitch, zoom = pose.get("heading") or 0, pose.get("pitch") or 0, pose.get("zoom") or 0
                pano_id = pose["panoId"]
                country = pose.get("country") or ""
                camera = pose.get("cameraGeneration") or ""
            else:
                row = connection.execute(
                    """SELECT asset_id, lat, lon, heading, pitch, zoom, country, camera_generation
                       FROM locations WHERE id=?""",
                    (hit["locationId"],),
                ).fetchone()
                if row is None:
                    continue
                lat, lng = row["lat"] or 0, row["lon"] or 0
                heading, pitch, zoom = row["heading"] or 0, row["pitch"] or 0, row["zoom"] or 0
                pano_id = row["asset_id"]
                country = row["country"] or ""
                camera = row["camera_generation"] or ""
            coordinates.append(
                location_record(
                    lat=lat,
                    lng=lng,
                    heading=heading,
                    pitch=pitch,
                    zoom=zoom,
                    pano_id=pano_id,
                    rank=rank,
                    score=hit["score"],
                    query_name=query_name,
                    lane=lane,
                    country=country,
                    camera_generation=camera,
                    processed_locations=processed,
                    min_score=min_score,
                )
            )
        return build_map(query_name, coordinates)

    def search(
        self,
        account_id: str,
        query: str | None,
        idempotency_key: str,
        *,
        query_faces: bytes | None = None,
        query_map: dict | None = None,
        lane: str = "scene",
        result_count: int = 200,
        max_per_country: int = 25,
        output_name: str | None = None,
        country_filter_mode: str | None = None,
        countries=None,
        camera_generations=None,
    ) -> dict:
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 100:
            raise ServiceError("invalid_idempotency_key")
        result_count = clamp_result_count(result_count)
        max_per_country = clamp_max_per_country(max_per_country)
        country_mode, selected_countries, selected_generations = normalize_filters(
            country_filter_mode, countries, camera_generations
        )
        if country_mode == "include" and not selected_countries:
            raise ServiceError("invalid_country_filter")
        visual = query_faces is not None or query_map is not None
        query_name = output_name.strip() if isinstance(output_name, str) and output_name.strip() else "VISION Community"
        parsed = None
        if query_map is not None:
            try:
                parsed = parse_map(query_map)
            except MMAError as error:
                raise ServiceError(error.code) from error
            query_name = output_name.strip() if isinstance(output_name, str) and output_name.strip() else parsed["name"]
            query_key = "mma:" + query_name + ":" + lane + ":" + ",".join(example["panoId"] for example in parsed["examples"])
        elif query_faces is not None:
            if not isinstance(query_faces, (bytes, bytearray)):
                raise ServiceError("invalid_query")
            query_key = "visual:" + sha256_hex(bytes(query_faces)) + ":" + lane
        else:
            if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
                raise ServiceError("invalid_query")
            query_key = query.strip()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT query, result_json FROM searches WHERE account_id=? AND idempotency_key=?",
                (account_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["query"] != query_key:
                    raise ServiceError("idempotency_conflict", 409)
                return json.loads(existing["result_json"])
            account = connection.execute(
                "SELECT units FROM accounts WHERE id=?", (account_id,)
            ).fetchone()
            if account is None:
                raise ServiceError("unauthorized", 401)
            if account["units"] < self.search_cost:
                raise ServiceError("insufficient_credit", 402)
            if visual:
                overfetch = candidate_result_count(result_count, max_per_country)
                accept = lambda record: accepts(record, country_mode, selected_countries, selected_generations)
                if parsed is not None:
                    vectors = []
                    for example in parsed["examples"]:
                        row = connection.execute(
                            """SELECT capture FROM locations
                               WHERE asset_id=? AND lane=?
                               ORDER BY CASE WHEN state='published' THEN 0 ELSE 1 END, id
                               LIMIT 1""",
                            (example["panoId"], lane),
                        ).fetchone()
                        capture = row["capture"] if row is not None else example["capture"]
                        vectors.append(
                            embedding_for(lane, render_faces(example["panoId"], capture, lane, MODEL_ID))
                        )
                    query_embedding = mean_embeddings(vectors)
                    matches = ranked_search_embedding(
                        self.registry, lane, query_embedding, limit=overfetch, accept=accept
                    )
                else:
                    matches = ranked_search(
                        self.registry, lane, bytes(query_faces), limit=overfetch, accept=accept
                    )
                matches = cap_by_country(prune_nearby(matches), result_count, max_per_country)
                mma = self._mma_map(connection, matches, query_name=query_name, lane=lane)
                result_demo = False
            else:
                matches = [
                    {"locationId": row["id"], "label": row["label"], "lane": row["lane"]}
                    for row in connection.execute(
                        """SELECT l.id, l.label, l.lane FROM published_index i
                           JOIN locations l ON l.id=i.location_id
                           WHERE l.state='published' AND i.embedding IS NULL
                             AND instr(i.index_text, ?) > 0
                           ORDER BY l.id LIMIT ?""",
                        (fixture_index_text(query_key), result_count),
                    )
                ]
                mma = None
                result_demo = True
            search_id = secrets.token_hex(16)
            result = {
                "searchId": search_id,
                "query": query_name if visual else query_key,
                "results": matches,
                "demo": result_demo,
                "persistImagery": False,
                "map": mma,
            }
            connection.execute(
                "UPDATE accounts SET units=units-? WHERE id=? AND units>=?",
                (self.search_cost, account_id, self.search_cost),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ServiceError("insufficient_credit", 402)
            connection.execute(
                "INSERT INTO searches (id, account_id, idempotency_key, query, result_json) VALUES (?, ?, ?, ?, ?)",
                (search_id, account_id, idempotency_key, query_key, json.dumps(result, separators=(",", ":"))),
            )
            connection.execute(
                "INSERT INTO ledger (account_id, units, reason, reference) VALUES (?, ?, 'search', ?)",
                (account_id, -self.search_cost, f"search:{search_id}"),
            )
            return result
