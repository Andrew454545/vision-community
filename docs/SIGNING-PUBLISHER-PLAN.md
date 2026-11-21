# Arrange trusted downloads

**Recommended: use a real organization as VISION's public publisher.** This
keeps Andrew's surname off the installer certificate. Signing providers still
verify the real account holder privately; this is publisher privacy, not
anonymous enrollment.

## 1. Choose the publisher

The project currently has no organization. Choose either a new legal entity with
a neutral name, or an existing organization willing and authorized to publish
and maintain VISION. A project nickname, alias or borrowed certificate is not a
substitute. The country and state/province need to be confirmed before choosing
registration and the Windows service. Registration costs, eligibility and any
public records depend on that jurisdiction; no formation or purchase has occurred.

Apple requires organization legal status, a D-U-N-S number, authority to enter
its agreement, a working organization website and an email on its domain. Its
organization enrollment does not accept a trade name alone.
[Apple enrollment requirements](https://developer.apple.com/programs/enroll/)

## 2. Enroll once the publisher exists

| Platform | Account to arrange | Published USD price checked 11 October 2026 |
| --- | --- | --- |
| Mac | Apple Developer **Program**, organization enrollment; Developer ID Application and notarization | $99/year; local pricing/tax may differ. [Apple](https://developer.apple.com/help/account/membership/program-enrollment/) |
| Windows | Azure **Artifact Signing Basic**, organization **Public Trust** validation and certificate profile, if eligible | $9.99/month, including 5,000 signatures; extra signatures $0.005 each. [Microsoft pricing tiers](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-change-sku) |

Budget about **$218.88/year** for those base fees, before taxes, domain/entity
costs or extras. These services do not require more GitHub Actions spending.
Provider verification time is external; do not promise an approval date.

Microsoft currently supports organization Public Trust validation in the US,
Canada, EU, UK, Australia, New Zealand, Japan, South Korea, Singapore, Switzerland,
Norway and Israel. Individual validation is limited to the US and Canada and
uses the billing identity on the public certificate. Confirm eligibility before
creating a paid resource.
[Microsoft prerequisites](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)

Use the legitimate organization's name in the providers' forms. Enter identity,
payment and legal documents only in their portals. Send the maintainer only the
enrollment status; certificates, keys and account access use the approved private
signing setup. Review the actual certificate subject and installer publisher
before sharing any candidate. Developer ID certificates identify their subscriber
or organization. [Apple certificate policy](https://images.apple.com/certificateauthority/pdf/Apple_Developer_ID_CPS_v3.2.pdf)

## 3. Arrange the two testers now

The laptop user has offered to recruit both testers. Send them the invitation in
[Help test VISION](TESTER-QUICKSTART.md). A fresh standard account can begin the
test; genuinely clean-device acceptance and an unaided beginner walkthrough must
still be recorded. They need no developer account, programming tools or signing
credentials. Wait for actual signed bytes and qualified lanes before dependent
processing checks.

## Maintainer work

After enrollment, configure the exact protected signing identities using
[signing account setup](SIGNING-ACCOUNT-SETUP.md). Use existing local build/sign
scripts on approved computers while GitHub Actions spending is on hold. The
prepared manual workflow remains disabled in practice: do not dispatch it.
Never mark an unsigned package, private-trust certificate or local bypass as a
trusted public download. Keep the publisher decision, actual signature checks and
six Windows/Mac Scenes/Objects/Both test results with the release evidence.

Current status: publisher jurisdiction pending; no accounts purchased, signatures
created, testers booked or clean-device acceptance claimed.
