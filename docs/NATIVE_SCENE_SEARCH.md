# Private native scene search adapter

`community.native_scene_search` connects an operator-sealed contribution snapshot
to VISION's real `search-four-view-index` command. It replaces neither the
reference models nor the credit gateway. It is an implemented private development
adapter; hosting, independent runtime admission, live snapshot export and general
Objects search remain release requirements.

## Data and trust

Use a snapshot built by `community.search_snapshot`, with a separately pinned
`snapshot.json` SHA-256. Only independently approved, published contributions
can enter that tool. The adapter copies those exact records into native v4
shards, writes complete-view masks and a native source TSV, and preserves every
registry ordinal. It never reads a maintainer corpus, imports queue catalogs,
creates accounts or changes credits. A new private work directory is required;
partial mounts retain a failure marker and cannot become completed mounts.

For an offline staging export, pass `--environment staging` to
`community.search_snapshot`. Production remains the default. The tool checks
the complete confirmed account/database/bucket pair and records it in the sealed
manifest. Updates cannot append a production snapshot to a staging snapshot,
even if their location IDs and record hashes match. Older v1 snapshots without
this field are treated as production only.

This option does not activate a live snapshot or approve any contribution. When
updating the hosted adapters, regenerate their helper/runtime/policy pins and
repeat the live activation/recovery checks; source edits cannot reuse old pins.

Pin `runtime.json` independently. Its SHA-256 is the gateway's
`SEARCH_RUNTIME_SHA256`; the snapshot pin is `SEARCH_SNAPSHOT_SHA256`, and its
`policyId` is `SEARCH_POLICY_ID`. The document has this shape:

```json
{
  "version": 1,
  "contractVersion": 2,
  "nativeLayout": 4,
  "policyId": "reviewed-scene-search-policy",
  "adapterSha256": "<SHA-256 of community/native_scene_search.py>",
  "pythonVersion": "<exact Python version>",
  "sourceFiles": {
    "__init__.py": {"bytes": "<integer>", "sha256": "<pin>"},
    "native_scene_search.py": {"bytes": "<integer>", "sha256": "<pin>"},
    "search_snapshot.py": {"bytes": "<integer>", "sha256": "<pin>"},
    "scene_quality.py": {"bytes": "<integer>", "sha256": "<pin>"},
    "four_view.py": {"bytes": "<integer>", "sha256": "<pin>"},
    "features.py": {"bytes": "<integer>", "sha256": "<pin>"}
  },
  "executable": "mma-vision.exe",
  "queryModes": ["textOnly"],
  "files": {
    "mma-vision.exe": {"bytes": "<integer>", "sha256": "<independent pin>"},
    "countries.txt": {"bytes": "<integer>", "sha256": "<independent pin>"},
    "models/vision_model.onnx": {"bytes": "<integer>", "sha256": "<independent pin>"},
    "models/vision_model_fp32.onnx": {"bytes": "<integer>", "sha256": "<independent pin>"},
    "models/text_model.onnx": {"bytes": "<integer>", "sha256": "<independent pin>"},
    "models/tokenizer.json": {"bytes": "<integer>", "sha256": "<independent pin>"}
  }
}
```

The example is a schema, not usable approval or file pins. Include every adjacent
native dependency in `files`, including DLLs on Windows. `countries.txt` must be
the pinned country list compiled into that binary. Store these files relative
to `runtime.json`, with all four canonical assets under `models/`. The document
pins the adapter and every imported Community helper, the Python version and
executable/models/dependencies. Source pins refer to the installed Community
package; asset pins refer to the directory containing `runtime.json`. Unknown
files/directories, traversal, symlinks and Windows reparse points fail closed.
Runtime payloads are bounded to 16 files / 1.5 GiB, with at most 512 MiB per file.
Strong hashes are checked before and after each actual native search. The
native size/mtime model identity is also preserved and checked; timestamps are
not used instead of content hashes.

Do not generate approval from a volunteer-supplied checksum. A digest establishes
identity, not inference quality. A pinned development runtime stays development
evidence until the acceptance checklist's controlled quality checks are complete.

## Private service

Prepare the private runtime on its intended service host, using the same Python
interpreter and Community package that will run the adapter:

```text
python -B -m community.native_scene_runtime --build NATIVE_BUILD/build-evidence.json --build-sha256 BUILD_RECEIPT_PIN --binary-dir NATIVE_BUILD/target/release --model-pins MODEL_PINS.json --model-pins-sha256 MODEL_INVENTORY_PIN --models CANONICAL_MODELS --countries NATIVE_SOURCE/app/src/data/country-names.txt --countries-sha256 COMPILED_COUNTRY_PIN --out NEW_PRIVATE_RUNTIME --policy-id SEARCH_POLICY_ID --query-mode textOnly
```

Use the independently supplied build-receipt, model-inventory and country pins.
The command copies the executable, every DLL declared in that receipt and all
four model files into the layout above, retaining model timestamps and executable
permissions. It checks the compiled country dependency and all copied bytes,
pins the installed adapter/helper sources and Python version, and writes
`runtime.json` last. Its JSON result supplies `runtimeSha256` for the gateway and
service command. Existing outputs are preserved; a failed copy retains a fixed
failure marker without a completed runtime manifest. No download, model
execution, qualification or deployment is performed. The selected query modes
still belong to the operator's acceptance decision; the command packages their
identity rather than generating approval from client data.

Run with the application's private Python:

```text
python -B -m community.native_scene_search --runtime PRIVATE_RUNTIME/runtime.json --runtime-sha256 RUNTIME_PIN --snapshot PRIVATE_SNAPSHOT --snapshot-sha256 SNAPSHOT_PIN --work NEW_PRIVATE_WORK --port 8766
```

Set `VISION_SEARCH_ENGINE_SECRET` in the trusted service environment, with at
least 32 printable characters. Do not put a credential in a command, Git, browser
or logs. The adapter listens only on `127.0.0.1` and requires Bearer authorization
on `/search`. A [private hosting bridge](../deploy/cloudflare/native-scene-bridge/README.md)
connects an operator-configured HTTPS ingress to the Community Worker's
`SEARCH_ENGINE` binding, preserving request bytes and injecting the host secret.
The hosted native process and HTTPS ingress still need configuration; the adapter
command creates no public endpoint or deployment. It accepts the version-2
gateway request, including all
runtime/snapshot/policy/request pins. The exact embedded JSON query bytes are
hashed, retaining JavaScript's numeric spellings and order across the Python
boundary. No browser-supplied engine URL or pin is accepted by the gateway.

One native process can run at a time per engine instance. Extra compute requests
fail unavailable; they do not create an unbounded queue. HTTP connection count
and header/body reads are bounded, bodies allow the gateway's 8 MiB plus a small
contract envelope, native execution stops after at most 110 seconds, logs and
output files are bounded, and responses fit the gateway's 4 MiB ceiling. Native
commands use no shell or inherited account credentials/provider overrides.

Every search uses a fresh private query/model-profile directory. Success and
failure remove that scratch, including prompts, cached text vectors and stderr.
The first redacted report for each fixed failure code is retained without
overwriting it; repeated outages do not create unlimited reports. Deliberate
private diagnostic studies preserve detailed raw evidence separately. Nothing
uploads the model files, private queries, indexes or reference images.

## Search semantics and limits

The existing native encoder, normalized vectors, compressed-vector scoring and
best-view selection remain the ranking path. The adapter applies authoritative
registry ordinals, import cutoff, duplicate-panorama removal, exclusions within
25 m, per-country caps and 100 m spatial pruning in score/ordinal order. The
gateway independently rechecks published contributor membership and poses before
settling the saved result and debit. Native pose metadata is checked at the
reference's seven-decimal export precision; returned IDs/scores/views are exact,
and the gateway's authoritative poses remain the output source. This introduces
no model-quality acceptance tolerance.

Native topK is limited to 10,000. The adapter scans the sealed snapshot and asks
for up to that many candidates before applying the remaining constraints. If the
budget is full and the requested count cannot be filled, it fails unavailable
instead of charging for a silently truncated/false-empty result. Snapshots remain
bounded to 100,000 locations by their sealer. Larger pools need a measured search
registry/partitioning design; this adapter does not advertise 200M capacity.

The runtime explicitly allowlists query modes. Only text-only mode was exercised
with real native inference in this development pass. Other native modes must be
separately exercised/admitted before listing them. Objects and road-name rejection
are unavailable: generic pose metadata cannot establish detection audits or road
authority. Unsupported modes/features, changed files, malformed native output,
incomplete scans, stale snapshots and engine timeouts spend no credit.

Saved-index queries explicitly request `sceneFp32: true`. The native saved-search
path must propagate that flag into the image-example encoder and graph-specific
query cache; an older binary may silently ignore an unknown JSON field. Before
accepting a hosted result, the adapter therefore checks actual CPU pool execution
and, whenever examples were supplied, explicit fp32 image-graph execution. This
does not admit image-example modes: their real comparison evidence and runtime
allowlist are still required. Changing the adapter requires regenerating the
runtime/helper manifest and gateway pins on the intended service host.

## Evidence and local gateway rehearsal

Fifteen synthetic/helper checks cover seals/pins/geometry, tampering, filters,
candidate exhaustion, exact JSON fingerprints, private HTTP authentication and
bounds, actual killed helper processes, failure recovery and bounded reports.
These tests do not run the model or approve its quality.

Separately, the pinned native Windows executable and actual retained 16-location
records completed road/shop/landscape HTTP searches. Ordered IDs, scores and
selected views match the direct native results after existing threshold/pruning
rules. The complete local workerd/D1 gateway then exercised these real searches,
saved-credit debits, replay without new inference/debit, JavaScript scientific
coordinate spelling, unavailable service and removal of contributor ownership.
All pass. Publication rows/accounts/credits in that rehearsal are disposable
local fixtures; no live contribution or account was created, and no reference
data was published. Original failures are preserved privately.

On 2026-10-01, the packaging command prepared the real Mac development runtime
from the independently pinned build receipt and all four canonical model files.
The retained 16-location scene records then passed the same complete local
workerd/D1 gateway rehearsal through the private bridge and the real native
adapter. Road/shop/landscape IDs, scores and selected views match the direct
native reference after existing thresholds/pruning. Four native queries, three
recoveries without extra inference/debit, scientific-coordinate fingerprints,
outage and removed-contributor checks all pass. An initial bridge request-framing
failure was retained and fixed by letting Fetch frame the unchanged byte body.
Nine transport tests include an actual HTTP check of its Unicode bytes and
computed request length. Eight runtime packaging tests cover pins, dependencies,
permissions/timestamps, startup and preserved incomplete outputs. The Python
suite ran 304 tests with 15 Windows-only skips; all 97 JavaScript tests pass.
Main/bridge dry-run builds and the separate local gateway/verifier checks pass.
This uses disposable local rows, accounts, credits and storage; the reference
corpus was not imported into the live Community index. The fixture, runtime,
queries, indexes and failure logs remain in the private technical handoff.

`deploy/cloudflare/tools/check-native-scene-gateway.mjs` reproduces the latter
rehearsal using a deliberately labeled private fixture and an already running
loopback engine. Provide Miniflare, the dry-run Worker bundle and fixture paths;
pass the loopback URL and secret through the test process environment. It rejects
external engine hosts and uses only ephemeral local D1/R2. Its fixture's expected
results must come from separately checked native output; do not invent scores.
Pass the private bridge module as an optional fourth argument to exercise its
request-byte and authorization forwarding in that same rehearsal.

For production continuation, first host the adapter behind a trusted HTTPS
ingress and configure the bridge secret, private service binding and three
gateway identity pins. Use a snapshot sealed from published contributions;
the private reference rehearsal is not a live publication inventory. Exercise
that actual HTTPS path before enabling search. The trusted scene verifier,
approved PC policy, real accepted contribution and Windows workload/recovery
exercise remain separate deployment work in
[PRODUCTION_ACCEPTANCE.md](PRODUCTION_ACCEPTANCE.md). The contributor owns the
remaining acceptance decisions under Andrew's existing authorization.

No Mac installed-runtime equivalence, full calibration/device/parallel admission,
live hosting, restoration, endurance, traffic-scale latency or cost claim follows
from these checks. Andrew withdrew a separate sign-off requirement; engineering
decisions can proceed independently while those evidence requirements remain.
