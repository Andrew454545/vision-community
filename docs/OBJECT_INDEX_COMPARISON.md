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
proposal rearrangement, decoded embedding distance or native search comparison.
Zero error with no shared detections does not mean a match; inspect record counts.

`COMPLETE` means the comparison ran. `exactFeatureMatch` describes stored feature
bytes, excluding manifest labels. Neither establishes reference provenance,
identical input pixels, model execution or an acceptable production tolerance.
All qualification and authorization flags remain false. Keep input provenance
receipts separately; the checker cannot turn a supplied checksum into trust.

Use a new output folder outside either index folder. Errors preserve a small
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
