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
native Object retry guards, Scene delivery and private diagnostics. Fourteen new
Object delivery scenarios use real loopback HTTP, SQLite
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
run in 42.753 seconds without skips.

All seven CI jobs for the change at
`cbbc555ea6656577454fd8b02763f670cfc7b395`:
[application checks](https://github.com/Andrew454545/vision-community/actions/runs/37323761047)
and [calibration](https://github.com/Andrew454545/vision-community/actions/runs/37323761239).
Windows passes 588 tests in 393.664 seconds with two Mac-only skips; Linux
passes 588 in 108.247 seconds with 31 platform skips. The actual private Mac
interpreter passes 62 privacy/transport/delivery/Object checks in 71.711 seconds
without skips, plus 41 setup, 42 sleep/background and 12 control guards.
Mac ownership passes 13 checks with two Windows-only skips. The service passes
all 232 JavaScript tests, complete workerd checks and six dry-run builds.
Both calibration jobs pass 80 guards; Linux has 18 platform skips.

After integrating Andrew's guided selection, legacy schema upgrade and native
package foundations, all nine CI jobs for head `37aeca9` pass:
[application](https://github.com/Andrew454545/vision-community/actions/runs/37393773137),
[calibration](https://github.com/Andrew454545/vision-community/actions/runs/37393773258)
and [native packages](https://github.com/Andrew454545/vision-community/actions/runs/37393773183).
Windows passes 605 tests in 429.128 seconds with two Mac-only skips; Linux passes
605 in 110.944 seconds with 31 platform skips. The service passes 237 tests,
complete workerd checks and six dry builds. The actual private Mac interpreter
passes 54 setup, 62 delivery, 42 sleep/background and 13 control guards.
Mac ownership and both 80-test calibration suites also pass. Package verification
is unsigned and performs no real processing. These pull-request jobs check
GitHub's proposed merge with main: the package receipts pin
`e3ba354e4341198b8c4285c90314ac386f941104`, not a distributed runtime.

The combined local focused run encountered one fixture setup error because
ordinary Windows accounts cannot create symbolic links. It is preserved. The
corrected staging test uses a real Windows junction when that privilege is
absent, and still verifies the unchanged reparse-point refusal. All three
staging tests pass; no security setting or application validator was weakened.

The final native-guide integration at head `068682e` also passes all nine jobs:
[application](https://github.com/Andrew454545/vision-community/actions/runs/37395584625),
[calibration](https://github.com/Andrew454545/vision-community/actions/runs/37395584294)
and [packages](https://github.com/Andrew454545/vision-community/actions/runs/37395584532).
Windows passes 609 tests in 402.223 seconds with two Mac-only skips; Linux passes
609 in 112.745 seconds with 31 platform skips. All 238 JavaScript tests, complete
workerd checks, six dry builds, actual private Mac guards, ownership checks and
both calibration suites pass. The unsigned package receipts pin the proposed
merge `3b8eaa79bfab1234e069f35c758447f82678ce9c`. Local native-guide/snapshot/staging
checks pass 22 tests with three platform skips; all five page tests pass.
The guide distinguishes the native app's button from extracted-folder files;
this does not validate the still-blocked native Windows startup path.

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

Guided Scenes / Objects / Both selection and serialized handover are now
implemented in source. Lane-specific native qualification, a trusted native
Object audit, verified runtime distribution and accepted background work on
both platforms remain in [the platform checklist](PLATFORM_ACCEPTANCE.md).
