# What is saved in Community R2

Read-only inspection on 2026-09-30 of the confirmed `vision-community` bucket.
No storage objects, credentials, public access settings or deployments changed.
The excluded bucket was not accessed. Counts describe this observation, not a
transactionally consistent snapshot: contributions continued arriving during it.

## Andrew's indexed location catalog

`catalog/vision-indexed-v1/manifest.json` identifies **20,955,444 rows** in
420 TSV shards. Its declared contract is `vision-community-pose-catalog-v1`,
rights are `metadata-only-no-imagery`, and both `embeddingsCopied` and
`imageryCopied` are false. Its source families are `legacy-four-view`,
`one-view-checkpoint` and `four-view-no-road-sealed`.

This is an export of locations from Andrew's local index. It supplies panorama
identifiers and saved poses for the work queue. It does not contain his original
calculated search vectors or frozen source images. `community/indexed_local.py`
confirms that the exporter reads pose TSVs and does not read embeddings.

The two other catalogs contain 206,722,626 whole-map rows in 414 TSV shards and
4,920,000 tail rows in 99 TSV shards. The whole-map manifest likewise explicitly
declares no copied embeddings or imagery. These are catalog row totals, not
counts of distinct indexed locations; do not assume their populations are disjoint.

The live D1 `pose_catalog` registers all 933 shards separately for Scenes and
Objects, with 232,598,070 metadata rows per lane. This confirms the shared queue's
source. It does not establish qualified inference, current imagery availability,
trusted Generation 4 object coverage or an unlimited supply of new work.

## Existing search-feature artifacts

| Storage family | Observation | Meaning and limits |
| --- | --- | --- |
| `four-view-v4/` | Earlier complete listing: 2,234 `.i8` files, all 49,280 bytes; 110,091,520 bytes total | Consistent with 16 locations per batch in the four-view layout. Binary contents and checksums were not independently verified in this inspection. |
| Live D1 publication records | Later query: 35,808 locations, 2,238 distinct four-view batches; zero NULL contributor IDs | Recorded Community contributions. Counts were taken at different times while uploads continued; this was not a transactional consistency check. |
| `segments/scene-000001/` | Manifest: 24 locations, 96 bytes per record, `community-visual-v1` | Prototype integer-descriptor scene index, not the reference application's 768-dimensional four-view scene model. |
| `segments/object-000002/` | Manifest: 4 locations, 128 bytes per record, `community-visual-v1` | Prototype integer-descriptor object index, not a validated reference object runtime. |

The root `registry.json` lists only the two small prototype segments and declares
`publicCorpus: false` and `persistImagery: false`. It is not an inventory of the
larger four-view batch collection. The newer four-view publication records use
the legacy D1 queue model label `community-visual-v1` and source
`street-metadata`; a queue label alone does not identify the model that actually
produced a binary result.

The inspected live database has neither `scene_qualifications` nor
`scene_candidates`, and `leases` lacks `scene_qualification_id`. A contributor
ID establishes attribution to a Community account, not the person's identity or
an independently audited reference runtime. These submissions may include
Andrew's processing; the inspected records do not attest that provenance. Do
not retroactively approve them or promote them to a controlled calibration
reference merely because their layout matches.

## What still makes the comparison controlled

The repository already contains a 1,024-location historical reference packet.
That packet was available for the earlier PC trials; it explicitly marks source
pixels, the active reference configuration and three-run repeatability as
unattested. Existing indexed data and a controlled reference are different
pieces of evidence.

The inspected R2 families do not supply the missing frozen-input/repeat-run
packet. Production qualification still needs an export from the actual
reference runtime containing:

1. The same ordered view images or inference tensors, their hashes and the
   preprocessing definition, with redistribution/use rights established.
2. Three repeat outputs from the reference runtime, with the exact models,
   binary/runtime, provider, precision and concurrency settings recorded.
3. The 1,024-location and 112-location canary mapping, plus fixed query results
   for evaluating search rankings and deriving numerical acceptance bounds.

Use that packet to measure 1/2/4-thread PC configurations and define tolerances
from observed repeatability and ranking behavior. Preserve these R2 artifacts
as historical evidence; only independently approved contributed snapshots
belong in the new production search service.

## Verification and access limitations

Catalog manifests were parsed through the connected Cloudflare API; complete
prefix listings confirmed the shard counts. D1 queries were SELECT-only and
reported zero rows written. The root registry and small segment manifests were
read from the signed-in dashboard's JSON previews. Catalog shard hashes are
declared hashes, not a completed independent download-and-hash audit. Object
ETags were not treated as SHA-256 hashes.

The connector fails on the small application/json object reads despite HTTP
200. Dashboard download event waits also timed out. A separate private Wrangler
read failed for unavailable CLI authentication and produced an empty download
placeholder. The local failure log, parsed inventory summaries and D1 aggregate
evidence are preserved outside Git in the operator's reference-discovery output
folder. These access failures do not negate the successfully read manifests.
