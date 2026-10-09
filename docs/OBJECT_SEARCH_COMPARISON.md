# Offline Object search comparison

Maintainer diagnostic only. This does not open Object contributions or approve
a computer. It complements the [stored-feature comparison](OBJECT_INDEX_COMPARISON.md).
The private native replay helper can now run blur filtering and actual native
Common, Hot and Semantic searches on sealed saved images. Keep complete native
replies, source locations and query text in the existing private handoff.

## Compare saved replies

Use exact independently recorded SHA-256 values for both complete native
replies, the path-free query packet and the same 12-column source TSV:

```sh
python -m calibration.compare_object_search \
  --reference PRIVATE_REFERENCE.json --reference-sha256 REFERENCE_SHA256 \
  --candidate PRIVATE_CANDIDATE.json --candidate-sha256 CANDIDATE_SHA256 \
  --query-packet PRIVATE_QUERIES.json --query-packet-sha256 QUERY_SHA256 \
  --source PRIVATE_SOURCE.tsv --source-sha256 SOURCE_SHA256 \
  --global-start 0 --out NEW_PRIVATE_REPORT_FOLDER
```

The query packet uses contract `vision-object-query-replay-v1`, a
`resultPruneMeters` value and 1–32 native query objects with all explicit
route/filter fields. It accepts at most 100 results per query and 1,000 source
locations. Paths, runtime overrides, unknown fields, duplicate names/keys,
invalid class/routes and nonfinite numbers are refused. Query/source/reply files
are size bounded and pinned before and after comparison. Existing output is
never overwritten; a failed comparison leaves a report without input paths.

Every reply must preserve the query order, source identities, score order,
unique panoramas, pruning distance and camera/country/road/global filters.
Reports measure missing/extra hits, result order, leading sets, rank inversions
and their reference-score gaps, scores, selected faces, support counts and aim.
Heading differences wrap at 360 degrees. Query text, panorama IDs and coordinates
are omitted from aggregate reports. Keep native replies private.

Empty replies are explicitly counted and have no score/aim comparison. A
single-location result cannot establish ranking on a larger collection.
Matching saved replies do not prove the executable ran, that the images are
official Gen4, or that a supplied reference is Andrew's installed application.
No production tolerance is assigned and all qualification/authorization flags
remain false. Trusted inference, broader Mac/reference comparisons, signed
releases and accepted contribution/search recovery remain release gates.

## Local Windows evidence — 8 October 2026

Three fresh full quality-enabled indexes completed on one distinct saved
six-face location, once each at 1/2/4 threads. Every index passed native full
verification before and after its ten-query search. The saved query results
match across those settings. Common detections were returned; both Hot queries
and the initial Semantic queries were empty and are counted as such.

A separate ten-query search on those same retained indexes used a zero Semantic
confidence floor to exercise proposal selection and aiming. Its Common and
Semantic hits agree exactly across 1/2/4 threads; filters for excluded country,
later global IDs and confidence one return no hits. This is a diagnostic floor,
not a changed production threshold. The first queries and their empty replies
remain unchanged. Every native index is fully verified again before and after
this follow-up. No new indexing or imagery retrieval occurs in the follow-up.

The outer stored-feature check initially refused the blur-only diagnostic's
missing protected authority. That failure is preserved. The repaired offline
reader validates structural quality only for a valid marked frozen diagnostic,
without inventing an authority hash. Normal publication still requires the
protected authority and rejects the diagnostic marker. Independent readback of
all retained indexes now completes; stored features match across 1/2/4 threads
and the missing authority is reported explicitly.

All six views were kept: this sample does not exercise rejected-face selection.
One location and one run per setting cannot establish broad accuracy, Hot hit
behavior, rank stability on a collection, sustained throughput or Mac parity.
Private native outputs and failure evidence remain local. GitHub Actions,
Cloudflare resources, production admission and the installed worker are unchanged.

All 173 affected public Python checks pass locally without skips, including
search/index/embedding comparison, feature validation, snapshots and Object
transport. All 52 affected private helper checks pass without skips. Earlier
test-launch failures from the sandbox's temporary folder and one incorrect
module name are retained; the final runs use a dedicated workspace test folder.
These checks use the existing local runtime and do not establish Mac execution.
