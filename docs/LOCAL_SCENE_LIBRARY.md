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
window exposes one example. They use the existing native contrastive/title
query modes, retrieving the example imagery normally. Text-only queries do not
fetch imagery. Provider refusals are reported; no route rotation or automatic
denial workaround exists. Arbitrary photo uploads, automatic preview downloads,
direct MMA connections and Objects are still separate follow-up work.

The library and API bind only to authenticated127.0.0.1. Writes require the exact
local Origin. Results use text DOM nodes and ordinary user-clicked Street View
links; there is no automatic third-party image request. Query scratch is private
and removed afterward; bounded failed-native logs stay in private diagnostics.
Queues, original indexes, library storage and optional
result backups all consume disk space. A complete searchable copy adds about
15.4 GB of vectors per5M locations, plus metadata. External/selectable storage
and reducing duplicate storage remain follow-up work; low space stops safely.

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
