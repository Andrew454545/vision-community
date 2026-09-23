# Architecture decision (2026-09-19)

The public site is a **shared indexing queue**. Place indexing runs
`mma-vision index-four-views` with the same 11-column TSV, the same SigLIP
model directory, and the same version-4 record (4 quarter-turn views, 3080
bytes). Community uses the fp32 image model on one CPU thread, because the
VISION app's CoreML run can change a few stored values between passes. The browser cannot run that model, so the
scene command is Terminal-only. Object indexing runs the same
`vision-object index-segment` program as the VISION app: a 12-column TSV, the
hybrid RF-DETR / YOLOE / OWLv2 runtime, and a version-4 six-face index. The
browser cannot run that model, so the object command is Terminal-only too.
`community-visual-v1` is no longer the object credit proof. A place submission stores the
3080-byte record only after its length and checksum match; those bytes are not
mixed into the visual-v1 search index. Community `import-shard` still accepts
the VISION indexer TSV so the established corpus can enter the queue as pose
metadata only.

## What is stored

- Canonical panorama ID, lat/lng, heading/pitch/zoom, capture, country, camera
  generation, and a versioned embedding.
- Sealed, checksummed segments with atomic registry publication.
- Credits, leases, and search authorization in trusted server code.

Pixels exist only in RAM while a volunteer processes a location. JPEG/PNG
bytes, tile URLs, and API keys are rejected by the importer. The place indexer is `python3 -m community.vision_index`. It fetches Street
View inside `mma-vision` and writes a version-4 index outside the live VISION
remainder job. The Worker stores that record in R2 and checks its shape and
checksum. It does not recompute SigLIP.

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
Street View scene and object batches are indexed on volunteer machines by the
VISION programs. The Worker checks the record shape and checksum. It does not
recompute SigLIP or RF-DETR.
