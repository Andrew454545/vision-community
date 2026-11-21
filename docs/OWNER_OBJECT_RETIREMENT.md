# Owner delivery of published-job cleanup

**Offline source only, inactive.** The [cost hold](COST_STOP_20261012.md), existing
pause/stop markers, zero native allowances and all launch gates are unchanged.
No deployment, migration, credential access or processing restart occurred.

Published Object jobs can now use the owner's outbound connection for the existing
[successful-job cleanup](OBJECT_NATIVE_RETENTION.md). This frees candidate,
successful reference and recomputable cache files while preserving successful
audit reports, original failures, source copies, logs and accepted work/credits.
It does not remove historical job/registry bounds or establish indefinite capacity.

The future independently pinned owner configuration must explicitly set
`retirement: true`; it is absent/off by default. The existing optional retirement
schema must already be installed by an approved operator. Private HTTP requests
never install it. Both routes use the existing distinct owner Object secret;
contributor account credentials cannot authorize cleanup.

Each `POST /api/object-audit-agent/retirement` reserves at most one command from
immutable acceptance, current publication and matching earned-credit authority.
Only the owner's exact approved policy/profile/resource pins are eligible. The
existing journal reserves backoff before handoff; competing polls cannot reserve
the same retry twice. No R2 bytes, model inference or financial changes are needed.
Incompatible historical policies remain preserved for their matching operator.

The owner saves the exact command before touching the native job. The native
auditor validates its job/assignment/submission/receipt/acceptance identity, records
retirement and performs one owned cleanup step. A dedicated `cleanup_once()` can
never fall through to inference for another queued job. A still-pending cleanup
retains its command. The owner saves a completed `retired`/`erased` reply before
`retirement-ack`; an intermediate `retiring`/`erasing` reply cannot finish delivery.

After a restart or lost acknowledgement, a saved completed reply is sent before
native files are accessed. The coordinator checks the immutable accepted identity
and saved request hash, even when the current policy/native assets are unavailable.
Complete pending writes recover an interrupted rename; incomplete bytes and
conflicting commands stop work and stay preserved. Ordinary lost acknowledgements
need neither another model run nor another credit award. The existing audit
completion outbox always takes priority before new maintenance.

Account deletion remains stronger and separate. A deletion racing retirement
leaves its account-erasure outbox pending; `privacyPending` is not confirmation
that account data was erased. Outbound cancellation, account erasure and removal
of delivery-state private receipts still require integration. Restoring native
inputs for an uncompleted command also needs legitimate matching authority;
this path cannot fabricate a fresh protection proof.

[Windows local evidence](evidence/owner-object-retirement-20261013.json) includes
actual Worker/local SQLite handlers and the real saved Python auditor's owned
filesystem cleanup. Native inference/models, coverage, R2 and credential access
are fixtures. Reports and original credit survive; lost acknowledgements recover
without native inputs. This does not prove authentic Mac/PC contributions, actual
Mac execution, Free-plan capacity or a completed endurance run.
