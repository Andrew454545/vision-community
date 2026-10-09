# One-location Windows resource diagnostic — 9 October 2026

A separate finite offline task started at **15:00 CDT on 9 October**. Its own
durable receipt confirms actual scheduled execution. It targets 24 hourly
rounds, rotates test-only 1/2/4-thread profiles and has a fixed 26-hour deadline
at **17:00 CDT on 10 October**. Completion is **pending**.

Each round runs recovery checks in a fresh process, indexes one already saved
location with the pinned Object models, fully verifies the index, runs four
native queries and fully verifies again. Comparisons to the existing Mac output
are retained. Native CPU/peak committed memory accounting covers only the
private owned job; optional working-set samples cover its observed descendants.
The installed contributor and Andrew's runner are unchanged.

## Preliminary actual windowless cycle

- **130 recovery tests: 129 passed, one existing Windows symlink-permission skip,
  zero failures/errors**; 155.547 seconds.
- Fresh native indexing, both full verifications and search completed in
  203.750 seconds. The full preliminary cycle took 363.004 seconds.
- Detection structures, quality masks, stored semantic PQ codes and selected
  faces matched the supplied Mac result. All four query hit orders/selections
  matched. Two queries were empty, including Hot; this is one distinct location,
  not broad ranking or coverage evidence. Numerical differences remain in the
  private comparison; no production tolerance was assigned.
- The index command used 196.498 wall seconds and 191.328 CPU seconds, with
  peak job committed memory 3,589,345,280 bytes. Its 768 working-set samples
  observed all four accounted processes. Working-set process coverage was
  incomplete for the two very short verification commands; their job CPU/commit
  accounting and verified descendant cleanup still completed.

Sampled working sets are not exact simultaneous/shared physical RAM, thermal
measurements or proof of GPU placement. This sparse fixture cannot approve a
production parallel profile or establish maximum useful throughput.

## Bounds and recovery

The task uses the existing limited Windows user and private windowless Python.
It is hidden, prevents overlap and can resume after sign-in during its finite
execution window. Its source snapshots and supervisor are checksum-pinned.
The supervisor retains interrupted attempts, imposes resource/evidence checks
and stops on a failed round or its deadline. It does not need Codex or a terminal.
Sleep/power-off pauses execution; missing periods do not become continuous work.

Command deadlines remain 900 seconds for indexing, 120 for each verification
and 180 for search. The private evidence allowance is 512 MiB, with free-space
and available-memory checks before each round. A `STOP` marker stops between
bounded stages/rounds. Task expiry and the supervisor deadline bound resumption;
this diagnostic is not installed as an indefinite contributor.

The original two-location timeout remains failed and preserved, and its exact
old task remains disabled. This smaller workload does not repair, replace or
explain that failure. No command deadline was extended.

This task retrieves no imagery and creates no accounts, contributions or
credits. It uses no GitHub Actions. It is **not** the
[seven-day accepted-work check](ACCEPTED_WORK_SOAK.md): neither operating
system's accepted-work clock has started while the current service is closed.

Aggregate counts and retained-file checksums are in the
[launch evidence](evidence/windows-native-diagnostic-20261009.json). The dated
launch evidence is not a completed 24-round result; inspect retained receipts
after the task finishes or fails before updating its status.
