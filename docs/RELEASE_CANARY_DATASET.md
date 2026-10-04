# Release-pinned PC check inputs

Operator guide. Users keep the same **Set up this PC → Run PC check** flow.
Do not rewrite the historical calibration fixture to make a new check pass.

Policy version 2 can select a separately pinned 112-location source and matching
reference. It retains the exact-runtime, completed full-calibration and explicit
quality-limit requirements of version 1. A policy's hash must come from the
trusted release; making a local policy does not grant server approval.

Add these fields to that policy:

```json
{
  "version": 2,
  "dataset": {
    "fixture": {"path": "locations.tsv", "bytes": 0, "sha256": "<fixtureSha256>"},
    "reference": {"path": "reference.i8", "bytes": 344960, "sha256": "<referenceSha256>"},
    "parentReferenceSha256": "<independently verified parent reference>"
  }
}
```

This fragment is not a usable approval policy. Replace the placeholder source
size and hashes, preserve its other required qualification fields, and record
the release decision and evidence. Paths are relative to the policy folder;
absolute paths, parent traversal, linked files and Windows reparse points are
rejected. Source rows must have 112 distinct panoramas; reference records must
have valid finite nonzero vectors. All sizes and hashes are checked before use.

For the Windows guided starter, the trusted `runtime_manifest.json` can include:

```json
"pcCanaryPolicy": {
  "path": "canary/release-policy.json",
  "sha256": "<independently approved policy SHA-256>"
}
```

Its `files` list must independently pin the policy, source and reference as
non-executable scene assets for Windows. Setup uses the existing checked
downloader, validates the installed policy and both input files, then checks
them again before running. Missing, duplicate, changed or unpinned assets stop
the check. An absent manifest field preserves legacy-release behavior; a broken
field cannot silently fall back to historical inputs.

Each check indexes a private copy of the verified source. Changed runtime,
source or reference bytes during the run invalidate the result and remove the
submission packet. The independent service still decides qualification.

**This version retrieves live imagery. It does not freeze pixels.** Refreshing
the reference cannot guarantee repeatable images or establish runtime parity.
Keep source drift and numerical differences separate; do not weaken limits
automatically. The new 112-location diagnostic finished but fell outside the
predeclared cosine limit, with minimum `0.999840435671` and maximum relative L2
`0.017863811758`. It remains unqualified. Subsequent isolation passes with the
fixed images at the ordinary sixteen-image batch size; fetching again changes
41 image views and fails both limits. See [the comparison](HELD_OUT_SCENE_REFERENCE_20261004.md).
Immutable starter inputs remain a separate release requirement. No version-2
production policy or refreshed release assets have been published by this change.
