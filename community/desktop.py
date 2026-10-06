"""Private, loopback-only guided contributor. No third-party packages."""
from __future__ import annotations

import argparse
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from community.bootstrap import BootstrapError, install_runtime, load_manifest, runtime_platform
from community.contribute import ContributeError, DEFAULT_URL, SERVICE_ERROR_CODES
from community.vision_index import (default_runner, index_from_queue, parse_json_stdout, require_layout,
                                    program_name, VisionIndexError, RETRYABLE_NATIVE_CODES)
from community.pc_canary import (run_canary, canary_profile_matches, released_canary_policy,
                                 compact_approved_canary)
from community.delivery import DurableCommunityClient
from community.work_plan import WorkPlan
from community.object_index import index_from_queue as object_index_from_queue

WEB = Path(__file__).with_name("desktop_web")
ERRORS = {
    "invalid_work_selection": "Your saved work choice could not be read safely. Your files are kept for review.",
    "unfinished_lane_needs_recovery": "An unfinished batch needs to resume first. Keep the current work choice until that batch finishes.",
    "object_pc_check_unavailable": "The Object computer check is not available yet. Choose Scenes, or wait for the Object release.",
    "object_pc_check_required": "Run and pass the Object computer check before processing Objects.",
    "object_qualification_rejected": "The service did not approve the Object check. Its report is saved for review.",
    "schema_update_required": "The service is being updated. Your saved work is kept. Try again later.",
    "rate_limit_unavailable": "The service is temporarily unavailable. Your saved work is kept. Try again later.",
    "service_maintenance": "The service is being updated. Your saved work is kept. Try again later.",
    "network_error": "The service could not be reached. Check your connection and try again.",
    "invalid_submission_result": "The service reply could not be confirmed. Your saved work is kept. Try again later.",
    "service_redirect_refused": "The service sent an unexpected reply. Your account code and saved work are kept. Try again later.",
    "service_response_limit": "The service reply could not finish safely. Your saved work is kept. Try again later.",
    "runtime_download_failed": "A download was interrupted. Check your connection and choose Download again; verified files will be reused.",
    "runtime_mismatch": "A downloaded file failed its safety check. It was not used. Try downloading again.",
    "unsupported_platform": "This preview supports Intel or AMD Windows PCs and Apple silicon Macs. A compatible download for this computer is not ready yet.",
    "recovery_failed": "That account code was not accepted. Check it and try again.",
    "invalid_recovery": "That account code was not accepted. Check it and try again.",
    "object_submission_rejected": "The service rejected this Object batch. Processing has stopped and your results are saved for review.",
    "object_verification_unavailable": "Object contributions are not available yet. Your saved work is kept.",
    "unauthorized": "Please reconnect your account using your saved code.",
    "scene_verification_unavailable": "VISION is not open for contributions yet. You have done nothing wrong. Close VISION and come back when the project maintainer announces it is ready.",
    "vision_scene_runtime_update_required": "Your VISION processing program needs an update. Get the latest VISION download and choose Set up this computer again. Your saved work and account code are kept.",
    "vision_object_runtime_update_required": "Object processing needs newer files. Your saved work is kept. Update VISION when the new object download is available.",
    "scene_reference_required": "The service has not approved this batch for contribution. Your local evidence has been kept.",
    "verification_failed": "The service did not accept this batch. Your local results have been kept for review.",
    "busy": "Another action is still running. Please wait for it to finish.",
    "account_required": "Connect an account first.",
    "save_code_first": "Confirm that you have saved your account code before indexing.",
    "runtime_not_ready": "Download and check the processing files first.",
    "pc_check_required": "Run the short computer check before indexing. Approval must be current and match these processing files.",
    "scene_qualification_required": "Your computer approval is missing or has expired. Run the short computer check again.",
    "canary_failed": "The computer check could not finish. Its report and logs have been kept. You can retry.",
    "pc_check_files_invalid": "The computer check files could not be verified. Choose Set up this computer again. Your saved work and account code are kept.",
    "scene_qualification_rejected": "The service could not approve this computer's check. Its report has been kept for review.",
    "scene_device_not_qualified": "The service could not approve this computer's check. Its report has been kept for review.",
    "scene_device_qualification_required": "Run the short computer check before indexing.",
    "scene_qualification_changed": "The computer approval changed. Run the short computer check again.",
    "scene_submission_rejected": "The service rejected this batch. Processing has stopped and your results are saved for review.",
    "scene_audit_backlog": "Your completed batches are waiting for verification. Processing will continue when they have been checked.",
    "invalid_request": "That request could not be used. Refresh the page and try again.",
    "indexer_timeout": "This batch reached its time limit. It has stopped and its logs were kept.",
    "indexer_no_progress": "The indexer stopped making progress. Its logs were kept for review.",
    "indexer_cancelled": "Indexing stopped. Your completed batches are safe.",
    "storage_check_failed": "Saved files could not be checked safely. Processing stopped and your files were kept. Ask the maintainer to review the local storage report.",
    "keep_awake_failed": "This computer could not accept VISION's sleep request. Processing stopped and your work was kept. Ask the maintainer to review the saved report.",
    "keep_awake_release_failed": "This computer could not release VISION's sleep request. The worker has stopped and your work was kept. Ask the maintainer to review the saved report.",
}


class DesktopError(RuntimeError):
    pass


class DesktopClient(DurableCommunityClient):
    """Bind each lease to that lane's configuration checked on this computer."""
    def __init__(self, url):
        super().__init__(url)
        self.profile_id = None
        self.object_profile_id = None

    def request(self, method, path, body=None):
        if method == "POST" and path == "/api/leases" and body and body.get("lane") == "scene":
            if not self.profile_id:
                raise DesktopError("pc_check_required")
            body = {**body, "profileId": self.profile_id}
        if method == "POST" and path == "/api/leases" and body and body.get("lane") == "object":
            if not self.object_profile_id:
                raise DesktopError("object_pc_check_required")
            body = {**body, "profileId": self.object_profile_id}
        return super().request(method, path, body)


def public_error(error):
    code = getattr(error, "code", None) or str(error)
    if isinstance(code, str) and code in ERRORS:
        return ERRORS[code]
    return "This action could not finish. Local diagnostic information was saved; you can retry or share it with the maintainer."


class DesktopApp:
    def __init__(self, root: Path, *, url=DEFAULT_URL, client_factory=DesktopClient,
                 indexer=index_from_queue, canary=run_canary, profile_matches=canary_profile_matches,
                 object_indexer=object_index_from_queue, object_canary=None, object_profile_matches=None):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.url, self.client_factory, self.indexer = url, client_factory, indexer
        self.canary, self.profile_matches = canary, profile_matches
        self.object_indexer = object_indexer
        self.object_canary, self.object_profile_matches = object_canary, object_profile_matches
        self.work_plan = WorkPlan(self.root)
        self.object_canary_report = None
        self.object_qualification = None
        self.lock = threading.RLock()
        self.operation = threading.Lock()
        self.batch_operation = threading.Lock()
        self.stop = threading.Event()
        self.client = None
        self.canary_report = None
        self.qualification = None
        try:
            self.canary_report = json.loads((self.root / "pc-check.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        try:
            self.object_canary_report = json.loads((self.root / "object-pc-check.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.last_seen = time.monotonic()
        self.state = dict(ready=False, connected=False, savedCode=False, busy=False,
                          phase="setup", message="Prepare this computer to begin.", completed=0,
                          units=0, batchCompleted=0, batchTotal=16, started=None,
                          stopping=False, serviceReady=False, qualified=False, pending=0, undelivered=0,
                          backgroundAvailable=sys.platform == 'win32')
        self.state.update(workType=self.work_plan.work_type, activeLane=None,
                          laneApprovals={"scene": False, "object": False},
                          laneAvailability={"scene": None, "object": False})

    @property
    def assets(self):
        return {"binary": self.root / "runtime/bin" / program_name("mma-vision"),
                "model_dir": self.root / "runtime/models/siglip-b16-224-canonical"}

    @property
    def object_assets(self):
        folder = "bin" if sys.platform == "win32" else "object-runtime"
        return {"binary": self.root / "runtime" / folder / program_name("vision-object"),
                "model_dir": self.root / "runtime/models/object-hybrid-v1"}

    def select_work(self, work_type):
        if not self.operation.acquire(blocking=False):
            raise DesktopError("busy")
        batch_locked = False
        try:
            if not self.batch_operation.acquire(blocking=False):
                raise DesktopError("busy")
            batch_locked = True
            self.work_plan.select(work_type)
            self.update(workType=work_type, ready=False, qualified=False, phase="setup",
                        message="Work choice saved. Set up this computer for the selected work.")
        finally:
            if batch_locked:
                self.batch_operation.release()
            self.operation.release()

    def reload_work_plan(self):
        # Read under the shared folder lock before owning any native work.
        self.work_plan = WorkPlan(self.root)
        self.update(workType=self.work_plan.work_type)

    def update_approvals(self):
        approvals = {"scene": self.qualification is not None, "object": self.object_qualification is not None}
        self.update(laneApprovals=approvals, qualified=all(approvals[lane] for lane in self.work_plan.lanes))

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
        code = str(error) if isinstance(error, DesktopError) else getattr(error, "code", None)
        if (not isinstance(code, str)
                or code not in ERRORS and code not in SERVICE_ERROR_CODES and code not in RETRYABLE_NATIVE_CODES):
            code = type(error).__name__
        report = {"status": "INCOMPLETE", "error_type": type(error).__name__, "code": code,
                  "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        status = getattr(error, "status", None)
        if type(status) is int and 100 <= status <= 599:
            report["http_status"] = status
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
                self.update(busy=False, stopping=False, started=None, activeLane=None)
                self.operation.release()
        thread = threading.Thread(target=work, name="vision-desktop-job", daemon=False)
        thread.start()
        return thread

    def prepare(self):
        self.qualification = None
        self.object_qualification = None
        if self.client:
            self.client.profile_id = None
            self.client.object_profile_id = None
        self.update_approvals()
        self.update(qualified=False)
        self.update(phase="download", message="Checking processing files. Downloads may take a few minutes.", ready=False)
        if runtime_platform() not in {"windows-x86_64", "darwin-arm64"}:
            raise BootstrapError("unsupported_platform")
        if "object" in self.work_plan.lanes:
            self.capabilities(self.client or self.client_factory(self.url))
        manifest = load_manifest()
        lane = "all" if self.work_plan.work_type == "both" else self.work_plan.work_type
        install_runtime(manifest, self.root / "runtime", lane=lane,
                        progress=lambda n, total: self.update(message=f"Checking and downloading file {n} of {total}. Please keep this window open."))
        if "scene" in self.work_plan.lanes:
            self.release_pc_check(manifest)
            binary = self.assets['binary']
            code, stdout, _ = default_runner([str(binary), "index-layout"], os.environ.copy(), self.root)
            if code:
                raise VisionIndexError("vision_binary_failed")
            require_layout(parse_json_stdout(stdout))
        self.update(ready=True, phase="ready", message="Setup complete. Go to step 2 to create an account or use your saved code.")

    def release_pc_check(self, manifest=None):
        try:
            return released_canary_policy(load_manifest() if manifest is None else manifest,
                                          self.root / 'runtime', platform_name=runtime_platform())
        except (OSError, ValueError, BootstrapError):
            raise DesktopError('pc_check_files_invalid') from None

    def capabilities(self, client):
        try:
            status, value, _ = client.request("GET", "/api/capabilities")
        except ContributeError as error:
            if error.status in {404, 405}:
                raise DesktopError("scene_verification_unavailable") from error
            raise
        scene = value.get("sceneContributions", {}) if isinstance(value, dict) else {}
        objects = value.get("objectContributions", {}) if isinstance(value, dict) else {}
        scene_ready = (isinstance(scene, dict) and scene.get("model") == "vision-four-view-v4"
                       and scene.get("ready") is True and scene.get("deviceQualificationRequired") is True
                       and scene.get("canaryLocations") == 112)
        object_ready = (isinstance(objects, dict) and objects.get("model") == "vision-object-index-v4"
                        and objects.get("ready") is True and objects.get("deviceQualificationRequired") is True
                        and objects.get("officialGen4Required") is True
                        and self.object_canary is not None and self.object_profile_matches is not None)
        self.update(laneAvailability={"scene": scene_ready, "object": object_ready})
        if status != 200 or not isinstance(value, dict) or value.get("version") != 1 or "scene" in self.work_plan.lanes and not scene_ready:
            self.update(serviceReady=False)
            raise DesktopError("scene_verification_unavailable")
        if "object" in self.work_plan.lanes and not object_ready:
            self.update(serviceReady=False)
            raise DesktopError("object_verification_unavailable")
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
            self.object_qualification = None
            self.update(connected=True, savedCode=not create, phase="ready", units=int(me.get("units", 0)),
                        qualified=False, pending=client.pending, undelivered=client.undelivered,
                        message="Account connected. Run the short computer check next.")
            if "scene" in self.work_plan.lanes and self.canary_report and self.profile_matches(self.canary_report, **self.assets):
                profile = self.canary_report["runtimeProfile"]["sha256"]
                _, previous, _ = client.request("GET", "/api/scene-qualifications?profileId=" + profile)
                self.set_qualification(previous)
            if ("object" in self.work_plan.lanes and self.object_canary_report and self.object_profile_matches
                    and self.object_profile_matches(self.object_canary_report, **self.object_assets)):
                profile = self.object_canary_report["runtimeProfile"]["sha256"]
                _, previous, _ = client.request("GET", "/api/object-qualifications?profileId=" + profile)
                self.set_object_qualification(previous)
            if self.snapshot()["qualified"]:
                self.update(message="This computer's existing approvals are current. You can start helping.")
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
        if (not isinstance(value, dict) or value.get("qualified") is not True or not profile
                or value.get("profileId") != profile
                or type(value.get("expiresAt")) not in (int, float)
                or not math.isfinite(value["expiresAt"]) or not time.time() < value["expiresAt"]):
            self.qualification = None
            if self.client:
                self.client.profile_id = None
            self.update_approvals()
            return False
        self.qualification = value
        self.client.profile_id = profile
        self.update_approvals()
        return True

    def set_object_qualification(self, value):
        profile = (self.object_canary_report or {}).get("runtimeProfile", {}).get("sha256")
        if (not isinstance(value, dict) or value.get("qualified") is not True or not profile
                or value.get("lane") != "object" or value.get("profileId") != profile
                or type(value.get("expiresAt")) not in (int, float)
                or not math.isfinite(value["expiresAt"]) or not time.time() < value["expiresAt"]):
            self.object_qualification = None
            if self.client:
                self.client.object_profile_id = None
            self.update_approvals()
            return False
        self.object_qualification = value
        self.client.object_profile_id = profile
        self.update_approvals()
        return True

    def check_pc(self):
        self.require_account()
        return self.launch(self.qualify)

    def qualify(self):
        self.capabilities(self.client)
        notices = []
        for lane in self.work_plan.lanes:
            if lane == "scene":
                notice = self.qualify_scene()
                if notice:
                    notices.append(notice)
            else:
                self.qualify_object()
        self.update(activeLane=None, phase="ready", message="Computer approved for your selected work. Go to step 4 and choose Start helping." +
                    (" " + " ".join(notices) if notices else ""))

    def qualify_scene(self):
        self.capabilities(self.client)
        self.qualification = None
        self.update_approvals()
        self.update(qualified=False, phase="checking", started=time.monotonic(),
                    batchCompleted=0, batchTotal=112,
                    message="Checking 112 locations on this computer. Please keep this window open.")
        folder = self.root / "checks" / (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4))
        policy = self.release_pc_check()
        self.canary_report = self.canary(folder, **self.assets, policy=policy, progress_callback=self.progress)
        if self.canary_report.get("status") != "COMPLETE" or not self.profile_matches(self.canary_report, **self.assets):
            raise DesktopError("canary_failed")
        # This contains public fixture results and processing-file hashes, never account codes.
        (self.root / "pc-check.json").write_text(json.dumps(self.canary_report), encoding="utf-8")
        self.update(message="computer check complete. Asking the service to verify the results.")
        _, decision, _ = self.client.request("POST", "/api/scene-qualifications", self.canary_report["submission"])
        if not self.set_qualification(decision):
            raise DesktopError("scene_qualification_rejected")
        message = "Scene computer check approved. Your selected work can start after every required check passes."
        cleanup_notice = None
        try:
            compact_approved_canary(folder, self.canary_report, decision, policy)
        except Exception as error:
            # Approval stands; cleanup failure must not erase evidence or rerun inference.
            message = "Scene check approved. Temporary check files could not be fully cleared; the cleanup report was kept."
            cleanup_notice = message
            try:
                (self.root/'pc-check-cleanup-failure.json').write_text(json.dumps({
                    'status':'INCOMPLETE', 'errorType':type(error).__name__,
                    'code':'pc_check_temporary_cleanup_incomplete'}, indent=2), encoding='utf-8')
            except OSError:
                message = "Scene check approved. Temporary file cleanup was interrupted. Check your free space before continuing."
                cleanup_notice = message
        self.update(phase="ready", message=message, batchCompleted=0, batchTotal=16)
        return cleanup_notice

    def qualify_object(self):
        if self.object_canary is None or self.object_profile_matches is None:
            raise DesktopError("object_pc_check_unavailable")
        self.object_qualification = None
        self.update_approvals()
        self.update(phase="checking", activeLane="object", started=time.monotonic(),
                    batchCompleted=0, batchTotal=0, message="Checking the Object processing files and fixed reference inputs.")
        folder = self.root / "object-checks" / (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4))
        report = self.object_canary(folder, **self.object_assets, progress_callback=self.progress)
        if (not isinstance(report, dict) or report.get("status") != "COMPLETE"
                or not self.object_profile_matches(report, **self.object_assets)):
            raise DesktopError("canary_failed")
        self.object_canary_report = report
        (self.root / "object-pc-check.json").write_text(json.dumps(report), encoding="utf-8")
        _, decision, _ = self.client.request("POST", "/api/object-qualifications", report["submission"])
        if not self.set_object_qualification(decision):
            raise DesktopError("object_qualification_rejected")
        self.update(phase="ready", activeLane=None, message="Object computer check approved. Your selected work can start after every required check passes.")

    def require_qualification(self):
        self.require_account()
        if "scene" in self.work_plan.lanes and (not self.profile_matches(self.canary_report, **self.assets)
                or not self.set_qualification(self.qualification)):
            self.update(qualified=False)
            raise DesktopError("pc_check_required")
        if "object" in self.work_plan.lanes and (not self.object_profile_matches
                or not self.object_profile_matches(self.object_canary_report, **self.object_assets)
                or not self.set_object_qualification(self.object_qualification)):
            raise DesktopError("object_pc_check_required")

    def run_batch(self, *, progress_callback=None):
        if not self.batch_operation.acquire(blocking=False):
            raise DesktopError("busy")
        try:
            self.require_qualification()
            lane = self.work_plan.begin()
            self.update(activeLane=lane, batchCompleted=0, batchTotal=0,
                        message=("Processing a Scene batch." if lane == "scene" else
                                 "Processing an Object location. This can take several minutes; please keep VISION open."))
            indexer = self.indexer if lane == "scene" else self.object_indexer
            arguments = dict(url=self.url, pace="slow", batches=1, count=16 if lane == "scene" else 1,
                             client=self.client, persist_session=False, use_nice=False,
                             work_dir=self.root / ("indexes" if lane == "scene" else "object-indexes"),
                             **(self.assets if lane == "scene" else self.object_assets))
            if lane == "scene" and progress_callback:
                arguments["progress_callback"] = progress_callback
            result = indexer(**arguments)
            self.work_plan.finish(lane)
            return result
        finally:
            self.update(activeLane=None)
            self.batch_operation.release()

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
        self.update(phase="indexing", message="Processing locations on this computer. Results wait for a service check before joining the search pool.",
                    batchCompleted=0, batchTotal=0, started=time.monotonic())
        empty_lanes = set()
        while not self.stop.is_set():
            if time.monotonic() - self.last_seen > 60:
                break
            self.resume_submissions()
            lane = self.work_plan.next_lane
            result = self.run_batch(progress_callback=self.progress)
            accepted = int(result.get("accepted", 0))
            if not result.get("batches"):
                empty_lanes.add(lane)
                if all(selected in empty_lanes for selected in self.work_plan.lanes):
                    self.update(phase="ready", message="There are no available locations right now. You can check again later.")
                    return
                continue
            empty_lanes.discard(lane)
            with self.lock:
                self.state["completed"] += accepted
                self.state["pending"] = int(getattr(self.client, "pending", 0))
                self.state["units"] = int(result.get("units", self.state["units"] + int(result.get("unitsEarned", 0))))
                self.state["batchCompleted"] = 0
        self.update(phase="ready", message="Processing paused. Your completed work is saved. Choose Start helping to continue.")

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
                elif self.path == "/api/work-type":
                    app.select_work(body.get("workType"))
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
    # Set by the starters inside an installed native app, so the page names
    # that app's buttons instead of files in an extracted download folder.
    parser.add_argument("--native-app", action="store_true")
    args = parser.parse_args()
    app = DesktopApp(args.root)
    app.state["nativeApp"] = args.native_app
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
    app.reload_work_plan()
    if args.prepare_only:
        try:
            app.prepare()
            print("Processing files are ready. No account was created and no imagery was retrieved.")
        finally:
            guard.close()
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
