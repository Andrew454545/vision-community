# Object replay separation — 8 October 2026

Full Object comparisons need the same saved image bytes on both computers.
Private native development now adds a pinned six-face input source to the
normal index loop. The local build, source and images remain private. It does
not change the installed contributor or authorize devices.

Replay outputs carry `frozenViewsManifestSha256`. The Python submission
validator, public snapshot sanitizer and service validator refuse that marker,
including null or empty values. Sanitizing paths must not hide a diagnostic
index's identity and turn it into a contribution.

The offline comparator can read a valid diagnostic marker. It reports the two
declared manifest hashes, but does not attest those images or their provenance.
Different declared hashes remain visible; they are not silently treated as an
identical-pixel comparison. All approval, pixel-attestation and native-search
parity flags remain false.

The affected Python comparison, embedding, feature and snapshot tests pass all
141 checks without skips. Focused service tests pass 74 checks. A wider local service run passes 243 of
246 checks; three existing file-link fixtures fail with Windows `EPERM` before
they can exercise their link-refusal assertion. The original failure report is
preserved. No security settings or production protections were weakened.

The private handoff asks for Mac runs on the same sealed fixture, a documented
relationship to the actual production source/reference, and legitimate signing
resources. It requests local execution, not paid GitHub Actions. Full quality
and protected-authority replay, raw pre-packing vectors/tensors, actual graph
placement, held-out native rankings, trusted admission, accepted work, signing,
clean-device tests, endurance and production recovery remain release gates.
