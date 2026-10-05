"""Lease exclusive catalog batches, process them locally, and submit results.

This talks to a Community server (loopback or the hosted prototype). Street View
thumbnails are fetched on this computer, then discarded. The site is only the
queue, credits, and search desk. This runs community-visual-v1, not VISION.app.

With no --batches limit it keeps going until the queue is empty or you press
Control-C. A failed batch is retried. A place that cannot be read is skipped
so the rest of the queue can continue.
"""

from __future__ import annotations

import argparse
from http.client import HTTPException
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .pano import CLI_LEASE_CAP
from .worker import ProcessingWorker

DEFAULT_URL = "https://vision-community.visioncommunity.workers.dev"
MAX_SERVICE_JSON_BYTES = 8 * 1024 * 1024
SERVICE_BODY_SECONDS = 120
RETRY_STATUSES = {429, 502, 503, 504}
RETRYABLE_CODES = {
    "network_error",
    "lease_failed",
    "submit_failed",
    "expired_lease",
    "lease_lost",
    "http_error",
    "view_unavailable",
    "verification_failed",
    "internal_error",
    "index_unavailable",
    "service_redirect_refused",
    "service_response_limit",
}

# Only published protocol reasons may become exceptions, CLI output or reports.
# A service/proxy can return arbitrary JSON here, including reflected private
# request text. Preserve the HTTP status but never copy an unknown error value.
SERVICE_ERROR_CODES = frozenset({
    "http_error", "lease_failed", "renew_failed", "search_failed", "verification_failed",
    "account_changed", "control_plane_unprovisioned", "cross_origin_request",
    "expired_lease", "idempotency_conflict", "imagery_url_forbidden",
    "incomplete_submission", "index_unavailable", "ingest_not_started",
    "insufficient_credit", "internal_error", "invalid_batch", "invalid_camera_filter",
    "invalid_catalog", "invalid_country_filter", "invalid_fixture", "invalid_idempotency_key",
    "invalid_index", "invalid_json", "invalid_lane", "invalid_lease_request", "invalid_mma_map",
    "invalid_object_coverage", "invalid_pace", "invalid_pano_id", "invalid_part", "invalid_pose",
    "invalid_query", "invalid_recovery", "invalid_submission", "lease_lost", "no_available_work",
    "not_found", "object_coverage_required", "object_coverage_requires_official_gen4",
    "object_index_required", "object_verification_unavailable", "online_search_required",
    "part_taken", "real_source_not_enabled", "rate_limited", "rate_limit_unavailable",
    "scene_audit_backlog", "scene_device_not_qualified", "scene_device_qualification_required",
    "scene_qualification_changed", "scene_qualification_rejected", "scene_qualification_required",
    "scene_reference_not_approved", "scene_reference_pool_unprepared", "scene_reference_required",
    "scene_submission_rejected", "scene_verification_unavailable", "scene_verifier_unavailable",
    "schema_update_required", "service_maintenance", "unauthorized", "unknown_lease",
    "unknown_search", "unknown_submission", "unsupported_model", "view_unavailable",
})


def service_error_code(data, fallback="http_error"):
    code = data.get("error") if isinstance(data, dict) else None
    if isinstance(code, str) and code in SERVICE_ERROR_CODES:
        return code
    return fallback if fallback in SERVICE_ERROR_CODES else "http_error"


class ContributeError(RuntimeError):
    def __init__(self, code: str, status: int = 0):
        super().__init__(code)
        self.code = code
        self.status = status


class _RefuseServiceRedirects(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        # Community API replies must come directly from the configured origin.
        # Do not forward account credentials or turn a POST into a redirected GET.
        try:
            fp.close()
        finally:
            raise ContributeError("service_redirect_refused", 503)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def read_service_json(response) -> bytes:
    """Bound reply memory and elapsed body reads, without trusting headers.

    The budget is checked between available fragments. Connection/header parsing
    and an individual blocked read remain subject to the existing socket timeout.
    """
    declared = response.headers.get("Content-Length")
    try:
        declared = int(declared) if declared is not None else None
    except (TypeError, ValueError):
        declared = None
    if declared is not None and not 0 <= declared <= MAX_SERVICE_JSON_BYTES:
        raise ContributeError("service_response_limit", 503)
    deadline = time.monotonic() + SERVICE_BODY_SECONDS
    body = bytearray()
    read = getattr(response, "read1", response.read)
    while True:
        if time.monotonic() >= deadline:
            raise ContributeError("service_response_limit", 503)
        fragment = read(min(64 * 1024, MAX_SERVICE_JSON_BYTES + 1 - len(body)))
        if not fragment:
            if declared is not None and len(body) != declared:
                raise HTTPException("Incomplete service reply")
            return bytes(body)
        body.extend(fragment)
        if len(body) > MAX_SERVICE_JSON_BYTES:
            raise ContributeError("service_response_limit", 503)


def origin_of(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ContributeError("invalid_url")
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def default_session_path() -> Path:
    override = os.environ.get("VISION_COMMUNITY_SESSION")
    if override:
        return Path(override)
    return Path.home() / ".config" / "vision-community" / "session.json"


def load_session(path: Path, url: str) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    stored = payload.get("url")
    if isinstance(stored, str) and origin_of(stored) != origin_of(url):
        return None
    return payload


def save_session(path: Path, *, url: str, account_id: str | None, recovery_code: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": origin_of(url),
        "accountId": account_id,
        "recoveryCode": recovery_code,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def require_street_decoder() -> None:
    try:
        from PIL import Image  # noqa: F401
    except ImportError as error:
        raise ContributeError("install_pillow") from error


class CommunityClient:
    def __init__(self, url: str, *, token: str | None = None):
        self.origin = origin_of(url)
        self.token = token or ""
        # An instance-local opener preserves default TLS/proxy handling without
        # changing urllib globally or sharing credentials between clients.
        self.opener = urllib.request.build_opener(_RefuseServiceRedirects())

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict, str | None]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Origin": self.origin,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "VISION-Community-contribute/1",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            self.origin + path, data=payload, headers=headers, method=method
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self.opener.open(request, timeout=120) as response:
                    raw = read_service_json(response)
                    cookie = response.headers.get("Set-Cookie")
                    data = json.loads(raw.decode("utf-8")) if raw else {}
                    return response.status, data, cookie
            except urllib.error.HTTPError as error:
                try:
                    raw = read_service_json(error)
                except (HTTPException, OSError, TimeoutError, ContributeError):
                    # A broken error body must not hide a definitive HTTP
                    # status (such as a revoked account's 401 or rejection).
                    raw = b""
                finally:
                    error.close()
                try:
                    data = json.loads(raw.decode("utf-8")) if raw else {}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    data = {}
                if error.code in RETRY_STATUSES and attempt < 2:
                    last_error = error
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise ContributeError(service_error_code(data), error.code) from error
            except (urllib.error.URLError, TimeoutError, OSError, HTTPException,
                    json.JSONDecodeError, UnicodeDecodeError) as error:
                last_error = error
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise ContributeError("network_error") from error
        raise ContributeError("network_error") from last_error

    def create_account(self) -> dict:
        status, data, cookie = self.request("POST", "/api/accounts", {})
        if status not in {200, 201} or not isinstance(data, dict):
            raise ContributeError("account_failed", status)
        self._apply_session(cookie)
        return data

    def recover(self, recovery_code: str) -> dict:
        status, data, cookie = self.request("POST", "/api/recovery", {"recoveryCode": recovery_code})
        if status != 200 or not isinstance(data, dict):
            raise ContributeError("recovery_failed", status)
        self._apply_session(cookie)
        return data

    def me(self) -> dict:
        status, data, _ = self.request("GET", "/api/me")
        if status != 200 or not isinstance(data, dict):
            raise ContributeError("unauthorized", status)
        return data

    def lease(self, lane: str, count: int, pace: str, *, part: int | None = None) -> dict:
        body = {"lane": lane, "count": count, "pace": pace, "client": "cli"}
        if part is not None:
            body["part"] = part
        status, data, _ = self.request(
            "POST",
            "/api/leases",
            body,
        )
        if status != 200:
            raise ContributeError(service_error_code(data, "lease_failed"), status)
        return data

    def submit(self, lease_id: str, outputs: list[dict]) -> dict:
        status, data, _ = self.request(
            "POST", "/api/submissions", {"leaseId": lease_id, "outputs": outputs}
        )
        if status != 200:
            raise ContributeError("submit_failed", status)
        return data

    def submit_object(self, lease_id: str, outputs: list[dict], object_index: dict) -> dict:
        status, data, _ = self.request(
            "POST",
            "/api/submissions",
            {"leaseId": lease_id, "outputs": outputs, "objectIndex": object_index},
        )
        if status != 200:
            raise ContributeError("submit_failed", status)
        return data

    def release(self, lease_id: str, *, skip: bool = False) -> dict:
        status, data, _ = self.request("POST", "/api/leases/release", {"leaseId": lease_id, "skip": skip})
        if status != 200:
            raise ContributeError("release_failed", status)
        return data

    def renew(self, lease_id: str) -> dict:
        status, data, _ = self.request("POST", "/api/leases/renew", {"leaseId": lease_id})
        if status != 200:
            raise ContributeError(service_error_code(data, "renew_failed"), status)
        return data

    def authorize_local_search(self, body: dict) -> dict:
        payload = dict(body)
        payload["execute"] = "local"
        status, data, _ = self.request("POST", "/api/searches", payload)
        if status == 402:
            raise ContributeError("insufficient_credit", status)
        if status != 200 or not isinstance(data, dict):
            raise ContributeError(service_error_code(data, "search_failed"), status)
        return data

    def published_snapshot(self, *, search_id: str, lane: str, after: int = 0, limit: int = 250) -> dict:
        query = urllib.parse.urlencode(
            {"searchId": search_id, "lane": lane, "after": after, "limit": limit}
        )
        status, data, _ = self.request("GET", f"/api/published-snapshot?{query}")
        if status != 200 or not isinstance(data, dict):
            raise ContributeError("index_unavailable", status)
        return data

    def object_index_catalog(self, search_id: str) -> dict:
        query = urllib.parse.urlencode({"searchId": search_id})
        status, data, _ = self.request("GET", f"/api/object-indexes?{query}")
        if status != 200 or not isinstance(data, dict):
            raise ContributeError("index_unavailable", status)
        return data

    def object_index_file(self, search_id: str, key: str) -> bytes:
        query = urllib.parse.urlencode({"searchId": search_id, "key": key})
        request = urllib.request.Request(
            self.origin + f"/api/object-index-file?{query}",
            headers={
                "Origin": self.origin,
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "VISION-Community-contribute/1",
            },
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise ContributeError("index_unavailable", error.code) from error

    def scene_index_catalog(self, search_id: str) -> dict:
        query = urllib.parse.urlencode({"searchId": search_id})
        status, data, _ = self.request("GET", f"/api/scene-indexes?{query}")
        if status != 200 or not isinstance(data, dict):
            raise ContributeError("index_unavailable", status)
        return data

    def scene_index_file(self, search_id: str, key: str) -> bytes:
        query = urllib.parse.urlencode({"searchId": search_id, "key": key})
        request = urllib.request.Request(
            self.origin + f"/api/scene-index-file?{query}",
            headers={
                "Origin": self.origin,
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "VISION-Community-contribute/1",
            },
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise ContributeError("index_unavailable", error.code) from error

    def index_manifest(self, *, search_id: str, lane: str) -> dict:
        query = urllib.parse.urlencode({"searchId": search_id, "lane": lane})
        status, data, _ = self.request("GET", f"/api/index-manifest?{query}")
        if status == 404:
            return {"shards": []}
        if status != 200 or not isinstance(data, dict):
            raise ContributeError("index_unavailable", status)
        return data

    def index_shard(self, *, search_id: str, key: str) -> bytes:
        query = urllib.parse.urlencode({"searchId": search_id, "key": key})
        path = f"/api/index-shard?{query}"
        headers = {
            "Origin": self.origin,
            "Accept": "application/octet-stream",
            "User-Agent": "VISION-Community-contribute/1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.origin + path, headers=headers, method="GET")
        try:
            with self.opener.open(request, timeout=120) as response:
                if response.status != 200:
                    raise ContributeError("index_unavailable", response.status)
                return response.read()
        except urllib.error.HTTPError as error:
            raise ContributeError("index_unavailable", error.code) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ContributeError("network_error") from error

    def fetch_views(self, item: dict) -> bytes:
        query = urllib.parse.urlencode(
            {
                "pano": item.get("panoId") or item["assetId"],
                "capture": item.get("capture") or "",
                "lane": item.get("lane") or "scene",
                "heading": item.get("heading") or 0,
                "pitch": item.get("pitch") or 0,
                "zoom": item.get("zoom") or 0,
            }
        )
        status, data, _ = self.request("GET", f"/api/views?{query}")
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get("faces"), str):
            raise ContributeError("view_unavailable", status)
        try:
            import base64

            return base64.b64decode(data["faces"])
        except (ValueError, TypeError) as error:
            raise ContributeError("view_unavailable", status) from error

    def _apply_session(self, cookie: str | None) -> None:
        if not cookie:
            return
        for part in cookie.split(";"):
            if part.strip().startswith("vision_session="):
                self.token = part.strip().split("=", 1)[1]
                return


def contribute(
    *,
    url: str,
    lane: str = "scene",
    pace: str = "medium",
    count: int | None = None,
    batches: int | None = None,
    recovery_code: str | None = None,
    part: int | None = None,
    client: CommunityClient | None = None,
    session_path: Path | None = None,
    persist_session: bool = False,
    progress=None,
) -> dict:
    if lane == "object":
        raise ContributeError("use_object_index")
    if lane != "scene":
        raise ContributeError("invalid_lane")
    size = CLI_LEASE_CAP[lane][pace]
    if count is not None:
        size = count
    session = client or CommunityClient(url)
    stored = load_session(session_path, url) if session_path is not None else None
    if not recovery_code:
        recovery_code = os.environ.get("VISION_COMMUNITY_RECOVERY") or None
    if not recovery_code and stored:
        code = stored.get("recoveryCode")
        recovery_code = code if isinstance(code, str) and code else None
    # Fetch Street View on this machine. Do not proxy thumbnails through the site.
    worker = ProcessingWorker(pace)
    created = None
    recovered = None
    if recovery_code:
        recovered = session.recover(recovery_code)
    elif not session.token:
        created = session.create_account()
        recovery_code = created.get("recoveryCode") if isinstance(created, dict) else None
    if persist_session and session_path is not None and recovery_code:
        account_id = None
        if created:
            account_id = created.get("accountId")
        elif recovered:
            account_id = recovered.get("accountId")
        save_session(session_path, url=url, account_id=account_id, recovery_code=recovery_code)
    accepted = 0
    units = 0
    processed_batches = 0
    lease = None
    stalls = 0
    batch_failures = 0
    try:
        while True:
            if batches is not None and processed_batches >= batches:
                break
            try:
                lease = session.lease(lane, size, pace, part=part)
            except ContributeError as error:
                if error.code == "no_available_work":
                    lease = None
                    break
                if batches is not None or error.code not in RETRYABLE_CODES:
                    raise
                stalls += 1
                print(f"still indexing; retrying after {error.code}", file=sys.stderr, flush=True)
                time.sleep(min(60, stalls * 2))
                continue
            stalls = 0
            try:
                outputs = worker.as_submission(
                    worker.process_lease(
                        lease,
                        progress=progress,
                    )
                )
                result = session.submit(lease["leaseId"], outputs)
            except Exception as error:
                code = error.code if isinstance(error, ContributeError) else ""
                skip = batch_failures >= 2 and code in {"", "view_unavailable", "verification_failed"}
                try:
                    session.release(lease["leaseId"], skip=skip)
                except ContributeError:
                    pass
                lease = None
                if batches is not None:
                    raise
                batch_failures += 1
                stalls += 1
                print("still indexing; the last batch will be tried again", file=sys.stderr, flush=True)
                time.sleep(min(60, stalls * 2))
                continue
            batch_failures = 0
            accepted += int(result.get("accepted") or 0)
            units += int(result.get("unitsEarned") or 0)
            processed_batches += 1
            if progress is not None:
                progress(
                    processed_batches,
                    processed_batches,
                    {
                        "event": "batch",
                        "accepted": int(result.get("accepted") or 0),
                        "unitsEarned": int(result.get("unitsEarned") or 0),
                    },
                )
            lease = None
    except KeyboardInterrupt:
        if lease is not None:
            try:
                session.release(lease["leaseId"])
            except ContributeError:
                pass
        raise
    report = {
        "ok": True,
        "lane": lane,
        "pace": pace,
        "batches": processed_batches,
        "accepted": accepted,
        "unitsEarned": units,
    }
    if created is not None:
        report["accountId"] = created.get("accountId")
        report["recoveryCode"] = created.get("recoveryCode")
    try:
        me = session.me()
        report["units"] = int(me.get("units") or 0)
        cost = int(me.get("searchCost") or 100000)
        report["searchCost"] = cost
        report["unitsRemainingToSearch"] = max(0, cost - int(me.get("units") or 0))
        report["searchesAvailable"] = int(me.get("searchesAvailable") or 0)
    except ContributeError:
        pass
    return report


def _stderr_progress(index: int, total: int, item: dict) -> None:
    if item.get("event") == "batch":
        print(
            f"batch {index}: +{item.get('accepted') or 0} locations, +{item.get('unitsEarned') or 0} units",
            file=sys.stderr,
            flush=True,
        )
        return
    identity = item.get("panoId") or item.get("assetId") or item.get("locationId") or ""
    print(f"{index}/{total} {identity}", file=sys.stderr, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--lane", choices=("scene",), default="scene")
    parser.add_argument("--pace", choices=("slow", "medium", "max"), default="medium")
    parser.add_argument("--count", type=int, help="locations per lease (default: 16/64/128 scene, 8/32/64 object)")
    parser.add_argument("--batches", type=int, help="stop after this many leases; default is until the queue is empty")
    parser.add_argument("--part", type=int, help="1-based catalog batch to exclusive-lease; default is the next free batch")
    parser.add_argument("--recovery-code", dest="recovery_code")
    parser.add_argument("--session-file", type=Path, dest="session_file")
    parser.add_argument("--no-save-session", action="store_true")
    args = parser.parse_args()
    try:
        require_street_decoder()
        session_path = args.session_file or default_session_path()
        report = contribute(
            url=args.url,
            lane=args.lane,
            pace=args.pace,
            count=args.count,
            batches=args.batches,
            recovery_code=args.recovery_code,
            part=args.part,
            session_path=session_path,
            persist_session=not args.no_save_session,
            progress=_stderr_progress,
        )
    except ContributeError as error:
        hint = "python3 -m pip install -r requirements.txt\n" if error.code == "install_pillow" else ""
        parser.exit(1, f"{hint}{error.code}\n")
    except KeyboardInterrupt:
        parser.exit(130, "interrupted\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
