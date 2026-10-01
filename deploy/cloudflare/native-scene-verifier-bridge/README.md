# Private native contribution verifier

This service binding transports `/qualify` and `/audit` to the operator's native
VISION host. The native implementation is `community/native_scene_verifier.py`.
Unlike the staging digest verifier, it recomputes every submitted location with
the pinned native binary and models before comparing the four scene vectors.
It has no public Worker URL, preview, database, bucket or browser approval route.

Prepare the native runtime using [the native runtime guide](../../../docs/NATIVE_SCENE_SEARCH.md).
Changing the shared Python runtime adapter requires repackaging `runtime.json`;
its source hashes must match the installed modules. Choose an always-on host and
a trusted HTTPS ingress that forwards only `/qualify` and `/audit` to its
loopback listener. The bridge expects an HTTPS origin without a path, query,
fragment or embedded credentials.

The operator supplies a separate private `policy.json` and
`canary-reference.i8` in the same directory. The policy is version 1 and contains:

- `scope`: `trusted-native-scene-audit`.
- `policyId`: the selected admission policy identity.
- `runtimeSha256`: the SHA-256 of the packaged `runtime.json`.
- `sourceFiles`: the exact mapping returned by
  `community.native_scene_verifier.source_pins()` in the installed checkout.
- `profiles`: one to sixteen independently admitted canary policy documents,
  validated by `community.pc_canary.CanaryPolicy`. Each identifies the runtime
  profile, 112-location fixture and reference hashes, approved full calibration
  evidence for 1,024 locations and at least three repetitions, and explicit
  numerical qualification thresholds. All use the same reference and policy ID.
  Optional `expiresInSeconds` is at most 30 days; the default is seven days.
- `auditThresholds`: explicit `minimumViewCosine` and `maximumViewRelativeL2`
  bounds for comparing client output with freshly recomputed native output.

Reference bytes are 112 complete four-view records of 3,080 bytes each. Their
SHA-256 must equal every admitted profile's `referenceSha256`. The service
requires a separately supplied SHA-256 of the entire policy. Policy fields that
claim approved calibration are operator assertions backed by the named evidence,
not automatic approval inferred from a client report. No production tolerances
or profiles are included here. Synthetic test policies must remain local tests.

Set `VISION_SCENE_VERIFIER_SECRET` in the host's private environment, then start
from the repository root with real paths and independently supplied hashes:

```text
python -B -m community.native_scene_verifier --runtime /private/runtime/runtime.json --runtime-sha256 RUNTIME_SHA256 --policy /private/policy/policy.json --policy-sha256 POLICY_SHA256 --work /private/new-audit-work --port 8767
```

The work directory must be new and outside the runtime and policy directories.
The service listens on `127.0.0.1`, permits one native audit at a time and removes
each job's temporary imagery and index files. Hosting failures remain retryable;
invalid contributions are rejected. A process manager should choose a fresh
work directory on each start. Startup readiness does not imply any PC profile
has been admitted.

From `deploy/cloudflare`, deploy the private bridge using the existing trusted
Cloudflare sign-in:

```text
node node_modules/wrangler/bin/wrangler.js deploy --config native-scene-verifier-bridge/wrangler.toml
node node_modules/wrangler/bin/wrangler.js secret put NATIVE_VERIFIER_ORIGIN --config native-scene-verifier-bridge/wrangler.toml
node node_modules/wrangler/bin/wrangler.js secret put NATIVE_VERIFIER_SECRET --config native-scene-verifier-bridge/wrangler.toml
```

The second secret matches the host's `VISION_SCENE_VERIFIER_SECRET`, a random
32–256-character printable ASCII value without spaces. Enter secrets at the
prompts; keep them out of source, command arguments and logs. The bridge forwards
exact JSON bytes and its own authentication, with bounded sizes and duration.
It does not forward caller cookies or credentials or follow redirects.

After the host and ingress are operational, configure the Community Worker:

```toml
[[services]]
binding = "SCENE_VERIFIER"
service = "vision-community-native-scene-verifier"

[vars]
SCENE_POLICY_ID = "THE_OPERATOR_POLICY_ID"
```

Preserve existing deployment variables. First use a separate staging D1/R2 pair
and test qualification, a real accepted contribution, a rejected contribution,
an unavailable host and replay protection. `/api/capabilities` must report the
expected policy and required device qualification. Confirm only accepted output
earns credits and repeated completion never earns a second credit. Setting a
binding alone does not establish readiness; the native host, measured policy,
actual client runtime and ingress must all work together.
