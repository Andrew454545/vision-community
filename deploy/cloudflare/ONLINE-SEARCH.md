# Online search with banked credits

The accepted product rule is one banked credit per completed hosted search.
`SEARCH_COST` remains 100,000 units; scenes earn one and objects earn ten.
Credits have no expiry or cap. An empty, valid result is a completed search.
Engine errors, invalid results and failed database transactions spend nothing.
A replay of the same request key and normalized query returns its saved result.
Changing that query under the same key returns 409 rather than another debit.
Clients send their expected anonymous `accountId` alongside the request. If
another sign-in changes the authenticated account during a retry, the Worker
returns `account_changed` instead of charging the other account.

## Engine requirements

The existing `community-visual-v1` demonstration extractor is not the engine.
Use VISION's pinned four-view SigLIP scene runtime and hybrid object runtime.
Verify reference parity on controlled inputs and held-out queries, including
country limits, saved poses, view choices, road labels, import cutoffs and
RF-DETR/YOLOE/OWLv2 routing. Measure memory, request concurrency and cost before
choosing a hosting configuration. A model file alone does not establish parity.

Build the engine registry from an independently sealed snapshot of verified
contributions. Never mount the maintainer's private corpus. Every snapshot
member must name its Community location ID and published artifact digest.
Object members also require official Gen4 historical-capture receipts. An
operator must verify the registry's member inventory against D1 before pinning
its digest. This exporter and general inference service are not implemented
yet; do not bind a fake or staging-reference-only verifier as a search engine.

Bind the validated private service as `SEARCH_ENGINE`; never accept a URL,
runtime digest, corpus digest or approval policy from the browser. Configure:

- `SEARCH_POLICY_ID`: reviewed engine/search policy identifier.
- `SEARCH_RUNTIME_SHA256`: fingerprint of the executable, model assets,
  preprocessing, postprocessing, settings and adapter.
- `SEARCH_SNAPSHOT_SHA256`: independently sealed contributed registry digest.

The Community Worker sends `POST https://search.internal/search` over the
service binding. Version 2 request fields are `contractVersion`, `policyId`,
`runtimeSha256`, `snapshotSha256`, `requestSha256` and `query`. Query fields are
`lane`, `prompt`, sampled `examples`, `excluded`, `queryName`,
`descriptionWeight`, `viewDirection`, `resultCount`, `maxPerCountry`, `filters`,
`objectConfidence`, `rejectRoadNames` and `minimumGlobalLocation`.
The last field is an engine-registry ordinal, not an arbitrary D1 row ID.
Object confidence choices are `highRecall`, `balanced`, `precise` as in VISION.

Return the same five identity fields, `processedLocations`, and ordered `hits`.
Each hit has `locationId`, `outputSha256`, `score`, `viewOffset`, and `sourceIndex`
(the zero-based ordinal in the sealed registry, not the D1 location ID). Object
hits also carry an absolute `heading`, `pitch`, `zoom` pointing at the detection,
and `object` with `lane` (`common`, `hot`, `semantic`), `className`, `classId`
(nullable outside common), `confidence`, `supportCount`, and `bboxArea`.
The gateway bounds the response to 4 MiB, checks all pins, validates published
membership/digests and authoritative poses, and enforces view/country/camera
filters, exclusions, duplicate removal and spatial pruning before settlement.
Trusted engine validation still owns model inference, complete corpus scans,
road-label authority, import ordinals and reference ranking quality.

Map exports use the reference application's mode, query text, model names,
seven-decimal rounding, source ordinal and detection fields. `visionMinScore`
is the query's threshold, not the lowest returned score. Those existing scene
query thresholds are unrelated to the still-undetermined Windows numerical
approval tolerances. Hits below the query threshold, malformed detection
metadata, out-of-range/duplicate ordinals and hits preceding the import cutoff
are rejected before spending credit. Ties are ordered by registry ordinal.
These structural checks do not independently prove the engine's ranking quality.

## Recovery and data boundaries

The browser stores its pending request before delivery, scoped to the anonymous
account on this origin. A restart recovers that exact request, even if the
balance is now below one credit. Results are saved locally before clearing the
pending request. Site-storage failure prevents starting a new paid request.
Request fingerprints in D1 are SHA-256, not raw prompt strings. Saved result
JSON includes the requested output name and returned coordinates; a separate
retention/deletion policy is still required. Do not log prompts, recovery codes
or bearer tokens in either service.

The Worker no longer distributes shared indexes. Offline diagnostic commands
and the local Python test service are not a way to spend production credits.
Data downloaded under the older model cannot be recalled. This change has
local concurrency/recovery tests; it is not a live engine deployment approval.

## Reproduce the Cloudflare runtime check

From `deploy/cloudflare`, install the following test dependencies locally (no
global installation), build without deploying, and run the synthetic check:

```sh
npm install --no-save --package-lock=false --ignore-scripts wrangler@4.144.0 miniflare@5.20260926.1-alpha
node node_modules/wrangler/bin/wrangler.js deploy --dry-run --outdir .local-test-build
node tools/check-local-runtime.mjs node_modules/miniflare/dist/src/index.js .local-test-build/worker.js
```

The check uses local D1/R2, a synthetic engine callback and a disposable
anonymous account. It tests six simultaneous retries, competing requests for
the final credit, account changes, zero-balance replay, every retired download
route, and rollback after a forced result-storage failure. It needs no
Cloudflare login and does not contact any production resource or fetch imagery.
The build folder is ignored. The same check now runs in GitHub CI.
