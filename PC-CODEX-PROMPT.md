# Prompt for an invited Windows user's Codex

I want to check this PC for the VISION Local Scenes invited preview. You may
prepare a normal local folder, download the published preview kit, install the
kit's private Python and Scene model files, and run the fixed112 computer check.
Do not install Python globally, request administrator access, change execution
policy, disable security, use GitHub Actions or start bulk processing.

Use the unsigned invited preview at:
https://github.com/Andrew454545/vision-community/releases/tag/local-vision-app-preview-20261017

1. Read the release notes and checksums-and-limits.json. Download the Windows kit
   and verify its SHA-256 against that inventory before extracting all files into
   a normal local folder. Keep the whole kit together. If there is no published
   preview or the hash differs, stop and report that exact problem.
2. Check that this is Windows x64 and that setup has at least3 GB free. Run
   `VISION Local Scenes.exe --self-check`, capturing output privately and without
   opening console windows. A successful check prints LOCAL_PILOT_PACKAGE_VERIFIED.
3. Run `VISION Local Scenes.exe --check-computer --accept-downloads`, also
   windowlessly with captured output. This handles the private Python/model setup
   and the fixed112 checks without browser/desktop control. Allow the finite check
   time; do not launch another copy while it runs. It does not fetch live imagery,
   upload anything or approve this PC for bulk work. If OS security refuses the
   unsigned app, stop and describe the refusal; do not bypass it.
4. Read the resulting JSON and find resultsZip.path. Return that local ZIP and its
   SHA-256 privately to me so I can give it to the maintainer. Preserve failed
   profiles/logs too. A failed faster profile must not be relabelled as passing.
   Do not post installation IDs, private paths or the report ZIP to a public issue.
5. Stop here. The maintainer reviews the actual vectors, then supplies my personal
   queue. When I receive it, extract it, open VISION Local Scenes, choose Open
   personal queue and select campaign.json. We will use one tiny initial live
   queue before issuing the long allocation. Google must permit imagery access on
   this normal connection; do not rotate proxies, automate challenges or retry
   around an access refusal.

The GUI is also available: open VISION Local Scenes.exe and click Check this
computer. Results stay local in both modes. No account, cloud inference, Community
submission or production-device approval is part of this instruction.
