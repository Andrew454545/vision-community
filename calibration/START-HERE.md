# Windows calibration: start here

This is the setup for a friend helping test VISION Community. You do **not** need Python, Git, a Community account, or a recovery code. Codex can download the project ZIP and run the PowerShell setup for you.

## What you are allowing

The setup downloads a private copy of Python from python.org and about **1 GB** of checksum-verified scene runtime/model files from this project's GitHub release. It then retrieves live imagery for the supplied 1,024 locations and performs **three sequential runs**. Allow at least 3 GB of free space and leave the PC awake and Codex open. Runtime depends on the PC and network; we have not measured a dependable completion time.

All downloaded runtime files, caches, and results go in a new directory under `%LOCALAPPDATA%\vision-community-calibration`. No administrator installation, global Python installation, PATH change, account, lease, cloud upload, or production index modification is required. Scripts do not alter VISION's configuration. Only ordinary process-scoped PowerShell execution is used; do not weaken system execution policy or antivirus protection.

This experiment contacts python.org, GitHub release download hosts, and the imagery endpoints used by the existing scene indexer. The owner of the PC must authorize these downloads and live imagery retrieval. The copy/paste prompt below grants that authorization when the friend sends it.

## Prompt for the friend's Codex

Use the exact repository revision/link Andrew supplies, not an unrelated project. Paste:

> Help me run the VISION Community Windows calibration from the repository link Andrew supplied. I am not technical. Read `calibration/START-HERE.md`, inspect its setup scripts, and handle the setup and execution for me. I authorize the listed private Python/runtime/model downloads and live imagery retrieval for the supplied fixture. Use the exact linked revision. Do not install anything globally, disable security protections, use a Community account, or upload results. Run the three full trials, then show me the resulting `pc-calibration-results.zip` and SHA-256 so I can send them to Andrew. Explain any blocker simply and preserve failure evidence. This is an exploratory test, not permission to contribute to a production index.

## Instructions for Codex

1. Confirm native x86-64 Windows and 64-bit PowerShell. Windows ARM/emulation and non-Windows devices are not supported by this setup. Do not substitute a runtime.
2. Download/extract the exact linked repository ZIP into a new local, non-synced folder; do not require the user to install Git. If a matching checkout already exists, inspect it without modifying its source. Read the scripts and use the pinned fixture/runtime checksums.
3. From the extracted repository root, run:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\calibration\Start-WindowsCalibration.ps1 -AcceptDownloadsAndLiveImagery
   ```

   `Bypass` applies only to this child process. Do not run `Set-ExecutionPolicy`, elevate, or disable security tools. If organizational policy blocks execution or a download, report that blocker instead of circumventing it.

4. No pip/Pillow installation is necessary for this path: Python's standard library and the existing scene helper are sufficient. The setup downloads only scene assets, not object models. It verifies checksums before execution.
5. Wait for all three trials. Show occasional progress from the process/task status without exposing panorama IDs or raw output records. Do not kill a quiet inference process solely because it has no console output; each subprocess has a two-hour timeout. Do not silently resume a failed trial or reconfigure inference to obtain matching bytes.
6. Return the ZIP path, SHA-256, completed/failed run counts, repeatability results, and limitations from `summary.json`. A nonzero exit can still produce a useful failure ZIP. Never upload automatically. If email rejects the ZIP, let the owner share it using their chosen file-sharing service rather than hiding/renaming executable content.
7. Do not process the 112-location canary yet. Do not tune parallelism or approve contributions. A later parallel-runtime cell requires separate full calibration.

For prerequisites only, append `-PrepareOnly`; it downloads scene assets and checks layout but does not retrieve imagery. `-BootstrapOnly` is for CI: it tests the private Python and fixture validation, with no model or imagery download. Each invocation makes a new isolated test directory.

## What this produces

`pc-calibration-results.zip` contains redacted machine/configuration evidence, source/model/runtime hashes, generated input specs, the actual scene-index payloads/masks/checkpoints, available process logs, whole/per-location/per-view hashes, exact byte difference counts, and timings. Failures remain visible. No runtime binaries, models, imagery, or unrelated files are included in the return ZIP. Local path prefixes are redacted in text copies; binary scene records remain unchanged.

This uses Community's **existing** slow policy (one inference thread, batch/chunk 16, fetch concurrency 8, one encoder session). The existing VISION observation used a different policy. Therefore `COMMUNITY_CONFIGURATION_GAP` remains; these trials characterize the Windows candidate rather than assert matched configuration.

## Reference and interpretation limits

The public `gen4-v1` packet contains 1,024 unique locations, 64 logical batches of 16, 75 source-country labels, 4,096 complete historical scene views, and a fixed 112-location subset. Generation 4 and official status were matched to existing strict validator metadata; no new generation classification was inferred from appearance. Original scene masks were checked as complete and source artifact hashes verified during extraction. Each full-fixture batch has 16 distinct source-country labels.

All records came from one sealed no-road scene segment. The sample has 1,010 distinct headings but only one pitch and zoom setting. It is not a general representative sample of all imagery. `generation-evidence.json` contains audit witnesses; the original large metadata sources remain local to Andrew.

**HISTORICAL_REFERENCE_ONLY:** these are established VISION scene records, not three fresh stable runs of the current Mac configuration. **SOURCE_PIXELS_NOT_FROZEN:** no sealed source pixels or inference-boundary digests exist in this packet. Live trials must be labeled **NOT_ISOLATED_END_TO_END**. Differences cannot be attributed specifically to Windows, hardware, threading, precision, or provider. No numerical tolerance or search-quality threshold has been established. Exact differences are evidence, not automatic rejection or approval. This does not test older camera generations, new parallel configurations, search parity, or large-scale performance.

The original private ZIP and its instructions are superseded for setup by this repository workflow. The fixture and historical reference bytes are unchanged. The owner explicitly authorized publishing the fixture, panorama IDs, coordinates and reference embeddings; do not publish friends' machine reports/results without their permission.

## Dependency sources

- [Python 3.14.7 release and SHA-256](https://www.python.org/downloads/release/python-3147/): official x86-64 embeddable ZIP; application-local distribution.
- [Scene runtime manifest](../community/runtime_manifest.json): exact published Windows executable, DLL and SigLIP asset identities.
- [Existing local scene helper](../community/vision_index.py): invoked unchanged through its process-runner interface; no account or contribution CLI is invoked.
- [Gmail attachment restrictions](https://support.google.com/mail/answer/6590): JavaScript and other blocked types can be rejected even inside ZIP archives. Share repository links instead of emailing source bundles.
