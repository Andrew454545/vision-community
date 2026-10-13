"""Inert owner-local Object verification, without an incoming web connection.

An explicitly activated future outbound worker can call this interface. Queue
transport, authentication, publication and financial authority remain separate.
The current operational hold forbids real activation or model/provider tests.
"""
from __future__ import annotations

import os
import re

from .object_audit_jobs import ObjectAuditJobs, JobError
from .object_audit_protocol import audit_route, dispatch_object_audit
from .search_snapshot import encoded

MAX_RESPONSE = 65536
HEX = re.compile(r'[0-9a-f]{64}\Z')
ID = re.compile(r'[0-9a-f]{32}\Z')
POLICY = re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')
JOB_KEYS = {'version','jobId','leaseId','profileId','policyId','assignmentSha256','submissionSha256',
            'candidateManifestSha256','state','decision','attempts','retryAt','receiptSha256',
            'serverAuthorization','productionQualified','acceptedContributions','searchCreditsCreated'}
EVIDENCE_KEYS = {'audit','policySha256','runtimeProfileSha256','qualityImplementationIdentity',
                 'protectedAuthoritySha256','protectedOriginHandoffSha256','resource','qualificationScope','issuedAt','expiresAt'}
ERASURE_KEYS = {'version','leaseId','policyId','assignmentSha256','state','serverAuthorization','productionQualified'}
ERRORS = {
    'invalid_object_job': 400, 'invalid_object_job_file': 400, 'not_found': 404,
    'unknown_object_assignment': 403, 'unknown_object_job': 404,
    'object_job_identity_mismatch': 409, 'object_job_conflict': 409,
    'object_job_control_conflict': 409, 'object_job_source_mismatch': 409,
    'object_assignment_revoked': 409, 'object_job_retirement_conflict': 409,
    'object_job_retirement_unavailable': 409, 'object_job_candidate_incomplete': 409,
    'object_job_retry_limited': 429, 'object_job_capacity_reached': 503,
    'object_job_disk_budget': 503, 'object_job_queue_full': 503,
}


def job_response(value):
    return (isinstance(value, dict) and set(value) == JOB_KEYS
        and type(value['version']) is int and value['version'] == 1
        and all(isinstance(value[k], str) and ID.fullmatch(value[k]) for k in ('jobId','leaseId'))
        and isinstance(value['policyId'], str) and POLICY.fullmatch(value['policyId'])
        and all(isinstance(value[k], str) and HEX.fullmatch(value[k]) for k in
                ('profileId','assignmentSha256','submissionSha256','candidateManifestSha256'))
        and value['state'] in {'staging','queued','running','approved','rejected','failed','cancelled','retiring','retired','erasing','erased'}
        and value['decision'] == (value['state'] if value['state'] in {'approved','rejected'} else 'pending')
        and type(value['attempts']) is int and 0 <= value['attempts'] <= 3
        and type(value['retryAt']) is int and value['retryAt'] >= 0
        and (value['receiptSha256'] is None or isinstance(value['receiptSha256'], str) and HEX.fullmatch(value['receiptSha256']))
        and value['serverAuthorization'] is False and value['productionQualified'] is False
        and all(type(value[k]) is int and value[k] == 0 for k in ('acceptedContributions','searchCreditsCreated')))


class OwnerObjectVerifier:
    """Reuse the real durable auditor without binding a port or starting a loop.

    The caller owns the already-pinned jobs instance and supplies an activation
    guard. run_next() is a separate, finite owner action; submit/status/control
    never start inference. Native guards, deadlines, attempts and reports stay
    with ObjectAuditJobs and NativeObjectVerifier.
    """

    def __init__(self, jobs, *, guard):
        if not isinstance(jobs, ObjectAuditJobs) or not callable(guard) or jobs.worker is not None:
            raise ValueError('owner_object_configuration_required')
        self.jobs, self.guard = jobs, guard

    def _marker(self):
        if (self.jobs.work/'STOP').exists():
            return 'stopped'
        if (self.jobs.work/'PAUSE').exists():
            return 'paused'
        return None

    def _failure(self):
        # Preserve only the first fixed diagnostic; arbitrary exception details
        # or private native paths never enter a transport response or this file.
        try:
            fd = os.open(self.jobs.work/'owner-object.failure.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded({'success': False, 'error': 'owner_object_operator_required'}))
                stream.flush(); os.fsync(stream.fileno())
        except FileExistsError:
            pass

    def _response(self, method, path, value):
        action, identity = audit_route(method, path)
        if action == 'settlement-evidence':
            valid = (isinstance(value, dict) and set(value) == EVIDENCE_KEYS
                and job_response(value['audit']) and value['audit']['jobId'] == identity
                and value['audit']['state'] == 'approved' and value['qualificationScope'] == 'batch-only'
                and all(isinstance(value[k], str) and HEX.fullmatch(value[k]) for k in EVIDENCE_KEYS
                        if k.endswith('Sha256') or k == 'qualityImplementationIdentity')
                and value['resource'] == self.jobs.verifier.document['resource']
                and type(value['issuedAt']) is int and value['issuedAt'] >= 0
                and type(value['expiresAt']) is int and value['expiresAt'] == value['issuedAt'] + 30)
        elif action == 'erase-assignment':
            valid = (isinstance(value, dict) and set(value) == ERASURE_KEYS
                and type(value['version']) is int and value['version'] == 1 and value['leaseId'] == identity
                and isinstance(value['policyId'], str) and POLICY.fullmatch(value['policyId'])
                and isinstance(value['assignmentSha256'], str) and HEX.fullmatch(value['assignmentSha256'])
                and value['state'] in {'erasing','erased'}
                and value['serverAuthorization'] is False and value['productionQualified'] is False)
        else:
            valid = job_response(value) and (action == 'submit' or value['jobId'] == identity)
        if not valid or len(encoded(value)) > MAX_RESPONSE:
            raise ValueError('owner_object_response_invalid')

    def handle(self, method, path, raw=None):
        """Return (status, bounded document) for one fixed private audit command.

        Not an authentication boundary. Only a future authenticated coordinator
        may supply commands; never expose this interface to uploaders directly.
        No response cache can renew or replay expired protection evidence.
        """
        try:
            if self._marker():
                return 503, {'error': 'object_verifier_paused'}
            self.guard()
            result = dispatch_object_audit(self.jobs, method, path, raw, require_retry_intent=True)
            self.guard()
            if self._marker():
                return 503, {'error': 'object_verifier_paused'}
            self._response(method, path, result)
            return 200, result
        except JobError as error:
            code = str(error)
            if code in ERRORS and ERRORS[code] == error.status:
                return error.status, {'error': code}
        except Exception:
            pass
        self._failure()
        return 503, {'error': 'object_verifier_unavailable'}

    def work_once(self):
        """One bounded local audit/erase/retire step; never starts a background job."""
        marker = self._marker()
        if marker:
            return {'status': marker}
        try:
            self.guard()
            if self.jobs.worker is not None:
                raise ValueError('owner_object_worker_already_started')
            worked = self.jobs.run_next()
            self.guard()
            return {'status': self._marker() or ('worked' if worked else 'idle')}
        except Exception:
            self._failure()
            return {'status': 'operator_required', 'error': 'owner_object_operator_required'}
