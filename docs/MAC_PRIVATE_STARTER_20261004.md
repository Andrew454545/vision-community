# Private Mac starter — 4 October 2026

The Apple-silicon Mac starter now prepares a private Python and a verified copy
of the guided application. This is a maintainer preview; a qualified Mac release,
Objects setup and Mac automatic processing still require separate evidence.

## What changed

- `Start VISION.command` uses macOS's existing shell and Perl to download and
  verify a private interpreter. It does not install Python globally, use `pip`,
  request administrator access or change security settings.
- The archive is checked before extraction. Every interpreter file, executable
  permission and permitted internal link is checked before Python runs. Unknown,
  missing, changed or escaping files stop setup and preserve a private report.
- First setup extracts into a new staging folder and publishes it atomically
  only after complete verification. A power interruption retains the unfinished
  stage; the next attempt can use a fresh verified stage. Existing interpreters
  are still checked and never silently overwritten or approved.
- The private application snapshot contains named public source/UI/fixture files
  only. Account codes, queues, private imagery, models and repository credentials
  are excluded. Reopening verifies the snapshot rather than overwriting it.
  Interrupted snapshots and existing account files are preserved.
- Guided Scenes setup selects the computer's native executable. Mac binaries no
  longer receive a Windows `.exe` suffix. The setup-only path takes the same
  single-instance lock as the normal local window.
- The shared window uses “computer” for its buttons and reports. Windows
  background instructions appear only on Windows; Mac's automatic-processing
  limitation is explicit rather than sending users to a `.cmd` file.
- Released comparison policies can be pinned separately with `pcCanaryPolicies`
  keyed by platform. The old `pcCanaryPolicy` applies only to Windows. A missing
  Mac policy remains diagnostic, and cannot borrow Windows approval. The service
  must still approve the exact runtime profile before contribution.

## Private interpreter pins

The interpreter is the upstream
[3 October python-build-standalone release](https://github.com/astral-sh/python-build-standalone/releases/tag/20261003):
`cpython-3.14.8+20261003-aarch64-apple-darwin-install_only.tar.gz`.

- Download size: **26,798,928 bytes**.
- Archive SHA-256: `d15291f940cfecd2e54010d5e37d2e03aa192f076a65d26ab741372fff2dabfe`.
- Public inventory SHA-256: `a0f5d70672a69e5f34433bc7f2de43a2c85443af610007711d20f00334fc0c0d`.
- Inventory: **1,689 regular files and 9 links**. Only relative names, sizes,
  hashes, executable flags and allowed directory/link identities are published.

HTTPS uses the CA bundle inside the verified private distribution. No TLS
verification bypass or global certificate change is used. The generator checks
the pinned archive and rejects path traversal, duplicate names and unsupported
members; the system Perl verifier checks the extracted tree before execution.

## Verification and remaining limits

The CI `mac-private-starter` job downloads the exact interpreter on an actual
Apple-silicon Mac, checks verified HTTPS, copies the public source, exercises
interpreter/snapshot/platform-policy guards, then opens and closes the real
loopback window. Its finite window check verifies the three assets, private
headers, denied unauthenticated status access, authenticated status and owned
process exit. It never downloads native models, creates an account, retrieves
imagery, publishes a contribution or qualifies the computer.

Only aggregate logs and a redacted window receipt are uploaded. Private roots,
loopback credentials and snapshots are excluded. The initial local test assertion
failure is retained separately.

The [actual Mac job](https://github.com/Andrew454545/vision-community/actions/runs/37235560511/job/111533829443)
passes at `0a1ad40` on `macos-26-arm64`: pinned download/tree verification,
verified HTTPS, source snapshot, **37 guards** in **2.353 seconds** with **no
skips**, and `MAC_PRIVATE_STARTER_WINDOW_VERIFIED`. All three local assets and
privacy headers pass, unauthenticated status access is denied, authenticated
status works, a second setup-only entry is refused and the owned window exits.
Its receipt records zero accounts, native commands and uploads, no imagery,
and `productionQualified: false`. The private interpreter is Python **3.14.8**.
The updated job additionally seeds an interrupted extraction and checks that
its bytes remain unchanged while a fresh staged interpreter starts. Record that
job's completion separately; the earlier successful job predates this recovery
check. This is an extraction-interruption fixture, not an actual Mac restart.

The first remote Mac bootstrap stopped safely on a checksum mismatch: Windows
had generated the inventory's final newline as CRLF, while the Git download is
LF. The archive/interpreter contents were unchanged. The generator now emits LF
explicitly, the launcher pins those exact Git bytes and a regression guard checks
the packaged inventory against both launcher pins. The original failed Mac log
is retained. The website progress test's old “PC check” expectation was updated
to “Computer check”; a platform-capability regression also verifies that Mac
does not display Windows background instructions.

Local Windows verification passes **500 application tests** in 368.645 seconds
(five filesystem-link permission skips), **36 final targeted guards** in
4.265 seconds (three link-permission skips), and **80 calibration guards** in
10.285 seconds. Shell/Perl/Python/JavaScript syntax checks and whitespace checks
pass. These Windows checks do not establish Mac execution.
After the packaged-pin guard, all **37 targeted guards** pass in 4.173 seconds
(three link-permission skips). CI verifies the final complete source separately.

The first calibration guard run failed when fixture-folder removal overtook
Windows' asynchronous child termination and hid the intended accounting error.
The fixture now independently holds a verified job-member process handle and
waits on that identity before removing its folder. The original failure is
retained; native reporting, qualification and the isolated running comparison
are unchanged. See Microsoft's
[termination semantics](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess).

A later remote calibration fixture caught an unrelated transient wrapper
name-read failure while exercising the deliberately failed name read of one
controlled child. That guard now mocks success for the other fixture wrappers;
the selected child still exits on its actual held, verified process identity.
Separate real-name and live-failure guards remain unchanged. Publishing the
child's ready marker is now atomic. All 80 local calibration guards pass in
9.894 seconds after that fixture-only repair; the failed remote log is retained.
This does not repair or approve an incidental native measurement failure.

The first complete 501-test Windows CI attempt failed two Mac-verifier fixtures
because `PATH` selected a native Windows Perl whose POSIX stat predicates were
unavailable (`Fcntl::AUTOLOAD`). Windows fixtures now explicitly use Git's POSIX
Perl. The actual Mac job continues to use its system Perl and passes without
skips; production Mac verification is unchanged. Both original failing logs are
preserved, and final Windows CI must pass after this test-environment repair.

## Next native Mac checks

The private VISION branch adds finite Apple-silicon builds of current Scenes
and Objects CPU programs, with locked dependencies, native tests, actual layout
startup and private build/dependency receipts. Both jobs were refused before any
step started because a GitHub Actions budget prevents further use. The failure
annotations are retained; build registration is not native startup evidence.

The GitHub account owner must increase the applicable Actions budget under
**Settings → Billing → Budgets and alerts**, retaining an appropriate spending
cap. Then retry the two finite Mac jobs once. No API key, contribution account,
engineering sign-off or security exception is needed. See GitHub's
[budget guide](https://docs.github.com/en/billing/how-tos/set-up-budgets).
Do not repeatedly retry unchanged budget-blocked jobs or describe these builds
as completed. Native inference, signed distribution and clean-device checks
remain separate gates.

The starter currently targets **Apple silicon only**. Intel Mac and Windows ARM
need their own interpreter/native builds and checks. The present distributed
Mac processing binary also needs a current dependency/layout and inference
review. No Mac model, production qualification, accepted batch, unattended
startup or clean-device beginner approval is established by this bootstrap.

The public beginner download remains the existing Windows Scenes preview.
Do not suggest changing Gatekeeper or other protections to open a Mac preview.
Publish a signed, tested Mac application before calling that beginner flow ready.
Track the complete scope in [platform acceptance](PLATFORM_ACCEPTANCE.md).
