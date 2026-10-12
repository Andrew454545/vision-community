# Owner search runner

**Source only; not activated or installed.** The [cost hold](COST_STOP_20261012.md)
continues. This is an operator component, not a contributor setup step. No real
credential, model, account, scheduler task or cloud service was accessed to build it.

[`owner-search.py`](../owner-search.py) now connects the pinned Scene/Object
engines, exact-origin OS credential reader, durable completion outbox and paced
supervisor. A process lock prevents competing runners, including while waiting.
The private Python can invoke it with `-I -B`, ignoring `PYTHONPATH` and user
packages. Windows startup must use the private `pythonw.exe`; no console is needed.
Importing the module or displaying help starts nothing.

## Private configuration

The JSON has exactly `version: 1`, `scope: "vision-owner-search-service-v1"`,
`origin`, `environment`, `state` and `lanes`. The origin is an exact canonical
HTTPS origin; the environment is `staging` or `production`. Use an existing
operator-private state folder outside the source checkout and native inputs.
All paths must be absolute and have no linked ancestors. No credential belongs
in this file, process arguments or environment.

`lanes` contains `scene`, `object` or both. Each definition has `policyId`,
`runtime`, `runtimeSha256`, `snapshot` and `snapshotSha256`. Objects additionally
require `binary` and `models`. These are independent approved native runtime and
contributor-only snapshot pins, not uploader reports. The runner verifies the
runtime policy and snapshot resource before constructing each native engine.
Full source/model/runtime/snapshot checks remain the engines' responsibility;
strict official Gen4 and gateway publication/payment checks are unchanged.

The operator pins the exact configuration bytes with SHA-256. Native engines and
OS credentials load lazily: deferred/blocked restarts do not read a vault or load
models. A saved completion can replay after restart even when native assets are
unavailable; it is never recomputed or retargeted to new pins. Native scratch is
under `state/native-scene` or `state/native-object`. Child `TEMP`, `TMP` and
`TMPDIR` point to that query's private scratch folder.

## Explicit activation boundary

There is no activation writer or automatic task installer. After the separate
budget/resource/deployment and acceptance decisions, an authorized operator must
deliberately supply `state/ACTIVATE.private.json`. Its exact fields are
`version: 1`, `scope: "explicit-owner-search-activation"`, `approved: true`,
`configSha256`, `origin` and `environment`, matching the pinned configuration.
This local marker prevents accidental starts; it does not independently prove
owner permission, valid release evidence or an affordable hosting plan.

The future invocation is the selected private interpreter with `-I -B`, the
absolute `owner-search.py` path, `--config ABSOLUTE_PRIVATE_CONFIG_PATH` and
`--config-sha256 INDEPENDENT_CONFIG_SHA256`. `--once` performs one paced step;
otherwise the explicit loop uses interruptible waits. PAUSE/STOP win, and no
command clears them or a connection latch. Authentication/configuration faults
stop for operator repair instead of continuously retrying a bad connection.

Activation/configuration are rechecked before new inference and every network
operation, including after credential lookup. Revocation during computation
retains the completion outbox without delivering it. A request already in flight
cannot be recalled; the gateway still fences stale claims and account deletion.
First fixed-code failures are preserved; no arbitrary prompt, path, key or native
stderr is printed. Interrupted timers and exact pending completions survive
process exit through the existing durable supervisor/outbox.

## Scene restart and remaining work

The Scene engine now accepts explicit `reuse_mount=True`. It reconstructs the
expected source, every shard/mask and manifest identity from the independently
sealed snapshot and runtime, then compares the complete saved mount. A local
mount's self-reported hashes are insufficient. Incomplete, changed or stale
mounts remain untouched for recovery; no automatic deletion/repair occurs. The
default constructor still requires a fresh mount folder. This source change
does not refresh or approve existing real runtime policies.

The [Windows synthetic receipt](evidence/owner-service-20261012.json) records
**132 passed checks, no failures or skips**, covering the
assembled runner, restart, lazy loading, revocation, process locking, exact query
bytes and private child scratch checks. Native outputs and credentials were
fixtures. No authentic inference, Mac execution, OS startup or endurance is claimed.

Explicit [secure credential provisioning](OWNER_CREDENTIAL_SETUP.md) now exists
in source, with hidden interactive entry and exact local vault readback. It has
not accessed real vaults. OS startup registration/readback, actual vault consent,
real source qualification and approved activation remain open. The computer must be on and
signed in to process; shutdown/sleep cannot perform computation. Outbound trusted
verification/import and bounded catalog integration also remain source work.
