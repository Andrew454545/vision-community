# Invited local Scene pilot

The user chose this immediate milestone on 15 October: a small group processes
Scenes on its own computers and keeps indexes locally. Uploads, credits, shared
search and seven-day endurance come later. Objects remain deferred. The earlier
cloud service and full-production checklist remain preserved; they do not gate
implementation of this separate local pilot.

## Participant flow

The maintainer supplies a prepared **VISION Local Scenes** kit and one assigned
Scene packet. Extract the kit to a regular local folder. On Windows open
**Start Local Scenes.cmd**; on Apple-silicon Mac open **Start Local Scenes.command**.
Choose the packet when prompted and accept setup downloads if wanted. The private
Python and about 0.9 GB of model files come from python.org and the project's
existing GitHub release. No administrator installation, account, contribution,
search, cloud inference or recurring task is created.

Choose **Start / Resume** in the local browser window. The native VISION indexer
retrieves imagery through that participant's connection and performs Scene
inference on their CPU. **Pause** completes the current group of at most 16
locations, then stops. A native child is bounded to ten minutes. Closing the
browser tab leaves work running; **Exit** waits for the current group and stops.
Reopening the launcher with the same packet checks and resumes saved work.
CPU1/fp32, batch shape and four-view v4 indexes retain the existing processing
semantics. Medium scheduling priority is used; parallel profiles and automatic
day/night scheduling are separate follow-up work.

The window shows the saved-work folder. Keep the whole folder, including packet,
part receipts, checkpoints, native logs, index files and `result.json`. Results
are **local and provisional**: they earn no credit and are not yet pool members.
Later admission must verify compatibility and provenance. The index is about
3,080 bytes per location plus masks, metadata and logs; native temporary usage
and model/Python installation require additional space.

Project hosting and Actions are absent from this processing path. Participants
still use their own electricity, storage and ordinary internet data. No imagery
or model download occurred during source verification. Setup itself does not
start processing. Public downloads, signatures and actual participant installation
are not claimed by a locally built unsigned maintainer kit. If OS policy refuses
the launcher, stop and use a legitimate trusted installation route; do not disable
security protections.

## Issuing distinct work without cloud coordination

Keep **one authoritative private issuer SQLite registry** on the maintainer PC.
Back it up together with its packets. Import a source-approved metadata-only
11-column native VISION TSV; this tool makes no provider call and infers no
coverage or rights authority:

```text
python -m community.local_scene_packets prepare --tsv approved-locations.tsv --registry issuer.sqlite
python -m community.local_scene_packets assign --registry issuer.sqlite --participant tester-01 --count 100 --allocation-id tester-01-001 --output tester-01-001.json
```

Use opaque participant labels. Start with 100 locations per participant (maximum
1,000 per packet), then issue another packet when appropriate. The registry
reserves panorama IDs atomically before delivery, across imported catalog versions.
Concurrent allocations cannot overlap. Repeating the same allocation ID reexports
the exact retained packet; changed parameters fail. Lost export or interrupted
delivery does not free the reservation. Do not automatically reassign abandoned
packets or clone independent issuer registries. This is cooperative offline
coordination; copies of a packet can still be processed by another person.
Checksums detect accidental changes and do not authenticate a dishonest issuer
or participant. Disjointness covers this registry's issued work, not earlier
service assignments: use a source export already excluding those when needed.

Rows preserve original source index, source TSV digest, country/generation tags,
heading/pitch/zoom and native source IDs. Generation tags retain their existing
basis: Gen2/3/Badcam can be heuristic, unknown stays unknown. No Object or official
coverage authority is created. No account codes or source database are placed in
packets. Do not distribute a private catalog without its applicable consent.

## Maintainer preparation

`community/local_scene_runtime.json` pins only Scene files. Windows uses the actual
CPU1 binary from the recorded Windows cohort (`6ce8f5…91ba`) and its DLLs; the
canonical four model files are unchanged. The Mac pin currently retains the
previously published `be0d98…19f2` binary. Its execution of the new pilot path and
explicit fp32/CPU1 messages must be confirmed on Mac before invitation; a missing
execution marker fails closed and does not make an approved result.

Build locally, using the directory of the pinned native binary and dependencies:

```text
python packaging/build_local_scene_pilot.py --output /absolute/path/pilot-kit --native-dir /absolute/path/native/bin --revision FULL_COMMIT_SHA --platform windows-x86_64
```

The builder validates native pins and uses the existing named public-source
inventory. It includes no model files, assigned packets, credentials, logs, database,
private Python or checkout. The ZIP is explicitly a **maintainer unsigned** artifact.
Model setup copies those checked native files and downloads only the four pinned
Scene models from the existing project release, with resumable digest checks.
Do not publish or invite users from a dirty build or claim a signed release.

For an already prepared machine, the account-free entrypoint is also available:

```text
python -m community.local_scene_ui --packet tester-01-001.json --runtime-root /path/to/prepared/runtime --data-dir /path/to/private/results
```

The local UI binds only `127.0.0.1`, uses a random session token, exact Host and
Origin checks and no remote assets. Browser requests cannot select filesystem
paths, accounts, uploads or cloud APIs. OS file locking prevents two pilot processes
writing the same packet folder. Each completed part is checked against saved
hashes, complete view masks, index layout and runtime profile on resume. Orphaned
uncheckpointed bytes stay in a separate attempt. Failed attempts are preserved.

## Next actions

1. Verify the prepared Windows kit/setup locally without downloading files, then
   exercise one genuinely fresh local packet on an installed participant machine.
2. Obtain the exact Mac-only pilot launcher/runtime execution result through PR17;
   fix only a relevant changed input or actual failure. No Actions or cloud is needed.
3. Choose the approved metadata-only source, retain one issuer registry, and make
   disjoint packets for the small invited group. Provide trusted installation help.
4. Record actual setup/start/pause/resume and saved-index evidence on each platform,
   then invite that platform's participants. No week-long wait is imposed here.

Only source/synthetic local verification and actual installed-file checks are
recorded so far; no fresh pilot indexing, participant installation, packet delivery,
model download, cloud operation or invitation is claimed. The separately paused
old tasks and operational cloud hold remain untouched. Later uploads/search use
the preserved service roadmap and their own activation/transfer authority.
