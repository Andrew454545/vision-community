# API protection and database maintenance — 4 October 2026

The service now limits expensive traffic before reading a request body or
performing database upgrades. HTTP and scheduled handlers never install a schema:
they read one persisted version record. An unprepared database or unavailable
limiter returns a temporary error; background processing keeps its saved work,
waits through its persisted cooldown and retries.

Source: `4c07c27`, with the lightweight-status regression correction in
`1a8e2d1`. This does not qualify a processing runtime or reopen contributions.

## Request budgets

| Scope | Configured limit | What it covers |
| --- | --- | --- |
| Broad ingress | 600/minute per hourly hashed network address | Every supported API route, including invalid credentials, before database/body access |
| Account | 120/minute per anonymous account | Shared across read and write routes; anonymous requests use an hourly hashed address |
| Imagery preview | 12/minute per anonymous account | Additional budget before retrieving a preview |

Staging and production use separate namespaces. Both configurations require all
three bindings. A missing/disabled required flag, missing binding, invalid reply,
exception or one-second limiter deadline closes the API with a retryable 503.
An exhausted budget returns 429 and a 60-second retry hint. Rejection does not
spend search credits or grant contributions.

Cloudflare's [rate-limit binding](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/)
uses local, permissive counters. These limits reduce bursts; they are not an
exact global quota, financial limit, bot-identity check or measured hosting
budget. Shared network addresses share ingress capacity. Counter keys contain
no raw address, credential, recovery code or search text; an anonymous UI does
not hide network traffic from the hosting provider.

## Maintainer upgrade

Use only the confirmed environment's database. Keep API writers paused and
drained while preparing its schema; preserve current backup/rollback evidence.
`RESTORE_MAINTENANCE=1` closes API requests before database access and stops the
scheduled cleanup handler. It does not cancel earlier requests or independent
writers. Keep contribution/search admission closed during this rollout.

For the existing current schema, review and apply only
`migrations/0004_schema_revision.sql`. It adds a lookup index and a version
record after checking all required columns and exact privacy fences. It does
not modify accounts, balances, saved searches, contributions or the work queue.
A missing fence or incompatible/newer revision refuses the checkpoint. Do not
run the entire historical migration directory blindly.

For a separately confirmed **empty** database, generate a data-free setup plan
using the existing private Node 24 runtime:

```sh
node tools/schema-plan.mjs --fresh --output fresh-schema.sql
```

The plan refuses existing application tables. This generator does not access
Cloudflare or import a queue. Apply it only in reviewed operator maintenance.
The older dynamic initializer is for finite fixtures and generating that fresh
plan; it is not an HTTP upgrade or a general live migration command.

After any restore or schema change, repeat the applicable checkpoint validation
before serving the new Worker. Read back revision `1` and contract
`vision-community-d1-v1-20261004`, required bindings, privacy headers and closed
admission, then restore maintenance to `0`. A version marker records a validated
installation; it does not detect later operator schema tampering or establish
complete financial/disaster recovery. See [restore precautions](PRIVATE_RESTORE.md).

## Evidence

All seven CI jobs pass at `1a8e2d1`: [application, Mac and Cloudflare](https://github.com/Andrew454545/vision-community/actions/runs/37252853663)
and [calibration guards](https://github.com/Andrew454545/vision-community/actions/runs/37252853600).

- Windows: 528 application tests, 281.783 seconds, two Mac-only skips.
  Linux: 528 tests, 66.089 seconds, 31 platform-specific skips.
- Cloudflare: 232 JavaScript tests, 3.203 seconds; six dry-run configurations
  and the complete finite workerd/D1/R2 checks pass.
- Five additional actual workerd fixtures exercise missing limiters, unprepared
  and damaged schemas, explicit setup, shared account quotas and an independent
  preview budget. They use two synthetic accounts, change no credit and retrieve
  no live imagery. They do not assert an exact global rate.
- Actual Apple-silicon CI passes 41 setup/platform, 42 sleep/background and
  12 control guards, plus finite private bootstrap/window/recovery checks.
  The added background case verifies saved work survives maintenance/protection
  outages and retries only after persisted cooldown.

The first CI failure was an existing source-format assertion for lightweight
status, corrected without changing that behavior. Its log and earlier local
fixture failures remain private. No reference imagery, vectors, account files
or credentials are published.

Confirmed Community staging now serves version
`070dec50-c1a1-43d9-8dfb-94774144812e` (5 October, 02:03 UTC).
The API was paused and drained before the three-statement checkpoint; the
existing current layout and privacy fences passed readback. Account/credit,
ledger, search, queue and publication aggregates match before and after.
All 13 live assets match the source, privacy headers and required bindings
pass, unauthorized/cross-origin access is refused, and contribution admission
remains closed. Production, native Containers, the installed contributor and
the independent laptop trials are unchanged. An older release ZIP was not
repackaged by this deployment.

The [production checklist](PRODUCTION_ACCEPTANCE.md) still requires approved
reference comparisons, native Mac and Objects/Both, verified parallel and
unattended accepted work, signed clean installs, endurance and hosting
load/cost/disaster recovery. Local tests and rate-limit configuration do not
satisfy those gates.
