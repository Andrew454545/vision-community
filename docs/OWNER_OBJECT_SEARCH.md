# Owner-local Object search

**Source only, disabled and undeployed.** The owner's [cost hold](COST_STOP_20261012.md)
continues. This is an inert Python engine for the approved offline architecture
work, not a new service, download or instruction to restart processing.
Contributors do not need these operator details.

[`NativeObjectSearchEngine`](../community/native_object_search.py) implements the
same `search(request, raw_query=bytes)` interface as the Scene engine. It can be
passed as the `object` engine to the existing [outbound agent](QUEUED_SEARCH_DELIVERY.md).
There is no command-line entry point, listener, account API, startup installer,
model download, provider lookup, publication or credit function in this adapter.

## Trust and input identity

The operator supplies an existing private binary/model directory, a separately
checksum-pinned runtime policy, a separately pinned [Object snapshot](OBJECT_SEARCH_SNAPSHOTS.md)
and a private scratch directory. The scratch directory cannot overlap any input.

The snapshot must contain only independently audited, published contributor
batches, with the existing exact official-Generation-4 coverage evidence and
approved complete feature bundles. Reusing an uploader's ID-record digest does
not approve RF-DETR/YOLOE/OWLv2 output. The existing snapshot verifier checks this
sealed authority; the adapter does not turn a frozen diagnostic, Andrew's personal
catalog or a client-supplied `gen4` label into a searchable contribution.

The runtime policy has exactly these fields:

| Field | Required value |
|---|---|
| `version`, `contractVersion`, `scope` | `1`, `2`, `trusted-native-object-search` |
| `policyId` | Independently configured policy; staging-prefixed IDs require staging |
| `pythonVersion`, `sourceFiles` | Exact Python version and current `source_pins()` inventory |
| `runtimeProfileSha256` | Independently approved `object_canary.runtime_profile` digest |
| `environment`, `resource` | Explicit production/staging and its confirmed Community resource pair |
| `maxLocations`, `maxBundles`, `timeoutSeconds` | Positive integers no greater than 4,096 / 32 / 110 |

The engine's `runtimeSha256` is the checksum of that policy file. It must match
the coordinator's configured search runtime. A matching hash identifies bytes;
it does not supply the missing authentic Mac/PC score-parity qualification.
Do not auto-generate a production approval from a locally discovered runtime.

Runtime checks include the exact native binary, adjacent DLL/dylib inventory,
all existing Object model assets, their internal relative-file references, the
official RF-DETR/codebook hashes and the Python source inventory. Bounds are
checked before hashing: 512 MiB per native/model asset, 2 GiB combined and at most
32 adjacent dependencies. The snapshot must have exactly its sealed files and
directories, without links, extra feature files or a different resource pair.
Complete verification brackets native execution; a changed input refuses the
entire completion. The supported native build must emit the existing shared
one-thread ONNX Runtime receipt. CPU selection alone does not certify parity.

## Search and batch identity

The original normalized query bytes are checked against their SHA-256 before
translation. Exponent spellings such as `1e-7` are preserved. Object requests must
have no image examples and use official Gen4 filtering. The gateway's historical
`bestOfFour` query field is retained for contract compatibility; native Objects
still use six cube faces. Road-name rejection remains unavailable because this
snapshot has no current road-name authority. Unsupported requests fail without
a completion or debit.

Routing reuses VISION's existing common-class / hot-concept / semantic planner,
confidence floors and native `search` command. Semantic query text is limited to
1,000 characters to satisfy the gateway's Object class-name contract. Queued
requests retain the 64 KiB normalized-input and 1,000-result limits.
The native input/output, absolute TSV-path requirement and candidate-heap
behavior were checked against the saved VISION reference
[`9811448` search source](https://github.com/Andrew454545/VISION/blob/9811448e3e05259e08f5106ab5a7740dce0c6b4a/object-sidecar/src/search.rs).

Each sealed batch has its own native IDs starting at zero. Searching all batches
as if those IDs were unique would mix locations. The adapter instead runs each
batch separately, maps each validated local result through its sealed member to
the stable snapshot ordinal, then merges by score and ordinal. Accepted feature
files, ID records and the snapshot are never rewritten. Native validation requires
an exact machine-local TSV path, so only that field is changed in an ephemeral
manifest in private scratch; every other manifest field stays identical.

Each batch requests the native maximum of 10,000 results and disables distance
pruning there. A sealed batch has at most 1,000 locations and 32,000,000 bytes;
the native million-candidate heap can contain all its relevant records. This
avoids hiding needed candidates behind a small per-country overfetch heuristic.
Cross-batch pano deduplication, 100-meter pruning, exclusions, country caps,
requested count and minimum **snapshot ordinal** then apply globally. The native
batch ID is never substituted for that ordinal. Native results must match the
exact member pose, route/class, view, confidence, aim, order and filters before
being used. Empty valid results remain distinguishable from execution failure.

One 110-second maximum covers all batch executions and input checks, with at most
one native child per instance. Children use the existing windowless bounded
runner and single-thread environment. Private scratch, query packets, native
stderr and model cache are removed on success and failure. Only the first report
for a fixed failure code is retained; no arbitrary exception text or prompt enters
it. A response is at most 1 MiB and contains no echoed raw query. The coordinator
still independently verifies live contributor membership and owns once-only
settlement. A lost acknowledgment replays the existing agent outbox, not inference.

## Offline verification

The final Windows run passed **37 checks with no skips**, using Python 3.12.14
and Node 24.19.0: 22 Object adapter/runner checks, 14 existing outbound transport
checks and the existing shared native-runner check. Real short Python helpers ran
hidden to test timeout/log growth and the Object binary's `output.<pid>.tmp`
filename. That temporary output is now included in the shared size guard.

Three Python-produced common/hot/semantic packets passed the actual JavaScript
gateway, queue and SQLite ledger. Nine changes to live-style contributor/Gen4
authority were refused without debits; three synthetic searches settled once and
their exact paid replies recovered with the configured service absent. The
initial cross-language fixture accidentally sorted normalized query keys and was
correctly refused before enqueue/debit. Its failure log remains preserved; the
fixture now preserves the original field order. Private logs, hashes and limits
are in `work/owner-object-search-20261012/receipt.json` on the laptop.

All native results, model bytes, coverage and initial credit were fixtures. No
genuine inference, earned credit, imagery, cloud access, OS vault access, service
activation, migration or Actions run occurred. Earlier queue checks were reused,
not rerun. These checks establish protocol behavior, not authentic ranking parity.

## Remaining activation work

This supplies the previously missing Object engine interface. The current queue
has **one** policy/runtime/snapshot pin set. An Object-only configuration can use
this adapter; serving both lanes from one coordinator still needs an explicitly
sealed composite runtime/snapshot contract or separately configured lane pins.
Do not advertise both lanes with unrelated, incompatible engine identities.

Outbound trusted verification/import, bounded catalog adaptation, startup and
credential provisioning, approved isolated resources/migration, authentic
Windows/Mac runtime qualification and earned-credit searches remain unfinished.
No real binary/model ran in the synthetic checks. Throughput, memory, Free-plan
capacity and real ranking parity must be measured after explicit activation and
budget authority. Existing signing, device and endurance launch gates remain.
