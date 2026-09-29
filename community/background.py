"""Unattended scene contributor. Uses no AI service or Codex check-ins.

Run only after opting into downloads, live imagery, and Community contributions.
The trusted service still decides whether this PC and its results are approved.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import threading
import time

from .contribute import DEFAULT_URL, RETRY_STATUSES, ContributeError, load_session, save_session
from .desktop import DesktopApp, DesktopClient, DesktopError

WAIT_SECONDS = 1800
MIN_FREE_BYTES = 5 * 1024**3


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
            guard.seek(0)
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
def keep_awake():
    """Inhibit idle sleep during a batch only; never change the power plan."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        yield
    finally:
        if os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


class BackgroundContributor:
    def __init__(self, root, *, url=DEFAULT_URL, app_factory=DesktopApp):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.app = app_factory(self.root, url=url)
        self.session = self.root / "account.json"
        self.url = url
        self.completed = 0
        self.prepared = False

    def status(self, state, message):
        atomic_json(self.root / "background-status.json", {
            "state": state, "message": message,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "acceptedThisRun": self.completed,
            "usesCodex": False,
        })

    def step(self):
        if (self.root / "PAUSE").exists():
            self.status("paused", "Paused. Remove the PAUSE file to continue.")
            return WAIT_SECONDS
        if (self.root / "NEEDS-ATTENTION").exists():
            self.status("needs_attention", "The PC check needs review. Evidence is saved. Remove NEEDS-ATTENTION after resolving the cause.")
            return WAIT_SECONDS
        if shutil.disk_usage(self.root).free < MIN_FREE_BYTES:
            self.status("waiting_for_space", "At least 5 GB of free disk space is required. Saved work is safe.")
            return WAIT_SECONDS
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
        with keep_awake():
            try:
                self.app.require_qualification()
            except DesktopError as error:
                if str(error) != "pc_check_required":
                    raise
                self.status("checking_pc", "Running the short PC check and requesting trusted approval.")
                self.app.qualify()
            self.status("processing", "Processing a batch. Completed work and checkpoints are saved.")
            result = self.app.indexer(
                url=self.url, pace="slow", batches=1, count=16, client=self.app.client,
                persist_session=False, work_dir=self.root / "indexes",
                **self.app.assets, use_nice=False,
            )
        self.completed += int(result.get("accepted", 0))
        if not result.get("batches"):
            self.status("waiting_for_work", "No locations are available. The worker will try again in 30 minutes.")
            return WAIT_SECONDS
        self.status("running", "Batch saved. Continuing with the next available batch.")
        return 1

    def run(self, *, once=False, stop=None):
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                delay = self.step()
            except Exception as error:
                self.app.record_failure(error)
                code = getattr(error, "code", None) or str(error)
                transient_response = (isinstance(error, ContributeError)
                                      and error.status in RETRY_STATUSES
                                      and code not in {"verification_failed", "scene_qualification_rejected",
                                                       "scene_device_not_qualified"})
                if code in {"scene_verification_unavailable", "network_error"} or transient_response:
                    self.status("waiting_for_service", "The verified Community service is unavailable. Retrying in 30 minutes; saved work is preserved.")
                else:
                    # Do not repeatedly run expensive rejected checks or create accounts.
                    (self.root / "NEEDS-ATTENTION").touch()
                    self.status("needs_attention", "Processing stopped safely. The failure report and work are saved for review.")
                delay = WAIT_SECONDS
            if once or stop.wait(delay):
                return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--accept-contributions", action="store_true")
    args = parser.parse_args()
    if not args.accept_contributions:
        parser.error("Opt in with --accept-contributions to allow private downloads, imagery retrieval, an anonymous account, and verified submissions.")
    worker = BackgroundContributor(args.root, url=args.url)
    try:
        with single_instance(worker.root):
            worker.run(once=args.once)
    except WorkerAlreadyRunning:
        # Another guided or background instance owns this folder.
        return


if __name__ == "__main__":
    main()
