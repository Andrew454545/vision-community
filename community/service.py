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

from .catalog import file_sha256, iter_jobs_from_path, load_jobs, parse_indexer_line
from .features import MODEL_ID, embedding_for, mean_embeddings, normalize_view_direction, render_faces, sha256_hex, wrap_heading
from .four_view import VISION_FOUR_VIEW_MODEL, valid_four_view_record
from .pano import QUERY_VIEW_CAP, ViewError, lease_cap, render_location_faces, uses_street_views
from .prompt import description_embedding, mix_embeddings, parse_prompt, snap_description_weight
from .parts import (
    STEAL_AFTER_SECONDS,
    describe_part,
    family_for_key,
    family_priority_sql,
    parse_part,
)
from .mma import MMAError, build_map, location_record, parse_map
from .rank import (
    MAX_EXCLUDE_LOCATIONS,
    accepts,
    cap_by_country,
    candidate_result_count,
    canonicalize_country,
    clamp_max_per_country,
    clamp_result_count,
    exclude_used,
    normalize_filters,
    prune_nearby,
)
from .search import query_vector, ranked_search_embedding
from .segments import SegmentRegistry
from .source import haversine_meters
from .store import r2_public_status
from .verify import VerificationError, locations_to_recompute, verify_output


DEFAULT_SEARCH_COST = 100_000
MAX_LEASE_SIZE = 1_000
LEASE_SECONDS = 30 * 60
CLI_LEASE_SECONDS = 6 * 60 * 60
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


def _exclude_points(exclude_map) -> list[dict]:
    if exclude_map is None:
        return []
    if isinstance(exclude_map, list):
        rows = exclude_map
    elif isinstance(exclude_map, dict):
        if isinstance(exclude_map.get("customCoordinates"), list):
            rows = exclude_map["customCoordinates"]
        elif isinstance(exclude_map.get("locations"), list):
            rows = exclude_map["locations"]
        elif isinstance(exclude_map.get("coordinates"), list):
            rows = exclude_map["coordinates"]
        else:
            rows = []
    else:
        raise ServiceError("invalid_mma_map")
    points = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pano = row.get("panoId") or row.get("pano_id") or row.get("pano") or ""
        if isinstance(pano, str) and ("maps.googleapis.com" in pano or pano.startswith("http")):
            raise ServiceError("imagery_url_forbidden")
        try:
            lat = float(row.get("lat") if row.get("lat") is not None else 0)
            lng = float(row.get("lng") if row.get("lng") is not None else row.get("lon") or 0)
        except (TypeError, ValueError):
            continue
        points.append({"lat": lat, "lng": lng, "panoId": pano if isinstance(pano, str) else ""})
        if len(points) >= MAX_EXCLUDE_LOCATIONS:
            break
    return points


def _exclude_key(excluded: list[dict]) -> str:
    if not excluded:
        return ""
    payload = json.dumps(excluded, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return ":exclude:" + sha256_hex(payload)[:16]


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
            "catalog_shard": "INTEGER",
        }
        for name, decl in additions.items():
            if name not in location_cols:
                connection.execute(f"ALTER TABLE locations ADD COLUMN {name} {decl}")
        connection.execute(
            """CREATE INDEX IF NOT EXISTS locations_nearby
               ON locations (lane, capture, model, lat, lon)"""
        )
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
        if "four_view_sha256" not in index_cols:
            connection.execute("ALTER TABLE published_index ADD COLUMN four_view_sha256 TEXT")
        if "four_view_key" not in index_cols:
            connection.execute("ALTER TABLE published_index ADD COLUMN four_view_key TEXT")
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
        connection.execute(
            """CREATE TABLE IF NOT EXISTS pose_catalog (
                    lane TEXT NOT NULL,
                    shard_id INTEGER NOT NULL,
                    r2_key TEXT NOT NULL,
                    row_start INTEGER NOT NULL,
                    row_count INTEGER NOT NULL,
                    bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    next_byte INTEGER NOT NULL DEFAULT 0,
                    next_row INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (lane, shard_id)
               )"""
        )
        catalog_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='pose_catalog'"
        ).fetchone()
        if catalog_sql and catalog_sql[0] and "r2_key TEXT NOT NULL UNIQUE" in catalog_sql[0]:
            connection.execute(
                """CREATE TABLE pose_catalog_v2 (
                    lane TEXT NOT NULL, shard_id INTEGER NOT NULL, r2_key TEXT NOT NULL,
                    row_start INTEGER NOT NULL, row_count INTEGER NOT NULL, bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, next_byte INTEGER NOT NULL DEFAULT 0,
                    next_row INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (lane, shard_id)
                )"""
            )
            connection.execute("INSERT OR IGNORE INTO pose_catalog_v2 SELECT * FROM pose_catalog")
            connection.execute("DROP TABLE pose_catalog")
            connection.execute("ALTER TABLE pose_catalog_v2 RENAME TO pose_catalog")
        catalog_cols = {row[1] for row in connection.execute("PRAGMA table_info(pose_catalog)")}
        if "assignee" not in catalog_cols:
            connection.execute("ALTER TABLE pose_catalog ADD COLUMN assignee TEXT")
        if "assigned_at" not in catalog_cols:
            connection.execute("ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER")
        if "held" not in catalog_cols:
            connection.execute("ALTER TABLE pose_catalog ADD COLUMN held INTEGER NOT NULL DEFAULT 0")
        connection.execute(
            """CREATE INDEX IF NOT EXISTS locations_part_queue
               ON locations (lane, catalog_shard, state, lease_until, id)"""
        )
        connection.execute(
            """UPDATE locations SET catalog_shard = (
                    SELECT p.shard_id FROM pose_catalog p
                    WHERE p.lane = locations.lane
                      AND p.r2_key LIKE 'catalog/all-locations-tail-v1/%'
                    ORDER BY p.shard_id LIMIT 1
               )
               WHERE catalog_shard IS NULL
                 AND COALESCE(source, '') = 'street-metadata'
                 AND asset_id NOT LIKE 'Prototype%'
                 AND asset_id NOT LIKE 'synthetic:%'
                 AND asset_id NOT LIKE 'CommunityPano%'
                 AND EXISTS (
                    SELECT 1 FROM pose_catalog p
                    WHERE p.lane = locations.lane
                      AND p.r2_key LIKE 'catalog/all-locations-tail-v1/%'
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

    def status(self, account_id: str | None = None, lite: bool = False) -> dict:
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
            for row in connection.execute(
                """SELECT lane, SUM(row_count - next_row) AS remaining
                   FROM pose_catalog GROUP BY lane"""
            ):
                lane_counts = counts.setdefault(row["lane"], {"pending": 0, "published": 0})
                remaining = int(row["remaining"] or 0)
                lane_counts["catalogRemaining"] = remaining
                lane_counts["pending"] = int(lane_counts.get("pending") or 0) + remaining
            visual_published = connection.execute(
                "SELECT COUNT(*) FROM published_index WHERE embedding IS NOT NULL"
            ).fetchone()[0]
            countries = [] if lite else sorted({
                canonicalize_country(row[0])
                for row in connection.execute(
                    """SELECT DISTINCT country FROM locations
                       WHERE country IS NOT NULL AND country != ''"""
                )
                if row[0]
            })
            generations = [] if lite else [
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
                "searchOnSite": True,
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
                if not lite:
                    scene_work = self._work_status(connection, account_id, "scene")
                    object_work = self._work_status(connection, account_id, "object")
                    result["work"] = scene_work
                    result["workByLane"] = {"scene": scene_work, "object": object_work}
            return result

    def _require_paid_search(self, connection: sqlite3.Connection, account_id: str, search_id: str) -> None:
        if not isinstance(search_id, str) or not search_id:
            raise ServiceError("unknown_search", 404)
        paid = connection.execute(
            """SELECT s.id FROM searches s
               WHERE s.id=? AND s.account_id=?
                 AND EXISTS (
                   SELECT 1 FROM ledger
                   WHERE reference=? AND account_id=? AND reason='search' AND units<0
                 )""",
            (search_id, account_id, f"search:{search_id}", account_id),
        ).fetchone()
        if paid is None:
            raise ServiceError("unknown_search", 404)

    def published_snapshot(
        self,
        account_id: str,
        *,
        search_id: str,
        lane: str = "scene",
        after: int = 0,
        limit: int = 250,
    ) -> dict:
        if lane not in {"scene", "object"}:
            raise ServiceError("invalid_lane")
        try:
            after = max(0, int(after or 0))
            limit = min(500, max(1, int(limit or 250)))
        except (TypeError, ValueError) as error:
            raise ServiceError("invalid_json") from error
        with self._connection() as connection:
            self._require_paid_search(connection, account_id, search_id)
            rows = connection.execute(
                """SELECT i.location_id, i.embedding, l.asset_id, l.lat, l.lon, l.heading,
                          l.pitch, l.zoom, l.country, l.camera_generation
                   FROM published_index i JOIN locations l ON l.id=i.location_id
                   WHERE i.embedding IS NOT NULL AND l.lane=? AND i.location_id>?
                   ORDER BY i.location_id LIMIT ?""",
                (lane, after, limit + 1),
            ).fetchall()
        page = rows[:limit]
        locations = []
        for row in page:
            embedding = row["embedding"]
            if isinstance(embedding, memoryview):
                embedding = bytes(embedding)
            if isinstance(embedding, bytes):
                hex_embedding = embedding.hex()
            else:
                hex_embedding = str(embedding or "")
            locations.append(
                {
                    "locationId": row["location_id"],
                    "panoId": row["asset_id"],
                    "lat": row["lat"] or 0,
                    "lng": row["lon"] or 0,
                    "heading": row["heading"] or 0,
                    "pitch": row["pitch"] or 0,
                    "zoom": row["zoom"] or 0,
                    "country": row["country"] or "",
                    "cameraGeneration": row["camera_generation"] or "",
                    "embedding": hex_embedding,
                }
            )
        next_after = page[-1]["location_id"] if len(rows) > limit else None
        return {"lane": lane, "locations": locations, "nextAfter": next_after}

    def index_manifest(self, account_id: str, *, search_id: str, lane: str = "scene") -> dict:
        if lane not in {"scene", "object"}:
            raise ServiceError("invalid_lane")
        with self._connection() as connection:
            self._require_paid_search(connection, account_id, search_id)
        return {"shards": []}

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

    def install_pose_catalog(self, manifest: dict, *, source_dir: Path) -> dict:
        """Register pose shards. Pending rows stay in the shard files, not SQLite."""
        if not isinstance(manifest, dict) or manifest.get("contract") != "vision-community-pose-catalog-v1":
            raise ServiceError("invalid_catalog")
        lane = manifest.get("lane") or "scene"
        if lane not in UNITS_PER_LOCATION:
            raise ServiceError("invalid_lane")
        source_dir = Path(source_dir)
        shards = manifest.get("shards")
        if not isinstance(shards, list) or not shards:
            raise ServiceError("invalid_catalog")
        installed = 0
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM pose_catalog WHERE lane=?", (lane,))
            for shard in shards:
                name = shard["file"]
                key = shard["key"]
                src = source_dir / name
                if not src.is_file():
                    raise ServiceError("invalid_catalog")
                dest = self.artifacts / key
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read_bytes())
                connection.execute(
                    """INSERT INTO pose_catalog
                       (lane, shard_id, r2_key, row_start, row_count, bytes, sha256)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        lane,
                        int(shard["shardId"]),
                        key,
                        int(shard["rowStart"]),
                        int(shard["rows"]),
                        int(shard["bytes"]),
                        shard["sha256"],
                    ),
                )
                installed += 1
        return {"lane": lane, "shards": installed, "rows": int(manifest.get("totalRows") or 0)}

    def append_pose_catalog(self, manifest: dict, *, source_dir: Path, lanes: tuple[str, ...] | None = None) -> dict:
        if not isinstance(manifest, dict) or manifest.get("contract") != "vision-community-pose-catalog-v1":
            raise ServiceError("invalid_catalog")
        lanes = lanes or (manifest.get("lane") or "scene",)
        source_dir = Path(source_dir)
        shards = manifest.get("shards")
        if not isinstance(shards, list) or not shards:
            raise ServiceError("invalid_catalog")
        installed = 0
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for lane in lanes:
                if lane not in UNITS_PER_LOCATION:
                    raise ServiceError("invalid_lane")
                for shard in shards:
                    name = shard["file"]
                    key = shard["key"]
                    src = source_dir / name
                    if not src.is_file():
                        raise ServiceError("invalid_catalog")
                    dest = self.artifacts / key
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(src.read_bytes())
                    connection.execute(
                        """INSERT OR IGNORE INTO pose_catalog
                           (lane, shard_id, r2_key, row_start, row_count, bytes, sha256)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            lane,
                            int(shard["shardId"]),
                            key,
                            int(shard["rowStart"]),
                            int(shard["rows"]),
                            int(shard["bytes"]),
                            shard["sha256"],
                        ),
                    )
                    installed += 1
        return {"lanes": list(lanes), "shards": installed, "rows": int(manifest.get("totalRows") or 0)}

    def _catalog_order_sql(self) -> str:
        return family_priority_sql("r2_key") + ", shard_id"

    def _part_count(self, connection: sqlite3.Connection, lane: str) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM pose_catalog WHERE lane=?", (lane,)
        ).fetchone()
        return int(row["n"] if row is not None else 0)

    def _part_number(self, connection: sqlite3.Connection, lane: str, shard_id: int) -> int:
        row = connection.execute(
            f"""SELECT COUNT(*) AS n FROM pose_catalog
                WHERE lane=? AND (
                    {family_priority_sql("r2_key")} < (
                        SELECT {family_priority_sql("r2_key")} FROM pose_catalog
                        WHERE lane=? AND shard_id=?
                    )
                    OR (
                        {family_priority_sql("r2_key")} = (
                            SELECT {family_priority_sql("r2_key")} FROM pose_catalog
                            WHERE lane=? AND shard_id=?
                        )
                        AND shard_id <= ?
                    )
                )""",
            (lane, lane, shard_id, lane, shard_id, shard_id),
        ).fetchone()
        return int(row["n"] if row is not None else 0)

    def _work_from_shard(self, connection: sqlite3.Connection, lane: str, shard) -> dict:
        part_count = max(1, self._part_count(connection, lane))
        shard_id = int(shard["shard_id"])
        remaining = max(0, int(shard["row_count"]) - int(shard["next_row"]))
        family = family_for_key(shard["r2_key"])
        payload = describe_part(
            part=self._part_number(connection, lane, shard_id),
            part_count=part_count,
            family=family,
            rows_left=remaining,
            lane=lane,
        )
        payload["shardId"] = shard_id
        return payload

    def _work_status(self, connection: sqlite3.Connection, account_id: str, lane: str) -> dict | None:
        shard = connection.execute(
            f"""SELECT * FROM pose_catalog
                WHERE lane=? AND assignee=? AND next_row < row_count
                ORDER BY {self._catalog_order_sql()} LIMIT 1""",
            (lane, account_id),
        ).fetchone()
        if shard is None:
            part_count = self._part_count(connection, lane)
            if part_count < 1:
                return None
            return {
                "lane": lane,
                "partCount": part_count,
                "separateParts": True,
                "summary": (
                    f"{part_count} separate batches are available. "
                    f"You get your own batch, so other people are not indexing the same "
                    f"{'objects' if lane == 'object' else 'places'}."
                ),
            }
        return self._work_from_shard(connection, lane, shard)

    def _catalog_remaining(self, connection: sqlite3.Connection, lane: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM pose_catalog WHERE lane=? AND next_row < row_count LIMIT 1",
            (lane,),
        ).fetchone()
        return row is not None

    def _shard_by_part(self, connection: sqlite3.Connection, lane: str, part: int):
        return connection.execute(
            f"""SELECT * FROM pose_catalog WHERE lane=?
                ORDER BY {self._catalog_order_sql()} LIMIT 1 OFFSET ?""",
            (lane, part - 1),
        ).fetchone()

    def _claim_shard(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        lane: str,
        shard,
        now: int,
    ):
        stale = now - STEAL_AFTER_SECONDS
        changed = connection.execute(
            """UPDATE pose_catalog
               SET assignee=?, assigned_at=?
               WHERE lane=? AND shard_id=? AND next_row < row_count AND COALESCE(held, 0)=0
                 AND (
                    assignee IS NULL OR assignee=?
                    OR (
                        assigned_at IS NOT NULL AND assigned_at < ?
                        AND NOT EXISTS (
                            SELECT 1 FROM leases
                            WHERE account_id=pose_catalog.assignee AND lane=pose_catalog.lane
                              AND state='active' AND expires_at>?
                        )
                    )
                 )""",
            (account_id, now, lane, shard["shard_id"], account_id, stale, now),
        ).rowcount
        if changed != 1:
            return None
        connection.execute(
            """UPDATE pose_catalog SET assignee=NULL
               WHERE lane=? AND assignee=? AND shard_id!=? AND next_row < row_count""",
            (lane, account_id, shard["shard_id"]),
        )
        return connection.execute(
            "SELECT * FROM pose_catalog WHERE lane=? AND shard_id=?",
            (lane, shard["shard_id"]),
        ).fetchone()

    def _assign_catalog_shard(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        lane: str,
        now: int,
        part: int | None,
    ):
        if part is not None:
            shard = self._shard_by_part(connection, lane, part)
            if shard is None:
                raise ServiceError("invalid_part")
            claimed = self._claim_shard(connection, account_id, lane, shard, now)
            if claimed is None:
                if int(shard["next_row"]) >= int(shard["row_count"]):
                    return self._assign_catalog_shard(connection, account_id, lane, now, None)
                current = shard["assignee"]
                if current and current != account_id:
                    raise ServiceError("part_taken", 409)
                return None
            return claimed
        existing = connection.execute(
            f"""SELECT * FROM pose_catalog
                WHERE lane=? AND assignee=? AND next_row < row_count AND COALESCE(held, 0)=0
                ORDER BY {self._catalog_order_sql()} LIMIT 1""",
            (lane, account_id),
        ).fetchone()
        if existing is not None:
            return existing
        candidates = connection.execute(
            f"""SELECT * FROM pose_catalog
                WHERE lane=? AND next_row < row_count AND COALESCE(held, 0)=0
                ORDER BY {self._catalog_order_sql()}""",
            (lane,),
        ).fetchall()
        for shard in candidates:
            claimed = self._claim_shard(connection, account_id, lane, shard, now)
            if claimed is not None:
                return claimed
        return None

    def _pending_for_shard(
        self,
        connection: sqlite3.Connection,
        lane: str,
        shard_id: int,
        now: int,
        count: int,
    ) -> list:
        return connection.execute(
            """SELECT id, asset_id, capture, lane, model, label, generation, source, rights, attribution,
                      lat, lon, heading, pitch, zoom, country, camera_generation, catalog_shard,
                      state, lease_until
               FROM locations WHERE lane=? AND catalog_shard=? AND COALESCE(queue_state, 'pending')='pending'
                 AND (state='pending' OR (state='leased' AND lease_until<=?))
               ORDER BY id LIMIT ?""",
            (lane, shard_id, now, count),
        ).fetchall()

    def _pending_shared(
        self,
        connection: sqlite3.Connection,
        lane: str,
        now: int,
        count: int,
    ) -> list:
        return connection.execute(
            """SELECT id, asset_id, capture, lane, model, label, generation, source, rights, attribution,
                      lat, lon, heading, pitch, zoom, country, camera_generation, catalog_shard,
                      state, lease_until
               FROM locations WHERE lane=? AND COALESCE(queue_state, 'pending')='pending'
                 AND (state='pending' OR (state='leased' AND lease_until<=?))
               ORDER BY id LIMIT ?""",
            (lane, now, count),
        ).fetchall()

    def _release_exhausted_shard(self, connection: sqlite3.Connection, lane: str, shard_id: int) -> None:
        connection.execute(
            """UPDATE pose_catalog SET assignee=NULL
               WHERE lane=? AND shard_id=? AND next_row >= row_count""",
            (lane, shard_id),
        )

    def _materialize_pose_catalog(
        self,
        connection: sqlite3.Connection,
        lane: str,
        count: int,
        now: int,
        shard,
    ) -> list:
        claimed = []
        attempts = 0
        shard_id = int(shard["shard_id"])
        while len(claimed) < count and attempts < 32:
            attempts += 1
            current = connection.execute(
                "SELECT * FROM pose_catalog WHERE lane=? AND shard_id=?",
                (lane, shard_id),
            ).fetchone()
            if current is None or int(current["next_row"]) >= int(current["row_count"]):
                break
            path = self.artifacts / current["r2_key"]
            data = path.read_bytes() if path.is_file() else b""
            start = int(current["next_byte"])
            if not data or start >= len(data):
                connection.execute(
                    "UPDATE pose_catalog SET next_byte=?, next_row=row_count WHERE lane=? AND shard_id=?",
                    (len(data), lane, shard_id),
                )
                self._release_exhausted_shard(connection, lane, shard_id)
                break
            needed = count - len(claimed)
            chunk = data[start : start + max(8192, needed * 256)]
            text = chunk.decode("utf-8")
            consumed = 0
            jobs = []
            while len(jobs) < needed:
                newline = text.find("\n", consumed)
                if newline < 0:
                    break
                raw = text[consumed:newline]
                consumed = newline + 1
                job = parse_indexer_line(raw, lane=lane)
                if job is not None:
                    jobs.append(job)
            if consumed == 0:
                connection.execute(
                    "UPDATE pose_catalog SET next_row=row_count, next_byte=? WHERE lane=? AND shard_id=?",
                    (len(data), lane, shard_id),
                )
                self._release_exhausted_shard(connection, lane, shard_id)
                break
            changed = connection.execute(
                """UPDATE pose_catalog SET next_byte=next_byte+?, next_row=next_row+?
                   WHERE lane=? AND shard_id=? AND next_byte=?""",
                (consumed, len(jobs), lane, shard_id, start),
            ).rowcount
            if changed != 1:
                continue
            self._release_exhausted_shard(connection, lane, shard_id)
            for job in jobs:
                connection.execute(
                    """INSERT OR IGNORE INTO locations
                       (asset_id, capture, lane, model, label, source, rights, attribution,
                        lat, lon, heading, pitch, zoom, country, camera_generation, queue_state,
                        catalog_shard)
                       VALUES (?, ?, ?, ?, '', 'street-metadata', 'metadata-only-no-imagery',
                               'Panorama metadata only. Imagery is not stored.',
                               ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                    (
                        job["assetId"],
                        job["capture"],
                        job["lane"],
                        job["model"],
                        job["lat"],
                        job["lon"],
                        job.get("heading") or 0,
                        job.get("pitch") or 0,
                        job.get("zoom") or 0,
                        job.get("country") or "",
                        job.get("cameraGeneration") or "",
                        shard_id,
                    ),
                )
                connection.execute(
                    """UPDATE locations SET catalog_shard=?
                       WHERE asset_id=? AND capture=? AND lane=? AND model=? AND catalog_shard IS NULL""",
                    (shard_id, job["assetId"], job["capture"], job["lane"], job["model"]),
                )
                row = connection.execute(
                    """SELECT id, asset_id, capture, lane, model, label, generation, source, rights, attribution,
                              lat, lon, heading, pitch, zoom, country, camera_generation, catalog_shard,
                              state, lease_until, queue_state
                       FROM locations WHERE asset_id=? AND capture=? AND lane=? AND model=?""",
                    (job["assetId"], job["capture"], job["lane"], job["model"]),
                ).fetchone()
                if row is None or row["state"] == "published" or row["queue_state"] == "skipped":
                    continue
                if row["state"] == "leased" and row["lease_until"] and int(row["lease_until"]) > now:
                    continue
                claimed.append(row)
                if len(claimed) >= count:
                    break
        return claimed

    def lease(
        self,
        account_id: str,
        lane: str,
        count: int,
        *,
        now: int | None = None,
        pace: str | None = None,
        client: str | None = None,
        part: int | None = None,
    ) -> dict:
        if lane not in UNITS_PER_LOCATION or type(count) is not int or not 1 <= count <= MAX_LEASE_SIZE:
            raise ServiceError("invalid_lease_request")
        if pace is not None and pace not in {"slow", "medium", "max"}:
            raise ServiceError("invalid_pace")
        if client is not None and client not in {"browser", "cli"}:
            raise ServiceError("invalid_lease_request")
        try:
            requested_part = parse_part(part)
        except ValueError:
            raise ServiceError("invalid_part") from None
        if client is not None:
            count = min(count, lease_cap(lane, pace or "medium", client))
        now = int(time.time()) if now is None else now
        expires_at = now + (CLI_LEASE_SECONDS if client == "cli" else LEASE_SECONDS)
        work = None
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # An expired lease loses its claim before any task can be reassigned.
            connection.execute(
                "UPDATE leases SET state='expired' WHERE state='active' AND expires_at<=?", (now,)
            )
            existing = connection.execute(
                """SELECT * FROM leases
                   WHERE account_id=? AND lane=? AND state='active' AND expires_at>?
                   ORDER BY expires_at DESC LIMIT 1""",
                (account_id, lane, now),
            ).fetchone()
            if existing is not None:
                rows = connection.execute(
                    """SELECT l.* FROM locations l JOIN lease_items i ON i.location_id=l.id
                       WHERE i.lease_id=? ORDER BY l.id""",
                    (existing["id"],),
                ).fetchall()
                items = self._lease_items(rows, {row["id"]: int(row["generation"] or 0) for row in rows})
                payload = {
                    "leaseId": existing["id"],
                    "expiresAt": existing["expires_at"],
                    "pace": existing["pace"] or pace,
                    "resourceBudget": {"slow": 1, "medium": "cpu/2", "max": "all-cores"}.get(existing["pace"] or pace or "medium"),
                    "items": items,
                    "resumed": True,
                }
                work = self._work_status(connection, account_id, lane)
                if work:
                    payload["work"] = work
                return payload
            lease_id = secrets.token_hex(16)
            rows: list = []
            active_shard = None
            if self._catalog_remaining(connection, lane):
                hops = 0
                while len(rows) < count and hops < 32:
                    hops += 1
                    shard = self._assign_catalog_shard(
                        connection, account_id, lane, now, requested_part if hops == 1 else None
                    )
                    if shard is None:
                        break
                    active_shard = shard
                    need = count - len(rows)
                    chunk = list(self._pending_for_shard(connection, lane, int(shard["shard_id"]), now, need))
                    if len(chunk) < need:
                        extra = self._materialize_pose_catalog(connection, lane, need - len(chunk), now, shard)
                        seen = {row["id"] for row in chunk}
                        chunk.extend(row for row in extra if row["id"] not in seen)
                    if not chunk:
                        self._release_exhausted_shard(connection, lane, int(shard["shard_id"]))
                        continue
                    seen = {row["id"] for row in rows}
                    for row in chunk:
                        if row["id"] in seen:
                            continue
                        rows.append(row)
                        seen.add(row["id"])
                        if len(rows) >= count:
                            break
                    current = connection.execute(
                        "SELECT * FROM pose_catalog WHERE lane=? AND shard_id=?",
                        (lane, shard["shard_id"]),
                    ).fetchone()
                    if current is not None:
                        active_shard = current
            else:
                rows = list(self._pending_shared(connection, lane, now, count))
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
            if active_shard is not None:
                latest = connection.execute(
                    "SELECT * FROM pose_catalog WHERE lane=? AND shard_id=?",
                    (lane, active_shard["shard_id"]),
                ).fetchone()
                work = self._work_from_shard(connection, lane, latest or active_shard)
            else:
                work = self._work_status(connection, account_id, lane)
        items = self._lease_items(rows, generation_by_id)
        payload = {
            "leaseId": lease_id,
            "expiresAt": expires_at,
            "pace": pace,
            "resourceBudget": {"slow": 1, "medium": "cpu/2", "max": "all-cores"}.get(pace or "medium"),
            "items": items,
        }
        if work:
            payload["work"] = work
        return payload

    def _lease_items(self, rows, generation_by_id: dict) -> list[dict]:
        items = []
        for row in rows:
            item = {
                "locationId": row["id"],
                "assetId": row["asset_id"],
                "panoId": row["asset_id"],
                "capture": row["capture"],
                "lane": row["lane"],
                "model": row["model"],
                "label": row["label"] if "label" in row.keys() else "",
                "generation": generation_by_id.get(row["id"], int(row["generation"] or 0)),
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
            if row["model"] == MODEL_ID and uses_street_views(row["asset_id"]):
                item["viewStrategy"] = "vision-pano-v1"
            elif row["model"] == MODEL_ID:
                faces = render_faces(row["asset_id"], row["capture"], row["lane"], row["model"])
                item["facesSha256"] = sha256_hex(faces)
            items.append(item)
        return items

    def release_lease(self, account_id: str, lease_id: str, *, now: int | None = None, skip: bool = False) -> dict:
        if not isinstance(lease_id, str) or not lease_id:
            raise ServiceError("invalid_lease_request")
        now = int(time.time()) if now is None else now
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            lease = connection.execute(
                "SELECT * FROM leases WHERE id=? AND account_id=?", (lease_id, account_id)
            ).fetchone()
            if lease is None:
                raise ServiceError("unknown_lease", 404)
            if lease["state"] == "submitted":
                return {"released": 0, "alreadySubmitted": True}
            if skip:
                released = connection.execute(
                    """UPDATE locations SET state='pending', active_lease=NULL, lease_until=NULL,
                       queue_state='skipped' WHERE active_lease=? AND state='leased'""",
                    (lease_id,),
                ).rowcount
            else:
                released = connection.execute(
                    """UPDATE locations SET state='pending', active_lease=NULL, lease_until=NULL
                       WHERE active_lease=? AND state='leased'""",
                    (lease_id,),
                ).rowcount
            connection.execute(
                "UPDATE leases SET state='expired' WHERE id=? AND state='active'", (lease_id,)
            )
        return {"released": int(released or 0), "leaseId": lease_id, "skipped": bool(skip)}

    def renew_lease(self, account_id: str, lease_id: str, *, now: int | None = None) -> dict:
        if not isinstance(lease_id, str) or not lease_id:
            raise ServiceError("invalid_lease_request")
        now = int(time.time()) if now is None else now
        expires_at = now + CLI_LEASE_SECONDS
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            lease = connection.execute(
                "SELECT * FROM leases WHERE id=? AND account_id=?", (lease_id, account_id)
            ).fetchone()
            if lease is None:
                raise ServiceError("unknown_lease", 404)
            if lease["state"] == "submitted":
                return {"renewed": False, "alreadySubmitted": True, "leaseId": lease_id}
            held = connection.execute(
                """SELECT COUNT(*) FROM locations
                   WHERE active_lease=? AND state!='published'""",
                (lease_id,),
            ).fetchone()[0]
            if not held:
                raise ServiceError("expired_lease", 409)
            connection.execute(
                "UPDATE leases SET state='active', expires_at=? WHERE id=?",
                (expires_at, lease_id),
            )
            connection.execute(
                """UPDATE locations SET state='leased', lease_until=?
                   WHERE active_lease=? AND state!='published'""",
                (expires_at, lease_id),
            )
        return {"renewed": True, "expiresAt": expires_at, "leaseId": lease_id}

    def views(self, account_id: str, params: dict) -> dict:
        with self._connection() as connection:
            if connection.execute("SELECT id FROM accounts WHERE id=?", (account_id,)).fetchone() is None:
                raise ServiceError("unauthorized", 401)
        pano = params.get("pano") or params.get("panoId")
        if not isinstance(pano, str) or not 4 <= len(pano) <= 80:
            raise ServiceError("invalid_pano_id")
        if "maps.googleapis.com" in pano or pano.startswith("http"):
            raise ServiceError("imagery_url_forbidden")
        lane = params.get("lane") or "scene"
        if lane not in UNITS_PER_LOCATION:
            raise ServiceError("invalid_lane")
        try:
            heading = float(params.get("heading") or 0)
            pitch = float(params.get("pitch") or 0)
            zoom = float(params.get("zoom") or 0)
        except (TypeError, ValueError) as error:
            raise ServiceError("invalid_pose") from error
        capture = params.get("capture") if isinstance(params.get("capture"), str) and params.get("capture") else "unknown"
        try:
            faces = render_location_faces(
                {
                    "panoId": pano,
                    "capture": capture,
                    "lane": lane,
                    "model": MODEL_ID,
                    "heading": heading,
                    "pitch": pitch,
                    "zoom": zoom,
                }
            )
        except ViewError as error:
            raise ServiceError(error.code, 422) from error
        return {
            "faces": base64.b64encode(faces).decode("ascii"),
            "persistImagery": False,
            "viewStrategy": "vision-pano-v1" if uses_street_views(pano) else "identity-seed",
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
            models = {payload.get("model") for payload in supplied.values()}
            four_view = models == {VISION_FOUR_VIEW_MODEL}
            if VISION_FOUR_VIEW_MODEL in models and not four_view:
                raise ServiceError("invalid_submission")
            verified = {}
            audit = locations_to_recompute(items)
            four_view_key = None
            for row in items:
                if row["state"] != "leased" or row["active_lease"] != lease_id:
                    raise ServiceError("lease_lost", 409)
                payload = supplied[row["id"]]
                if four_view:
                    if row["lane"] != "scene":
                        raise ServiceError("verification_failed", 422)
                    embedding = payload["embedding"]
                    if not valid_four_view_record(embedding):
                        raise ServiceError("verification_failed", 422)
                    digest = sha256_hex(embedding)
                    if not hmac.compare_digest(payload["digest"], digest):
                        raise ServiceError("verification_failed", 422)
                    embed_digest = payload.get("embeddingSha256")
                    if isinstance(embed_digest, str) and not hmac.compare_digest(embed_digest, digest):
                        raise ServiceError("verification_failed", 422)
                    verified[row["id"]] = {
                        "digest": digest,
                        "index_text": "",
                        "embedding": None,
                        "four_view": bytes(embedding),
                    }
                    continue
                if row["model"] == MODEL_ID:
                    try:
                        embedding = verify_output(
                            {key: row[key] for key in row.keys()},
                            payload,
                            recompute=row["id"] in audit,
                        )
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
            if four_view:
                blob = b"".join(verified[row["id"]]["four_view"] for row in items)
                four_view_key = f"four-view-v4/{lease_id}.i8"
                dest = self.artifacts / four_view_key
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob)
            connection.executemany(
                """UPDATE locations SET state='published', active_lease=NULL,
                   lease_until=NULL, output_sha256=?, contributor_id=? WHERE id=?""",
                [(verified[row["id"]]["digest"], account_id, row["id"]) for row in items],
            )
            connection.executemany(
                """INSERT INTO published_index
                   (location_id, index_text, output_sha256, published_at, embedding, four_view_sha256, four_view_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        row["id"],
                        verified[row["id"]]["index_text"],
                        verified[row["id"]]["digest"],
                        now,
                        verified[row["id"]]["embedding"],
                        sha256_hex(verified[row["id"]]["four_view"]) if verified[row["id"]].get("four_view") else None,
                        four_view_key if verified[row["id"]].get("four_view") else None,
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
            view_offset = int(hit.get("viewOffset") or 0) if lane == "scene" else 0
            heading_offset = view_offset * 90
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
                    heading=wrap_heading(heading + heading_offset),
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
                    heading_offset=heading_offset,
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
        view_direction: str | None = None,
        exclude_map: dict | None = None,
        execute: str | None = None,
        prompt: str | None = None,
        description_weight: int | None = None,
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
        direction = normalize_view_direction(view_direction, lane)
        excluded = _exclude_points(exclude_map)
        try:
            prompt_text = parse_prompt(prompt)
        except ValueError as error:
            raise ServiceError("invalid_query") from error
        parsed = None
        if query_map is not None:
            try:
                parsed = parse_map(query_map)
            except MMAError as error:
                if error.code in {"invalid_mma_map", "empty_mma_map"} and prompt_text:
                    parsed = None
                else:
                    raise ServiceError(error.code) from error
        has_json = parsed is not None
        has_prompt = bool(prompt_text)
        visual = query_faces is not None or has_json or has_prompt
        if not visual:
            if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
                raise ServiceError("invalid_query")
        weight = snap_description_weight(description_weight, has_json=has_json, has_prompt=has_prompt)
        query_name = output_name.strip() if isinstance(output_name, str) and output_name.strip() else "VISION Community"
        if has_json:
            query_name = output_name.strip() if isinstance(output_name, str) and output_name.strip() else parsed["name"]
        elif has_prompt and query_name == "VISION Community":
            query_name = prompt_text[:80]
        if visual:
            json_key = ",".join(example["panoId"] for example in parsed["examples"]) if has_json else ""
            prompt_key = f":prompt:{prompt_text}:w{weight}" if has_prompt else ""
            query_key = (
                "mix:"
                + query_name
                + ":"
                + lane
                + ":"
                + direction
                + ":"
                + json_key
                + prompt_key
                + _exclude_key(excluded)
            )
            if query_faces is not None:
                if not isinstance(query_faces, (bytes, bytearray)):
                    raise ServiceError("invalid_query")
                query_key = (
                    "visual:"
                    + sha256_hex(bytes(query_faces))
                    + ":"
                    + lane
                    + ":"
                    + direction
                    + prompt_key
                    + _exclude_key(excluded)
                )
        else:
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
            connection.execute(
                "UPDATE accounts SET units=units-? WHERE id=? AND units>=?",
                (self.search_cost, account_id, self.search_cost),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ServiceError("insufficient_credit", 402)
            execute_local = execute == "local"
            if execute_local:
                if not has_json and not has_prompt:
                    raise ServiceError("invalid_query")
                published = connection.execute(
                    "SELECT COUNT(*) FROM published_index WHERE embedding IS NOT NULL"
                ).fetchone()[0]
                search_id = secrets.token_hex(16)
                result = {
                    "searchId": search_id,
                    "query": query_name,
                    "local": True,
                    "lane": lane,
                    "results": [],
                    "demo": False,
                    "persistImagery": False,
                    "map": None,
                    "published": published,
                }
                connection.execute(
                    "INSERT INTO searches (id, account_id, idempotency_key, query, result_json) VALUES (?, ?, ?, ?, ?)",
                    (search_id, account_id, idempotency_key, query_key, json.dumps(result, separators=(",", ":"))),
                )
                connection.execute(
                    "INSERT INTO ledger (account_id, units, reason, reference) VALUES (?, ?, 'search', ?)",
                    (account_id, -self.search_cost, f"search:{search_id}"),
                )
                return result
            if visual:
                overfetch = candidate_result_count(result_count, max_per_country)
                accept = lambda record: accepts(record, country_mode, selected_countries, selected_generations)
                query_embedding = None
                if query_faces is not None:
                    query_embedding = query_vector(lane, bytes(query_faces))
                if has_json:
                    examples = parsed["examples"]
                    if any(uses_street_views(example["panoId"]) for example in examples):
                        examples = examples[:QUERY_VIEW_CAP]
                    vectors = []
                    for example in examples:
                        row = connection.execute(
                            """SELECT capture FROM locations
                               WHERE asset_id=? AND lane=?
                               ORDER BY CASE WHEN state='published' THEN 0 ELSE 1 END, id
                               LIMIT 1""",
                            (example["panoId"], lane),
                        ).fetchone()
                        capture = row["capture"] if row is not None else example["capture"]
                        try:
                            faces = render_location_faces(
                                {
                                    "panoId": example["panoId"],
                                    "capture": capture,
                                    "lane": lane,
                                    "model": MODEL_ID,
                                    "heading": example.get("heading") or 0,
                                    "pitch": example.get("pitch") or 0,
                                    "zoom": example.get("zoom") or 0,
                                }
                            )
                        except ViewError as error:
                            raise ServiceError(error.code, 422) from error
                        vectors.append(embedding_for(lane, faces))
                    visual_query = mean_embeddings(vectors)
                    query_embedding = visual_query if query_embedding is None else mean_embeddings(
                        [query_embedding, visual_query]
                    )
                if has_prompt:
                    text_query = description_embedding(prompt_text, lane)
                    query_embedding = (
                        mix_embeddings(query_embedding, text_query, weight)
                        if query_embedding is not None
                        else text_query
                    )
                matches = ranked_search_embedding(
                    self.registry,
                    lane,
                    query_embedding,
                    limit=overfetch,
                    accept=accept,
                    view_direction=direction,
                )
                matches = cap_by_country(
                    prune_nearby(exclude_used(matches, excluded)),
                    result_count,
                    max_per_country,
                )
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
                "INSERT INTO searches (id, account_id, idempotency_key, query, result_json) VALUES (?, ?, ?, ?, ?)",
                (search_id, account_id, idempotency_key, query_key, json.dumps(result, separators=(",", ":"))),
            )
            connection.execute(
                "INSERT INTO ledger (account_id, units, reason, reference) VALUES (?, ?, 'search', ?)",
                (account_id, -self.search_cost, f"search:{search_id}"),
            )
            return result
