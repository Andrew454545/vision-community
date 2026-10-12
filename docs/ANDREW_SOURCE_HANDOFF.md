# One source-side task for Andrew's AI

**Needed artifact:** a fresh protected-origin capture from the real current MMA
profile. That source is on Andrew's computer and unavailable on this laptop.
This consolidates the [existing request](https://github.com/Andrew454545/VISION/pull/17#issuecomment-6102363428);
it does not add a model matrix, build or general review.

## Execute once

Use VISION source revision `e118a442e0123477c4c64c4b0488ccd509548eff`, its
existing private Node runtime and the existing native exporter. The capture
wrapper is unchanged at the later PR head `5e57a26bad52fe195bc277cac55dd6c4a6a0cd07`.
Resolve the two real canonical private input paths locally. Briefly pause MMA
writes; choose a new output folder in an existing private parent.

```text
node automation/runtime-source/scripts/prepare-protected-mma-handoff.mjs --db <absolute-real-current-mma.db> --exporter <absolute-existing-mma-exclusion-sidecar> --exporter-sha256 3f021e023263c7e442d28a7f1bce7905f3f4da9ee84a3e6456c1e17c7cac3793 --output-dir <absolute-new-private-output-folder>
```

The exporter pin comes from protected-reference asset `624430825`. If the
existing binary differs, preserve the failure and return its actual build/source
identity; do not change the expected hash just to pass. Do not rebuild or install
anything to satisfy this request.

## Return privately

Return the complete generated success or failure folder through the existing
private VISION draft-release handoff (release ID `407402399`), using a new asset
name. Include the returned asset ID and independently computed archive SHA-256.
In the PR reply include only the safe wrapper summary, manifest/archive hashes,
capture/expiry times and private asset ID. Keep paths, coordinates, map names and
stderr inside the private artifact. Preserve the original output on the source
machine. Do not paste private files into a public issue or comment.

The wrapper exports twice, fingerprints Main/WAL and every selected Arrow/delta
member, and preserves bounded failure evidence. It copies **no Main, WAL, Arrow
or complete MMA database bytes** and performs no imagery/model processing,
downloads, paid Actions or Community-account work.

## What this does and does not unblock

This is origin capture, not portable Object import approval. Its original live
files must still match, and origin verification expires one hour after capture
starts. Never extend or relabel that timestamp. One capture supplies genuine
source/export evidence; do not repeatedly refresh it while integration is pending.

Codex here handles portable/live protection, runtime/tolerance decisions, trusted
assignments, registry/retention, publication/credit/search, recovery and rollout.
Human object-presence labels are unnecessary; numerical Mac/Windows parity uses
identical images, models and settings. No repeated broad owner signoff is needed.
Signing identities and clean testers are separate human resources already being
arranged with the laptop user; Andrew need not investigate them again.

If the real source or pinned existing exporter is unavailable, return that one
specific blocker plus the preserved failure artifact. Leave owner indexing and
the frozen Windows Scene pilot unchanged. Never access `geonections-images`.
