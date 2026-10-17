# Local Scene library and owner import

The launcher now offers **My library** independently of a queue. Completed Scene
packets also appear in the processing window's library. The library records exact
source rows and byte hashes, then creates normal VISION version4 segments of at
most50,000 locations when first searched. It copies packed vectors and complete
masks; it never recomputes indexed embeddings. Full segments are reused. Only the
last growing segment needs rebuilding; its superseded derived copy is removed
after successful publication. Original packet files remain the recovery source.

Pause processing before a search. Text search uses the pinned native VISION
engine and models, without a service account, credits, hosted inference or live
imagery. Country, generation and camera-direction filters use recorded source
metadata. Unknown values are not guessed. Native per-segment candidates are
merged by score/global ordinal, deduplicated and pruned at100m across segments.
The candidate budget is bounded at10,000; a requested result count is a limit,
not a guarantee of that many separated matches. Search results preserve selected
heading, pitch, zoom, panorama and VISION metadata in MMA-compatible JSON.

Reference searches accept up to8 saved Street View poses through the API; the
window accepts one pose or up to eight views from a small MMA JSON map. They use the existing native contrastive/title
query modes, retrieving the example imagery normally. Text-only queries do not
fetch imagery. Provider refusals are reported; no route rotation or automatic
denial workaround exists. Local photo queries are described below. Automatic preview
downloads and Objects are still separate follow-up work.

## Process a personal MMA map

Open **My library → Add my own MMA map**. Choose an MMA JSON export (up to
100,000 locations or 20 MB) with saved panorama IDs. Countries come from saved
country fields/tags, or an explicitly selected fallback country. The app does
not guess missing countries or resolve missing panoramas online. Camera generations
without a recognized saved value remain unknown. Only supported poses, map name
and tags are retained; arbitrary export fields are discarded.

Choose **Prepare my private queue**, then **Save my personal queue**. Extract
the ZIP and open its **campaign.json** using the VISION launcher. Existing
day/night settings, pause/resume, provider-refusal stop and saved-index recovery
apply. New imports omit panoramas already reserved by another personal map or
indexed in the personal library. Reimporting the same map reexports the same queue;
interrupted file delivery keeps committed reservations and exact packet bodies.
Maps with no new work can still attach their names/tags to saved results.

Preparation recomputes the saved fixed112 report comparison against the cached
trusted reference and exact current runtime, accepting each offered CPU profile
only when all448 views meet cosine≥0.9999 and relativeL2≤0.02. Open **Check this
computer** from the current kit once to cache its reference. Existing saved checks
can be resumed; preparation itself starts no inference or imagery retrieval.
The owned metadata worker stops after120 seconds without progress and retains
committed work. This contains a stalled read; it does not establish its cause.

Personal results have a separate local library and can be searched alone or
together with Community assignments. Combined results deduplicate panoramas and
preserve tags. This private workflow grants no Community approval, assignment,
credit or upload authority. Its private queue registry is not a global Community
exclusion list. Owner imports retain their original assignment checks. Personal
collection exports use a distinct contract rejected by the Community owner importer.

The library and API bind only to authenticated127.0.0.1. Writes require the exact
local Origin. Results use text DOM nodes and ordinary user-clicked Street View
links; there is no automatic third-party image request. Query scratch is private
and removed afterward; bounded failed-native logs stay in private diagnostics.
Queues, original indexes, library storage and optional
result backups all consume disk space. A complete searchable copy adds about
15.4 GB of vectors per5M locations, plus metadata. The launcher can select a local/external folder for new work. Existing queues
keep their recorded folder; previous folders remain library recovery sources.
The same device identity is retained. Missing drives stop startup. No automatic
file migration or deletion is performed; low space stops safely.

## Import a participant's private results

Keep the single authoritative owner issuer from allocation. Never accept an
arbitrary archive's self-declared assignment or runtime as authority. The import
command reads that existing issuer without writing to it and accepts only an
exact retained campaign packet, panorama reservations and approved runtime.
It verifies archive inventory/size/path bounds, all saved hashes, checkpoint,
full15 view masks, vector shape, source TSV and duplicate conflicts. Portablev1
andv2 exports are supported, including their normalized path fields. This is
qualified-device output checking, not independent embedding recomputation,
public production certification or a server credit award.

```sh
python -m community.local_scene_import \
  --collection /private/tester-results/collection-HASH.json \
  --registry /private/issuer.sqlite --campaign EXACT_ALLOCATION_ID \
  --library /private/community-scene-library
```

For a single exported packet use `--archive /private/packet-results.zip` instead
of `--collection`. Partial collections can be imported again as work accumulates;
already admitted identical records are skipped. A conflicting panorama is
rejected instead of replacing an existing record. Named files are retained under
the separate library's imports folder, with import receipts. A collection import
commits each verified archive independently; if a later member fails, earlier
accepted archives remain and a corrected rerun safely resumes. Existing owner
VISION indexes, its personal5M queue, Community assignments and cloud state are
not modified.

The resulting library compacts into ordinary version4 index directories on first
search. Registering those new segments with the owner's current VISION catalog
is a separate additive integration step, to be performed with actual participant
output. Do not modify existing manifests/checkpoints or claim that prepared
imports have already been registered. Manual private transfer is sufficient;
automatic R2 upload is not required and no bucket credentials reach participants.

## Focused evidence

Four focused local tests cover incremental byte-preserving segments, filters,
damaged masks, assignment-checked/idempotent imports and token/Origin controls.
One executed shipped-JavaScript flow covers the library, filters, links and map
download. One real native text query returned20 results over the reused frozen
112-location synthetic compatibility output, with identical vector bytes and
unchanged original files. No live imagery, new indexing, full model matrix,
Cloudflare request or Actions run was used. This is a native library-use check,
not a claim of newly processed live locations or actual Windows execution.

## Optional online MMA

Connect with a user-provided map-making.app API key, choose an enumerated map and
explicitly confirm sending current results. Keys remain in memory and are cleared
on disconnect/exit or a new connection attempt. Requests use a fixed HTTPS origin,
no redirects and bounded responses. The delivery journal records the intent before
the first write; a timeout/crash/partial result is held for manual destination
inspection, with no automatic replay. The backend accepts only the current local
search result and a map from the connected account. Local MMA uses the exported
JSON through its existing file import. Real online MMA use has not been executed.

## Prepare an additive owner catalog

After importing actual qualified results into the separate owner library, prepare
segments against the owner's actual canonical models and a hash-pinned version2
current.json. This copies vector bytes unchanged and rebinds model/path metadata:

```sh
python -m community.local_scene_catalog \
  --library /private/community-scene-library \
  --models /private/owner-canonical-models \
  --base-catalog /private/owner-indexes/current.json \
  --base-sha256 EXACT_CURRENT_FILE_SHA256 \
  --output /private/community-publication-001
```

Inspect catalog-update-plan.json, catalog.before.json and catalog.next.json.
With all catalog writers actually paused, repeat the exact command adding
`--apply --writers-paused`. The tool checks both hashes, preserves unrelated
sources and fields, and atomically replaces the supplied catalog. Expanding a
Community segment replaces its prior entry only if all original source rows and
vectors are an exact prefix. Sealed segments remain available when a derived
library partial segment is replaced; hard links avoid an extra copy on the same
filesystem, and cross-filesystem copies are hash checked. A guarded before copy
is retained. This requires cooperative paused writers; the flag is not an OS-wide
lock on other applications. No personal index, old queue or cloud service restarts.

## Additional evidence and current limits

The15 October predecessor passed one real owner-native text query against two
isolated synthetic imported records; vector bytes and the empty synthetic base
catalog stayed unchanged. The actual personal catalog was never applied. That
native-consumer result is reused; it is not a claim that real contributor output
has arrived or that every recovered source byte was re-executed by the native app.

On16 October the cleared temporary checkout was recovered into persistent source.
Four focused storage/MMA/catalog checks passed. One loopback API check initially
found a missing recovered page helper; after restoring it, that check passed.
The shipped-JavaScript DOM harness passed reference JSON privacy, key clearing,
map selection and export. No broad suite, numerical matrix or live provider test
was repeated. Preserved prior selected-storage CLI recovery passed with112 saved
synthetic records in temporary storage. Two earlier Documents-path attempts stalled
in packet reads; the cause is unproven. Physical external storage, real online MMA,
actual Windows execution and real owner-catalog registration remain unverified.

The owner asked to slow Google requests; development stays offline. CPU pace
controls are not a network request cap. No slower per-request implementation or
recovered Google access is claimed in this release.

## Private photo queries (source update after the a3402cb preview)

Choose a local JPEG, PNG or WebP up to20MB in My library. The browser handles image
orientation, draws a224-square preview and sends only RGB pixels to the private
loopback app. The original filename/EXIF and original image file are not sent.
Choose Photo only, or combine the photo with a description. Clear photo discards
the selected pixels; closing the app discards the in-memory selection.

The pinned native encoder consumes sealed local RGB with no network fallback.
Its temporary one-record container exists only to obtain full-precision query
vectors and a text vector; it is not a location contribution, admission result or
new library record. The native ranker consumes an isolated query-profile cache.
Queries contain no remote examples, and a cache miss is refused rather than
silently returning text-only matches. Original location vectors remain unchanged.
Ordinary completion cleans temporary pixels/vectors. A process crash can retain
private scratch files; this is not secure disk erasure or a cloud privacy claim.

One actual offline native encoding/ranking use passed on generated test pixels
and two synthetic saved records (one result after geographic pruning). It is not
an arbitrary-photo quality benchmark or a Windows execution claim. The focused
pixel-boundary, token/Origin, in-memory clear/query forwarding and shipped-script
checks passed. Existing fixed112 qualification is unchanged and was not rerun.
This source update is newer than the published a3402cb kits and is not yet in them.

## Cautious download pacing and bounded recovery (source update)

New live groups use one concurrent download and a30-second interruptible pause
before the next native processing group. CPU priority/thread choices still use
qualified profiles. New campaigns use16-location saved groups; existing128-group
layouts are preserved for safe resume. This is a serial-download policy with
saved-group pauses, not a strict requests-per-second guarantee. The original
planned input remains intact; receipts/exported results additionally bind the
actual native input, changing only download concurrency. All batch/session/graph
settings remain unchanged. No Google request was used to verify this change.

Recovery now runs in an owned metadata-only process. A20-second lack of progress
stops that child, preserves earlier committed metadata and reports a readable
error rather than keeping the UI's recovery thread stuck. Cancel is observed
separately so a stalled source read does not block the watchdog. Existing libraries
search directly; they no longer scan every old packet before every query. Refresh
explicitly recovers missed work, and normal processing still adds completed groups.
Two original Documents-path stalls remain preserved with unknown root cause;
physical-drive/cloud-filesystem behavior is not independently certified.

Focused checks cover the actual network-input delta, cancellable waiting, portable
export/owner import, old128/new16 layouts, watchdog cancellation/timeout and an
actual owned metadata recovery. No broad suite, model matrix or live trial ran.
