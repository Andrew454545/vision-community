# Release-pinned PC check inputs

Operator guide. Users keep the same **Set up this PC → Run PC check** flow.
Do not rewrite the historical calibration fixture to make a new check pass.

Policy versions 2 and 3 select a separately pinned 112-location source and
matching reference. Both retain the exact-runtime, completed full-calibration
and explicit quality-limit requirements of version 1. A policy's hash must come
from the trusted release; making a local policy does not grant server approval.

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

## Fixed inputs for version 3

Version 3 sets `version` to `3` and adds this object inside `dataset`:

```json
"syntheticInputs": {
  "generatorVersion": 1,
  "generatorSha256": "<trusted generator code SHA-256>",
  "manifestSha256": "<verified generated input manifest SHA-256>"
}
```

The pinned generator creates 448 nonphotographic RGB inputs locally from the
pinned source and model inventory. The reference must come from an independently
verified run on these exact inputs. The native check uses the FP32 scene graph,
the ordinary sixteen-image batch size and the requested shared thread pool.
It checks graph/model/source evidence, complete views and tensors, errors and
saved-index masks. Generator, manifest and RGB bytes are checked before and
after processing. Incomplete or changed inputs retain a failed report without
a submission packet or local approval.

This check retrieves no live imagery; the CLI needs no live-imagery consent for
version 3. It retains the same guided setup and independent service approval
flow. The existing three release assets are still required. A successful fixed
check neither approves a runtime without its full 1,024-location qualification
nor verifies the provenance of later live contributions.

Each attempt requires at least 1 GiB free space and caps native study evidence
at 384 MiB. Reports and failures remain private. Long-term attempt cleanup and
release distribution remain open requirements; these checks do not establish
a hard storage quota. No version-3 production policy or runtime release is
published by this code change.

## Why live inputs remain separate

**Version 2 retrieves live imagery. It does not freeze pixels.** Refreshing
the reference cannot guarantee repeatable images or establish runtime parity.
Keep source drift and numerical differences separate; do not weaken limits
automatically. The new 112-location diagnostic finished but fell outside the
predeclared cosine limit, with minimum `0.999840435671` and maximum relative L2
`0.017863811758`. It remains unqualified. Subsequent isolation passes with the
fixed images at the ordinary sixteen-image batch size; fetching again changes
41 image views and fails both limits. See [the comparison](HELD_OUT_SCENE_REFERENCE_20261004.md).
Version 3 provides the fixed starter path. No version-2 production policy or
refreshed release assets have been published. Trusted imagery identity for live
contribution audits remains a separate requirement; a fixed starter check cannot
remove changes in subsequently retrieved photographs.
