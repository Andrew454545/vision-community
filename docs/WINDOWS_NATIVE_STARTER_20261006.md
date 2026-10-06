# Native Windows startup

The later [native background update](WINDOWS_NATIVE_BACKGROUND_20261006.md)
also implements Windows automatic controls, owned startup and actual removal,
with passing finite Restricted-policy and lifecycle evidence. The remaining
controls/removal statements below describe this earlier startup-only phase.

**Start VISION now uses native setup code.** The Windows candidate verifies its
sealed package, copies an immutable public source snapshot, downloads the pinned
private Python archive and checks every extracted file before opening the guided
page. It does not execute PowerShell files, change execution policy or install
anything globally. Python uses isolated imports and a small clean environment.
Download consent remains in the app; account creation and indexing remain
explicit guided actions.

Setup rejects redirected paths, changed/missing/extra source or Python files,
altered snapshot receipts and unfamiliar directories. Concurrent setup refuses
before downloads or consent writes. Failed downloads/stages and fixed-code private
reports are kept. Existing-page reopening requires the matching private Python
process, same Windows session, a strict loopback bearer URL and an authenticated
bounded status response. Long local file verification uses native path handling;
the user's registry and security settings stay unchanged.

## Evidence

The laptop passes all 28 native bootstrap guards with no skips, package
verification and a detached **native** helper. The complete unsigned package
build passes while its children inherit Restricted policy. A fresh download of
private Python `3.14.7` matches SHA-256
`d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15`.
The real empty guided page passes authenticated status/reuse, complete close
reply and independent imports from the copied snapshot. A cached-archive run
also passes. Eleven packaging, guide and signing-preflight tests pass.

These local builds record a dirty worktree and the preceding revision; they are
development evidence, not immutable release artifacts. All eleven CI jobs pass
for application head `b96ea6ad1f61c772b15f0c17e4022e77622d8357`:
[native packages](https://github.com/Andrew454545/vision-community/actions/runs/37403460067),
[application](https://github.com/Andrew454545/vision-community/actions/runs/37403460035),
[calibration guards](https://github.com/Andrew454545/vision-community/actions/runs/37403459985),
[Mac lifecycle](https://github.com/Andrew454545/vision-community/actions/runs/37403460096).
Package receipts pin GitHub's proposed main merge
`e4c5326466f6cd82ed16d1dc4e1116ccec611d22` and a clean source tree.
The Windows package job proves the fresh native private download/page path
under Restricted; the separate native detached-helper probe passes too.
Windows real-window lifecycle retains all 30 checks; Mac lifecycle retains 22
and signing cleanup retains 19. Windows/Linux each run 624 application tests;
the service runs 238 tests plus full workerd checks. Both calibration runners
run 80 guards. Actual private Mac setup/delivery/background/control/removal
checks pass. These are finite fixtures, not signed clean-device or accepted
native indexing/endurance evidence.

Failures are preserved: the first build had a missing output parent; long-path
checks found `FileNotFoundException` at a copied fixture and then Python cleanup
failed on the same long path. Native verification and narrowly scoped disposable
cleanup now use explicit long local paths. The first policy probes inherited
PowerShell 7's module path and could not load Windows PowerShell's standard
command. The corrected probe uses Windows' own modules and case-normalized
child environment. A sandboxed junction test failed; its authorized unchanged
assertions pass. These earlier failures are not overall passes.

No installed contributor, task, account, model, imagery, contribution, Cloudflare
resource, public download or production admission changed in these checks.

## Remaining Windows release work

**Automatic processing and application removal still execute PowerShell files.**
They remain blocked on a normally configured Restricted PC and must be migrated
to native operations with the existing ownership and cooperative handover checks.
The finite detached helper above is not the application uninstaller. Legitimate
signing, clean physical-device/beginner acceptance, qualified Scene/Object
runtimes and trusted admission, accepted active-batch handover, real restart
and extended unattended operation remain open in
[Production acceptance](PRODUCTION_ACCEPTANCE.md).

The native architecture check uses Microsoft's
[IsWow64Process2](https://learn.microsoft.com/en-us/windows/win32/api/wow64apiset/nf-wow64apiset-iswow64process2)
to reject x64 emulation on ARM. Native downloads disable automatic redirects
using [HttpClientHandler](https://learn.microsoft.com/en-us/dotnet/api/system.net.http.httpclienthandler.allowautoredirect?view=netframework-4.8.1)
and retain ordinary certificate validation. Modern .NET path handling is
[process-local](https://learn.microsoft.com/en-us/dotnet/framework/configure-apps/file-schema/runtime/appcontextswitchoverrides-element).
