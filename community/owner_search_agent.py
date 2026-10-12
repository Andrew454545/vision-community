"""Outbound owner search transport; inert until an operator invokes it.

Reuse independently pinned native engines, each exposing search(request,
raw_query=bytes). No inbound listener, scheduler, download or activation is
installed here. The gateway alone verifies membership and settles credits.
"""
from __future__ import annotations

from contextlib import contextmanager
import http.client
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from .native_scene_search import plain_path, query_bytes, strict_json
from .search_snapshot import bounded_read, encoded

MAX_REPLY = 1024 * 1024 + 8192
ID = re.compile(r"[0-9a-f]{32}\Z")
TOKEN = re.compile(r"[0-9a-f]{64}\Z")
ROUTES = {"claim", "complete", "fail"}


class OwnerSearchError(ValueError):
    def __init__(self, code, status=None):
        super().__init__(code)
        self.code, self.status = code, status


class HTTPSCoordinator:
    """Operator-selected exact HTTPS origin; no redirects/proxy credential forwarding."""

    def __init__(self, origin: str, secret: str):
        parts = urlsplit(origin)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.port not in (None, 443) or parts.path not in ("", "/") or parts.query or parts.fragment
                or not isinstance(secret, str) or not TOKEN.fullmatch(secret)):
            raise OwnerSearchError("invalid_owner_connection")
        self.host, self.secret = parts.hostname, secret

    @classmethod
    def from_os_credentials(cls, origin):
        # Explicit future operator action only. No secret in CLI arguments,
        # environment or project configuration; no OS vault enumeration.
        from .owner_search_credentials import canonical_origin, read_owner_search_secret
        try:
            origin = canonical_origin(origin)
            return cls(origin, read_owner_search_secret(origin))
        except Exception:
            raise OwnerSearchError("owner_credentials_unavailable") from None

    def post(self, action, value):
        if action not in ROUTES:
            raise OwnerSearchError("invalid_owner_route")
        raw = encoded(value)
        if len(raw) > MAX_REPLY:
            raise OwnerSearchError("owner_payload_limit")
        connection = http.client.HTTPSConnection(self.host, port=443, timeout=30)
        try:
            connection.request("POST", "/api/search-agent/" + action, body=raw,
                               headers={"Authorization": "Bearer " + self.secret,
                                        "Content-Type": "application/json", "Accept": "application/json"})
            response = connection.getresponse()
            # Claim is a 64 KiB query plus envelope. Acks/errors are tiny.
            limit = 81920 if action == "claim" else 4096
            payload = response.read(limit + 1)
            if len(payload) > limit:
                raise OwnerSearchError("owner_reply_limit")
            document = strict_json(payload)
            if not isinstance(document, dict):
                raise OwnerSearchError("invalid_owner_reply")
            if response.status != 200:
                # Never echo an arbitrary upstream error body, URL or credential.
                code = "coordinator_unavailable"
                if response.status == 409:
                    if document.get("error") == "search_claim_lost":
                        code = "search_claim_lost"
                    elif document.get("error") in {"search_binding_required", "search_binding_changed"}:
                        code = "owner_binding_configuration_required"
                raise OwnerSearchError(code, response.status)
            return document
        except OwnerSearchError:
            raise
        except Exception:
            raise OwnerSearchError("coordinator_unavailable") from None
        finally:
            connection.close()


@contextmanager
def _exclusive(root, *, name="agent.lock"):
    if name not in {"agent.lock", "supervisor.lock"}:
        raise OwnerSearchError("invalid_owner_lock")
    path = root / name
    if path.exists():
        plain_path(path)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+b") as guard:
        if os.fstat(guard.fileno()).st_size == 0:
            guard.write(b"\0")
            guard.flush()
        guard.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise OwnerSearchError("owner_agent_busy") from None
        try:
            yield
        finally:
            guard.seek(0)
            if os.name == "nt":
                msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(guard, fcntl.LOCK_UN)


class OwnerSearchAgent:
    """One finite step per call. A future approved supervisor supplies pacing.

    The private outbox contains at most one completion/failure. It is replayed
    before claiming more work. Queries stay in memory/native temporary scratch;
    no prompt, account code or exception detail enters a diagnostic report.
    """

    def __init__(self, coordinator, engines: dict, state: Path, *, bindings=None):
        if (not isinstance(engines, dict) or not engines or set(engines) - {"scene", "object"}
                or any(not callable(getattr(engine, "search", None)) for engine in engines.values())):
            raise OwnerSearchError("invalid_owner_engines")
        self.coordinator, self.engines = coordinator, dict(engines)
        self.bindings = self._bindings(bindings, set(engines)) if bindings is not None else None
        self.state = plain_path(Path(state), directory=True)
        self.outbox = self.state / "outbox.json"
        self.pending = self.state / "outbox.pending"

    @staticmethod
    def _bindings(value, lanes):
        if not isinstance(value, dict) or set(value) != lanes:
            raise OwnerSearchError("invalid_owner_bindings")
        saved = {}
        for lane, pin in value.items():
            if (not isinstance(pin, dict) or set(pin) != {
                    "contractVersion", "policyId", "runtimeSha256", "snapshotSha256"}
                    or type(pin["contractVersion"]) is not int or pin["contractVersion"] != 2
                    or not isinstance(pin["policyId"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", pin["policyId"])
                    or any(not isinstance(pin[key], str) or not TOKEN.fullmatch(pin[key])
                           for key in ("runtimeSha256", "snapshotSha256"))):
                raise OwnerSearchError("invalid_owner_bindings")
            saved[lane] = dict(pin)
        return saved

    def _report(self, code):
        # Finite allowlist and first evidence only; failures cannot grow logs.
        if code not in {"owner_search_failed", "owner_outbox_incomplete"}:
            code = "owner_search_failed"
        try:
            descriptor = os.open(self.state / ("failure-" + code + ".json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded({"success": False, "error": code}))
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            pass

    @staticmethod
    def _validate_outbox(document):
        if (not isinstance(document, dict) or set(document) != {"action", "body"}
                or document["action"] not in {"complete", "fail"} or not isinstance(document["body"], dict)):
            raise OwnerSearchError("invalid_owner_outbox")
        body = document["body"]
        keys = {"jobId", "claimToken", "result"} if document["action"] == "complete" else {"jobId", "claimToken"}
        if (set(body) != keys or not isinstance(body.get("jobId"), str) or not ID.fullmatch(body["jobId"])
                or not isinstance(body.get("claimToken"), str) or not TOKEN.fullmatch(body["claimToken"])
                or (document["action"] == "complete" and not isinstance(body.get("result"), dict))):
            raise OwnerSearchError("invalid_owner_outbox")
        return document

    def _save(self, action, body):
        raw = encoded(self._validate_outbox({"action": action, "body": body}))
        if len(raw) > MAX_REPLY:
            raise OwnerSearchError("owner_payload_limit")
        # With the writer lock, a leftover pending file means recovery is needed.
        descriptor = os.open(self.pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(self.pending, self.outbox)

    def _recover_pending(self):
        if not self.pending.exists():
            return
        plain_path(self.pending)
        if self.outbox.exists():
            raise OwnerSearchError("invalid_owner_outbox")
        try:
            self._validate_outbox(strict_json(bounded_read(self.pending, MAX_REPLY)))
        except ValueError:
            # No network delivery happened before the rename. Preserve a fixed
            # failure receipt, erase partial private scratch, allow lease retry.
            self._report("owner_outbox_incomplete")
            self.pending.unlink()
            return
        os.replace(self.pending, self.outbox)

    def _deliver(self):
        document = self._validate_outbox(strict_json(bounded_read(plain_path(self.outbox), MAX_REPLY)))
        try:
            reply = self.coordinator.post(document["action"], document["body"])
            wanted = "completed" if document["action"] == "complete" else "failed"
            if (reply.get(wanted) is not True or (wanted == "completed" and reply.get("searchId") != document["body"]["jobId"])
                    or (wanted == "failed" and reply.get("charged") is not False)):
                raise OwnerSearchError("invalid_owner_reply")
            status = wanted
        except OwnerSearchError as error:
            if error.code != "search_claim_lost" or error.status != 409:
                raise  # Outage/quota/auth/ambiguous reply: keep exact outbox.
            status = "claim_lost"  # Cancellation, deletion or expired/replaced claim.
        self.outbox.unlink()
        return {"status": status}

    def run_once(self):
        if any((self.state / marker).exists() for marker in ("PAUSE", "STOP")):
            return {"status": "paused"}
        with _exclusive(self.state):
            if any((self.state / marker).exists() for marker in ("PAUSE", "STOP")):
                return {"status": "paused"}
            self._recover_pending()
            if self.outbox.exists():
                return self._deliver()
            reply = self.coordinator.post("claim", {"lanes": sorted(self.engines),
                **({"bindings": self.bindings} if self.bindings is not None else {})})
            job = reply.get("job")
            if job is None:
                if set(reply) != {"job", "retryAfterSeconds"} or reply["retryAfterSeconds"] != 30:
                    raise OwnerSearchError("invalid_owner_reply")
                return {"status": "idle", "retryAfterSeconds": 30}
            if (not isinstance(job, dict) or set(job) != {"jobId", "claimToken", "claimUntil", "expiresAt", "requestJson"}
                    or not isinstance(job.get("jobId"), str) or not ID.fullmatch(job["jobId"])
                    or not isinstance(job.get("claimToken"), str) or not TOKEN.fullmatch(job["claimToken"])
                    or not isinstance(job.get("requestJson"), str) or len(job["requestJson"].encode("utf-8")) > 81920
                    or type(job.get("claimUntil")) is not int or type(job.get("expiresAt")) is not int
                    or not 0 < job["claimUntil"] <= job["expiresAt"]):
                raise OwnerSearchError("invalid_owner_reply")
            body = {"jobId": job["jobId"], "claimToken": job["claimToken"]}
            try:
                raw = job["requestJson"].encode("utf-8")
                request = strict_json(raw)
                lane = request["query"]["lane"]
                engine = self.engines[lane]
                if self.bindings is not None and {key: request.get(key) for key in self.bindings[lane]} != self.bindings[lane]:
                    raise OwnerSearchError("invalid_owner_binding")
                result = engine.search(request, raw_query=query_bytes(raw))
                # Never retain an engine's echoed prompt; the contract excludes query.
                if not isinstance(result, dict) or set(result) != {
                    "contractVersion", "policyId", "runtimeSha256", "snapshotSha256", "requestSha256", "processedLocations", "hits"
                } or len(encoded(result)) > 1024 * 1024:
                    raise OwnerSearchError("invalid_owner_result")
                if self.bindings is not None and ({key: result.get(key) for key in self.bindings[lane]} != self.bindings[lane]
                        or result.get("requestSha256") != request.get("requestSha256")):
                    raise OwnerSearchError("invalid_owner_binding")
                self._save("complete", {**body, "result": result})
            except Exception:
                # A disk write may have completed before acknowledgement failed;
                # keep that saved completion instead of replacing it with failure.
                if self.outbox.exists() or self.pending.exists():
                    raise OwnerSearchError("owner_outbox_recovery_required") from None
                self._report("owner_search_failed")
                self._save("fail", body)
            if any((self.state / marker).exists() for marker in ("PAUSE", "STOP")):
                return {"status": "paused"}
            return self._deliver()
