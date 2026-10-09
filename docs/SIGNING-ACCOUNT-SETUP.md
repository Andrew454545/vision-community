# Set up signing accounts

This is for the VISION account holder. People using VISION do not need either
account. The installer code is prepared, but no signing account is configured
as of 8 October 2026. The protected GitHub `signing` environment is ready; it
contains no credentials. GitHub Actions spending is currently on hold, so do
not dispatch the signing workflow until that restriction is lifted.

## Mac

1. Open [Apple Developer enrollment](https://developer.apple.com/programs/enroll/).
2. Sign in with your own Apple Account, with two-factor authentication enabled.
   Enroll as yourself or your legal organization and complete Apple's identity,
   agreement and membership steps.
3. After approval, tell the maintainer that enrollment is complete. They can
   help create the Developer ID Application certificate and configure
   notarization on the signing Mac.

Apple's enrollment page lists the membership fee. The account holder completes
the purchase and legal agreements. Send only the enrollment status in chat;
the certificate's private key and notarization credentials stay on the signing
machine or in approved CI secrets.

## Windows

1. Open [Microsoft's Artifact Signing setup guide](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart).
2. Use your own Azure account and subscription. Review the billing terms, then
   create the Artifact Signing account and complete **Public Trust** identity
   validation in the Azure portal.
3. Create the Public Trust certificate profile. Tell the maintainer when it is
   ready; they can configure the signing node and permissions.

Microsoft's guide lists eligible countries and account requirements. The
account holder completes identity verification and paid subscription choices.
Keep authentication and identity documents in the provider's portal. Public
Trust is required for public installers; a private certificate profile does
not satisfy this requirement.

## Connect the accounts to GitHub (maintainer)

The manual **signed candidates** workflow
(`.github/workflows/signed-candidates.yml`) builds signed candidates without
anyone copying a private key to their own computer. The `signing` environment
was created on 8 October 2026 with `Andrew454545` as required reviewer and
`codex/windows-production-readiness` as the only permitted branch. Readback
confirmed zero environment secrets and zero variables. The account holder may
review their own manual candidate; administrator bypass remains GitHub's
default, so this is a reviewer gate, not an assertion that bypass is disabled.
If the release branch changes, update the branch restriction before signing.
Add these values to that environment only after the accounts are ready:

| Platform | Secrets | Variables |
| --- | --- | --- |
| Mac | `MAC_DEVELOPER_ID_P12_BASE64` (exported Developer ID Application certificate and key), `MAC_DEVELOPER_ID_P12_PASSWORD`, `APPLE_NOTARY_KEY_P8`, `APPLE_NOTARY_KEY_ID`, `APPLE_NOTARY_ISSUER` (App Store Connect API key for notarization) | `MAC_SIGNING_IDENTITY` (exactly `Developer ID Application: …`) |
| Windows | none | `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` (an Entra app with a GitHub federated credential for the `signing` environment and the *Artifact Signing Certificate Profile Signer* role), `ARTIFACT_SIGNING_ENDPOINT`, `ARTIFACT_SIGNING_ACCOUNT`, `ARTIFACT_SIGNING_PROFILE`, `WINDOWS_PUBLISHER_SUBJECT` (the certificate's exact subject) |

Windows uses a federated identity, so no Azure password or client secret is
stored. The workflow first runs `packaging/signing_preflight.py`, which stops
and names any missing setting without printing values. The Mac job keeps the
certificate in a temporary keychain that it deletes afterwards. The Windows job
downloads the checksum-pinned `Microsoft.ArtifactSigning.Client` 1.0.128.
Preparation failures also clean that owned keychain and raw key files. Signing
and notarization explicitly use the same keychain, with no manual change to the
user's keychain search list. The finite Mac cleanup test uses invalid synthetic
key material and local command fixtures; it does not prove real signing.
Each job uploads one seven-day artifact named
`SIGNED-CANDIDATE-FOR-CLEAN-DEVICE-TEST-…`. It never creates a Release or
changes a download link. The workflow has not run with real credentials yet,
because none exist.

## What happens next

The maintainer builds the exact committed source using
[Native installer packaging](NATIVE_INSTALLER_PACKAGING.md). The Mac candidate
must pass signature, notarization, stapling and Gatekeeper checks. The Windows
candidate must pass signature, timestamp and publisher checks.

Then test installation, startup, automatic processing handover and removal
with a new user account on each platform. Signing only addresses distribution.
Trusted Scene/Object admission, accepted work and the remaining
[production acceptance](PRODUCTION_ACCEPTANCE.md) gates also need to pass
before the public download links change.

Review the actual certificate subject and displayed publisher against the
project's anonymity requirements before distributing any signed candidate.
