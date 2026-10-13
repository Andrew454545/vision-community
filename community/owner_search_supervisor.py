"""Inert owner-search supervision; no startup registration or activation.

An approved operator supplies an already configured agent and stop event. A
durable attempt deadline prevents fast retry after restart. This module does
not provision credentials, create accounts, download models or run at import.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import random
import time

from .native_scene_search import plain_path, strict_json
from .owner_search_agent import OwnerSearchError, _exclusive
from .search_snapshot import bounded_read, encoded

MAX_STATE_BYTES = 4096
IDLE_SECONDS = 30
SUCCESS_SECONDS = 5
FIRST_RETRY_SECONDS = 60
MAX_RETRY_SECONDS = 3600
ERRORS = {None, "attempt_interrupted", "connection_unavailable", "native_search_failed", "native_verification_failed",
          "authentication_required", "owner_configuration_required"}


class OwnerSupervisorError(ValueError):
    """Fixed code only; private paths, tokens and upstream errors stay private."""


def _validate(value):
    if (not isinstance(value, dict)
            or set(value) != {"revision", "mode", "nextAttemptAt", "failures", "lastError"}
            or type(value["revision"]) is not int or value["revision"] != 1
            or value["mode"] not in {"ready", "waiting", "blocked"}
            or type(value["nextAttemptAt"]) is not int or not 0 <= value["nextAttemptAt"] <= 253402300799
            or type(value["failures"]) is not int or not 0 <= value["failures"] <= 20
            or value["lastError"] not in ERRORS
            or (value["mode"] == "blocked" and value["lastError"] not in {
                "authentication_required", "owner_configuration_required"})):
        raise OwnerSupervisorError("owner_supervision_state_invalid")
    return value


def _ready():
    return {"revision": 1, "mode": "ready", "nextAttemptAt": 0, "failures": 0, "lastError": None}


class OwnerSearchSupervisor:
    """One durable, paced step, or an explicitly invoked stop-event loop.

    The agent's own lock/outbox remain authoritative. A separate supervisor
    lock prevents competing timers from overwriting retry state. It is never
    held while sleeping. PAUSE/STOP are checked before state or agent access.
    """

    def __init__(self, agent, *, wall_clock=time.time, jitter=random.random, native_failure="native_search_failed"):
        if not callable(getattr(agent, "run_once", None)):
            raise OwnerSupervisorError("invalid_owner_agent")
        self.agent = agent
        self.root = plain_path(Path(agent.state), directory=True)
        self.path = self.root / "supervisor.json"
        self.pending = self.root / "supervisor.pending"
        self.wall_clock, self.jitter = wall_clock, jitter
        if native_failure not in {"native_search_failed", "native_verification_failed"}:
            raise OwnerSupervisorError("invalid_owner_agent")
        self.native_failure = native_failure

    def _now(self):
        value = self.wall_clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 253402290000:
            raise OwnerSupervisorError("owner_clock_invalid")
        return math.floor(value)

    def _delay(self, base):
        value = self.jitter()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise OwnerSupervisorError("owner_pacing_invalid")
        # Additive jitter never undercuts the idle/error minimum or exceeds the
        # one-hour retry cap. No request is made merely to inspect retry state.
        return min(MAX_RETRY_SECONDS, base + math.ceil(base * .25 * value))

    def _marker(self):
        if (self.root / "STOP").exists():
            return "stopped"
        if (self.root / "PAUSE").exists():
            return "paused"
        return None

    def _read(self, path):
        try:
            return _validate(strict_json(bounded_read(plain_path(path), MAX_STATE_BYTES)))
        except (ValueError, OSError, TypeError):
            raise OwnerSupervisorError("owner_supervision_state_invalid") from None

    def _load(self):
        try:
            if self.pending.exists():
                # A complete write can survive a crash before rename. An incomplete
                # write is preserved and stops work; never reset it and poll anyway.
                self._read(self.pending)
                os.replace(self.pending, self.path)
            return self._read(self.path) if self.path.exists() else _ready()
        except OSError:
            raise OwnerSupervisorError("owner_supervision_storage_unavailable") from None

    def _save(self, state):
        raw = encoded(_validate(state))
        try:
            descriptor = os.open(self.pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(self.pending, self.path)
        except OSError:
            raise OwnerSupervisorError("owner_supervision_storage_unavailable") from None

    def _report(self, category):
        # One first fixed-code receipt; neither repeated outages nor months of
        # successful work can grow a diagnostic log or overwrite this evidence.
        try:
            descriptor = os.open(self.root / "supervisor.failure.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded({"success": False, "error": category}))
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            pass
        except OSError:
            raise OwnerSupervisorError("owner_supervision_storage_unavailable") from None

    def _failure(self, state, category, *, blocked=False, minimum_delay=0):
        failures = min(state["failures"] + 1, 20)
        delay = max(self._retry_delay(failures), minimum_delay)
        saved = {"revision": 1, "mode": "blocked" if blocked else "waiting",
                 "nextAttemptAt": self._now() + delay, "failures": failures, "lastError": category}
        self._save(saved)
        self._report(category)
        return {"status": "operator_required" if blocked else "retry_wait", "error": category, "waitSeconds": delay}

    def _retry_delay(self, failures):
        return self._delay(min(MAX_RETRY_SECONDS, FIRST_RETRY_SECONDS * 2 ** min(failures - 1, 6)))

    def resume_after_operator_fix(self):
        """Explicit future operator action; never clears an outbox or failure.

        The current operational cost hold forbids invoking this for live work.
        PAUSE/STOP stay untouched and still win over a cleared connection latch.
        """
        with _exclusive(self.root, name="supervisor.lock"):
            self._load()  # Refuse damaged evidence rather than overwrite it.
            self._save(_ready())

    def step(self):
        marker = self._marker()
        if marker:
            return {"status": marker, "waitSeconds": IDLE_SECONDS}
        try:
            with _exclusive(self.root, name="supervisor.lock"):
                marker = self._marker()
                if marker:
                    return {"status": marker, "waitSeconds": IDLE_SECONDS}
                state, now = self._load(), self._now()
                if state["mode"] == "blocked":
                    return {"status": "operator_required", "error": state["lastError"], "waitSeconds": MAX_RETRY_SECONDS}
                if state["nextAttemptAt"] > now:
                    return {"status": "deferred", "waitSeconds": min(MAX_RETRY_SECONDS, state["nextAttemptAt"] - now)}
                if state["lastError"] == "attempt_interrupted":
                    self._report("attempt_interrupted")
                # Persist a conservative cooldown BEFORE any network/native
                # work. A crash between delivery and saving success cannot
                # reset the timer; the agent still replays its exact outbox.
                failures = min(state["failures"] + 1, 20)
                self._save({"revision": 1, "mode": "waiting", "nextAttemptAt": now + self._retry_delay(failures),
                            "failures": failures, "lastError": "attempt_interrupted"})
                marker = self._marker()
                if marker:
                    # An intentional pause before execution is not a crash.
                    self._save({**state, "mode": "waiting", "nextAttemptAt": now + IDLE_SECONDS})
                    return {"status": marker, "waitSeconds": IDLE_SECONDS}
                try:
                    result = self.agent.run_once()
                except OwnerSearchError as error:
                    if error.status in {401, 403}:
                        return self._failure(state, "authentication_required", blocked=True)
                    if error.code in {"coordinator_unavailable", "owner_agent_busy", "owner_outbox_recovery_required"}:
                        return self._failure(state, "connection_unavailable")
                    return self._failure(state, "owner_configuration_required", blocked=True)
                except Exception:
                    return self._failure(state, "owner_configuration_required", blocked=True)
                if not isinstance(result, dict) or not isinstance(result.get("status"), str) or result["status"] not in {
                    "idle", "completed", "failed", "claim_lost", "paused"
                }:
                    return self._failure(state, "owner_configuration_required", blocked=True)
                minimum_delay = result.get("retryAfterSeconds", 0)
                if type(minimum_delay) is not int or not 0 <= minimum_delay <= MAX_RETRY_SECONDS:
                    return self._failure(state, "owner_configuration_required", blocked=True)
                if result["status"] == "failed":
                    return self._failure(state, self.native_failure, minimum_delay=minimum_delay)
                base = SUCCESS_SECONDS if result["status"] == "completed" else IDLE_SECONDS
                delay = self._delay(max(base, minimum_delay))
                self._save({"revision": 1, "mode": "waiting", "nextAttemptAt": self._now() + delay,
                            "failures": 0, "lastError": None})
                return {"status": result["status"], "waitSeconds": delay}
        except OwnerSearchError as error:
            if error.code == "owner_agent_busy":
                return {"status": "busy", "waitSeconds": IDLE_SECONDS}
            raise OwnerSupervisorError("owner_supervision_storage_unavailable") from None
        except OSError:
            raise OwnerSupervisorError("owner_supervision_storage_unavailable") from None

    def run(self, stop_event):
        """Explicit future activation only. Waits are interruptible; no new task.

        Exits on STOP, external shutdown, corrupt durable state or an operator
        latch. It cannot run while the computer is off; an approved OS startup
        registration is still needed to invoke this loop after login/restart.
        """
        while not stop_event.is_set():
            result = self.step()
            if result["status"] in {"stopped", "operator_required"}:
                return result
            # Short interruptible waits also recheck pause/stop and wall-clock
            # changes. step() does not contact the service before its deadline.
            if stop_event.wait(min(60, result["waitSeconds"])):
                break
        return {"status": "stopped"}
