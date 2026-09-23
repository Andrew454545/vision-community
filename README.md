# VISION Community

Anonymous, contribution-gated visual search. Volunteers process locations.
The service stores **panorama metadata and embeddings only**, then outputs
**map-making.app JSON**. Street View imagery is not saved. Open the downloaded
JSON on map-making.app to view the locations.

Each verified scene location earns 1 unit. Each verified object location earns
10 units. **One search costs 100,000 units** (100,000 scene locations, or
10,000 object locations). New accounts start at zero. There is no trial, owner,
or API bypass.

## Start on a new computer

Works on an Apple silicon Mac or a Windows PC. Python 3.9 or newer is required. Intel Macs and Linux are not in this download.

1. On this GitHub page, choose **Code**, then **Download ZIP**, and unzip it.
2. Open Terminal, move into the unzipped folder, and run:

```sh
python3 -m community.bootstrap
```

On Windows, open PowerShell and use `python` instead of `python3` if `python3` is not recognized. That installs the Python requirement and downloads the scene program, the object program, and their model folders for this computer. It does not copy a live VISION queue or a CoreML cache.

3. Open the site, get an account, and paste the scene or object command in that same folder.

https://vision-community.visioncommunity.workers.dev

## How to use the site

Scenes and objects are indexed in Terminal with the same programs as the VISION app. The browser cannot run those models.

1. Click **Get a free account**. Write down the code it shows you.
2. Click **Copy scene command** (or **Copy object command**). Open Terminal, paste, and press Return. Leave that window open. Each finished scene fills 1 toward a search. Each finished object fills 10.
3. When the bar is full, copy the search command and run it in Terminal. Connect map-making.app under **Connect a map app** to add the JSON to a map, or copy/download it for the local Map Making App.

A search needs **100,000 places** (or 10,000 objects). There is no shortcut. An example search is already loaded, so you do not need a JSON file unless you have one from VISION.

If you were given the project folder and want it to go faster, see [CONTRIBUTING.md](CONTRIBUTING.md). Most people can ignore that.

The queue is the local 20.96M already-indexed VISION poses (metadata only) plus
the ALL LOCATIONS tail. Scene indexing runs `mma-vision index-four-views` on
the volunteer computer, using the fp32 SigLIP model on one CPU thread. That
keeps the stored scene bytes the same from run to run and from computer to
computer. Object indexing
runs `vision-object index-segment` with the hybrid RF-DETR, YOLOE, and OWLv2
models. `python3 -m community.bootstrap` downloads them into the usual VISION
folders. Set `VISION_FOUR_VIEW_BINARY`, `VISION_MODEL_DIR`,
`VISION_OBJECT_BINARY`, and `VISION_OBJECT_MODEL_DIR` only when you already
have those files somewhere else.

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

Process exclusive place batches with the same four-view program as VISION.
Street View is fetched by that program, not proxied through the site. The
command keeps going until the queue is empty or you press Control-C:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m community.vision_index --url https://vision-community.visioncommunity.workers.dev --pace slow --recovery-code YOUR_CODE
PYTHONDONTWRITEBYTECODE=1 python3 -m community.vision_index --url https://vision-community.visioncommunity.workers.dev --search --prompt "red barn in snow" --recovery-code YOUR_CODE
```

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin check --db community/.data/demo.sqlite
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin backup --db community/.data/demo.sqlite --to /tmp/vision-community-backup.sqlite
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin import-shard --db community/.data/demo.sqlite --tsv /path/to/shard.tsv
```

`import-shard` accepts Community catalog TSV **or** VISION’s headerless 11-column
indexer TSV (pose metadata only). Do not import embeddings or imagery.

Leases send panorama identity and pose, not image bytes. Scene indexing runs
`mma-vision index-four-views` on the volunteer computer. Object indexing runs
`vision-object index-segment` there too. Street View is fetched by those
programs and is not stored. Invented test IDs (`Prototype…`, `CommunityPano…`)
are still recomputed with the old `community-visual-v1` descriptor. That
descriptor is not the scene or object credit proof.

## Storage at 200 million locations

Fast search at 200 million locations runs **on the user's computer**. The site
is only the queue and credit desk. Workers Free cannot scan 200M vectors, so
there is no paid search host to buy. Scene search is `python3 -m
community.vision_index --search`, the same four-view search as VISION. It reads
indexes on that computer and, after the search is paid for, downloads finished
scene indexes from the queue. Object search is `python3 -m community.object_index
--search`, the same object search as VISION. It reads indexes on that computer
and downloads finished object indexes from the queue after the search is paid
for. On a computer where VISION is already indexing objects, Community uses
that same `vision-object` program. Finished object indexes are then added to
the local VISION app's object catalog. Scene indexes stay in the Community
search: the running remainder catalog owns scene discovery.

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

   Scene credit requires the four-view record. Object credit requires the
   version-4 object index. `community-visual-v1` is only the old test descriptor.

2. **Cut the live remainder TSV** at `reservedFromLocationIndex` only after the
   local indexer is stopped or has passed that cursor. Do not shrink the file
   while `mma-vision` is running.

3. **Later, when the corpus is real:** custom domain if you want one. Never
   touch `geonections-images`. Do not upload the 20.96M VISION embeddings.
   Search already costs 100,000 units. Large searches run
   on the user's computer (`python3 -m community.vision_index --search` and
   `python3 -m community.object_index --search`). Do not buy a
   search VM.

The hosted site is the shared queue and credit desk. Search at 200 million
locations runs on volunteers' computers after they unlock it. Search already
costs 100,000 units with no bypass.
