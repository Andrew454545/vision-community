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

Process exclusive batches from the terminal (same extractor as the browser):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m community.contribute --url http://127.0.0.1:8765 --lane scene --pace medium
```

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin check --db community/.data/demo.sqlite
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin backup --db community/.data/demo.sqlite --to /tmp/vision-community-backup.sqlite
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin import-shard --db community/.data/demo.sqlite --tsv /path/to/shard.tsv
```

`import-shard` accepts Community catalog TSV **or** VISION’s headerless 11-column
indexer TSV (pose metadata only). Do not import embeddings or imagery.

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

Do these in order. Everything else in this repo is already wired.

1. **Hide the personal hostname.** In Cloudflare → Workers → Account settings, change
   the `workers.dev` subdomain from `drewjohnburke` to `visioncommunity` (that
   name is free). This is account-wide. Then buy a privacy-protected domain if
   you want a real URL, add it in Cloudflare, and attach it to the
   `vision-community` Worker.

2. **Feed the established corpus as metadata, not embeddings.** Export pose-only
   rows from local VISION (the existing 11-column indexer TSV). Import them into
   Community — the importer now accepts that format:

   ```sh
   PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin import-shard \
     --db community/.data/demo.sqlite --tsv /path/to/vision-indexer.tsv --lane scene
   ```

   Do **not** copy SigLIP/RF-DETR files or imagery. For the live Worker, seed D1
   the same way only after you are ready for that catalog to be public.

3. **Let volunteers process, then index in VISION.app.** They can use the site
   or `python3 -m community.contribute --url …`. After work is published:

   ```sh
   PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin export-vision \
     --db community/.data/demo.sqlite --to handoff/vision-indexer
   ```

   Point the existing local four-view / object indexer at
   `scene-published.tsv` / `object-published.tsv`. Prototype IDs such as
   `PrototypeBerkeleyCA000001` will not fetch as real Street View.

4. **Later, when the corpus is real:** dedicated search host (Workers Free cannot
   scan ~200M vectors); upload sealed **community-visual-v1** segments to R2
   bucket `vision-community` only; set `SEARCH_COST` back to 100,000; decide
   what happens when the queue is empty; keep GitHub private. Never touch
   `geonections-images`.

The hosted prototype is the product loop. It is not the 200M public service.
