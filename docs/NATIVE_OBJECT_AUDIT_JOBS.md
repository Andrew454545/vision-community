# Saved private Object audit jobs

The [native Object auditor](NATIVE_OBJECT_AUDIT.md) can require several minutes.
`community.object_audit_jobs` now saves the job before acknowledging it, runs
native verification separately, and returns its decision through short status
requests. `deploy/cloudflare/native-object-verifier-bridge/worker.js` transports
that protocol through a private service binding. It does not expose a public API.

This is a tested operator component. Object device qualification, public
quarantine, publication, deletion integration and once-only credit settlement
still need to be connected. Neither a saved job nor an `approved` audit grants
an account permission or credit. All responses explicitly retain
`serverAuthorization: false` and `productionQualified: false`.

## Recovery behavior

- Repeating an identical submission returns the same job. Changed candidate
  bytes, assignment or policy for that lease produce a conflict.
- One service owns the private spool, and one native audit runs at a time.
  Cancelling an active job does not free its compute slot until that audit ends.
  A late approval cannot undo cancellation.
- A restart reuses the **same work folder**. A complete, correlated native
  receipt can be settled without rerunning inference. An incomplete or
  unconfirmed attempt retains its original report and files. Recovery records
  its unconfirmed state separately; it never rewrites the auditor's evidence.
- Failures remain pending, rather than becoming quality rejections. Explicit
  retries require a persisted backoff and stop after three attempts. Each
  attempt has a new folder. Polling or repeating the initial submission never
  silently starts another failed audit.
- A transient database error after native completion can recover the saved
  receipt during the next worker cycle, without restarting the service or
  recomputing the models. Shutdown refuses new work before releasing ownership.

## Operator inputs

Use the existing private Python runtime and an independently approved
`NativeObjectVerifier` policy, program, models and real protected import authority.
There are no default production profiles or numerical tolerances.

An independently pinned registry has `version: 1`,
`scope: "private-object-audit-registry"`, matching `policyId` and confirmed
Community `resource`, and an `assignments` list. Each entry has:

```json
{
  "leaseId": "OPERATOR_LEASE_ID",
  "profileId": "APPROVED_PROFILE_SHA256",
  "assignment": {"path": "ABSOLUTE_PRIVATE_ASSIGNMENT_PATH", "bytes": 123, "sha256": "TRUSTED_SHA256"},
  "source": {"path": "ABSOLUTE_PRIVATE_SOURCE_PATH", "bytes": 123, "sha256": "TRUSTED_SHA256"}
}
```

The example is a field description, not valid authority. The actual assignment
must pass the native auditor's exact source, pose, current official Gen4,
profile and protected-location guards. Preserve the source's exact bytes,
including its platform's line endings, when sealing an assignment. The service
does not rewrite candidate sources or accept assignment paths from callers.
It rechecks the registry, assignment, source, candidate and native receipt pins.

Set `VISION_OBJECT_VERIFIER_SECRET` privately to a random 32–256-character
printable ASCII secret without spaces. Do not put it in source, arguments or logs.

```text
python -B -m community.object_audit_jobs --binary <private-program> --models <private-models> --policy <private-policy.json> --policy-sha256 <trusted-pin> --registry <private-registry.json> --registry-sha256 <trusted-pin> --work <persistent-private-spool> --port 8768
```

The service listens only on `127.0.0.1`; trusted authenticated HTTPS ingress is
required for remote use. The bridge uses separately configured private
`NATIVE_OBJECT_VERIFIER_ORIGIN` and `NATIVE_OBJECT_VERIFIER_SECRET`, forwards its
own authentication, refuses redirects and strips all unrelated response fields
and credentials. Its request, fetch and response reads share a 20-second limit.
Native processing keeps the existing independently pinned four-location /
900-second ceiling; HTTP acknowledgement does not wait for inference.

The service's endpoints are:

| Method and path | Body / result |
|---|---|
| `POST /object-audits` | `version`, `leaseId`, `profileId`, `policyId`, `assignmentSha256`, `submissionSha256`, and the existing `objectIndex` transport. Returns a saved job. |
| `GET /object-audits/<jobId>` | Returns the correlated saved state and native receipt hash; no source data or native logs. |
| `POST /object-audits/<jobId>/retry` | `{}`; explicitly retries an eligible failed job within backoff and attempt limits. |
| `POST /object-audits/<jobId>/cancel` | `{}`; revokes the job's decision, including an approval that arrives later. |

The trusted caller must bind `submissionSha256` to its own quarantined payload
and reconcile every response with that candidate and account before settlement.
The service also fingerprints the complete request; an uploader-supplied hash
cannot make changed bytes an idempotent replay.

## Finite component limits

This first private cohort service accepts at most 64 retained jobs, eight
staging/queued/running jobs, 512 MiB of input and two HTTP connections. Bodies
are limited to 4 MiB; each new job requires at least 1 GiB of free space plus its
input size. The native auditor separately checks feature and location limits.
Capacity exhaustion stops new work safely. Evidence is retained, rather than
automatically deleted or recycled. A changed registry or policy requires a
separate spool; it cannot silently reinterpret old jobs.

These limits support a controlled integration cohort, not indefinite public
capacity. Before deployment, connect authenticated hosted qualification,
quarantine ownership, privacy revocation/cleanup, publication and credit
settlement; add measured retention/cost/capacity and provider restart tests.
No bridge binding, public route or readiness flag was enabled by this change.

## Verification

[Recorded evidence](evidence/object-audit-jobs-20261010.json) includes real
Windows SQLite/filesystem and HTTP checks, an abruptly terminated separate
Python process followed by a fresh verifier host, and actual local workerd
transport tests. Native inference in these new tests uses an explicit synthetic
runner. Actual Mac execution, authentic Object acceptance, genuinely earned
search credit and the seven-day accepted-work soak remain required.
