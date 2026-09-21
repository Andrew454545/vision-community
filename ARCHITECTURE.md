# Architecture decision (2026-09-19)

The public site is a **shared indexing queue**. Volunteers process exclusive
locations (browser or `python3 -m community.contribute`). Published poses export
as the 11-column TSV the local VISION indexer already consumes. The owner then
indexes those rows in VISION.app and searches them there. Browser
`community-visual-v1` embeddings are a credit proof for the queue; they are not
merged into the SigLIP / RF-DETR index. Community `import-shard` also accepts
that same VISION indexer TSV so the established corpus can enter the queue as
pose metadata only.

## What is stored

- Canonical panorama ID, lat/lng, heading/pitch/zoom, capture, country, camera
  generation, and a versioned embedding.
- Sealed, checksummed segments with atomic registry publication.
- Credits, leases, and search authorization in trusted server code.

Pixels exist only in RAM while a volunteer processes a location. JPEG/PNG
bytes, tile URLs, and API keys are rejected by the importer. The recommended
indexer is `python3 -m community.contribute`, which fetches Street View on the
volunteer machine. The Worker audits one Street View location per submitted
batch.

## Search output

A credited search returns a VISION-compatible map:

```json
{
  "name": "Reference",
  "customCoordinates": [
    {
      "lat": 41.9,
      "lng": 12.5,
      "heading": 90,
      "pitch": 0,
      "zoom": 0,
      "panoId": "…",
      "extra": { "visionRank": 1, "visionScore": 1.0, "tags": ["Italy"] }
    }
  ]
}
```

Query input is the same document (up to 100 reference panoramas), matching the
local VISION reference JSON.

## Cost at 200 million locations

Imagery is not the storage problem. Community-visual-v1 embeddings (96 bytes)
plus ~176 bytes of sealed pose metadata at 200M is about **51 GiB** (~$0.61/month R2
after the 10 GB free tier). VISION-scale 3,080-byte embeddings at 200M are
about **590 GiB** (~$9/month storage). Both sit under a $20 storage-only
budget.

Fast gated search still cannot run on Workers Free (10 ms, 128 MB). Search at
that scale runs on the user's computer after a 100,000-unit debit. R2 remains
the durable copy of segments, not a query engine you have to rent.

## Verification

Invented test panos are always recomputed from the identity-seed extractor.
Street View batches are processed on volunteer machines; the Worker re-fetches
one location per lease as an audit. That is not RF-DETR/OWLv2.
