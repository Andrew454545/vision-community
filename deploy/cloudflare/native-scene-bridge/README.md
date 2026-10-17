# Private native scene search bridge

This Worker connects the Community Worker's `SEARCH_ENGINE` service binding to
the operator's hosted native scene adapter. It has no public Worker/preview URL,
browser route, D1 or R2 binding. The gateway owns credit settlement and admission.

Run the native adapter behind a trusted HTTPS ingress that forwards to its
loopback `/search` listener. Prepare its runtime/snapshot using
[the native service guide](../../../docs/NATIVE_SCENE_SEARCH.md). Set the same
32–256-character printable ASCII secret in the adapter's
`VISION_SEARCH_ENGINE_SECRET` and this Worker's `NATIVE_ENGINE_SECRET`.
`NATIVE_ENGINE_URL` is that ingress's HTTPS `/search` URL without credentials,
query parameters or fragments. These are operator configuration, never values
from a browser request.

From `deploy/cloudflare`, using the existing trusted Cloudflare sign-in:

```text
node node_modules/wrangler/bin/wrangler.js deploy --config native-scene-bridge/wrangler.toml
node node_modules/wrangler/bin/wrangler.js secret put NATIVE_ENGINE_URL --config native-scene-bridge/wrangler.toml
node node_modules/wrangler/bin/wrangler.js secret put NATIVE_ENGINE_SECRET --config native-scene-bridge/wrangler.toml
```

The secret commands prompt for values. Keep them out of command arguments,
source, browser state and logs. Once the hosted adapter and bridge are configured,
add this binding to the Community Worker's deployment configuration:

```toml
[[services]]
binding = "SEARCH_ENGINE"
service = "vision-community-native-scene-search"
```

Set `SEARCH_POLICY_ID`, `SEARCH_RUNTIME_SHA256` and `SEARCH_SNAPSHOT_SHA256` to the
operator-selected policy/runtime/snapshot identities. The adapter and Community
gateway verify them. This component supplies transport; it does not approve a
runtime or deploy models/indexes.

The bridge preserves exact JSON request bytes, including Unicode and scientific
number spellings, and injects only its native-host Bearer secret. Caller cookies
and authorization are not forwarded. Redirects are not followed; request and
response sizes and upstream duration are bounded. Upstream failures and invalid
or oversized responses produce a fixed unavailable response. Native diagnostics,
cookies and extra headers are not returned. No request logging is added. The
gateway validates the complete response before any debit.

CI runs transport tests and a Wrangler dry-run build. The private native gateway
rehearsal accepts the bridge module as an optional fourth path:

```text
node tools/check-native-scene-gateway.mjs node_modules/miniflare/dist/src/index.js .local-test-build/worker.js PRIVATE_FIXTURE.json native-scene-bridge/worker.js
```

That rehearsal uses an explicitly labeled disposable local fixture and a
diagnostic fetch adapter mapping a fixed synthetic HTTPS hostname to the
validated loopback engine. It does not change the production bridge's HTTPS
requirement or connect live D1/R2. Hosting the native adapter and exercising its
actual HTTPS ingress remain deployment work.
