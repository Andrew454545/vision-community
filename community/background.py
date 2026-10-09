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
import re
import shutil
import stat
import sys
import threading
import time

from .contribute import DEFAULT_URL, RETRY_STATUSES, ContributeError, load_session, save_session
from .desktop import DesktopApp, DesktopClient, DesktopError, public_error
from .vision_index import RETRYABLE_NATIVE_CODES, VisionIndexError

WAIT_SECONDS = 1800
MIN_FREE_BYTES = 5 * 1024**3
MAX_STORAGE_ENTRIES = 200_000
STORAGE_SCAN_SECONDS = 10
PACES = ("slow", "medium", "max", "pause")
DEFAULT_DAY_START = "06:00"
DEFAULT_NIGHT_START = "00:00"
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
    "schema_update_required", "rate_limit_unavailable", "service_maintenance",
    "invalid_submission_result",
    "service_redirect_refused", "service_response_limit",
})
SLEEP_REQUEST_ERRORS = frozenset({'keep_awake_failed', 'keep_awake_release_failed'})


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
        raise ValueError("Use a time such as 06:00 or 00:00 (24-hour clock).") from None


@dataclass(frozen=True)
class ProcessingSchedule:
    day_pace: str = "medium"
    night_pace: str = "max"
    day_start: str = DEFAULT_DAY_START
    night_start: str = DEFAULT_NIGHT_START

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


def measure_storage(root, *, approved_links=None):
    """Count logical file sizes without opening private files or following links.

    This is a batch-boundary estimate, not a filesystem quota. Incomplete or
    oversized inventories stop work rather than assuming unknown bytes are zero.
    """
    root = Path(root)
    approved_links = approved_links or {}
    deadline = time.monotonic() + STORAGE_SCAN_SECONDS
    pending = [Path(root)]
    used, files, entries, links = 0, 0, 0, 0
    try:
        while pending:
            folder = pending.pop()
            info = folder.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise DesktopError("storage_check_failed")
            with os.scandir(folder) as children:
                for child in children:
                    entries += 1
                    if entries > MAX_STORAGE_ENTRIES or time.monotonic() > deadline:
                        raise DesktopError("storage_check_failed")
                    info = child.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        relative = Path(child.path).relative_to(root).as_posix()
                        target = approved_links.get(relative)
                        # The only exception is an exact pinned direct link to a
                        # regular sibling. Never resolve/follow it or count its
                        # target twice. Unknown, chained and escaping links stop.
                        if (not isinstance(target, str) or not re.fullmatch(r'[A-Za-z0-9_.+-]+', target)
                                or target in {'.', '..'} or os.readlink(child.path) != target):
                            raise DesktopError("storage_check_failed")
                        sibling = Path(child.path).parent / target
                        sibling_info = sibling.lstat()
                        if (not stat.S_ISREG(sibling_info.st_mode)
                                or getattr(sibling_info, "st_file_attributes", 0) & 0x400):
                            raise DesktopError("storage_check_failed")
                        used += info.st_size
                        links += 1
                        continue
                    if getattr(info, "st_file_attributes", 0) & 0x400:
                        raise DesktopError("storage_check_failed")
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(Path(child.path))
                    elif stat.S_ISREG(info.st_mode):
                        used += info.st_size
                        files += 1
                    else:
                        raise DesktopError("storage_check_failed")
    except OSError:
        raise DesktopError("storage_check_failed") from None
    return {"usedBytes": used, "files": files, "entries": entries, "links": links,
            "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "measurement": ("logical-file-and-link-bytes-at-batch-boundary" if links else
                            "logical-file-bytes-at-batch-boundary")}


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
    previous = None
    mac_request = None
    if enabled and os.name == "nt":
        try:
            previous = _sleep_state(0x80000001)
        except (OSError, AttributeError):
            raise DesktopError('keep_awake_failed') from None
        if not previous:
            raise DesktopError('keep_awake_failed')
    elif enabled and sys.platform == 'darwin':
        try:
            mac_request = _MacSleepRequest()
        except (OSError, AttributeError):
            raise DesktopError('keep_awake_failed') from None
    try:
        yield
    finally:
        if mac_request is not None:
            try:
                mac_request.close()
            except (OSError, AttributeError):
                raise DesktopError('keep_awake_release_failed') from None
        if previous is not None:
            try:
                released = _sleep_state(previous | 0x80000000)
            except (OSError, AttributeError):
                raise DesktopError('keep_awake_release_failed') from None
            if not released:
                raise DesktopError('keep_awake_release_failed')


def _sleep_state(flags):
    import ctypes
    setter = ctypes.windll.kernel32.SetThreadExecutionState
    setter.argtypes, setter.restype = [ctypes.c_uint32], ctypes.c_uint32
    return setter(flags)


class _MacSleepRequest:
    """A process-owned idle-system-sleep assertion, with no helper process.

    IOKit owns this assertion and removes it when the caller exits, including
    an abrupt exit. Display sleep, explicit sleep, lid closure and emergency
    sleep remain under macOS control. No system settings or privileges change.
    """
    def __init__(self):
        import ctypes

        self.assertion = None
        self.cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.io = ctypes.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
        self.cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        self.cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.cf.CFRelease.restype = None
        self.io.IOPMAssertionCreateWithDescription.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_double, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        self.io.IOPMAssertionCreateWithDescription.restype = ctypes.c_int32
        self.io.IOPMAssertionRelease.argtypes = [ctypes.c_uint32]
        self.io.IOPMAssertionRelease.restype = ctypes.c_int32
        strings = []
        try:
            for text in (b'PreventUserIdleSystemSleep', b'VISION Community processing'):
                value = self.cf.CFStringCreateWithCString(None, text, 0x08000100)  # UTF-8.
                if not value:
                    raise OSError('keep_awake_failed')
                strings.append(value)
            token = ctypes.c_uint32()
            # Zero timeout: protect a batch of any length, then explicitly release.
            # This API creates an assertion at the on level without retaining a
            # child, polling, forcing the display awake or changing power policy.
            result = self.io.IOPMAssertionCreateWithDescription(
                strings[0], strings[1], None, None, None, 0.0, None, ctypes.byref(token))
            if result != 0:
                raise OSError('keep_awake_failed')
            self.assertion = token.value
        finally:
            for value in reversed(strings):
                self.cf.CFRelease(value)

    def close(self):
        if self.assertion is not None:
            token, self.assertion = self.assertion, None
            if self.io.IOPMAssertionRelease(token) != 0:
                raise OSError('keep_awake_release_failed')


class BackgroundContributor:
    def __init__(self, root, *, url=DEFAULT_URL, app_factory=DesktopApp, schedule=None,
                 retry_minutes=30, prevent_sleep=True, clock=datetime.now,
                 elapsed_clock=time.monotonic, wall_clock=time.time, storage_limit_gb=0):
        if type(retry_minutes) is not int or not 1 <= retry_minutes <= 1440:
            raise ValueError("Retry minutes must be between 1 and 1440.")
        if type(storage_limit_gb) is not int or not 0 <= storage_limit_gb <= 4096:
            raise ValueError("Storage allowance must be a whole number from 0 to 4096 GB (0 means no folder allowance).")
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
        self.empty_lanes = set()
        self.storage_limit_bytes = storage_limit_gb * 1024**3
        self.storage = {"limitBytes": self.storage_limit_bytes, "usedBytes": None,
                        "minimumFreeBytes": MIN_FREE_BYTES, "freeBytes": None,
                        "scope": "entire-private-worker-folder", "hardQuota": False}

    def space_available(self):
        self.storage["freeBytes"] = shutil.disk_usage(self.root).free
        if self.storage_limit_bytes:
            # Do not leave a stale success estimate visible after a failed scan.
            self.storage.update(usedBytes=None, files=None, entries=None, links=None, measuredAt=None)
            if sys.platform == 'darwin':
                try:
                    from community.mac_runtime import runtime_links
                    approved = runtime_links(self.root)
                except (OSError, ValueError):
                    raise DesktopError('storage_check_failed') from None
                self.storage.update(measure_storage(self.root, approved_links=approved))
            else:
                self.storage.update(measure_storage(self.root))
        return (self.storage["freeBytes"] >= MIN_FREE_BYTES and
                (not self.storage_limit_bytes or self.storage["usedBytes"] < self.storage_limit_bytes))

    def wait_for_space(self):
        if self.storage["freeBytes"] < MIN_FREE_BYTES:
            message = "At least 5 GB of free disk space is required. Saved work is safe."
        else:
            message = ("Your saved files reached the chosen storage allowance. New processing is paused; "
                       "saved deliveries can still recover. Keep recovery files in place and increase the allowance if needed.")
        self.status("waiting_for_space", message)
        return self.retry_seconds

    def connect_account(self, *, allow_create=True):
        if self.app.client:
            return True
        stored = load_session(self.session, self.url)
        if self.session.exists() and not stored:
            raise DesktopError("invalid_saved_account")
        if stored:
            self.app.connect(stored.get("recoveryCode"))
        elif not allow_create:
            return False
        else:
            created = self.app.connect(create=True)
            save_session(self.session, url=self.url, account_id=None,
                         recovery_code=created["recoveryCode"])
        self.app.update(savedCode=True)
        return True

    def pace(self):
        return self.schedule.pace_at(self.clock())

    def status(self, state, message):
        self.last_state = state
        undelivered = getattr(self.app.client, "undelivered", 0)
        atomic_json(self.root / "background-status.json", {
            "state": state, "message": message,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "acceptedThisRun": self.completed,
            "undeliveredBatches": undelivered if type(undelivered) is int else 0,
            "usesCodex": False,
            "pace": self.pace(), "schedule": self.schedule.public_settings(),
            "retryMinutes": self.retry_seconds // 60,
            "idleSleepPreventionRequested": self.prevent_sleep,
            "localStorage": self.storage,
            "workType": self.app.work_plan.work_type,
            "nextLane": self.app.work_plan.next_lane,
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
        space_ready = self.space_available()
        if not space_ready and not self.app.client and not self.session.exists():
            return self.wait_for_space()
        retry = self.retry_record()
        if retry and retry["nextAttemptAt"] > self.wall_clock():
            state = {"indexing": "retrying_indexing", "service": "waiting_for_service",
                     "verification": "waiting_for_verification"}[retry["kind"]]
            self.status(state, "Waiting before the next recovery attempt. Saved work and failure reports are preserved.")
            return min(86400, retry["nextAttemptAt"] - self.wall_clock())
        # Check before downloading, creating an account, or consuming a lease.
        self.app.capabilities(DesktopClient(self.url))
        if space_ready and not self.prepared:
            self.status("preparing", "Checking the private processing files.")
            self.app.prepare()
            self.prepared = True
            space_ready = self.space_available()
        if not self.connect_account(allow_create=space_ready):
            return self.wait_for_space()
        recovered = self.app.resume_submissions()
        self.completed += int(recovered.get("accepted", 0))
        # Existing accounts can deliver/audit saved work even at the allowance.
        # Budget pressure never creates another account or claims a new lease.
        if not self.space_available():
            return self.wait_for_space()
        if not self.prepared:
            # Space may become available while an existing delivery settles.
            self.status("preparing", "Checking the private processing files.")
            self.app.prepare()
            self.prepared = True
            if not self.space_available():
                return self.wait_for_space()
        with keep_awake(self.prevent_sleep):
            try:
                self.app.require_qualification()
            except DesktopError as error:
                if str(error) not in {"pc_check_required", "object_pc_check_required"}:
                    raise
                self.status("checking_pc", "Running the short computer check and requesting trusted approval.")
                self.app.qualify()
            if not self.space_available():
                return self.wait_for_space()
            self.status("processing", "Processing a batch. Completed work and checkpoints are saved.")
            lane = self.app.work_plan.next_lane
            started = self.elapsed_clock()
            result = self.app.run_batch()
            processing_seconds = max(0, self.elapsed_clock() - started)
        self.completed += int(result.get("accepted", 0))
        (self.root / "background-retry.json").unlink(missing_ok=True)
        if not result.get("batches"):
            self.empty_lanes.add(lane)
            if not all(selected in self.empty_lanes for selected in self.app.work_plan.lanes):
                self.status("running", "No locations in this work queue. Checking the other selected work next.")
                return 1
            self.empty_lanes.clear()
            self.status("waiting_for_work", "No locations are available. The worker will check again after the retry interval.")
            return self.retry_seconds
        self.empty_lanes.discard(lane)
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
                elif (code in {"scene_verification_unavailable", "object_verification_unavailable", "network_error", "runtime_download_failed"}
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
                    message = (public_error(error) if code in SLEEP_REQUEST_ERRORS else
                               "Processing stopped safely. The failure report and work are saved for review.")
                    self.status("needs_attention", message)
                    if code in SLEEP_REQUEST_ERRORS:
                        # Exit the caller as well; it owns the OS sleep request.
                        return
                    delay = self.retry_seconds
            if once:
                return
            try:
                self.wait(delay, stop)
            except DesktopError as error:
                if str(error) not in SLEEP_REQUEST_ERRORS:
                    raise
                self.app.record_failure(error)
                (self.root / 'NEEDS-ATTENTION').touch()
                self.status('needs_attention', public_error(error))
                return


def main(*, stop=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--work-type", choices=("scene", "object", "both"), default=None)
    parser.add_argument("--accept-contributions", action="store_true")
    parser.add_argument("--day-pace", choices=PACES, default="medium")
    parser.add_argument("--night-pace", choices=PACES, default="max")
    parser.add_argument("--day-start", default=DEFAULT_DAY_START, help="Local 24-hour time (default: 06:00).")
    parser.add_argument("--night-start", default=DEFAULT_NIGHT_START, help="Local 24-hour time (default: 00:00).")
    parser.add_argument("--retry-minutes", type=int, default=30)
    parser.add_argument("--storage-limit-gb", type=int, default=0,
                        help="Private folder allowance in binary GB (0 disables; checked between batches, not a hard quota).")
    parser.add_argument("--no-keep-awake", action="store_true", help="Allow normal idle sleep during work.")
    args = parser.parse_args()
    if not args.accept_contributions:
        parser.error("Opt in with --accept-contributions to allow private downloads, imagery retrieval, an anonymous account, and verified submissions.")
    try:
        schedule = ProcessingSchedule(args.day_pace, args.night_pace, args.day_start, args.night_start)
        worker = BackgroundContributor(args.root, url=args.url, schedule=schedule,
                                       retry_minutes=args.retry_minutes, prevent_sleep=not args.no_keep_awake,
                                       storage_limit_gb=args.storage_limit_gb)
    except ValueError as error:
        parser.error(str(error))
    try:
        with single_instance(worker.root):
            worker.app.reload_work_plan()
            if args.work_type is not None and worker.app.work_plan.work_type != args.work_type:
                worker.app.select_work(args.work_type)
            worker.run(once=args.once, stop=stop)
    except WorkerAlreadyRunning:
        # Another guided or background instance owns this folder.
        return


if __name__ == "__main__":
    main()
