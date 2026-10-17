# Verified allocation handoff and database rehearsal — 9 October 2026

The replacement contributor pool is complete. Andrew supplied a privately
pinned allocation packet; its archive checksum and all **34 contained file
pins** pass independent local verification. The separate real protected-reference
packet and all **21 contained file pins** also pass. Raw identities, coordinates,
account records and private receipts remain outside this repository.

An independent primary read of the confirmed Community D1 shows **618 distinct
input shards per lane**, **307,758,881 rows per lane**, no held replacement shards
and **zero registrations from the three retired catalog families**. Scenes and
Objects share the same physical input pool; their row counts must not be added.
Andrew's pinned removal inventory reports 936 old input objects absent and the
complete replacement remotely read back. This session did not redownload all
618 objects. No allocation, historical output, account or credit was changed.

The allocation excludes the complete indexed identities and the five-million
reservation, as described in [the allocation policy](CONTRIBUTOR_POOL.md).
Unknown camera labels still cannot qualify an Object assignment as Generation 4.

## Database compatibility

The live schema read confirms missing `accounts.deleted_at` and
`leases.scene_qualification_id`, plus the absence of the newer qualification,
privacy and revision tables. Deploying current application code over that
unprepared database would fail; do not treat the completed pool as a deployment.

A new [schema-only fixture](../deploy/cloudflare/fixtures/legacy-20261009.sql)
preserves the deployed CHECK and foreign-key constraints, without production
rows. The existing upgrade tool passes an actual local workerd/D1 rehearsal on
this structure with synthetic history. A late failure and a changed schema both
roll back. Success preserves synthetic credential hashes, balances, paid search
bytes, publications, active leases and automatic-ID high-water marks; deletion
fences and original constraints remain enforced. The first fixture seed inserted
child rows before their parents and correctly failed the foreign-key check; its
log is preserved. The corrected seed uses parent-first ordering.

This is **schema compatibility evidence, not a full production-data rehearsal**.
A private production backup, full-data upgrade rehearsal and fresh rollout
readback remain required. The live database and deployment were not modified.
Retain and drain/reconcile existing legacy leases before replacing their writer;
never assign a new qualification to old work merely to make it pass.

## Other checks

- Three actual local workerd catalog fixtures pass: retired and held inputs stay
  unavailable, existing valid leases resume, a late hold rolls back, and competing
  requests cannot claim the same location. Object admission stays closed.
- The full Worker source suite runs **314 tests: 307 pass, seven explicit Windows
  link-privilege skips, zero failures**. The new schema test is included.
- The final full Windows application suite, including the new protected guard,
  runs **772 tests: 757 pass, 15 platform/permission skips, zero failures or
  errors**. The earlier sandbox-limited failure is retained separately; these
  results do not establish Mac execution or accepted production work.
- The real protected packet contains **18,549 unique coordinates**; all **121**
  supplied positive candidates independently match them exactly. A one-location
  strict metadata check is prepared but has not run. This proves neither current
  Generation 4 coverage, a native protected-import seal nor tunnel visual evidence.
- The Object auditor now independently checks assignments against the pinned
  snapshot before running models, while retaining the sealed database checks.
  Its geographic implementation matches the native packet on all **139** real
  positions: **121 protected, 18 unprotected**. Synthetic boundary tests cover
  inclusive 25 metres, poles and the date line; missing, changed or stale snapshot
  authority cannot approve work. See [the auditor contract](NATIVE_OBJECT_AUDIT.md).
- The already-failed finite offline endurance task is now disabled, with exact
  ownership and disabled-state readback retained. All failed evidence remains;
  the installed contributor and native owner runner are unchanged.

## Closed staging website

The existing staging Worker was updated using the saved private sign-in after
its exact database, bucket, service and closed policy were independently
confirmed. The staging schema contract and structural checks pass. All **13**
deployed website files match local bytes, with the expected privacy/security
headers; both contribution capability flags remain false. Provider readback
confirms the original staging resource pair, required deletion archive and rate
limits, empty Scene policy and no search-engine binding. Production was not
deployed or migrated. No account, model work or credit was created.

The [redacted evidence summary](evidence/allocation-protected-schema-20261009.json)
records exact counts, retained log checksums, scope and remaining limits. The
complete-data backup and one protected-candidate metadata lookup were not run:
automatic approval review requested specific authorization for their private
payloads and destinations. Independent schema/geographic work continued.

The [five release gates](LAUNCH_PLAN.md) remain open. This work used no GitHub
Actions, retrieved no imagery and created no contributions or search credits.
