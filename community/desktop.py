"""Private, loopback-only guided scene contributor. No third-party packages."""
from __future__ import annotations

import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from community.bootstrap import BootstrapError, install_runtime, load_manifest, runtime_platform
from community.contribute import CommunityClient, ContributeError, DEFAULT_URL
from community.vision_index import index_from_queue, parse_json_stdout, require_layout, VisionIndexError
from community.pc_canary import run_canary, canary_profile_matches
from community.submission_outbox import SubmissionOutbox, MAX_PENDING_SUBMISSIONS

WEB = Path(__file__).with_name("desktop_web")
ERRORS = {
    "network_error": "The service could not be reached. Check your connection and try again.",
    "runtime_download_failed": "A download was interrupted. Check your connection and choose Download again; verified files will be reused.",
    "runtime_mismatch": "A downloaded file failed its safety check. It was not used. Try downloading again.",
    "unsupported_platform": "This starter supports 64-bit Intel or AMD Windows PCs. This computer is not supported.",
    "recovery_failed": "That account code was not accepted. Check it and try again.",
    "unauthorized": "Please reconnect your account using your saved code.",
    "scene_verification_unavailable": "The shared service is not ready to verify PC contributions. Please ask the project maintainer to enable verification before indexing.",
    "scene_reference_required": "The service has not approved this batch for contribution. Your local evidence has been kept.",
    "verification_failed": "The service did not accept this batch. Your local results have been kept for review.",
    "busy": "Another action is still running. Please wait for it to finish.",
    "account_required": "Connect an account first.",
    "save_code_first": "Confirm that you have saved your account code before indexing.",
    "runtime_not_ready": "Download and check the processing files first.",
    "pc_check_required": "Run the short PC check before indexing. Approval must be current and match these processing files.",
    "scene_qualification_required": "Your PC approval is missing or has expired. Run the short PC check again.",
    "canary_failed": "The PC check could not finish. Its report and logs have been kept. You can retry.",
    "scene_qualification_rejected": "The service could not approve this PC's check. Its report has been kept for review.",
    "scene_device_not_qualified": "The service could not approve this PC's check. Its report has been kept for review.",
    "scene_device_qualification_required": "Run the short PC check before indexing.",
    "scene_qualification_changed": "The PC approval changed. Run the short PC check again.",
    "scene_submission_rejected": "The service rejected this batch. Processing has stopped and your results are saved for review.",
    "scene_audit_backlog": "Your completed batches are waiting for verification. Processing will continue when they have been checked.",
    "invalid_request": "That request could not be used. Refresh the page and try again.",
    "indexer_timeout": "This batch reached its time limit. It has stopped and its logs were kept.",
    "indexer_no_progress": "The indexer stopped making progress. Its logs were kept for review.",
    "indexer_cancelled": "Indexing stopped. Your completed batches are safe.",
    "storage_check_failed": "Saved files could not be checked safely. Processing stopped and your files were kept. Ask the maintainer to review the local storage report.",
}


class DesktopError(RuntimeError):
    pass


class DesktopClient(CommunityClient):
    """Bind each scene lease to the configuration checked on this PC."""
    def __init__(self, url):
        super().__init__(url)
        self.profile_id = None
        self.outbox = None
        self._pending = 0

    @property
    def pending(self):
        return self.outbox.count() if self.outbox else self._pending

    @property
    def undelivered(self):
        return self.outbox.undelivered() if self.outbox else 0

    def enable_outbox(self, root, account_id):
        self.outbox = SubmissionOutbox(Path(root) / "submissions.sqlite", self.origin, account_id)

    def submission_is_saved(self, lease_id):
        return self.outbox is not None and self.outbox.saved(lease_id)

    def lease(self, *args, **kwargs):
        if self.pending >= MAX_PENDING_SUBMISSIONS:
            raise ContributeError("scene_audit_backlog", 503)
        return super().lease(*args, **kwargs)

    def submit(self, lease_id, outputs):
        if self.outbox:
            self.outbox.remember(lease_id, outputs)
        result = super().submit(lease_id, outputs)
        if self.outbox:
            self.outbox.result(lease_id, result)
        if result.get("rejected"):
            raise ContributeError("scene_submission_rejected", 422)
        return result

    def request(self, method, path, body=None):
        if method == "POST" and path == "/api/leases" and body and body.get("lane") == "scene":
            if not self.profile_id:
                raise DesktopError("pc_check_required")
            body = {**body, "profileId": self.profile_id}
        response = super().request(method, path, body)
        if not self.outbox and method == "POST" and path == "/api/submissions":
            self._pending += int(response[1].get("pending", 0))
        return response

    def audit_submission(self, submission_id):
        status, data, _ = super().request("POST", "/api/scene-audits", {"submissionId": submission_id})
        if status != 200:
            raise ContributeError(str(data.get("error") if isinstance(data, dict) else "verification_failed"), status)
        if self.outbox:
            self.outbox.result(submission_id, data)
        if data.get("rejected"):
            raise ContributeError("scene_submission_rejected", 422)
        return data

    def resume_submissions(self):
        accepted = earned = lost = 0
        if not self.outbox:
            return {"accepted": 0, "unitsEarned": 0}
        for delivery in self.outbox.pending():
            lease_id = delivery["lease_id"]
            if delivery["state"] == "ready":
                try:
                    result = self.submit(lease_id, json.loads(delivery["payload_json"]))
                except ContributeError as error:
                    # Do not keep an expired delivery at the front of the
                    # journal forever. Preserve its output and fixed reason,
                    # never reassign it or interpret a generic outage as loss.
                    definitive = (error.code, error.status) in {
                        ("expired_lease", 409), ("lease_lost", 409), ("unknown_lease", 404),
                    }
                    if not definitive or not self.outbox.lose_lease(lease_id, error.code):
                        raise
                    lost += 1
                    continue
            else:
                result = self.audit_submission(lease_id)
            if result.get("pendingAudit") and delivery["state"] == "ready":
                result = self.audit_submission(lease_id)
            accepted += int(result.get("accepted", 0))
            earned += int(result.get("unitsEarned", 0))
        result = {"accepted": accepted, "unitsEarned": earned}
        if lost:
            result["leaseLost"] = lost
        return result


def public_error(error):
    code = getattr(error, "code", None) or str(error)
    return ERRORS.get(code, "This action could not finish. Local diagnostic information was saved; you can retry or share it with the maintainer.")


class DesktopApp:
    def __init__(self, root: Path, *, url=DEFAULT_URL, client_factory=DesktopClient,
                 indexer=index_from_queue, canary=run_canary, profile_matches=canary_profile_matches):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.url, self.client_factory, self.indexer = url, client_factory, indexer
        self.canary, self.profile_matches = canary, profile_matches
        self.lock = threading.RLock()
        self.operation = threading.Lock()
        self.stop = threading.Event()
        self.client = None
        self.canary_report = None
        self.qualification = None
        try:
            self.canary_report = json.loads((self.root / "pc-check.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.last_seen = time.monotonic()
        self.state = dict(ready=False, connected=False, savedCode=False, busy=False,
                          phase="setup", message="Prepare this PC to begin.", completed=0,
                          units=0, batchCompleted=0, batchTotal=16, started=None,
                          stopping=False, serviceReady=False, qualified=False, pending=0, undelivered=0)

    @property
    def assets(self):
        return {"binary": self.root / "runtime/bin/mma-vision.exe",
                "model_dir": self.root / "runtime/models/siglip-b16-224-canonical"}

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def snapshot(self):
        with self.lock:
            self.last_seen = time.monotonic()
            value = dict(self.state)
        started = value.pop("started")
        value["elapsedSeconds"] = int(time.monotonic() - started) if started else 0
        value["folder"] = str(self.root)
        return value

    def record_failure(self, error):
        # No request contents, account identifiers, credentials, or raw process output.
        code = getattr(error, "code", None) or type(error).__name__
        if isinstance(error, DesktopError) and str(error) in ERRORS:
            code = str(error)
        if not isinstance(code, str) or len(code) > 100:
            code = type(error).__name__
        report = {"status": "INCOMPLETE", "error_type": type(error).__name__, "code": code,
                  "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        (self.root / "desktop-failure.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    def launch(self, action):
        if not self.operation.acquire(blocking=False):
            raise DesktopError("busy")
        self.update(busy=True)
        def work():
            try:
                action()
            except Exception as error:
                self.record_failure(error)
                self.update(phase="error", message=public_error(error))
            finally:
                self.update(busy=False, stopping=False, started=None)
                self.operation.release()
        thread = threading.Thread(target=work, name="vision-desktop-job", daemon=False)
        thread.start()
        return thread

    def prepare(self):
        self.qualification = None
        self.update(qualified=False)
        self.update(phase="download", message="Checking processing files. Downloads may take a few minutes.", ready=False)
        if runtime_platform() != "windows-x86_64":
            raise BootstrapError("unsupported_platform")
        install_runtime(load_manifest(), self.root / "runtime", lane="scene",
                        progress=lambda n, total: self.update(message=f"Checking and downloading file {n} of {total}. Please keep this window open."))
        binary = self.root / "runtime/bin/mma-vision.exe"
        checked = subprocess.run([str(binary), "index-layout"], capture_output=True, text=True, timeout=60,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if checked.returncode:
            raise VisionIndexError("vision_binary_failed")
        require_layout(parse_json_stdout(checked.stdout))
        self.update(ready=True, phase="ready", message="This PC is ready. Connect your account below.")

    def capabilities(self, client):
        try:
            status, value, _ = client.request("GET", "/api/capabilities")
        except ContributeError as error:
            if error.status in {404, 405}:
                raise DesktopError("scene_verification_unavailable") from error
            raise
        scene = value.get("sceneContributions", {}) if isinstance(value, dict) else {}
        if status != 200 or not isinstance(value, dict) or value.get("version") != 1 or scene.get("model") != "vision-four-view-v4" or scene.get("ready") is not True or scene.get("deviceQualificationRequired") is not True or scene.get("canaryLocations") != 112:
            self.update(serviceReady=False)
            raise DesktopError("scene_verification_unavailable")
        self.update(serviceReady=True)

    def connect(self, code=None, *, create=False):
        if not self.operation.acquire(blocking=False):
            raise DesktopError("busy")
        self.update(busy=True)
        try:
            client = self.client_factory(self.url)
            self.capabilities(client)  # Avoid asking users to sign up for a blocked service.
            if create:
                account = client.create_account()
            else:
                if not isinstance(code, str) or not 1 <= len(code.strip()) <= 256:
                    raise DesktopError("invalid_request")
                account = client.recover(code.strip())
            me = client.me()
            client.enable_outbox(self.root / "indexes", me.get("accountId"))
            self.client = client
            self.qualification = None
            self.update(connected=True, savedCode=not create, phase="ready", units=int(me.get("units", 0)),
                        qualified=False, pending=client.pending, undelivered=client.undelivered,
                        message="Account connected. Run the short PC check next.")
            if self.canary_report and self.profile_matches(self.canary_report, **self.assets):
                profile = self.canary_report["runtimeProfile"]["sha256"]
                _, previous, _ = client.request("GET", "/api/scene-qualifications?profileId=" + profile)
                if self.set_qualification(previous):
                    self.update(message="This PC's existing approval is current. You can start indexing.")
            return {"recoveryCode": account.get("recoveryCode")} if create else {"connected": True}
        finally:
            self.update(busy=False)
            self.operation.release()

    def require_account(self):
        with self.lock:
            if not self.state["ready"]:
                raise DesktopError("runtime_not_ready")
            if not self.client:
                raise DesktopError("account_required")
            if not self.state["savedCode"]:
                raise DesktopError("save_code_first")

    def set_qualification(self, value):
        profile = (self.canary_report or {}).get("runtimeProfile", {}).get("sha256")
        if (not isinstance(value, dict) or value.get("qualified") is not True
                or value.get("profileId") != profile
                or type(value.get("expiresAt")) not in (int, float)
                or not time.time() < value["expiresAt"]):
            self.qualification = None
            self.update(qualified=False)
            return False
        self.qualification = value
        self.client.profile_id = profile
        self.update(qualified=True)
        return True

    def check_pc(self):
        self.require_account()
        return self.launch(self.qualify)

    def qualify(self):
        self.capabilities(self.client)
        self.qualification = None
        self.update(qualified=False, phase="checking", started=time.monotonic(),
                    message="Checking 112 locations on this PC. Please keep this window open.")
        folder = self.root / "checks" / (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4))
        self.canary_report = self.canary(folder, **self.assets, progress_callback=self.progress)
        if self.canary_report.get("status") != "COMPLETE" or not self.profile_matches(self.canary_report, **self.assets):
            raise DesktopError("canary_failed")
        # This contains public fixture results and processing-file hashes, never account codes.
        (self.root / "pc-check.json").write_text(json.dumps(self.canary_report), encoding="utf-8")
        self.update(message="PC check complete. Asking the service to verify the results.")
        _, decision, _ = self.client.request("POST", "/api/scene-qualifications", self.canary_report["submission"])
        if not self.set_qualification(decision):
            raise DesktopError("scene_qualification_rejected")
        self.update(phase="ready", message="This PC is approved. You can start indexing.", batchCompleted=0, batchTotal=16)

    def require_qualification(self):
        self.require_account()
        if (not self.profile_matches(self.canary_report, **self.assets)
                or not self.set_qualification(self.qualification)):
            self.update(qualified=False)
            raise DesktopError("pc_check_required")

    def start(self):
        self.require_account()
        self.stop.clear()
        return self.launch(self.process)

    def progress(self, event):
        if event.get("event") in {"indexing", "resume"}:
            self.update(batchCompleted=event.get("completedLocations", 0), batchTotal=event.get("totalLocations", 16))

    def process(self):
        self.require_qualification()
        self.capabilities(self.client)
        self.update(phase="indexing", message="Processing locations on this PC. Results wait for a service check before joining the search pool.", started=time.monotonic())
        while not self.stop.is_set():
            if time.monotonic() - self.last_seen > 60:
                break
            self.require_qualification()
            self.resume_submissions()
            result = self.indexer(url=self.url, pace="slow", batches=1, count=16, client=self.client,
                                  persist_session=False, work_dir=self.root / "indexes",
                                  binary=self.root / "runtime/bin/mma-vision.exe",
                                  model_dir=self.root / "runtime/models/siglip-b16-224-canonical",
                                  use_nice=False, progress_callback=self.progress)
            accepted = int(result.get("accepted", 0))
            if not result.get("batches"):
                self.update(phase="ready", message="There are no available locations right now. You can check again later.")
                return
            with self.lock:
                self.state["completed"] += accepted
                self.state["pending"] = int(getattr(self.client, "pending", 0))
                self.state["units"] = int(result.get("units", self.state["units"] + int(result.get("unitsEarned", 0))))
                self.state["batchCompleted"] = 0
        self.update(phase="ready", message="Indexing paused. Completed batches are saved. Choose Start indexing to continue.")

    def resume_submissions(self):
        result = self.client.resume_submissions()
        with self.lock:
            self.state["pending"] = self.client.pending
            self.state["undelivered"] = self.client.undelivered
            self.state["completed"] += int(result.get("accepted", 0))
            self.state["units"] += int(result.get("unitsEarned", 0))
        return result


def handler_for(app: DesktopApp, token: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def authorized(self):
            host = f"127.0.0.1:{self.server.server_port}"
            origin = self.headers.get("Origin")
            return (self.headers.get("Host") == host
                    and origin in {None, "http://" + host}
                    and hmac.compare_digest(self.headers.get("X-Vision-Token", ""), token))

        def send(self, status, data, kind="application/json"):
            body = json.dumps(data).encode() if kind == "application/json" else data
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                return self.send(403, {"error": "Local access only."})
            if self.path == "/api/status":
                if not self.authorized():
                    return self.send(403, {"error": "Reopen VISION from the starter."})
                return self.send(200, app.snapshot())
            paths = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
            if self.path not in paths:
                return self.send(404, {"error": "Not found."})
            name, kind = paths[self.path]
            self.send(200, (WEB / name).read_bytes(), kind)

        def do_POST(self):
            if not self.authorized():
                return self.send(403, {"error": "Reopen VISION from the starter."})
            try:
                if self.headers.get_content_type() != "application/json":
                    raise DesktopError("invalid_request")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise DesktopError("invalid_request")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise DesktopError("invalid_request")
                result = {"ok": True}
                if self.path == "/api/prepare":
                    app.launch(app.prepare)
                elif self.path == "/api/connect":
                    result = app.connect(body.get("code"), create=body.get("create") is True)
                elif self.path == "/api/saved-code":
                    app.update(savedCode=True)
                elif self.path == "/api/start":
                    app.start()
                elif self.path == "/api/check-pc":
                    app.check_pc()
                elif self.path == "/api/stop":
                    app.stop.set()
                    app.update(stopping=True, message="Finishing the current batch, then pausing. Please keep this window open.")
                elif self.path == "/api/quit":
                    if app.state["busy"]:
                        raise DesktopError("busy")
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    return self.send(404, {"error": "Not found."})
                self.send(200, result)
            except (ValueError, json.JSONDecodeError):
                self.send(400, {"error": ERRORS["invalid_request"]})
            except Exception as error:
                app.record_failure(error)
                self.send(409 if str(error) == "busy" else 400, {"error": public_error(error)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    app = DesktopApp(args.root)
    if args.prepare_only:
        app.prepare()
        print("This PC is ready. No account was created and no imagery was retrieved.")
        return
    # Prevent two copies from leasing work from the same local working directory.
    guard = (app.root / "desktop.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            guard.seek(0); guard.write(b"0"); guard.flush(); guard.seek(0)
            msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        guard.close()
        print("VISION is already open. Use the existing VISION window.")
        return
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app, token))
    url = f"http://127.0.0.1:{server.server_port}/#{token}"
    instance_path = app.root / "instance.json"
    instance_path.write_text(json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8")
    if args.prepare:
        app.launch(app.prepare)
    print("VISION is open in your browser. Keep this window open while indexing.", flush=True)
    if args.no_browser:
        # Local test harness only; the bearer URL is never sent to the shared service.
        (app.root / "local-test-url.txt").write_text(url, encoding="utf-8")
    else:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        app.stop.set()
        print("Finishing the current batch before closing.")
    finally:
        app.stop.set()
        server.server_close()
        # Keep the single-instance lock until the current batch has finished.
        with app.operation:
            pass
        instance_path.unlink(missing_ok=True)
        (app.root / "local-test-url.txt").unlink(missing_ok=True)
        guard.close()


if __name__ == "__main__":
    main()
