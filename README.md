# VISION Community

Anonymous, contribution-gated visual search. Volunteers process locations.
The service stores **panorama metadata and embeddings only**, then outputs
**map-making.app JSON**. Street View imagery is not saved. Open the downloaded
JSON on map-making.app to view the locations.

Each verified scene location earns 1 unit. Each verified object location earns
10 units. **One search costs 100,000 units** (100,000 scene locations, or
10,000 object locations). New accounts start at zero. There is no trial, owner,
or API bypass.

## How to use the site

https://vision-community.visioncommunity.workers.dev

You only need a web browser.

1. Click **Get a free account**. Write down the code it shows you.
2. Click **Start** and leave the tab open. Each place you finish fills the bar.
3. When the bar is full, click **Search**. Connect map-making.app under **Connect a map app** to add the JSON to a map, or copy/download it for the local Map Making App.

A search needs **100,000 places** (or 10,000 objects). There is no shortcut. An example search is already loaded, so you do not need a JSON file unless you have one from VISION.

If you were given the project folder and want it to go faster, see [CONTRIBUTING.md](CONTRIBUTING.md). Most people can ignore that.

The queue is the local 20.96M already-indexed VISION poses (metadata only) plus
the ALL LOCATIONS tail. SigLIP embeddings stay on this computer.

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
the local VISION app exports). Scene search can use the same view directions as
VISION.app: best of four, saved pan, opposite, left/right, saved axis, and
cross-axis. Optionally exclude a previous map within 25 m. Download the result
JSON and open it on map-making.app.

Process exclusive batches from this computer (Street View is fetched here, not
proxied through the site):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m community.contribute --url https://vision-community.visioncommunity.workers.dev --lane scene --pace medium --recovery-code YOUR_CODE
PYTHONDONTWRITEBYTECODE=1 python3 -m community.local_search --url https://vision-community.visioncommunity.workers.dev --query community/web/sample-query.json --recovery-code YOUR_CODE
```

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin check --db community/.data/demo.sqlite
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin backup --db community/.data/demo.sqlite --to /tmp/vision-community-backup.sqlite
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin import-shard --db community/.data/demo.sqlite --tsv /path/to/shard.tsv
```

`import-shard` accepts Community catalog TSV **or** VISION’s headerless 11-column
indexer TSV (pose metadata only). Do not import embeddings or imagery.

Leases send panorama identity and pose, not image bytes. The CLI looks at
Street View the same way VISION.app does: four compass views for scenes
(heading + 0/90/180/270 at the saved pitch and zoom FOV) and a six-face cube
for objects. Thumbnails are fetched on the volunteer machine, downsampled to
16×16, and discarded. The Worker re-fetches **one** Street View location per
batch as an audit. Invented test IDs (`Prototype…`, `CommunityPano…`) are
always recomputed. Published segments seal `embeddings.bin`, `ids.bin`, and
`poses.bin` so search can emit map-making.app JSON without a SQLite round-trip
per hit.

## Storage at 200 million locations

Fast search at 200 million locations runs **on the user's computer**. The site
is only the queue and credit desk. Workers Free cannot scan 200M vectors, so
there is no paid search host to buy. After 100,000 units, `python3 -m
community.local_search` downloads the shared index and ranks it locally. While
the published index is still small, the website can search in the tab.

## Invariants

- Canonical pano ID, capture, lane, and model have one queue row.
- Expired leases are fenced; stale, forged, duplicate, and replayed work does
  not credit.
- Imagery bytes and tile URLs are rejected. Only metadata and embeddings persist.
- Search debit and JSON emission happen in trusted server code.

## Remaining owner-only steps

Volunteer processing, the ALL LOCATIONS tail queue, exclusive leases, and
VISION-matching Street View views are already running on the hosted prototype.
What still needs a person:

1. **Index published poses in VISION.app.** After volunteers process, export
   the 11-column TSV and point the local four-view / object indexer at it
   (isolated sidecar directory, not the live remainder run):

   ```sh
   PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin export-vision \
     --from-d1-remote --to community/.data/vision-handoff-live
   ```

   Community browser embeddings stay `community-visual-v1`. They are a credit
   proof, not a drop-in for SigLIP / RF-DETR.

2. **Cut the live remainder TSV** at `reservedFromLocationIndex` only after the
   local indexer is stopped or has passed that cursor. Do not shrink the file
   while `mma-vision` is running.

3. **Later, when the corpus is real:** custom domain if you want one; keep
   GitHub private. Never touch `geonections-images`. Do not upload the 20.96M
   VISION embeddings. Search already costs 100,000 units. Large searches run
   on the user's computer (`python3 -m community.local_search`). Do not buy a
   search VM.

The hosted site is the shared queue and credit desk. Search at 200 million
locations runs on volunteers' computers after they unlock it. Search already
costs 100,000 units with no bypass.
