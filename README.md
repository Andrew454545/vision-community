# VISION Community

**Preview: public contribution approval and the validated online search engine
are not live yet.** The PC starter checks the service before creating an
account or accepting work. See the [release checklist](docs/PRODUCTION_ACCEPTANCE.md)
for what is verified and
what still needs to be completed.

Anonymous, contribution-gated visual search. Volunteers process locations.
The service stores **panorama metadata and embeddings only**, then outputs
**map-making.app JSON**. Street View imagery is not saved. Open the downloaded
JSON on map-making.app to view the locations.

Each verified scene location earns 1 unit. Each verified object location earns
10 units. **One search costs 100,000 units** (100,000 scene locations, or
10,000 object locations). New accounts start at zero. There is no trial, owner,
or API bypass.

## Start on a Windows PC

1. On this GitHub page, choose **Code**, then **Download ZIP**.
2. Open the downloaded ZIP and choose **Extract all**.
3. Open the extracted folder and double-click **Start VISION.cmd**.
4. Follow the window: **Prepare this PC**, save your private account code,
   then run the **PC check**.
5. When your PC is approved, choose **Start indexing**. Choose **Pause after
   this batch** when you want to stop.

Most contributors do not need Python or a terminal. The starter keeps Python and
processing files in a private folder under your Windows user profile. It does
not install software globally, require administrator access, change security
settings, or create an account for you.

The guided window has four steps: prepare the PC, connect or create your
account, run the short 112-location PC check, and start indexing. The short
check is required for each PC before it receives regular work. Results wait for
a trusted service audit before joining the shared search pool.

Andrew's larger 1,024-location runs are a maintainer calibration study. They
qualify the processing profile and are not repeated by every user. The project
does not claim byte-for-byte equality across machines; trusted review compares
decoded numerical results and the exact runtime identity.

To stop, choose **Pause after this batch**. Keep the PC awake and connected.
If a batch fails, its local report and completed work stay in the private VISION
folder for review.

You can keep processing after earning a search. Unused credits stay in your
account; keep your private recovery code to access them on another device.
The shared search index contains published user contributions, not a supplied
copy of the maintainer's private index.

Unattended Windows processing is available for maintainer testing through the
[background setup guide](docs/BACKGROUND_PROCESSING.md). It resumes after you
sign into Windows and waits when no work is available. The guide explains how
to choose daytime and nighttime activity, including overnight-only processing.
A sleeping or powered-off computer cannot process locations.

### Advanced command-line setup

The original Python workflow remains available for maintainers and Mac users.
On a new computer, download and unzip the project, then run:

```sh
python3 -m community.bootstrap
```

On Windows, use the guided starter unless you are intentionally testing the
advanced workflow.

## How to use the site

The website shows your account and search credits. Processing runs on your
computer. Use the guided Windows starter above for scenes. Object processing on
Windows and Linux still needs a published, validated runtime.

1. Connect using your private account code. No name or email is needed.
2. Contribute locations using the local app. Verified scenes earn 1 unit;
   verified object locations earn 10. Pending checks do not earn credits yet.
3. Use saved credits to search in the browser. One completed online search
   spends 100,000 units. Retrying the same interrupted request recovers its
   result without another charge.
   Exported results open in map-making.app. Hosted search is still awaiting its
   validated engine; while unavailable, credits remain saved.

A search needs **100,000 places** (or 10,000 objects). There is no shortcut. An example search is already loaded, so you do not need a JSON file unless you have one from VISION.

If you were given the project folder and want it to go faster, see [CONTRIBUTING.md](CONTRIBUTING.md). Most people can ignore that.

Account deletion is being prepared for the hosted site. Open **Index → Delete
my account**, read the warning and type **DELETE**. It revokes your recovery
code and removes saved searches and unused credits. Verified anonymous
contributions remain in the shared pool. See [account privacy](docs/ACCOUNT_PRIVACY.md)
for interrupted requests, local files and retained records. This feature is
tested locally but is not deployed yet.

The work queue contains imported panorama identities and poses. Queue metadata
does not make a location searchable: a verified user contribution must be
published first. Scene indexing runs `mma-vision index-four-views` on the
volunteer computer. The approved runtime profile records its model,
helper files, settings, and thread policy; results are compared numerically and
then audited before publication. Object indexing
runs `vision-object index-segment` with the hybrid RF-DETR, YOLOE, and OWLv2
models. `python3 -m community.bootstrap` downloads them into the usual VISION
folders. Set `VISION_FOUR_VIEW_BINARY`, `VISION_MODEL_DIR`,
`VISION_OBJECT_BINARY`, and `VISION_OBJECT_MODEL_DIR` only when you already
have those files somewhere else.

For a local development prototype:

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

Open `http://127.0.0.1:8765` to inspect the local prototype. The local server and
command-line search helpers retain development and diagnostic behavior; they
are not the hosted contribution and credit workflow. Real PC contributions
require the trusted qualification and audit service.

The browser search interface supports prompts and map-making.app examples,
scene view directions, country filters and excluding a previous map. Its online
engine must be validated against VISION before these are advertised as matching
the reference application's results. Search results export as map-making.app
JSON; users do not download the shared search index.

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

## Shared storage and online search

Users process locations locally and bank credits from verified contributions.
Search runs online through the website against published contributions only.
The maintainer's private index and unprocessed queue metadata are not part of
the searchable pool.

The server owns account balances, verifies search results and records the result
with its credit charge. The browser can recover the same request after an
interruption. When the search engine is unavailable or its output cannot be
verified, the request does not spend credit. The updated hosted-service code
rejects shared-index downloads and the old paid local-search route.

The repository includes the online search gateway and its checks, but a
validated hosted inference engine still needs to be deployed. It will need
an approved snapshot of contributed indexes. Storage, compute costs, latency
and memory must be measured before promising performance at 200 million
locations; index-only storage estimates are not a complete hosting budget.

## Invariants

- Canonical pano ID, capture, lane, and model have one queue row.
- Expired leases are fenced; stale, forged, duplicate, and replayed work does
  not credit.
- Imagery bytes and tile URLs are rejected. Only metadata and embeddings persist.
- Search debit and JSON emission happen in trusted server code.

## Remaining maintainer steps

1. Review the full calibration evidence against Andrew's reference, approve
   measured processing profiles, and deploy the trusted PC qualification and
   contribution-audit service. Do not invent numerical approval thresholds.
2. Exercise real approved contributions and recovery on the supported devices.
   Publish verified outputs into the shared pool without importing the
   maintainer's private corpus or using unrelated storage.
3. Build and validate the hosted search engine against an approved snapshot of
   those contributions. Compare rankings with VISION and measure hosting costs
   and performance before enabling public search.
4. Complete the deployment, backup, privacy and long-run checks in the
   [release checklist](docs/PRODUCTION_ACCEPTANCE.md). Local tests and a running
   background task do not establish production readiness.

## Windows calibration volunteers

Helping Andrew test scene-index compatibility on a PC? Start with
[the guided Windows calibration setup](calibration/START-HERE.md).
It prepares its own Python/runtime, runs the fixed 1,024-location fixture three
times, and packages results without a Community account or production submission.
