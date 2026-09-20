"""Lease exclusive catalog batches, process them locally, and submit results.

This talks to a Community server (loopback or the hosted prototype). It runs
community-visual-v1, not the VISION.app sidecar.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse

from .worker import ProcessingWorker


class ContributeError(RuntimeError):
    def __init__(self, code: str, status: int = 0):
        super().__init__(code)
        self.code = code
        self.status = status


def origin_of(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ContributeError("invalid_url")
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


class CommunityClient:
    def __init__(self, url: str, *, token: str | None = None):
        self.origin = origin_of(url)
        self.token = token or ""

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict, str | None]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Origin": self.origin, "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            self.origin + path, data=payload, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                cookie = response.headers.get("Set-Cookie")
                data = json.loads(raw.decode("utf-8")) if raw else {}
                return response.status, data, cookie
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                data = {}
            code = data.get("error") if isinstance(data, dict) else None
            raise ContributeError(str(code or "http_error"), error.code) from error

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

    def lease(self, lane: str, count: int, pace: str) -> dict:
        status, data, _ = self.request("POST", "/api/leases", {"lane": lane, "count": count, "pace": pace})
        if status != 200:
            raise ContributeError("lease_failed", status)
        return data

    def submit(self, lease_id: str, outputs: list[dict]) -> dict:
        status, data, _ = self.request(
            "POST", "/api/submissions", {"leaseId": lease_id, "outputs": outputs}
        )
        if status != 200:
            raise ContributeError("submit_failed", status)
        return data

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
    client: CommunityClient | None = None,
) -> dict:
    if lane not in {"scene", "object"}:
        raise ContributeError("invalid_lane")
    size = 4 if lane == "scene" else 1
    if count is not None:
        size = count
    worker = ProcessingWorker(pace)
    session = client or CommunityClient(url)
    created = None
    if recovery_code:
        session.recover(recovery_code)
    elif not session.token:
        created = session.create_account()
    accepted = 0
    units = 0
    processed_batches = 0
    while True:
        if batches is not None and processed_batches >= batches:
            break
        try:
            lease = session.lease(lane, size, pace)
        except ContributeError as error:
            if error.code == "no_available_work":
                break
            raise
        outputs = worker.as_submission(worker.process_lease(lease))
        result = session.submit(lease["leaseId"], outputs)
        accepted += int(result.get("accepted") or 0)
        units += int(result.get("unitsEarned") or 0)
        processed_batches += 1
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
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--lane", choices=("scene", "object"), default="scene")
    parser.add_argument("--pace", choices=("slow", "medium", "max"), default="medium")
    parser.add_argument("--count", type=int, help="locations per lease (default: 4 scene / 1 object)")
    parser.add_argument("--batches", type=int, help="stop after this many leases; default is until the queue is empty")
    parser.add_argument("--recovery-code", dest="recovery_code")
    args = parser.parse_args()
    try:
        report = contribute(
            url=args.url,
            lane=args.lane,
            pace=args.pace,
            count=args.count,
            batches=args.batches,
            recovery_code=args.recovery_code,
        )
    except ContributeError as error:
        parser.exit(1, f"{error.code}\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
