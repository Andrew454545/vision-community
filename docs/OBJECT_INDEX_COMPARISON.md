# Compare complete Object indexes

This offline maintainer diagnostic compares complete native v4 feature files.
It does not approve contributions or run models, downloads, accounts or searches.
Use Andrew's independently verified reference and a candidate made from the same
saved imagery. Matching location identifiers alone cannot prove identical pixels.

```text
<private-python> -B -m calibration.compare_object_indexes --reference-manifest <reference/manifest.json> --reference-sha256 <trusted-reference-checksum> --candidate-manifest <candidate/manifest.json> --candidate-sha256 <candidate-checksum> --source <identical-locations.tsv> --out <new-report-folder>
```

Both indexes must bind the exact same TSV bytes, country order, global IDs and
quality policy. The reader validates bounded files, checksums and native record
contents before comparing, then verifies the inputs again. It never follows
manifest source paths. Source allocation labels and private paths are ignored
in memory; original inputs remain unchanged. Limits are 1,000 locations,
87 feature files and 32 MB of features per index.

The report distinguishes missing/added detections and discrete metadata changes
from numeric score, confidence, heading, pitch, zoom and area differences.
Heading errors use circular degrees. Semantic proposals compare in stored
ordinal order: code bytes, faces, boxes, logit shifts and scales. There is no
proposal rearrangement. Native replies can be measured separately with the
[offline search comparator](OBJECT_SEARCH_COMPARISON.md).
Zero error with no shared detections does not mean a match; inspect record counts.

Add `--codebook <models/owlv2-pq128-codebook.bin>` to measure decoded semantic
vector differences. The codebook must match the canonical v4 model checksum and
both manifests; it is checked again after comparison. No model execution is needed.
The report adds minimum cosine similarity, maximum absolute L2 and maximum
relative L2 (divided by the reference vector norm). These describe reconstructed
512-dimensional PQ vectors, not original uncompressed model tensors. Logit
calibration differences remain separate.

Zero-view/rejected locations are excluded from vector metrics, with counts kept
visible. Zero-norm vectors have explicit undefined-metric counters and JSON
`null` values where necessary. Inspect those counters and the number of compared
pairs before interpreting extrema; an absent cosine is not a passing cosine.
Different codes can decode to the same centroid values. Neither code counts nor
vector closeness alone establish native query ranking or contribution approval.
No centroids, vectors, private paths or images enter the report.

`COMPLETE` means the comparison ran. `exactFeatureMatch` describes stored feature
bytes, excluding manifest labels. Neither establishes reference provenance,
identical input pixels, model execution or an acceptable production tolerance.
All qualification and authorization flags remain false. Keep input provenance
receipts separately; the checker cannot turn a supplied checksum into trust.

Use a new output folder outside the index and codebook folders. Errors preserve a small
failure report without paths or native data. An interrupted run remains
`INCOMPLETE`. Reports and native inputs stay private; nothing is uploaded.

GitHub Actions spending is on hold. Run the comparison and its synthetic guards
locally; fresh Mac execution remains a separate release requirement.

Local Windows validation on 8 October 2026: all 22 comparator checks pass without
skips, including altered pins/content, source changes, different quality
authorities, semantic/quality drift and preserved failure reports. The related
112-check comparison/content/snapshot run also passes without skips (the counts
overlap). A preserved one-location native index passes file readback and
self-comparison. This is compatibility evidence, not an Andrew/candidate
accuracy comparison or new native inference.

The codebook extension passes 20 analytical/integration checks locally, alongside
the 22 existing comparator checks. Fixtures cover centroid layout, known cosine/
L2 values, opposite/zero vectors, aliased codes, the reference denominator,
changed codebooks and excluded placeholders. No tests are skipped. Readback of
16 preserved native proposals with the canonical codebook agrees with an
independent byte-offset calculation. A finite repeated-fixture check exercises
16,000 proposals at the 1,000-location bound; it has only one distinct input
location and is not a model throughput or accuracy trial.
