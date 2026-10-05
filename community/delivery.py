"""Restart-safe delivery for both contribution lanes.

Inference and qualification stay in their lane-specific clients. This journal
never approves an index or awards credit; only a coherent service reply does.
"""
from pathlib import Path

from .contribute import CommunityClient, ContributeError, service_error_code
from .submission_outbox import SubmissionOutbox, MAX_PENDING_SUBMISSIONS, submission_result_state


class DurableCommunityClient(CommunityClient):
    def __init__(self, url):
        super().__init__(url)
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
        self.save_submission_result(lease_id, result)
        if result.get("rejected"):
            raise ContributeError("scene_submission_rejected", 422)
        return result

    def submit_object(self, lease_id, outputs, object_index):
        if self.outbox:
            self.outbox.remember_object(lease_id, outputs, object_index)
        result = super().submit_object(lease_id, outputs, object_index)
        if isinstance(result, dict) and result.get("pendingAudit"):
            raise ContributeError("invalid_submission_result", 503)
        self.save_submission_result(lease_id, result)
        if result.get("rejected"):
            raise ContributeError("object_submission_rejected", 422)
        return result

    def save_submission_result(self, lease_id, result):
        try:
            submission_result_state(lease_id, result)
            if self.outbox:
                self.outbox.result(lease_id, result)
        except ValueError as error:
            if str(error) != "invalid_submission_result":
                raise
            # A malformed acknowledgement cannot retire the saved delivery.
            raise ContributeError("invalid_submission_result", 503) from None

    def request(self, method, path, body=None):
        response = super().request(method, path, body)
        if (not self.outbox and method == "POST" and path == "/api/submissions"
                and body and "objectIndex" not in body and isinstance(response[1], dict)):
            self._pending += int(response[1].get("pending", 0))
        return response

    def audit_submission(self, submission_id):
        status, data, _ = super().request("POST", "/api/scene-audits", {"submissionId": submission_id})
        if status != 200:
            raise ContributeError(service_error_code(data, "verification_failed"), status)
        self.save_submission_result(submission_id, data)
        if data.get("rejected"):
            raise ContributeError("scene_submission_rejected", 422)
        return data

    def resume_submissions(self):
        accepted = earned = lost = 0
        if not self.outbox:
            return {"accepted": 0, "unitsEarned": 0}
        # Snapshot a bounded set of identities, then load one body at a time.
        # Object bundles can be much larger than Scene vectors. Loading sixteen
        # pending bundles together would unnecessarily multiply memory usage.
        for identity in self.outbox.pending(include_payload=False):
            lease_id = identity["lease_id"]
            delivery = self.outbox.pending_delivery(lease_id)
            if delivery is None:
                continue
            payload = self.outbox.decode_delivery(delivery)
            if delivery["state"] == "ready":
                try:
                    if delivery["lane"] == "object":
                        result = self.submit_object(lease_id, payload["outputs"], payload["objectIndex"])
                    else:
                        result = self.submit(lease_id, payload)
                except ContributeError as error:
                    definitive = (error.code, error.status) in {
                        ("expired_lease", 409), ("lease_lost", 409), ("unknown_lease", 404),
                    }
                    if not definitive or not self.outbox.lose_lease(lease_id, error.code):
                        raise
                    lost += 1
                    continue
            elif delivery["lane"] == "scene":
                result = self.audit_submission(lease_id)
            else:
                raise ValueError("invalid_saved_submission")
            if result.get("pendingAudit") and delivery["state"] == "ready":
                result = self.audit_submission(lease_id)
            accepted += int(result.get("accepted", 0))
            earned += int(result.get("unitsEarned", 0))
        result = {"accepted": accepted, "unitsEarned": earned}
        if lost:
            result["leaseLost"] = lost
        return result
