# Object upload ownership and recovery — 11 October 2026

Object files now use the durable upload journal already used for Scenes.
The local prototype previously wrote Object bundle members directly to R2,
so an interrupted upload was not discoverable by account cleanup.

The shared writer records the account, lease, checksum and size before storage.
Writes are create-only; retries must match the original bytes. Object binary
lanes may be empty, while source and manifest files must contain data.
Hash-named private quarantine is limited to 4 MiB and its name must match its
payload. Exact key parsing prevents cross-lease, nested or escaping writes.

Deletion fences incomplete bundle members and quarantine, including delayed
creates that have not returned an acknowledgement. Lost storage replies recover
without rewriting files. Published Object prefixes remain as anonymous
contributions; a different lease cannot borrow that retention authority.
Offline privacy recovery independently checks Object fences and their ownership.
Scene deletion retains its indexed lookup. No schema revision changed.

## Evidence and limits

[Pinned evidence](evidence/object-owned-storage-20261011.json) records **271 of
274 Windows checks passed**, three existing file-symlink permission skips and
zero failures. **18 actual local workerd/D1/R2 cases pass across three separate
processes**, including cleanup and late-upload refusal after restart. The full
local upload route also checks journalled publication, once-only replay and
deletion during upload. All inference, input coverage and provider replies in
these checks are explicit synthetic fixtures; no real credit was awarded.

The first local-engine compatibility failure and the new route fixture's wrong
500 expectation are preserved privately. The correct existing account-revocation
response is 401; the server behavior was not weakened to satisfy the fixture.

This closes the new Object writer/storage-cleanup component. Public Object
admission remains closed. Authentic qualification, portable protected authority,
saved-job admission/publication/credit settlement and real hosted verification
remain required. Existing unjournalled legacy orphans require a separate
inventory reconciliation. An R2 inventory still cannot certify native spool
erasure. No provider deployment, Actions run, frozen pilot change or launch-gate
approval was made.
