# Object reference check

This is a maintainer diagnostic, not a contributor setup step. It compares
RF-DETR, YOLOE and OWLv2 outputs on identical saved images. A successful run
does not approve a computer, grant searches or open Object contributions.

From the repository folder, run the module with the private Python runtime:

```text
<private-python> -B -m community.object_canary --binary <vision-object> --model-dir <object-model-folder> --fixture <fixture.json> --fixture-sha256 <trusted-checksum> --out <new-check-folder>
```

Use a fresh output folder. Failed checks keep their report, partial outputs,
native logs and exit receipts. Retrying cannot overwrite that folder.
An incomplete report is saved atomically before and after commands, so an
abrupt process exit keeps the completed comparisons for review. This is not
physical power-loss or restart acceptance evidence.

The separate `mac-object-reference` workflow collects portable detector values
from the pinned published Mac program, with CPU and CoreML requested on the same
six faces. It uses both `car` and `a car`. Results are encrypted for the local
operator before artifact upload; the private key stays outside Git and CI.
This older executable cannot attest the newer shared CPU pool, actual node
placement, correspondence with Andrew's installed executable or full indexing.
The workflow records those limits explicitly. It is not a qualification provider.

Small reference/transport guards run automatically. A native Mac trial requires
adding the PR label `run-native-object-reference`, or a manually confirmed
**mac-object-reference** workflow run once the workflow exists on the default
branch. Keeping the label on a PR does not repeat native inference on later
commits. Manual runs without confirmation run only the guards. The native trial
has a 45-minute deadline, downloads only twelve pinned Object assets, and fetches
one location's six views; it cannot start an installed contributor or create
accounts or credits.

Nothing is downloaded or uploaded; the checker does not connect to a service or read
an account. Each native command has a 15-minute limit and uses the existing
process owner, CPU execution and one shared inference thread. Private account,
cloud and proxy environment values are excluded from the child process.

## Reference bundle

Obtain the fixture checksum from trusted reference evidence, independently
of the downloaded bundle. Keep the images and native outputs private.
The checker validates pins and provenance fields; it cannot establish that
the person supplying the reference actually used Andrew's trusted runtime.

`fixture.json` version 1 has these fields:

| Field | Required content |
| --- | --- |
| `reference` | `sourceRevision` (40 lowercase hex), `runtimeProfileSha256`, `evidenceSha256`, and `execution` (`cpu` or `coreml`). Retain the independently verified original receipt. |
| `modelSha256` | All 11 Object model and configuration filenames from `community.object_canary.MODELS`, each with a SHA-256. The candidate must use those exact model files. |
| `cases` | Between 1 and 112 unique cases, each with `id`, `images`, `queries`, and `reference`. |

Each case contains six 640-by-640 saved PNG faces in the original order and
one to eight distinct semantic queries. Every image entry and the case's
reference entry has exactly `path`, `bytes`, and `sha256`. Paths are relative
to the fixture folder. Symbolic links, directory redirection, traversal, repeated paths, incorrect pins and
oversized bundles are refused. The PNG header/dimensions are checked before
execution; the native image decoder validates the actual pixels.

The reference file contains `common` and `hybrid`. `common` is the six native
`detect-images` result rows. `hybrid` maps each query to the six corresponding
`detect-hybrid-images` rows. Remove the original rows' machine-local `path`
field only after verifying the original image paths and order. Retain every
other field and value. Candidate paths, queries, dimensions, identities,
scores and boxes are validated before comparison.

## Reading the result

`object-check-report.json` records the input identity, candidate runtime and
model/pipeline hashes, each comparison and elapsed time. Native outputs remain
private; adjacent `*-portable.json` files omit only verified machine paths.
Neither file should be uploaded automatically.

`COMPLETE` means the diagnostic ran and the before/after input and runtime
checksums passed.
`exactReferenceMatch` says whether every checked value matched. The report
separately measures score and box differences and counts structural changes
in detections. Different counts, identities, support counts or order are kept
visible; the checker does not rearrange detections to hide differences.
Numeric errors compare corresponding entries, not an optimal box assignment.
No automatic tolerance is inferred from these measurements.

This check exercises frozen-image detectors on CPU. It does not replay the
production indexing path or prove CoreML parity, official historical Gen4
coverage, trusted service audits or sustained throughput. Its `qualified`,
`serverAuthorization`, `productionPathVerified` and `coverageAdmissionVerified`
fields stay false. There is no submission packet or credit request. The app's
Object qualification gate remains closed until a separate approved production
policy/provider, trusted coverage and hosted audit are implemented and verified.

The first actual Windows replay uses the existing six-view, one-location CPU
pilot as a regression baseline. That baseline is not Andrew's gold standard
and cannot establish broad accuracy. Actual Mac execution of this new checker
and larger identical-input reference comparisons remain separate evidence.

The final local replay completed in 169.813 seconds at one shared CPU thread.
All 1,014 compared scores/box coordinates matched the earlier four-thread
pilot, with no structural differences. All 11 model/configuration pins and
the saved images passed their before/after checks. This elapsed time includes
model loading on a laptop doing other work; it is not a throughput benchmark.
The full local application run passed 638 tests in 490.128 seconds with eight
skips. The later incremental-receipt addition passed 21 focused tests,
including an actual child process exiting abruptly after the Common lane.
Its report remained incomplete and retained that completed comparison.
The native Windows package build passed its 28 setup guards with the new module
included. That local package records a modified source tree and remains unsigned
and unqualified. Exact committed-source CI evidence is recorded separately.

All eleven CI jobs pass for application head `f890e63`, using clean proposed
merge `09b789f84ebcecf2c3ce24bc3e8f51c8dace1218`. Windows and Linux each pass
639 tests (two and 31 platform skips respectively). The private Apple-silicon
Python run passes 66 setup/qualification guards, including all 12 new checker
tests without skips. This tests the checker with synthetic data, not native
Mac model inference. Native Windows/Mac packaging, actual lifecycle controls,
the service's 238 tests and runtime checks, and both calibration guards pass.
The sealed Windows private snapshot independently imports this module under
inherited process-only Restricted. Package receipts remain unsigned and
unqualified. See [application CI](https://github.com/Andrew454545/vision-community/actions/runs/37424547007),
[native packages](https://github.com/Andrew454545/vision-community/actions/runs/37424546193),
[calibration](https://github.com/Andrew454545/vision-community/actions/runs/37424546204)
and [Mac lifecycle](https://github.com/Andrew454545/vision-community/actions/runs/37424546189).
