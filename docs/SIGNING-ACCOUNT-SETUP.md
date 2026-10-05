# Set up signing accounts

This is for the VISION account holder. People using VISION do not need either
account. The installer code is prepared, but no signing account is configured
as of 5 October 2026.

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
