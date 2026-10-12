# Native Object registry rollover

The private auditor can now add independently trusted assignments without
abandoning its saved jobs. A version-2 registry pins the previous registry and
keeps its entire assignment list as an exact prefix. Every old lease, profile,
path, byte count and hash remains unchanged. The runtime policy hash must match
the spool's existing policy; this does not authorize a policy/runtime change.

The service validates all assignments before atomically recording the registry
extension and updating its identity. A failed transaction preserves the original
identity and jobs. Restart is idempotent; rollback, forks, removed/reordered
assignments and changed historical entries are refused. Original registry files,
attempts, retry nonces, receipts and deletion tombstones remain available.

## Operator procedure

Use the existing private Python runtime. Prepare a separately pinned version-1
registry containing only the new trusted assignments, at most 64 per extension.
These inputs must come from operator authority, never an uploader's request.

```text
python -B -m community.object_audit_registry --previous <current-registry.json> --previous-sha256 <current-pin> --additions <trusted-new-assignments.json> --additions-sha256 <new-assignments-pin> --out <new-private-registry.json>
```

The helper creates a new file and returns its SHA-256 and counts. It does not
validate native inference or grant admission. Gracefully stop the private
auditor, retaining its spool; restart with the new registry and returned pin,
the **same** policy pin and the **same** work folder. Startup performs the full
assignment validation. Preserve the previous files and exact failed outputs.

An older installed runtime's source policy cannot simply be rewritten to match
new code: it requires a separate verified policy/spool migration. This command
only extends registries under one already-installed, pinned runtime policy.
No installed runtime or existing spool is upgraded by this source change.

## Bounds and recovery

Version 1 retains its 64-assignment/job limit. Version 2 supports at most 4,096
assignments/jobs and an 8 MiB registry. Eight unfinished native jobs, 512 MiB of
retained input, 1 GiB free-space reserve, two HTTP handlers and three attempts
remain unchanged. No evidence is automatically deleted to create capacity.
This removes the prototype's immediate 64-job barrier; it is **not indefinite
storage**. Terminal retention, trusted assignment automation and measured
capacity remain launch work.

Current deletion/cancellation recovery binds the complete extended registry,
including old leases. The closed-database exporter and Python consumer support
the larger registry; old registry pins cannot authorize its recovery. The
independent current ledger and ten-minute authority window remain mandatory.
An authority over 1 MiB fails before export success; it is never truncated.

Portable live protection and authentic qualification remain separate gaps.
The existing one-hour live-origin guard is unchanged. No source capture becomes
portable approval, and no real work, credit or deployment is claimed here.
See [verification evidence](evidence/object-registry-rollover-20261012.json).
