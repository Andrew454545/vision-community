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
141 checks without skips. The full local service suite passes all 246 checks
without skips. Its initial sandbox run passed 243; three existing Windows
junction fixtures could not be created there. Repeating the same suite with
normal filesystem permissions in a dedicated workspace test folder passes
those checks too. The original failure report is preserved. No security
settings or production protections were weakened.

The verified guard is deployed to confirmed Community staging version
`667d926c-2ee9-4060-9a74-f60ada14f7b5` (9 October, 00:10 UTC). All 13 served
assets match the source, privacy headers pass, anonymous account access and
cross-origin API access are refused, and Scene/Object admission remains closed.
The database, bucket, service and rate-limiter bindings match their pre-deploy
settings. Production, native Containers and the installed contributor were not
changed by this rollout.

The private handoff asks for Mac runs on the same sealed fixture, a documented
relationship to the actual production source/reference, and legitimate signing
resources. It requests local execution, not paid GitHub Actions. Full quality
and protected-authority replay, raw pre-packing vectors/tensors, actual graph
placement, held-out native rankings, trusted admission, accepted work, signing,
clean-device tests, endurance and production recovery remain release gates.
