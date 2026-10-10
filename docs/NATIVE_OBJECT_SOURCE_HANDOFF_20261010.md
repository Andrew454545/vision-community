# Authentic Object source handoff

Andrew's 10 October private source/failure packet is received and verified: the
archive and all 76 contained file pins match. The first Windows extraction hit
the path-length limit; its failure receipt is preserved. A short-path extraction
keeps the original file bytes and a private original-name map.

## What the evidence establishes

- Exact-byte scans found none of the supplied 100 candidate pano IDs in the
  owner's completed Scene sources. This is expected for contributor candidates
  outside the owner's indexed union. Requiring those candidates to occur in that
  same owner-only Scene index would prevent this contribution path. Community
  Scene completions need an explicit native authority route; do not relabel them
  as owner MMA completions.
- The authentic historical sealer rejects its candidate because the strict
  official-Google proof is missing. The protected guard independently rejects
  a changed Main/WAL pair. These are valid failures, not permission to edit the
  old manifest, seal, database timestamps or guard.
- The packet contains exact source and failure evidence. It does not contain
  the large Scene sources, models or protected database bytes, and it is not a
  current portable production import seal.

## Native compatibility fix

[Private VISION PR #16](https://github.com/Andrew454545/VISION/pull/16), commit
`47c99c8663bf93c6db9c5f97f06fa349309155f4`, adds explicit support for the native
exact-pano v7 validator alongside v6. Builder, inline sealer and guarded runner
preserve the actual policy identity and reject mixed or contradictory proofs.
Scene-source, pose, protected-location, quality and database-freshness checks
remain required. The authentic old candidate still fails and creates no seal.

The same fix repairs read-only file flushes on Windows and hides native child
windows. Windows publication records file flush and rename without claiming a
POSIX directory flush or guaranteed power-loss durability. Other platforms keep
directory-flush checks and propagate storage errors.

The final Windows selection passes **39 of 40 checks**, with one explicit
POSIX-executable-fixture skip and zero failures. Fixtures use no native inference
or live imagery. Actual Mac execution and power-loss acceptance remain open.
The earlier Windows flush failures and all original owner failures are preserved.
[Pinned evidence](evidence/native-object-source-handoff-20261010.json) records
the separate packet, regression and remote-branch verification.

## Next engineering work

Build and test a distinct Community Scene authority route with genuine audited
membership, exact source/runtime/model/quality pins and a freshly obtained,
matching protected-database authority. Revalidate coverage at import time.
Then connect the saved Object jobs to hosted qualification, owned quarantine,
publication, search and once-only credit. These are implementation tasks, not a
request for another general owner signoff. Signing identities, clean devices and
nontechnical testers still require legitimate external resources.

No Object admission, live native host or production policy was enabled here.
The Windows Scene pilot and refresher retain their frozen pins and deadlines.
