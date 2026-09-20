# VISION Community

Anonymous, contribution-gated visual search. Volunteers process locations.
The service stores **panorama metadata and embeddings only**, then outputs
**map-making.app JSON**. Street View imagery is not saved. Open the downloaded
JSON on map-making.app to view the locations.

Each verified scene location earns 1 unit. Each verified object location earns
10 units. Production search costs **100,000 units**. The hosted prototype uses
**4 units** (one verified scene batch) so the VISION loop can be tried.

## Hosted prototype

https://vision-community.drewjohnburke.workers.dev

This is a working VISION-style workspace: anonymous account, exclusive
processing, ranked visual search, map-making.app JSON in and out. The corpus is
a small public-place metadata set, not the local 20.96M VISION index.

1. Create an anonymous account and save the recovery code.
2. Process a scene batch (slow / medium / max control real device workers).
3. Load sample JSON (or upload a VISION export).
4. Search. Rank 1 is the matching reference when that pano is in the index.
5. Download JSON and open it on [map-making.app](https://map-making.app).

Local equivalent:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m community.server --prototype
```

## What works locally

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s community/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m community.measure
PYTHONDONTWRITEBYTECODE=1 python3 -m community.server --metadata
```

`--metadata` loads a panorama-ID catalog (pose only). `--visual` is an invented
descriptor self-test. `--demo` is the old fixture/label prototype and must not
be shipped as the product.

Open `http://127.0.0.1:8765`. Create an anonymous account, process a batch, then
search by uploading a map-making.app JSON (the same `customCoordinates` format
the local VISION app exports). Download the result JSON and open it on
map-making.app.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin check --db community/.data/demo.sqlite
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin backup --db community/.data/demo.sqlite --to /tmp/vision-community-backup.sqlite
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin import-shard --db community/.data/demo.sqlite --tsv /path/to/shard.tsv
```

Leases send panorama identity and pose, not image bytes. The worker recomputes
pixels from that identity in RAM. Published segments seal `embeddings.bin`,
`ids.bin`, and `poses.bin` so search can emit map-making.app JSON without a
SQLite round-trip per hit.

## Storage at 200 million locations

A 200M corpus of community embeddings plus sealed pose metadata is about 51 GiB
(~$0.61/month on R2 after the free 10 GB). VISION-scale 3,080-byte embeddings
at 200M are about 590 GiB (~$9/month storage). Neither stores imagery. Fast
search still needs a dedicated host; Workers Free cannot scan 200M vectors.
See [ARCHITECTURE.md](ARCHITECTURE.md) and [MEASUREMENTS.md](MEASUREMENTS.md).

## Invariants

- Canonical pano ID, capture, lane, and model have one queue row.
- Expired leases are fenced; stale, forged, duplicate, and replayed work does
  not credit.
- Imagery bytes and tile URLs are rejected. Only metadata and embeddings persist.
- Search debit and JSON emission happen in trusted server code.

## Remaining owner-only steps

1. A privacy-protected custom domain. The current Worker hostname identifies
   the Cloudflare login.
2. A dedicated search host before a 200M corpus. This prototype fits Workers +
   D1; production search will not.
3. The real ~200M metadata catalog path. Do not copy live VISION embeddings.
4. VISION pixel-model parity (RF-DETR / YOLOE / OWLv2) if that is required.
   Prototype search uses `community-visual-v1`.
5. Restore the 100,000-unit production search cost when the corpus is real.
