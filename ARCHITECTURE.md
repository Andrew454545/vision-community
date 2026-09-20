# Architecture decision (2026-09-19)

The public product stores **panorama metadata and derived embeddings**, then
outputs **map-making.app JSON**. It does not persist Street View imagery.
Users open the JSON on map-making.app, which loads Street View live.

## What is stored

- Canonical panorama ID, lat/lng, heading/pitch/zoom, capture, country, camera
  generation, and a versioned embedding.
- Sealed, checksummed segments with atomic registry publication.
- Credits, leases, and search authorization in trusted server code.

Pixels exist only in RAM while a volunteer (or the verifier) processes a
location. JPEG/PNG bytes, tile URLs, and API keys are rejected by the importer.

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

Fast gated search still cannot run on Workers Free (10 ms, 128 MB). The
smallest remaining tradeoff is a dedicated search host with the sealed index
on local disk or RAM. R2 remains the durable copy of segments, not the query
engine.

## Verification

Every credited `community-visual-v1` embedding is recomputed from the canonical
pano identity without writing imagery to disk. That is not RF-DETR/OWLv2.
