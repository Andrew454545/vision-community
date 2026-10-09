# Native installer packaging

Windows **Start VISION** now performs private setup in native C# and starts its
verified private Python directly. It does not run PowerShell or change policy.
The finite real-page check exercises a fresh pinned download, authenticated
existing-page verification and complete close reply under the normal
[Restricted script policy](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies?view=powershell-5.1);
it creates no account or processing work. **Automatic processing, scheduling
and removal now also use native C#**, with full source/private-Python checks
before every autonomous launch. See the
[native background evidence](WINDOWS_NATIVE_BACKGROUND_20261006.md).
Signed clean-device installation and accepted unattended work remain open;
enterprise application restrictions are still respected. Do not change the
user's execution policy or add a Bypass/EncodedCommand workaround. The Mac app
now offers cooperative removal of its owned background worker before moving
this app to Trash, retaining private account and work data. Active native work
and clean-device removal still need acceptance. These are release gates, not
signing instructions.
The older extracted Windows starter contains a process-level Bypass argument;
the production launcher must replace that path without weakening user policy.

The packaging branch provides a native Apple-silicon **VISION Community.app**
and a Windows per-user **VISION-Community-Setup.exe**. Users do not install
Python or run terminal commands. The app opens the same four-step guided page
and offers an **Automatic processing** button. Runtime setup remains private to
that user. The choice in step 1 is made before downloading models.

These are build candidates. Public launch still requires the trusted Scene and
Object runtime/service gates, accepted work, recovery/endurance evidence and
signed clean-device installation in [Production acceptance](PRODUCTION_ACCEPTANCE.md).
Unsigned artifacts are clearly named `MAINTAINER-UNSIGNED-*`; CI does not
publish them to Releases or replace the beginner download links.
The [signing account setup guide](SIGNING-ACCOUNT-SETUP.md) gives the account
holder the enrollment steps. Users of VISION need neither account.

## Package boundaries

The stager copies an explicit public client/fixture list, never a checkout or
worker folder. It excludes Git history, credentials, accounts, indexes, databases,
imagery, logs and model weights. An embedded SHA-256 binds the release inventory
and every packaged file. Native startup verifies it before executing a helper.
Changed, missing, extra or redirected files refuse startup. The Mac app drains
child output without displaying or sharing private text. Windows installation
uses the current user's Programs folder, desktop/Start-menu shortcuts and
uninstall registry entry; it asks for no elevation or execution-policy change.
Both launchers wait for the guided app to finish before allowing a normal quit.
Windows verifies every extracted private Python file against its pinned archive,
including reused files, and refuses unknown files or redirected paths. Source
snapshots use a public allowlist and reject changed receipts, files or extra
directories. Downloads have size/time limits; interrupted files and fixed-code
failure reports are kept. Python starts with isolated imports and a small clean
environment. Native path handling supports long local paths without changing
the computer's registry preference. These checks do not approve model inference,
trusted contributions or months of unattended work.

Windows removal first uses the existing task ownership and cooperative handover
controls. A changed package, unfamiliar task or active batch refuses removal.
It removes only the installed program and matching shortcuts/registry entry;
the private worker folder, account, outputs and reports stay in place. On Mac,
close the guided page/controls, then choose **Remove VISION** in the app.
Removal verifies the existing private interpreter and exact owned startup
registration, waits for its writer lock, removes automatic startup and moves
only this application to Finder's Trash. It downloads nothing. An active batch,
unfamiliar job or changed runtime keeps the app for review/retry; saved account,
checkpoints, pending deliveries and reports stay in place. A never-used app can
be removed without installing Python. Trashing the app directly does not run
these controls.

Each package receipt records the checked source revision, whether the working
tree was dirty, archive hash and signing state. A wrong revision is refused.
Public signing requires a clean source tree. A package signature alone never
qualifies a runtime or device; receipts always say `productionQualified: false`
and `nativeRuntimesQualified: false`.

## Maintainer preview build

Use a clean checkout and a new output directory outside it. On each platform:

```sh
python -B packaging/build_mac.py --output /private/tmp/vision-mac-package --revision FULL_COMMIT_SHA
python -B packaging/check_mac.py --app '/private/tmp/vision-mac-package/VISION Community.app'
```

```powershell
python -B packaging/build_windows.py --output C:\Temp\vision-windows-package --revision FULL_COMMIT_SHA
```

The Mac build requires Apple command-line tools and targets Apple silicon on
macOS 13 or later. The Windows build uses the system Framework compiler and
requires an Intel/AMD Windows 10/11 machine with .NET Framework 4.8. CI builds
both native packages and runs actual package verification with zero account,
model, imagery or contribution operations. It preserves unsigned maintainer
artifacts for seven days. Windows unsigned CI also waits for a detached helper
to finish after its launcher process exits, retaining its finite result receipt.
The signing build skips that unsigned-script fixture. A successful package check is not a clean-user
installation, uninstall, native admission or production endurance test.
Separate lifecycle jobs install two built revisions on disposable Windows and
Mac runner accounts: interrupted setup, repeat, repair, update, active-work
refusal, idle handover and removal, with synthetic private files kept intact.
Setup repairs a changed installation in place and retires closed earlier
versions. See [installer acceptance](INSTALLER_ACCEPTANCE_20261005.md) for
results, fixed defects and the blockers that still need signing, a clean
device or a maintainer decision. The later native C# launcher and background
controls described above remove the earlier script-policy blocker; genuine
signatures and clean-device acceptance remain required.

## Signed Mac candidate

Andrew has confirmed no Apple Developer account is configured. The account
holder must [enroll with Apple](https://developer.apple.com/programs/enroll/)
and create a [Developer ID Application certificate](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/).
Keep the private key on the signing machine or in approved CI secrets, never in
Git, an issue, an archive or a chat. Set up a `notarytool` keychain profile with
Apple's authenticated workflow; do not put a password on the build command.

```sh
python -B packaging/build_mac.py --output /private/tmp/vision-mac-signed --revision FULL_COMMIT_SHA \
  --identity 'Developer ID Application: YOUR SIGNING IDENTITY' --notary-profile VISION-notary
```

The builder enables hardened runtime, verifies the signature, requires an
accepted notarization result, staples and validates the ticket, and checks
Gatekeeper before emitting a public-distribution receipt. Missing credentials,
ad-hoc signing or failed notarization cannot produce a public-ready receipt.
See [Apple's notarization workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).
Downloaded native runtime assets must also meet the maintainer's signed,
immutable distribution and qualification policy; signing this launcher does
not close that separate requirement.

Before publishing, inspect the actual certificate subject, displayed publisher
and released metadata against the project's anonymity requirements. The app's
labels cannot substitute for this check; use a legitimate signing identity.

## Signed Windows candidate

Andrew has confirmed no Windows signing service is configured. Set up a
validated public-trust code-signing profile first. Microsoft
[Artifact Signing](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-signing-integrations)
supports signing nodes and GitHub Actions. Its account, identity verification,
signer role and certificate profile need to exist before signing can work.
Enrollment and any paid subscription are account-holder decisions.

The included signing-node adapter uses configured official SignTool, signing
library and metadata paths in `VISION_SIGNTOOL`, `VISION_SIGNING_DLIB` and
`VISION_SIGNING_METADATA`. Authentication stays on the signing node. Another
approved signing service can provide an equivalent script accepting `-File`.

```powershell
python -B packaging/build_windows.py --output C:\Temp\vision-windows-signed --revision FULL_COMMIT_SHA `
  --signer packaging\windows\Artifact-Sign.ps1 --publisher 'EXACT CERTIFICATE SUBJECT'
```

The builder signs the PowerShell payload before sealing its inventory, then
signs the final embedded installer. It requires valid signatures, timestamps
and the exact expected publisher for every script and the executable before
emitting a public-distribution receipt. It never changes execution policy or
asks users to ignore a security warning. Missing credentials or a failed check
cannot yield a public-ready receipt. Test the signed downloads with a new user
account on both platforms before updating the simple download links.
