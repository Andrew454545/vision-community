# Hosted scene verification: 3 October 2026

The private staging host completed three fresh eight-location audits and a
separate native capture with three same-pixel replays. This establishes a
measured initial batch size and small-fixture repeatability. Admission policy,
accepted Windows contributions, credits and hosted paid search remain open.

## Eight-location audit budget

Each invocation started the existing immutable Linux image, used the actual
`NativeSceneVerifier.recompute` path, and stopped compute afterward. The fixed
fixture is the first eight public canary locations, covering eight countries.
No commands, locations, URLs, vectors or thresholds can be supplied to the
diagnostic. All runs used the pinned fp32 image graph and one CPU thread.

| Fresh run | Processing and identity checks | Full request | Peak native RSS |
| --- | --- | --- | --- |
| 1 | 18.186 s | 22.962 s | 818,500 KiB |
| 2 | 20.399 s | 25.260 s | 825,388 KiB |
| 3 | 18.142 s | 24.935 s | 830,508 KiB |

All 32 views completed per run, with zero fetch/inference errors. The native
timeout remained 50 seconds. Keep the existing eight-location batch limit;
these measurements do not justify increasing it to 128. They also do not
establish large-index search latency, simultaneous-request capacity or cost.

Runs 1 and 3 had matching packed output hashes; run 2 differed. Independent live
retrieval is therefore unsuitable as evidence of byte-for-byte repeatability.
The difference alone does not identify its cause or establish a tolerance.

## Same-pixel native replay

The follow-up captured the actual 224×224 thumbnail RGB boundary once, then used
the native sealed-input path in three new index and query-cache directories.
Each replay checked the immutable manifest, all 32 preprocessed input hashes,
raw normalized vectors, complete packed records/masks and three saved-index
native text queries. All temporary imagery, vectors and logs were removed.

The three replays took 17.575, 17.524 and 17.375 seconds, including their native
queries. All preprocessing hashes, normalized vectors, packed index bytes and
native query results matched the capture. Maximum normalized and packed
relative L2 differences were zero. The complete diagnostic took 72.593 seconds
and peaked at 825,748 KiB native RSS.

Two earlier diagnostic failures are preserved privately. The replay path records
its selected graph in sealed native evidence rather than the ordinary indexer's
explicit-input log message. The diagnostic initially expected that ordinary
message. Its corrected check requires the bounded CPU pool and the sealed fp32
graph evidence. Ordinary contribution audits still require both original log
markers; their verification was not relaxed.

## Deployment and limits

- Image digest: `d951eff7987b0284d333f193489de339cc5bd63252284bfc8297d1a322bf91d6`.
- Runtime SHA-256: `bbc60e94e6590c657f256d89f6d63db47f7f3d53d1ba37ffeafba07b6211d64e`.
- Private Worker version: `e66b2fa5-1f94-4dfa-bc26-be704ed11edc`.
- Independently downloaded Worker source matches the local 67,956-byte bundle:
  SHA-256 `6f8eb197b58c494b41a807a1a110a73952b21e80c621cdb012e265a486e2ef84`.
- 185 JavaScript tests and 37 actual workerd private-route checks pass.

Model, audit-budget and replay diagnostics now refuse any active sealed workload
before starting, hydrating or stopping compute, and stop after success or
failure. Failed shutdown cannot be reported as success. Failure metadata contains
only allowlisted phases, bounded run numbers and timestamps. Public/preview
routes, container logs and SSH remain disabled. No recurring test was installed.

The tests accepted zero contributions and awarded zero credits. No calibration
archive was uploaded, no contributor snapshot was activated and no production
gate was opened. Only the confirmed Community staging resources were used.
Broader fixed-input comparison with Andrew's results and the remaining
[release checks](PRODUCTION_ACCEPTANCE.md) still apply.
