# Official Generation 4 Object inputs

This is a private maintainer operation. Contributors only choose their work
in the app; they never certify coverage or run this importer.

The importer is implemented and tested with synthetic inputs. **Live coverage
is not established yet**, and Object contribution/search admission remains
closed. No model result or numerical comparison can replace this check.

## Trusted source

Use Andrew's current private Rust `catalog-validator-v2` with policy
`strict-google-official-historical-v7-exact-pano-2026-10-06`. Verify its actual
source/build and execution, then obtain the manifest SHA-256 through a trusted
operator channel. A SHA-256 supplied by a volunteer does not establish trust.
Private VISION PR #14 fixes the previous policy: an older panorama in a newer
Generation 4 panorama's history cannot inherit the newer camera dimensions.
The exact requested panorama's own metadata must pass the official copyright,
country, date and camera checks. A redirected/unavailable panorama is rejected;
its ID and pose are never replaced by a current one.
New receipts use `official-gen4-historical-v2-exact-pano`. Assignment,
publication, snapshots and Object search refuse the retired v1 authority even
with an otherwise valid digest. Old rows remain stored for investigation; do
not relabel them. They need a fresh trusted v7 validation.

Do not use the retired Node validator, generic R2 catalog labels, the calibration
fixture's camera labels, v6 cache/manifests, or relabeled files. Prepare at most
1,000 input rows per shard with `--max-rows 1000 --cache-max-age-days 1`. Prepare
the import within 24 hours of validation. This bounds cache reuse; it is not a
guarantee that Google will continue serving the panorama indefinitely.

## Prepare privately

Use a private folder outside Git for the original input TSV, country authority,
and validator output (`manifest.json`, `normalized.tsv`, `rejected.tsv`). Keep
the independently checked input/country/manifest hashes. With the project's
private Node runtime, run:

```text
node deploy/cloudflare/tools/import-object-coverage.mjs \
  --validator <validator-output-folder> --manifest-sha256 <trusted-manifest-sha256> \
  --input <original-input.tsv> --input-sha256 <original-input-sha256> \
  --countries <country-names.txt> --countries-sha256 <country-file-sha256> \
  --out <new-private-output-folder>
```

The backslashes above mean continuation in a Unix shell; use a single line on
Windows. Preparation makes no network request. It saves an eight-statement
`import-batch.private.json`, a private coverage receipt and a short report.
Source paths/provenance stay out of queue attribution and reports. The batch
still contains private panorama/pose metadata; do not upload it to Git, a public
artifact or an unrelated bucket. Failed inputs and existing outputs are preserved.
A failed preparation saves `failure.private.json` when the private output folder
is safe and writable. A missing final success report is incomplete, even if a
batch file exists. Before application, verify the report's batch/coverage SHA-256
pins; do not apply changed or partial files.

Verify the complete confirmed Community account/database/environment pair,
obtain a current rollback point, and submit **the entire prepared list in one
supported D1 batch**. Each entry has `sql` and `params`. Do not execute statements
individually or replace this with a split SQL import. A late constraint failure
must roll back the whole batch. The temporary guard table disappears on success
or transaction rollback. A stale guard table signals an incorrectly split import;
inspect/restore that operation before retrying, never remove guards to force it.

Import adds pending Object queue metadata and its official coverage receipt
together. Exact repeats are safe, including later leased/published work with the
same receipt. Conflicting ID/date/pose/country, uncertified active work, a changed
receipt, or an old schema aborts the batch. Existing output, accounts, credits,
publications, leases and Scene work remain unchanged. Input rows from other
camera generations are accounted for but do not enter the Object queue.

## Evidence and remaining work

The 19 focused importer checks and all 259 service checks pass on Windows.
The full local application suite passes 640 tests in 487.920 seconds with eight
skips; these skips are not treated as verified platform/filesystem behavior.
The new snapshot regression rejects retired v1 coverage, and all queue, search,
snapshot and restore boundaries require the new exact-panorama authority.
Actual local workerd/D1 verifies late-failure rollback, exact retries, changed
pose refusal, preservation of already leased certified work and refusal of
uncertified active work. All data in those checks is explicitly synthetic;
no real coverage, imagery, model inference or financial change occurred.
The initial sandbox refusals are retained separately from the ordinary passing
checks; no security setting was changed.

The v7 native validator test/build workflow is tracked in private PR #14. Its
corrected source `48cab4e` run `37480716583` was blocked before runner startup:
GitHub reports that an Actions budget prevents further use. It did not compile
or run native tests. The earlier invalid runner-context configuration failure
and its correction are preserved separately. A passing actual native result,
followed by a small trusted live historical shard and independent
readback, is required before using this importer on real queue work. Object
device qualification, trusted native auditing, immutable runtime distribution
and sustained background processing remain separate acceptance requirements.
