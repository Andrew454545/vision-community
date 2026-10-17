# Installer integration and safe Mac removal

The development branch integrates contributor [PR12](https://github.com/Andrew454545/vision-community/pull/12)
and [PR14](https://github.com/Andrew454545/vision-community/pull/14). Public
downloads and production admission are unchanged.

## Changes

Windows setup repairs damaged copies, removes interrupted staging folders,
retires closed earlier versions and preserves private work during removal.
Setup and removal share an exclusive lock, with linked lock paths refused.
An overlapping removal cannot unregister startup or erase program/private
files while setup holds the lock.

Mac signing uses a scoped temporary keychain and cleans raw credentials after
failed import/notary preparation. The owned keychain is passed explicitly to
codesign and notarytool; cleanup refuses unrelated paths. This prepares a
manual, gated signing candidate workflow. No real signing identity or
notarization request has been used.

The Mac app now offers **Remove VISION**. Close the guided page/controls first.
Removal downloads nothing: it verifies the existing private interpreter and
the exact saved/loaded startup registration, requests a stop after the batch,
and waits for the shared writer lock before unregistering. It preserves the
account, checkpoints, pending deliveries, old source snapshots and reports.
Only this app moves to Trash, using [Finder's supported API](https://developer.apple.com/documentation/appkit/nsworkspace/recycle(_:completionhandler:)).
A never-used app can be removed without installing Python. Active work,
changed files and unfamiliar jobs keep the app for retry/review. Moving it
directly to Trash does not perform the startup cleanup.

The guided page and Mac automatic controls now flush the complete close reply
before shutting down their server. A previously observed early exit cut off
the valid acknowledgement; the original failed run is retained below.

## Contributor integration evidence

All eleven CI jobs pass at `a37ef40949144c25f51ecc51154f65a77fb897b6`:
[application](https://github.com/Andrew454545/vision-community/actions/runs/37398515945),
[calibration](https://github.com/Andrew454545/vision-community/actions/runs/37398515722),
[native packages](https://github.com/Andrew454545/vision-community/actions/runs/37398515777),
and [Mac lifecycle](https://github.com/Andrew454545/vision-community/actions/runs/37398515698).
The checked proposed main merge is `376f5af5d5d2d65cea986d9706d6e02c06e1e4c6`.

- Windows and Linux each run 613 client tests; Windows has two Mac-only skips,
  Linux 31 platform skips. The service passes 238 JavaScript checks, full
  workerd checks and six dry builds. Calibration passes 80 guards per platform.
- Windows real-window lifecycle passes all 30 checks, including three new
  setup/removal contention checks. Private synthetic files and the test task
  remain unchanged on refused removal.
- Mac lifecycle passes 19 checks. Temporary signing cleanup passes 19 checks,
  including an actual invalid-certificate import, early/late failures,
  successful fixture cleanup, unrelated-path refusal and unchanged user
  keychain search list. These use no valid credentials or real notarization.
- Unsigned native packages verify on both platforms. Actual private Mac
  setup, saved delivery, sleep/background controls and ownership also pass.

## Mac removal validation

The first removal implementation is `86fbe243b03a9a43eb7c7263edd21ccbb751af44`.
Its [Mac lifecycle](https://github.com/Andrew454545/vision-community/actions/runs/37399748705)
passes 22 checks, including the actual native Trash API, app disappearance
and no private folder/agent created for a never-used app.
The [private Mac run](https://github.com/Andrew454545/vision-community/actions/runs/37399748725)
fails at closing the controls, before reaching the new removal helper, with
`RemoteDisconnected`. The temporary job was removed on failure; no native work,
real account or imagery was used. This is the shutdown ordering failure above.
It is not relabelled as a successful removal test.

The shutdown correction `fea5add3c436e4a531a35956e28916e7d1b90837`
[passes closing the controls](https://github.com/Andrew454545/vision-community/actions/runs/37400172812)
but then reports `JSONDecodeError`: the verified removal shell returned zero
with a verifier progress line before the status receipt. The correction keeps
that progress off status output while retaining verification and its exit
check. Both failed runs and their cleanup receipts remain preserved.

Corrected application source `40f6e2d88f47eef0c0ea18439fc853b1db5880ca`
passes all eleven CI jobs:
[application](https://github.com/Andrew454545/vision-community/actions/runs/37400449933),
[calibration](https://github.com/Andrew454545/vision-community/actions/runs/37400449892),
[native packages](https://github.com/Andrew454545/vision-community/actions/runs/37400449852),
and [Mac lifecycle](https://github.com/Andrew454545/vision-community/actions/runs/37400449899).
The proposed main merge is `a9ab59e77fdae1ef69c9696c8cea8cd2c3992910`.
Windows runs 624 tests in 431.913 seconds (two Mac-only skips); Linux runs
624 in 94.506 seconds (31 platform skips). The service passes 238 JavaScript
checks, complete workerd checks and six dry builds. Calibration passes 80
guards on each platform, and Windows lifecycle passes all 30 checks.
Unsigned packages verify on both platforms. Mac ownership runs 13 guards,
with two Windows-only skips. This source also
[passes the actual private Mac checks](https://github.com/Andrew454545/vision-community/actions/runs/37400449933):
54 setup guards, 62 saved-delivery/privacy guards, 42 sleep/background guards
and 23 control/removal guards, with no skips in these Mac suites. The real
guarded worker starts paused, is cooperatively stopped by the removal shell
after its private interpreter is fully verified, and its owned temporary
LaunchAgent is removed. A repeat preserves the registration receipt/account.
The browser receives its complete close reply while independent background
processing continues. No native inference, real account or imagery is used.
The [Mac lifecycle](https://github.com/Andrew454545/vision-community/actions/runs/37400449899)
passes all 22 checks and the 19 signing-cleanup checks. These are finite
synthetic/paused checks, not acceptance of active production work.

Local Windows checks pass: 24 removal/background/staging guards in 16.541
seconds (one unavailable Mac-link fixture); 23 source/guide/signing guards in
1.994 seconds (three platform skips); final 23 removal/control guards in
15.769 seconds (one link skip); and four actual guided-close/progress checks
in 0.993 seconds with no skips. The first sandboxed run failed because local
loopback, Git's POSIX verifier and the junction helper lacked sandbox access.
The unchanged authorized rerun passes; both logs are kept. No security policy
was changed.

The local full Windows package builder remains failed under Windows
PowerShell's `Restricted` policy. The compiled native executable's direct
self-check passes, including changed-file refusal, but that narrow check does
not repair the script startup. The failed builder output/log is retained;
it is not a full package or clean-device success.

## Release limits

This integration phase still needed native bootstrap, controls and removal without changing
execution policy. The ordinary default policy blocked that revision's script
launcher, including signed scripts. The CI diagnostic imposes Restricted in
its own process/children only, restores its environment and makes no user or
machine policy changes. Signing cannot solve this startup defect.
The later [native Windows starter](WINDOWS_NATIVE_STARTER_20261006.md) replaces
startup and the finite detached helper. Automatic controls/removal still need
native migration; the full Windows release gate remains open.

The new Mac flow still needs signed clean-device keyboard/VoiceOver checks,
removal during accepted native work, real sign-in/restart and long-duration
recovery. If existing private setup files are damaged, removal keeps the app
for repair/review rather than executing them or deleting saved work.
Trusted Scene/Object admission, qualified immutable runtime/downloads and all
other [production acceptance](PRODUCTION_ACCEPTANCE.md) gates remain open.
No installed laptop contributor or Cloudflare resource was inspected or
changed in this integration, and earlier full calibration trials were not
rerun. All reported processing/credit fixtures are synthetic.
