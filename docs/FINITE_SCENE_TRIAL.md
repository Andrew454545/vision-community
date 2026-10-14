# One private Scene trial

**Prepared and checked locally; not deployed or run.** The laptop user directly
approved the [staging reads](evidence/scene-staging-readonly-20261014.json), not
activation or uploads. The exact account/profile/policy qualification is current
until **18 October 2026, 05:51:41 UTC**. Staging workers.dev/previews are off and
crons empty. One bounded SELECT read seven rows, wrote none and returned one
matching qualification. Configuration reads returned no secret values. Provider
charges were not independently measured.

## Prepared execution

The [operator-only gateway](../deploy/cloudflare/tools/finite-scene-gateway.mjs)
uses the existing staging D1/R2 resources, a random private one-trial header
credential whose SHA-256 alone is configured, one invited account and a deadline
no more than 20 minutes ahead. Wrong/missing credentials, other resource settings,
expired/overlong windows and unsupported endpoints are refused before database
access. No public web/download, new-account, fresh qualification, Object or search
route is available. Native verification/search bindings and static assets are
absent from the prepared candidate. Regular checked-in deployments do not select
this entrypoint; zero native allowances and disabled recurring tasks stay intact.

The [client](../community/finite_scene_trial.py) defaults to offline preparation.
It reuses the saved account/canary, checks existing native/model/CPU1/pipeline
fingerprints against the pinned policy, and requires explicit `--run` and
`--allow-staging-contribution` for execution. Those arguments do not grant user or
provider authority. The separately approved operator supplies the existing private
files and one-trial credential; no account code/token is printed or committed.

The supervisor uses existing process ownership to bound the entire child and its
descendants to **600 seconds**. The unchanged default native runner/provenance is
used. The child checks the exact qualified Scene capability and existing server
qualification before taking **one assignment of at most two locations**. There is
no second assignment or account creation. Results use the existing durable local
outbox and distinct qualified publication path. One award and a zero-credit replay
must reconcile against the existing balance. Failed/ambiguous work stays private
and recoverable; local failure does not imply the server awarded no credit.

The transport counts actual attempts, including retries: at most **32 requests**
and **512 KiB** sent to the exact staging origin/allowed endpoints. Unexpected HTTP,
network or missing-usage replies stop further transport. Known read/write/put/byte
headers are accumulated across requests. At most **four R2 put attempts/512 KiB**
are admitted for this prepared client: it sends the measured remaining allowance,
which the gateway checks before each put. Unbounded streaming writes are refused
before storage access. This is not a durable global quota for other credential holders.
The database meter keeps the original D1 batch transaction intact and reports
actual returned row metadata. After **2,000 observed reads/128 observed writes**,
further work is refused. A completed operation can cross that observed threshold;
already-metered usage or committed credit cannot be undone. Missing metadata
fails closed. These controls are not a provider invoice cap or measured capacity.

## Close and preserve

The child deliberately reports `gatewayClosed:false` and
`shutdownReadbackRequired:true`, even on success. The operator must close in a
`finally` path: restore the prepared closed gateway configuration, verify its
public/previews/schedules posture, and retain child/supervisor/closure receipts.
If restoration fails, preserve the failure and report it; never relabel child
completion as verified closure. The private token/deadline independently blocks
new database/contribution access after its short window. Native/model downloads,
cloud inference/search, background-task/pilot restarts, Actions and public rollout
are outside this trial.

Current configuration inspection found the cached 10 October restore file had
an old search snapshot and omitted the dynamic-snapshot setting. The corrected
private candidate/restore files use the current exact vars and confirmed bindings;
they preserve current search authority instead of restoring that stale pointer.
Both passed offline Wrangler dry runs. Original drafts and diagnostics remain in
`work/scene-resume-20261014`; refresh only the short deadline immediately before
an approved deployment and pin/freeze the exact verified source. Verify the live
configuration has not changed before applying that prepared restore plan.

## Evidence and approval boundary

[Preparation evidence](evidence/finite-scene-preparation-20261014.json) records
six Node tests, eight Python tests and 11 actual local workerd/D1/R2 checks,
without skips. The two-location fixture published with one two-unit award,
replayed for zero additional units, blocked search, and reported 136 reads,
42 writes and two puts/12,320 bytes. All qualification/account/features were
synthetic; this is not real inference or a hosted contribution. Real saved-asset
offline preparation also passed with zero network requests.

The first local runtime hit sandbox SQLite path restrictions; its approved offline
rerun then caught the fixture's wrong ledger-entry count. Only the test expectation
was corrected. The first dry run's global log-path refusal was corrected by using
private workspace logs. Preserve those originals; do not repeat completed model
matrices or change production transaction/credit rules to satisfy a fixture.

Next obtain the laptop user's explicit approval for the concrete temporary
gateway deployment, existing-account recovery, live retrieval/CPU1 processing of
at most two exclusively assigned Scenes, private indexed-result uploads to
**`vision-community-staging` R2**, once-only credit/replay and mandatory closure.
Accept possible small staging coordination/database/R2 charges. That approval
does not grant ongoing operation or public release, signing, a new qualification,
cloud-native compute/search or access to any other bucket/service.
