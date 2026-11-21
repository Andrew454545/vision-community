# Desktop service reply protection

Source `a80f22b` bounds JSON replies from the Community service and refuses API
redirects. This protects local processing during unexpected service responses;
there is no evidence that the live service leaked credentials or returned an
oversized reply.

The account token stays with the configured service. JSON requests and all
three legacy credential-bearing binary downloads use a private HTTP opener
that refuses 301/302/303/307/308 redirects, including redirects to the same
origin. A submission cannot silently become a redirected GET. The opener keeps
normal TLS verification and proxy handling; it does not change HTTP behavior
globally or share credentials between clients.

JSON response bodies have an 8 MiB limit, enforced during reads even when the
length is absent or transfer encoding is chunked. Declared oversized replies
stop before body accumulation. A 120-second elapsed body budget is checked
between available fragments; connection/header parsing and individual blocked
reads remain subject to the existing socket timeout. This is not a strict
whole-request deadline or a total Python-memory limit. Legacy binary response
sizes are outside this JSON bound.

Redirects and body-limit failures preserve the exact saved delivery and enter
the background worker's persisted service cooldown. Once the service recovers,
a fresh worker retries the original delivery without creating another account
or requesting another batch. A truncated success is never an acknowledgement.
An oversized or broken error body cannot hide its HTTP revocation/rejection
status; error streams are closed after reading.

All **66 focused checks pass** in 41.546 seconds. They include actual loopback
HTTP, every redirect code across JSON and binary requests, separate account
tokens, chunked/unknown/declared lengths, incomplete responses, bounded fragment
reads and SQLite delivery recovery across fresh Python workers. All **564 local
Windows application checks pass** in 437.046 seconds; eight skips are existing
platform/filesystem limitations. The existing private PowerShell 7 runs under
its unchanged policy. Initial test-fixture account/tuple/setup mistakes are
retained with the corrected passing reports.

A credential-free actual HTTPS read of staging capabilities returns HTTP 200
through the guarded client, with Scene admission still closed. All seven CI
jobs pass at the exact source: [application checks](https://github.com/Andrew454545/vision-community/actions/runs/37282073208)
and [calibration guards](https://github.com/Andrew454545/vision-community/actions/runs/37282073216).
Windows passes 564 tests in 316.734 seconds with two Mac-only skips; Linux
passes the same 564 tests. Mac passes 41 setup, 42 background, 12 controls and
13 ownership checks. Both calibration runners pass 80 guards; hosted service
checks also pass. No staging deployment, account, credit, contribution,
installed contributor, immutable release or runtime-policy change occurs.
