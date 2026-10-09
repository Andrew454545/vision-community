# Which locations contributors process

Contributors process the remaining official Google locations from MMA Main's
**ALL LOCATIONS** map. Locally indexed locations and Andrew's next five million
unique locations are excluded by complete panorama ID, across every pose and
catalog. Small calibration/reference fixtures may remain for testing; they are
not assignment sources.

The 9 October 2026 allocation was calculated from the saved native MMA commit:

| Allocation | Unique panorama IDs |
| --- | ---: |
| Current ALL LOCATIONS master | 337,705,814 |
| Already indexed locally, present in that master | 24,946,933 |
| Additional local reservation | 5,000,000 |
| Remaining contributor pool | **307,758,881** |

The complete allocation was uploaded, independently read back and registered on
9 October: **618 unique input shards**, shared by the Scene and Object lanes.
All three old input families were retired and their **936 objects** were removed
and checked absent. Contribution history and testing references were retained.

The indexed input union contains 24,955,313 unique IDs; 8,380 are absent from the
current master. The master has zero duplicate panorama IDs. Different poses of
one panorama are one location for allocation purposes. Published contribution,
account, lease and credit history is preserved when catalogs are replaced.

This is a metadata pool, not a release qualification. The MMA refresh preserved
official coverage and validated new Google additions on 6 October. Old positional
camera/road classifications became invalid when rows changed. The new export uses
`unknown` for those fields; production coverage, runtime and quality gates still
apply. Presence in the pool does not independently establish current Gen4 status
or permission to retrieve imagery.

## Operator workflow

These tools are for maintainers. Contributors use the application; they do not
need Python, Arrow, source exports or Cloudflare credentials.

1. Capture the current master commit, full source SHA-256, row count, country
   authority and stable native index checkpoints. Preserve failures and source
   evidence privately. Do not rewrite a live local indexing queue.
2. Build `deploy/cloudflare/tools/pool-identity.cpp` and `pool-export.cpp` with
   C++20 and the same pinned Apache Arrow installation. PyArrow's matching C++
   headers/library can be installed into an isolated operator directory. No
   application dependency or global installation is required.
3. Supply a private three-column TSV specification: input role, indexed prefix
   length, path. Supported roles are `indexed`, `queue`, `reserved`, `community`.
   `indexed` length zero means the entire file. `queue` length zero means no
   indexed prefix. In owner mode, future queue rows are reservation candidates;
   existing contributor work can be excluded from that reservation with a plain
   panorama-ID `community` file. Pose TSV panorama IDs are column eight.
4. Run `pool-identity owner SPEC NEW_OUTPUT QUEUE_ROWS 5000000`. It selects the
   next distinct unindexed IDs, preserves the live input and records the exclusive
   physical queue boundary. Configure the local indexer's allocation boundary
   separately before it reaches that point; the manifest alone is not a stop
   control.
5. Create a source exclusion specification from indexed prefixes and the sealed
   reservation. Run `pool-identity source SPEC NEW_OUTPUT SOURCE_ROWS ARROW`.
   Hash routing is only a partitioning aid: exclusions and deduplication compare
   all 22 panorama-ID bytes. Reports retain malformed-input counts; publication
   refuses nonzero counts. Temporary partitions are bounded and disk capacity is
   checked before starting. Existing outputs are never overwritten.
6. Run the offline integration checks with explicit locally built binaries:

   ```sh
   VISION_POOL_IDENTITY=/absolute/path/pool-identity \
   VISION_POOL_EXPORT=/absolute/path/pool-export \
   python -m unittest community.tests.test_pool_allocation -v
   ```

   On macOS, use a physical temporary directory (for example an existing private
   directory under `/private/tmp`) for `TMPDIR`; keep failures from other paths.

7. Use `pool-publish.py --help` with a dedicated catalog prefix and a private
   adapter exposing `put(key, bytes)` and `get(key) -> bytes`. Confirm the actual
   Community bucket in the adapter. The publisher pins its inputs, verifies each
   fresh remote object by SHA-256, journals verified shards durably, and deletes
   only its own verified temporary files. Missing acknowledgement, invalid
   country/pose, readback mismatch or changing input stops publication. Failed
   shards and journals remain available. Rerunning the same command renders the
   same bytes and verifies prior objects before continuing.
8. Register the replacement only after the full allocation is uploaded and its
   manifest and every shard have been independently read back. Partial manifests
   are progress evidence; they do not authorize retiring the old full/tail
   catalogs or changing their pending assignment rows.
   `pool-split.py` prepares disjoint masks for bounded parallel publication and
   verifies their complete union against the original mask, optionally reusing
   an already verified ordered prefix. Reconcile pending rows by exact panorama ID: skip only owner or
   reserved IDs and map eligible rows to the replacement shards. Preserve active
   leases and historical outputs. Retire overlapping old catalog registrations
   and remove their input objects only after the replacement is usable. Retain
   test/reference artifacts separately. Never delete embedding results as a
   substitute for retiring assignment metadata.

Keep raw owner exports, reservation identities, provider credentials and private
receipts outside this public repository. Never use the `geonections-images`
bucket. GitHub Actions spending remains on hold; do not dispatch cloud workflows
for this operation or bypass existing release gates.
