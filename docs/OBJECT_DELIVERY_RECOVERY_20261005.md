# Saved Object delivery

Object processing now saves the exact completed submission before uploading it.
If the service accepts a batch but its reply is lost, a fresh process retries
the same files under the same anonymous account and lease. It does not release
that lease or recompute the finished index. Service accounting remains authoritative.

`DurableCommunityClient` supplies this behavior to the default Object command
and the guided Scene client. The shared SQLite journal records the work lane,
output and Object bundle, immutable payload hash and service result. Existing
Scene journals migrate without rewriting their payload or hash. Recovery loads
one body at a time; it does not load sixteen large Object bundles together.
The existing 64-batch backlog limit and bounded recovery pass remain in place.

Recovery verifies saved bytes before transmission. Corrupt records stop with
evidence retained. A malformed acknowledgement cannot discard saved output;
an explicit rejection preserves it for review. Definitive lease loss preserves
the files and a terminal journal record. Object pending-audit replies remain
unconfirmed because there is no Object audit endpoint; they cannot be sent to
the Scene audit endpoint or treated as approval. Interrupted native commands
and exhausted retryable native attempts retain their active lease/checkpoint
for a later attempt, subject to the service's expiry and ownership checks.
Before the first upload, an explicit renewal ownership or credential refusal
stops processing and keeps the index. A temporary renewal outage may continue
to exact, journaled submission; it cannot grant approval locally.

Both private starters include and require the new delivery module. Missing
source fails during snapshot preparation instead of opening a broken app.
An invalid account code now shows a short correction message and does not
erase saved work.

## Verification

The 104 focused checks pass on Windows in 187.444 seconds, with three existing
platform/filesystem skips. They cover transport, both private source snapshots,
native Object retry guards, Scene delivery and private diagnostics. Fourteen
Object delivery scenarios. The new scenarios use real loopback HTTP, SQLite
and fresh Python processes, with an explicit synthetic native contract fixture.

The lost-reply scenario commits one synthetic Object location, loses all three
bounded upload replies, then resumes from a fresh process. Every upload has the
same bundle. The local prototype awards ten fixture units once; the replay
awards zero additional units, no new inference occurs, and recovery does not
release the lease or call a Scene audit. Further cases cover malformed replies,
corrupt valid JSON, account/service isolation, legacy migration, mixed-lane
recovery, explicit rejection, expiry and retained interrupted checkpoints.
The full client suite passes 585 checks in 479.019 seconds, with eight existing
skips, before the final renewal guards. Those three additional guards and all
Object/Scene delivery and native Object retry guards pass in the final 48-check
run in 42.753 seconds without skips. Exact-commit CI covers the final source.

The first synthetic fixture run failed before upload: it pinned LF TSV bytes
while the Windows writer produced CRLF. The fixture now pins the actual file
bytes, as the native program does. Native settings, validators and acceptance
limits were not weakened. The initial five failures/four errors and the
temporary-path setup mistake are preserved in the private failure report.

## Release limits

This is delivery evidence, not Object model equivalence, trusted Generation 4
coverage, a real contribution, OS reboot or months-long operation. The synthetic
prototype is separate from the hosted service, whose Object admission remains
closed. No Cloudflare resource, installed contributor, runtime manifest or
published download was changed. Custom injected clients retain their own
delivery behavior; the default Object command uses the durable client.

Guided Objects/Both setup, lane-specific qualification, a trusted native Object
audit, verified runtime distribution and accepted background work on both
platforms remain in [the platform checklist](PLATFORM_ACCEPTANCE.md).
