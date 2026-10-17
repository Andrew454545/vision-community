# Saved Object search in the local app

**My library → Search saved Objects** can import and search a VISION v4 Object
index on the user's computer. Object processing still needs its separate
100–112-location cross-platform qualification. These controls never approve a
device, assign work, start indexing, contact Community or upload anything.

1. Choose **Set up Object search** and accept the first private download, about
   900 MB. Existing verified files are reused. No global installation is needed.
2. Choose an **Object library ZIP**, then **Import saved Objects**. A normal MMA
   map contains locations; it is not an Object index.
3. Enter an object or description, optionally select country, generation and
   confidence, then choose **Search my Objects**. Pause Scene processing first.
4. Results appear in the library. Use **Save results as a map**, or the existing
   optional MMA connection, to use them. **Stop library action** cancels an
   outstanding action; completed indexes remain saved.

Common objects, hot concepts and semantic descriptions use the existing native
query planner, confidence floors, PQ128 data and Object search executable.
Original global IDs map back to the correct source rows and are retained in
result metadata. Packed records, source poses, quality masks and original
provenance are preserved. Results use Object camera aim, rather than the Scene
four-direction selector. Unknown country/generation tags stay unknown.

The optional runtime is pinned by the existing `runtime_manifest.json` and lives
in its own private folder. It cannot replace the Scene program or dependencies.
Each action runs in an owned child so closing/cancelling the app can stop it;
private diagnostics survive ordinary failures. Setup resumes retained partial
files. It makes no imagery request. A Scene-only user need not set up Objects.

## Preparing a private library ZIP

With the repository's private Python, run:

```text
python -m community.local_object_library --index /path/to/completed/index --source-tsv /path/to/locations.tsv --output /private/path/objects.zip --label "My Objects"
```

The initial portable format supports one complete index of up to 1,000 locations,
32 MB of feature data and a ZIP no larger than 40 MB. It verifies source/hash,
packed record and metadata consistency before export. Import also requires the
pinned native full verifier. Unsupported/incomplete indexes are rejected.
Use individual completed groups for this initial format; it does not split a
large owner segment. No personal owner catalog is modified.

Imports go into a separate Object library. Reimporting the same content is
idempotent. A different index with any already-imported panorama is rejected as
a whole; existing records are kept. No index is registered until verification
succeeds. Search rechecks saved contents before native use, filters using saved
metadata and merges results with stable library ordinals. The native per-group
candidate limit is 1,000 and the merged map candidate limit is 10,000.

Frozen diagnostic data keeps its marker and a private, explicitly unapproved
receipt. Private imports are not eligible contributions. Existing Object
qualification, historical coverage, protected-source and publication validators
are unchanged. Never use this local receipt as a Community approval.

See [the implementation evidence](evidence/local-object-library-20261017.json).
Actual Windows execution, interactive file panels and new Object processing
remain separate requirements. This is still an unsigned invited application.
