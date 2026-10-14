# Scene search metadata

Tag **before assignment and indexing**. Keep country, capture date, camera
classification, saved heading/pitch/zoom and the classification policy with the
catalog. Reuse them through publication and the sealed search snapshot. Searching
must not fetch panorama metadata again for every query.

Country include/exclude, camera-generation selection and all seven saved-pan
choices already connect the browser, coordinator and native Scene search.
They follow Andrew's [VISION query semantics](https://github.com/Andrew454545/VISION/blob/9811448e3e05259e08f5106ab5a7740dce0c6b4a/VisionEngine.swift).
Saved pan is the input map's heading; right/opposite/left use offsets 90/180/270°.
Four view embeddings are indexed once. A saved heading is not verified car-front.

## Generation classification

The [offline preparation tool](../community/scene_catalog_metadata.py) follows
Andrew's [catalog validator](https://github.com/Andrew454545/VISION/blob/9811448e3e05259e08f5106ab5a7740dce0c6b4a/catalog-validator-v2/src/lib.rs#L1324)
at revision `9811448e3e05259e08f5106ab5a7740dce0c6b4a`, including its country-name
authority, image-height/source rules, Badcam exceptions and country/date Gen 2
cutoff. This avoids introducing a different Community heuristic.

**Gen 2 versus Gen 3 is an estimate**, using country and capture month, not a
camera model directly supplied by the provider. Missing dates, unsupported
dimensions and ambiguous indoor-level metadata remain `unknown`; they are not
silently labelled Gen 3. A generation-only search excludes unknown classifications;
All generations keeps them. The web filter now states the estimation clearly.
These classifications never establish official coverage or Object eligibility.
The existing strict Object validation path remains separate and closed.

## Implemented locally

The operator-only tool streams a pinned metadata TSV into existing VISION
11-column `locations.tsv`, a raw-field/classification `metadata.jsonl` sidecar and
a last-written checksummed manifest. It refuses conflicting country/generation
labels, invalid poses, unexpected imagery/key headers and overwrites. Country,
generation and saved pan reach the existing catalog/native-input path unchanged.
It makes no provider calls, stores no imagery, runs no inference and grants no
credit. It is repository tooling, not another contributor setup step.

Input headers: `pano_id`, `lat`, `lng`, `country_code`, `capture_year`,
`capture_month`, `image_height`; optional `country`, `heading`, `pitch`, `zoom`,
`camera_source`, `has_level_id`, `road_name_state`, `source_row`, `map_id`,
`camera_generation`. Fields are already obtained by the upstream metadata
validator; this tool does not read an MMA account/database or invent provenance.
Missing road-name metadata stays unknown. Preserve upstream source/validation
receipts separately; operator-supplied input alone is not provider verification.

For an authorized operator's local metadata file:

```text
python -m community.scene_catalog_metadata --input metadata.tsv --input-sha256 <SHA-256> --output prepared-catalog
```

The resulting TSV is accepted by the existing catalog importer. Keep its sidecar
and manifest alongside the immutable shard, including during recovery. The
11-column TSV itself does not carry capture dates or classification provenance;
do not discard the sidecar or call an old unversioned shard freshly verified.
This preparation has not been applied to the live catalog or any private MMA data.

## Next release steps

1. Reuse already-tagged assigned catalog rows. Require the matching classification
   sidecar/policy for new raw-metadata batches before importing them. Do not repeat
   inference merely to retag metadata; corrections need a new controlled metadata
   revision and search snapshot, preserving earlier admission/credit evidence.
2. Address the finite trial's observed coordinator read limit before more hosted
   work; add route-level usage evidence and remove unnecessary table scans using
   local copies/fixtures. Its two accepted uploads are retained; replay is unfinished.
3. Complete automatic contributed-Scene snapshot refresh and online earned-credit
   search/recovery under a separately bounded activation. Keep contributor-only
   membership and account/credit authority through rollback.
4. Begin with the supported bounded Scene corpus. For larger corpora, seal batches
   with country/generation summaries and stable global location IDs, then select
   relevant batches **before hydration**. Verify identical result semantics before
   enabling this optimization. Current native mounting hydrates the whole bounded
   snapshot: tagging alone does not yet reduce R2 downloads or establish million-
   location capacity. Do not create one R2 object per location.

Continue trusted Windows/Mac installs, recovery/cost evidence and accepted-work
endurance in [the Scene release checklist](SCENES_FIRST_RELEASE.md). Objects remain
deferred. No Actions, new paid service or continuing indexing was started here.
