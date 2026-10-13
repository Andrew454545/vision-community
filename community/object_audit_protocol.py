"""Finite saved-audit commands shared by private HTTP and owner-local delivery.

No listener, worker, credentials, downloads or activation are created here.
The independently pinned job registry remains the only assignment authority.
"""
from __future__ import annotations

import re


def audit_route(method, path):
    from .object_audit_jobs import JobError
    if not isinstance(method, str) or not isinstance(path, str) or len(path) > 128:
        raise JobError('not_found', 404)
    if method == 'POST' and path == '/object-audits':
        return 'submit', None
    job = re.fullmatch(r'/object-audits/([0-9a-f]{32})(?:/(cancel|retry|erase|retire|settlement-evidence))?', path)
    if job and method == 'GET' and job[2] is None:
        return 'status', job[1]
    if job and method == 'POST' and job[2]:
        return job[2], job[1]
    assignment = re.fullmatch(r'/object-assignments/([0-9a-f]{32})/erase', path)
    if method == 'POST' and assignment:
        return 'erase-assignment', assignment[1]
    raise JobError('not_found', 404)


def dispatch_object_audit(jobs, method, path, raw=None, *, require_retry_intent=False):
    from .native_scene_search import strict_json
    from .object_audit_jobs import MAX_REQUEST, JobError, require
    action, identity = audit_route(method, path)
    if action == 'status':
        require(raw is None)
        return jobs.get(identity)
    require(isinstance(raw, bytes) and 0 < len(raw) <= (MAX_REQUEST if action == 'submit' else 1024))
    try:
        body = strict_json(raw)
    except (ValueError, UnicodeError):
        raise JobError('invalid_object_job') from None
    require(isinstance(body, dict))
    if action == 'submit':
        require(type(body.get('version')) is int and body['version'] == 1)
        return jobs.submit(raw)
    if action == 'retire':
        return jobs.retire(identity, body)
    if action == 'retry':
        # New owner delivery must carry the existing durable nonce/CAS intent.
        # Replaying an old command may observe state, never start another retry.
        require(not require_retry_intent or set(body) == {'requestId', 'expectedAttempts'})
        return jobs.control(identity, action, body if body else None)
    require(body == {})
    if action == 'erase-assignment':
        return jobs.erase_assignment(identity)
    if action == 'settlement-evidence':
        return jobs.settlement_evidence(identity)
    return jobs.control(identity, action)
