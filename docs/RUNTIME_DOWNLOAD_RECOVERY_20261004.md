# Setup download recovery — 4 October 2026 local

Source `4378f88d453cc139cb8cbf4ca7a28a639be708c4` preserves interrupted runtime
and model downloads. Retrying setup or reopening it after a restart can request
the remaining bytes. A complete file must still match its pinned size and
SHA-256 before installation; incomplete bytes are never executed.

Validated range responses append only at the saved offset and with the expected
complete length. Servers that return a complete response instead replace the
partial file safely. Short fragments and connection/chunked-transfer failures
retain their bounded prefix for another retry. Oversized responses are stopped
before excess bytes are written. Corrupt full files, wrong pins, unsupported
encoding and incorrect range offsets cannot pass installation. Existing complete
verified files are reused as before.

Native setup no longer runs the obsolete automatic Pillow/pip installation.
It downloads the native programs and models; it does not install Python packages
globally. The old developer prototype's optional dependencies remain separate
from guided native processing. Setup's final message directs users back to VISION
to check availability instead of telling them to obtain an account immediately.

## Evidence

Follow-up `dc597dc` checks a **30-minute response-body budget** using elapsed
time between available HTTP fragments. A server sending tiny amounts of data
can no longer hide its body progress inside a large buffered read. Expired
attempts retain bounded prefixes and restart with a fresh budget; complete
bytes still require their pinned checksum before reuse. The existing 120-second
socket inactivity timeout remains. This body check is not an operating-system
hard limit on connection/header handling or blocked filesystem operations.
Python's [single-fragment reader](https://docs.python.org/3/library/http.client.html#http.client.HTTPResponse)
provides the body reads.

All **28 targeted tests** pass in 0.665 seconds, including four added guards:
trickling body/resume, deadline at the last fragment, wall-clock independence
and actual loopback HTTP interruption/range recovery. All **547 local Windows
tests** pass in 426.935 seconds, with eight expected platform/filesystem skips,
using the existing private PowerShell 7 and unchanged security policy. A second
actual pinned HTTPS tokenizer recovery also passes with this code.
[Follow-up application CI](https://github.com/Andrew454545/vision-community/actions/runs/37274191169)
and [calibration CI](https://github.com/Andrew454545/vision-community/actions/runs/37274191082)
pass all seven jobs at `dc597dc`: Windows 547 tests in 302.209 seconds with two
Mac-only skips; Linux 547; all 232 hosted-service tests and complete workerd
checks; actual Mac setup/background/controls and ownership; both 80-test
calibration jobs. The earlier completed CI below describes `4378f88`.

- All 24 targeted bootstrap/recovery tests pass in 0.055 seconds. Fifteen new
  guards cover interruptions, valid/invalid ranges, fresh attempts, ignored
  ranges, short fragments, chunked disconnects, oversize/corruption, complete
  partial reuse, directory protection and no global package installer.
- A finite actual HTTPS check of the unchanged public `siglip-tokenizer.json`
  saves a 4,096-byte prefix, recovers the complete 2,398,744-byte file and verifies
  SHA-256 `4a17c975210be5ab4c36b47d8dae4eefb866dbfb1e676e394aad85dc30a3ae08`.
  This downloads a small model asset only; it installs nothing and runs no model,
  creates no account and uploads no contribution.
- The first full local Windows run executes 543 tests in 374.723 seconds, with
  33 failures and eight platform/filesystem skips. The launcher fixtures selected
  Windows PowerShell 5, whose existing script policy refused the files. The
  original failure log is preserved. The full rerun explicitly selects the
  existing private PowerShell 7 under its unchanged `RemoteSigned` policy:
  **all 543 tests pass in 451.258 seconds**, with eight expected platform/filesystem
  skips. No security setting is modified.
- [Complete Community CI](https://github.com/Andrew454545/vision-community/actions/runs/37257153471)
  and [calibration guards](https://github.com/Andrew454545/vision-community/actions/runs/37257153520)
  pass all seven jobs at this source revision. Windows passes all 543 tests
  in 339.854 seconds with two Mac-only skips; Linux passes 543 in 50.006 seconds
  with 31 platform skips. Cloudflare passes all 232 tests and the complete
  workerd checks. Mac passes 41 setup, 42 sleep/background and 12 control
  guards, plus 13 process-ownership checks with two Windows-only skips.
  Calibration passes 80 guards on each platform, including actual Windows
  private interpreter and native layout startup.

The fix is committed to the development branch. The installed contributor,
existing immutable Windows ZIP, public Mac executable pins, hosted website,
production admission and ongoing independent reference trials are unchanged.
This improves setup recovery; it does not establish full release readiness or
months of unattended operation. See [production acceptance](PRODUCTION_ACCEPTANCE.md).
