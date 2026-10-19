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
2. Download/extract the exact linked repository ZIP into a new local, non-synced folder; do not require the user to install Git. If a matching checkout already exists, inspect it without modifying its source. Read the scripts and use the pinned fixture/runtime checksums. The fixture and runtime manifest are sealed byte-for-byte; Git's `.gitattributes` prevents line-ending conversion of these files.
3. From the extracted repository root, run:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\calibration\Start-WindowsCalibration.ps1 -AcceptDownloadsAndLiveImagery
   ```

   `Bypass` applies only to this child process. Do not run `Set-ExecutionPolicy`, elevate, or disable security tools. If organizational policy blocks execution or a download, report that blocker instead of circumventing it.

4. No pip/Pillow installation is necessary for this path: Python's standard library and the existing scene helper are sufficient. The setup downloads only scene assets, not object models. It verifies checksums before execution.
5. Wait for all three trials. Show occasional progress from the process/task status without exposing panorama IDs or raw output records. Do not kill a quiet inference process solely because it has no console output; each subprocess has a two-hour timeout. Do not silently resume a failed trial or reconfigure inference to obtain matching bytes.
6. Return the ZIP path, SHA-256, completed/failed run counts, repeatability results, and limitations from `summary.json`. A nonzero exit can still produce a useful failure ZIP. Never upload automatically. If email rejects the ZIP, let the owner share it using their chosen file-sharing service rather than hiding/renaming executable content.
7. Keep the default one-thread experiment unless the user requests the thread experiment described below. The initial full 1,024-location runtime qualification comes before the 112-location user screen described below. Calibration never approves production contributions automatically.

For prerequisites only, append `-PrepareOnly`; it downloads scene assets and checks layout but does not retrieve imagery. `-BootstrapOnly` is for CI: it tests the private Python and fixture validation, with no model or imagery download. Each invocation makes a new isolated test directory.

## What this produces

`pc-calibration-results.zip` contains redacted machine/configuration evidence, source/model/runtime hashes, generated input specs, the actual scene-index payloads/masks/checkpoints, available process logs, whole/per-location/per-view hashes, exact byte difference counts, decoded numerical comparisons, and timings. Failures remain visible, with completed, failed and unstarted trials counted separately. No runtime binaries, models, imagery, or unrelated files are included in the return ZIP. Local path prefixes are redacted in text copies; binary scene records remain unchanged.

The default uses one inference thread, batch/chunk 16, fetch concurrency 8 and one encoder session. On Windows, the helper disables an unsupported macOS thermal-state query that otherwise prevents indexing; operating-system thermal protections remain unchanged. Generated inputs, effective thread environment and source hashes record the actual policy. The existing VISION observation used a different policy. Therefore `COMMUNITY_CONFIGURATION_GAP` remains; these trials characterize the Windows candidate rather than assert matched configuration.

## Optional full thread experiment

When the user requests a thread comparison, append `-Threads '1,2,4'` to the PowerShell command. This runs **nine full trials**: three each at 1, 2 and 4 requested inference threads. It takes longer than the default three trials. Each trial starts with a fresh index/checkpoint. Cell order rotates across repetitions to reduce systematic timing effects; fetch concurrency, batch/chunk size and encoder sessions stay fixed. The requested environment settings are recorded, but the binary's effective backend threading is not independently attested.

For an already prepared private Python/runtime, the equivalent developer command is:

```powershell
& '<private-python>\python.exe' -B .\calibration\run_windows.py --root '<new-test-folder>' --allow-downloads --allow-live-imagery --threads 1 2 4 --reuse-runtime '<existing-runtime-folder>'
```

`--reuse-runtime` rechecks every pinned asset's size and SHA-256; it never repairs or modifies that folder. All new outputs and temporary files go in the new test folder. Download consent remains explicit. The runner stops on the first failed trial and packages the available evidence without secretly retrying it.

Reports compare every completed trial with Andrew's historical reference, compare repetitions within each thread cell, and compare matching repetition numbers across thread cells when a one-thread baseline is present. They include observed throughput ratios, cosine distributions, unit-vector L2 distances, scale-aware relative L2 errors, and coordinate errors. Cosine measures direction; scale-aware errors also detect magnitude differences. None of these diagnostics establishes search quality or an acceptance threshold.

Because imagery is fetched live, this experiment cannot isolate numerical changes caused by threading. Before changing production defaults, use a rights-approved fixed-input benchmark or matching inference-boundary digests, fresh repeated Andrew reference runs with known model/provider/precision/preprocessing settings, measured memory/temperature, and held-out search queries judged against his rankings. Agree on quality tolerances from that evidence, then validate each hardware/runtime configuration. Do not infer tolerance from a single average cosine or turn historical byte differences into an automatic rejection.

## Short check for a new user's PC

The intended sequence is: the maintainer reviews full 1,024-location runtime trials against Andrew's reference, defines a versioned approval policy, and then each user's PC runs the **112-location canary once** before contributing. The canary is a fixed subset of the full fixture with a fixed record order. It checks complete views and compares decoded vectors to the corresponding historical reference records.

The guided starter uses `community.pc_canary`. For a private diagnostic run with the processing files already prepared:

```powershell
& '<private-python>\python.exe' -B -m community.pc_canary --root '<new-canary-folder>' --binary '<runtime-folder>\bin\mma-vision.exe' --model-dir '<runtime-folder>\models\siglip-b16-224-canonical' --allow-live-imagery
```

This produces a local `canary-report.json`, retaining failure evidence. It does not create an account or upload anything. A completed diagnostic without an owner-approved policy remains unqualified. A trusted server qualification is separate from the local report: the server must check the full canary output and runtime qualification, not trust a client-supplied “passed” flag. Only an explicitly authorized contribution workflow may submit the report's verification packet.

The runtime profile fingerprints the executable, model files, Windows DLLs, indexing helper, layout code and inference settings. The starter must recheck this identity before indexing; a changed runtime or settings requires a new check. Policies name the exact fixture/reference/profile and reviewed full-calibration evidence, with explicit per-view cosine and relative-error bounds chosen by the owner. No numerical thresholds are supplied by this repository.

## Reference and interpretation limits

The public `gen4-v1` packet contains 1,024 unique locations, 64 logical batches of 16, 75 source-country labels, 4,096 complete historical scene views, and a fixed 112-location subset. Generation 4 and official status were matched to existing strict validator metadata; no new generation classification was inferred from appearance. Original scene masks were checked as complete and source artifact hashes verified during extraction. Each full-fixture batch has 16 distinct source-country labels.

All records came from one sealed no-road scene segment. The sample has 1,010 distinct headings but only one pitch and zoom setting. It is not a general representative sample of all imagery. `generation-evidence.json` contains audit witnesses; the original large metadata sources remain local to Andrew.

**HISTORICAL_REFERENCE_ONLY:** these are established VISION scene records, not three fresh stable runs of the current Mac configuration. **SOURCE_PIXELS_NOT_FROZEN:** no sealed source pixels or inference-boundary digests exist in this packet. Live trials must be labeled **NOT_ISOLATED_END_TO_END**. Differences cannot be attributed specifically to Windows, hardware, threading, precision, or provider. No numerical tolerance or search-quality threshold has been established. Exact differences are evidence, not automatic rejection or approval. The default does not test parallel configurations; even the optional thread experiment does not test older camera generations, search parity, or large-scale performance.

The original private ZIP and its instructions are superseded for setup by this repository workflow. The fixture and historical reference bytes are unchanged. The owner explicitly authorized publishing the fixture, panorama IDs, coordinates and reference embeddings; do not publish friends' machine reports/results without their permission.

## Dependency sources

- [Python 3.14.7 release and SHA-256](https://www.python.org/downloads/release/python-3147/): official x86-64 embeddable ZIP; application-local distribution.
- [Scene runtime manifest](../community/runtime_manifest.json): exact published Windows executable, DLL and SigLIP asset identities.
- [Local scene helper](../community/vision_index.py): invoked through its process-runner interface with explicit thread settings and the documented Windows thermal compatibility fix; no account or contribution CLI is invoked.
- [Gmail attachment restrictions](https://support.google.com/mail/answer/6590): JavaScript and other blocked types can be rejected even inside ZIP archives. Share repository links instead of emailing source bundles.
