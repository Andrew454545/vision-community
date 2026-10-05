# Native installer packaging

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

## Package boundaries

The stager copies an explicit public client/fixture list, never a checkout or
worker folder. It excludes Git history, credentials, accounts, indexes, databases,
imagery, logs and model weights. An embedded SHA-256 binds the release inventory
and every packaged file. Native startup verifies it before executing a script.
Changed, missing, extra or redirected files refuse startup. The Mac app drains
child output without displaying or sharing private text. Windows installation
uses the current user's Programs folder, desktop/Start-menu shortcuts and
uninstall registry entry; it asks for no elevation or execution-policy change.
Both launchers wait for the guided app to finish before allowing a normal quit.

Windows removal first uses the existing task ownership and cooperative handover
controls. A changed package, unfamiliar task or active batch refuses removal.
It removes only the installed program and matching shortcuts/registry entry;
the private worker folder, account, outputs and reports stay in place. On Mac,
remove automatic startup in the controls before moving the app to Trash; the
private worker folder also stays in place.

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
artifacts for seven days. A successful package check is not a clean-user
installation, uninstall, native admission or production endurance test.

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
