"""Unattended scene contributor. Uses no AI service or Codex check-ins.

Run only after opting into downloads, live imagery, and Community contributions.
The trusted service still decides whether this PC and its results are approved.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import json
import math
import os
from pathlib import Path
import shutil
import threading
import time

from .contribute import DEFAULT_URL, RETRY_STATUSES, ContributeError, load_session, save_session
from .desktop import DesktopApp, DesktopClient, DesktopError
from .vision_index import RETRYABLE_NATIVE_CODES, VisionIndexError

WAIT_SECONDS = 1800
MIN_FREE_BYTES = 5 * 1024**3
PACES = ("slow", "medium", "max", "pause")
RECOVERABLE_QUEUE_ERRORS = frozenset({"expired_lease", "lease_lost", "unknown_lease"})
TERMINAL_SERVICE_ERRORS = frozenset({
    "verification_failed", "scene_qualification_rejected", "scene_device_not_qualified",
    "scene_submission_rejected", "scene_reference_required", "unauthorized", "recovery_failed",
    "scene_qualification_changed", "scene_device_qualification_required", "scene_qualification_required",
})
TRANSIENT_HTTP_CODES = frozenset({
    "http_error", "lease_failed", "submit_failed", "internal_error", "index_unavailable",
    "rate_limited", "control_plane_unprovisioned", "scene_verifier_unavailable",
    "scene_verification_unavailable",
})


def clock_minutes(value):
    try:
        if (not isinstance(value, str) or len(value) != 5 or value[2] != ":" or not (value[:2] + value[3:]).isascii()
                or not (value[:2] + value[3:]).isdigit()):
            raise ValueError
        hour, minute = int(value[:2]), int(value[3:])
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError
        return hour * 60 + minute
    except (TypeError, ValueError):
        raise ValueError("Use a time such as 08:00 or 22:00 (24-hour clock).") from None


@dataclass(frozen=True)
class ProcessingSchedule:
    day_pace: str = "medium"
    night_pace: str = "max"
    day_start: str = "08:00"
    night_start: str = "22:00"

    def __post_init__(self):
        if self.day_pace not in PACES or self.night_pace not in PACES:
            raise ValueError("Choose slow, medium, max or pause.")
        if clock_minutes(self.day_start) == clock_minutes(self.night_start):
            raise ValueError("Day and night must start at different times.")

    def pace_at(self, now):
        # Use the computer's local wall clock; DST and timezone changes apply
        # at the next batch boundary, without assuming every day is 24 hours.
        minute = now.hour * 60 + now.minute
        day, night = clock_minutes(self.day_start), clock_minutes(self.night_start)
        daytime = (minute - day) % 1440 < (night - day) % 1440
        return self.day_pace if daytime else self.night_pace

    def public_settings(self):
        return {"dayPace": self.day_pace, "nightPace": self.night_pace,
                "dayStart": self.day_start, "nightStart": self.night_start,
                "clock": "computer-local"}


class WorkerAlreadyRunning(BlockingIOError):
    """Only a conflicting lock, not an unrelated filesystem failure."""


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    with pending.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    pending.replace(path)


@contextmanager
def single_instance(root):
    # Same lock as the guided application, so the two cannot claim work together.
    with (root / "desktop.lock").open("a+b") as guard:
        if os.name == "nt":
            import msvcrt
            if guard.seek(0, os.SEEK_END) == 0:
                guard.write(b"0")
                guard.flush()
            guard.seek(0)
            try:
                msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
            except (BlockingIOError, PermissionError) as error:
                raise WorkerAlreadyRunning("The folder is already in use") from error
        else:
            import fcntl
            try:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise WorkerAlreadyRunning("The folder is already in use") from error
        yield


@contextmanager
def keep_awake(enabled=True):
    """Inhibit idle sleep during work or pacing rests; never change the power plan."""
    if enabled and os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        yield
    finally:
        if enabled and os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


class BackgroundContributor:
    def __init__(self, root, *, url=DEFAULT_URL, app_factory=DesktopApp, schedule=None,
                 retry_minutes=30, prevent_sleep=True, clock=datetime.now,
                 elapsed_clock=time.monotonic, wall_clock=time.time):
        if type(retry_minutes) is not int or not 1 <= retry_minutes <= 1440:
            raise ValueError("Retry minutes must be between 1 and 1440.")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.app = app_factory(self.root, url=url)
        self.session = self.root / "account.json"
        self.url = url
        self.completed = 0
        self.prepared = False
        self.schedule = schedule or ProcessingSchedule()
        self.retry_seconds = retry_minutes * 60
        self.prevent_sleep = prevent_sleep
        self.clock, self.elapsed_clock, self.wall_clock = clock, elapsed_clock, wall_clock
        self.paced_wait = False
        self.last_state = None

    def pace(self):
        return self.schedule.pace_at(self.clock())

    def status(self, state, message):
        self.last_state = state
        atomic_json(self.root / "background-status.json", {
            "state": state, "message": message,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "acceptedThisRun": self.completed,
            "usesCodex": False,
            "pace": self.pace(), "schedule": self.schedule.public_settings(),
            "retryMinutes": self.retry_seconds // 60,
            "preventsIdleSleepWhileWorking": self.prevent_sleep,
        })

    def retry_record(self):
        path = self.root / "background-retry.json"
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if (record.get("version") != 1 or record.get("kind") not in {"indexing", "service", "verification"}
                    or type(record.get("attempts")) is not int or not 1 <= record["attempts"] <= 1_000_000
                    or type(record.get("nextAttemptAt")) not in (int, float)
                    or not math.isfinite(record["nextAttemptAt"]) or record["nextAttemptAt"] < 0):
                raise ValueError
            return record
        except (ValueError, TypeError, AttributeError):
            raise DesktopError("invalid_background_retry_state") from None

    def retry_later(self, kind):
        previous = self.retry_record()
        attempts = min(1_000_000, previous["attempts"] + 1) if previous and previous["kind"] == kind else 1
        # Indexing failures have already exhausted native retries. Cool down
        # progressively rather than continuously relaunching a broken batch.
        delay = self.retry_seconds
        if kind == "indexing":
            delay = min(6 * 60 * 60, delay * 2 ** min(attempts - 1, 10))
        atomic_json(self.root / "background-retry.json", {
            "version": 1, "kind": kind, "attempts": attempts,
            "nextAttemptAt": self.wall_clock() + delay,
        })
        return delay

    def step(self):
        self.paced_wait = False
        if (self.root / "PAUSE").exists():
            self.status("paused", "Paused. Remove the PAUSE file to continue.")
            return self.retry_seconds
        if (self.root / "NEEDS-ATTENTION").exists():
            self.status("needs_attention", "A saved failure needs review. Remove NEEDS-ATTENTION after resolving the cause.")
            return self.retry_seconds
        pace = self.pace()
        if pace == "pause":
            self.status("waiting_for_schedule", "Paused by your day/night schedule. Processing resumes automatically in the next active period.")
            return 60
        if shutil.disk_usage(self.root).free < MIN_FREE_BYTES:
            self.status("waiting_for_space", "At least 5 GB of free disk space is required. Saved work is safe.")
            return self.retry_seconds
        retry = self.retry_record()
        if retry and retry["nextAttemptAt"] > self.wall_clock():
            state = {"indexing": "retrying_indexing", "service": "waiting_for_service",
                     "verification": "waiting_for_verification"}[retry["kind"]]
            self.status(state, "Waiting before the next recovery attempt. Saved work and failure reports are preserved.")
            return min(86400, retry["nextAttemptAt"] - self.wall_clock())
        # Check before downloading, creating an account, or consuming a lease.
        self.app.capabilities(DesktopClient(self.url))
        if not self.prepared:
            self.status("preparing", "Checking the private processing files.")
            self.app.prepare()
            self.prepared = True
        if not self.app.client:
            stored = load_session(self.session, self.url)
            if self.session.exists() and not stored:
                raise DesktopError("invalid_saved_account")
            if stored:
                self.app.connect(stored.get("recoveryCode"))
            else:
                created = self.app.connect(create=True)
                save_session(self.session, url=self.url, account_id=None,
                             recovery_code=created["recoveryCode"])
            self.app.update(savedCode=True)
        recovered = self.app.resume_submissions()
        self.completed += int(recovered.get("accepted", 0))
        with keep_awake(self.prevent_sleep):
            try:
                self.app.require_qualification()
            except DesktopError as error:
                if str(error) != "pc_check_required":
                    raise
                self.status("checking_pc", "Running the short PC check and requesting trusted approval.")
                self.app.qualify()
            self.status("processing", "Processing a batch. Completed work and checkpoints are saved.")
            started = self.elapsed_clock()
            result = self.app.indexer(
                url=self.url, pace="slow", batches=1, count=16, client=self.app.client,
                persist_session=False, work_dir=self.root / "indexes",
                **self.app.assets, use_nice=False,
            )
            processing_seconds = max(0, self.elapsed_clock() - started)
        self.completed += int(result.get("accepted", 0))
        (self.root / "background-retry.json").unlink(missing_ok=True)
        if not result.get("batches"):
            self.status("waiting_for_work", "No locations are available. The worker will check again after the retry interval.")
            return self.retry_seconds
        pace = self.pace()
        if pace == "pause":
            self.status("waiting_for_schedule", "Batch saved. Paused by your day/night schedule until the next active period.")
            return 60
        # Keep the qualified native profile (including input.json) unchanged.
        # Pace controls the rest between complete 16-location batches, not
        # inference threads, memory limits or the correctness of the output.
        rest = {"max": 0, "medium": 1, "slow": 3}[pace] * processing_seconds
        if rest > 1:
            self.paced_wait = True
            self.status("running", "Batch saved. Resting between batches according to your processing pace.")
            return rest
        self.status("running", "Batch saved. Continuing with the next available batch.")
        return 1

    def wait(self, delay, stop):
        initial_pace, initially_paused = self.pace(), (self.root / "PAUSE").exists()
        deadline = self.elapsed_clock() + delay
        with keep_awake(self.prevent_sleep and self.paced_wait):
            while not stop.is_set():
                if (self.root / "STOP-AFTER-BATCH").exists():
                    return
                if self.pace() != initial_pace or (self.root / "PAUSE").exists() != initially_paused:
                    return
                remaining = deadline - self.elapsed_clock()
                if remaining <= 0 or stop.wait(min(5, remaining)):
                    return

    def run(self, *, once=False, stop=None):
        stop = stop or threading.Event()
        while not stop.is_set():
            if (self.root / "STOP-AFTER-BATCH").exists():
                self.status("stopped", "Stopped safely between batches. Saved work and account files are preserved.")
                return
            try:
                delay = self.step()
            except Exception as error:
                self.app.record_failure(error)
                code = getattr(error, "code", None) or str(error)
                transient_response = (isinstance(error, (ContributeError, VisionIndexError))
                                      and error.status in RETRY_STATUSES
                                      and code in TRANSIENT_HTTP_CODES
                                      and code not in TERMINAL_SERVICE_ERRORS)
                if code == "scene_audit_backlog":
                    delay = self.retry_later("verification")
                    self.status("waiting_for_verification", "Completed batches are saved and waiting for verification. Retrying automatically.")
                elif (code in {"scene_verification_unavailable", "network_error", "runtime_download_failed"}
                      or transient_response
                      or isinstance(error, VisionIndexError) and code in RECOVERABLE_QUEUE_ERRORS):
                    delay = self.retry_later("service")
                    self.status("waiting_for_service", "The verified Community service is unavailable. Retrying automatically; saved work is preserved.")
                elif isinstance(error, VisionIndexError) and code in RETRYABLE_NATIVE_CODES:
                    delay = self.retry_later("indexing")
                    self.status("retrying_indexing", "The indexer was interrupted or stalled. Retrying after a rest; saved checkpoints and failure reports are preserved.")
                else:
                    # Do not repeatedly run expensive rejected checks or create accounts.
                    (self.root / "NEEDS-ATTENTION").touch()
                    self.status("needs_attention", "Processing stopped safely. The failure report and work are saved for review.")
                    delay = self.retry_seconds
            if once:
                return
            self.wait(delay, stop)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--accept-contributions", action="store_true")
    parser.add_argument("--day-pace", choices=PACES, default="medium")
    parser.add_argument("--night-pace", choices=PACES, default="max")
    parser.add_argument("--day-start", default="08:00", help="Local 24-hour time (default: 08:00).")
    parser.add_argument("--night-start", default="22:00", help="Local 24-hour time (default: 22:00).")
    parser.add_argument("--retry-minutes", type=int, default=30)
    parser.add_argument("--no-keep-awake", action="store_true", help="Allow normal Windows idle sleep during work.")
    args = parser.parse_args()
    if not args.accept_contributions:
        parser.error("Opt in with --accept-contributions to allow private downloads, imagery retrieval, an anonymous account, and verified submissions.")
    try:
        schedule = ProcessingSchedule(args.day_pace, args.night_pace, args.day_start, args.night_start)
        worker = BackgroundContributor(args.root, url=args.url, schedule=schedule,
                                       retry_minutes=args.retry_minutes, prevent_sleep=not args.no_keep_awake)
    except ValueError as error:
        parser.error(str(error))
    try:
        with single_instance(worker.root):
            worker.run(once=args.once)
    except WorkerAlreadyRunning:
        # Another guided or background instance owns this folder.
        return


if __name__ == "__main__":
    main()
