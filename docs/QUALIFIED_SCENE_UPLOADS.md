# Qualification-based Scene uploads

**Implemented in source, disabled and undeployed.** This implements the Scene
part of the user's [approved hybrid plan](HYBRID_LAUNCH_DECISION_20261013.md).
It removes native inference from routine Scene submission settlement. Initial
device qualification still requires the pinned 112-location reference check.
The existing fully audited path remains the default. Objects are unchanged.

## Admission and credit

The operator must explicitly select `SCENE_ADMISSION_MODE=qualified-device-v1`
with the existing measured `SCENE_POLICY_ID`. No checked-in deployment selects
it. Unknown modes fail closed, including when an older preapproved reference
pool is configured. Staging policies retain their environment/bucket isolation.

An account needs an active qualification for the exact policy/profile. Once that
exists, the capability/status/assignment/upload path can operate without a
`SCENE_VERIFIER` binding. Creating a new qualification still requires that
verifier; routine settlement never invokes it. This is not removal of the initial
Mac/PC numerical comparison or a substitute for an actually approved runtime.

Assignments reuse the existing exclusive leases. A retry recovers the same
assignment; another qualified account cannot receive its locations concurrently.
Expired/crashed leases can cause repeated computation, but acceptance and credit
remain once-only. Default batch size remains bounded at eight locations, with
the existing explicit configuration accepting at most 128; this is not a measured
new parallel profile or Free-plan throughput claim.

The upload keeps the existing private artifact journal, create-only R2 writes,
quarantine, record checks and transaction fences. Settlement rechecks finite
positive four-view scales, exact record/submission digests, policy/qualification,
current assigned pose/model/country/generation metadata, queue ownership and
lease membership. Qualification revocation and account deletion during delivery
cannot grant credit. These checks establish integrity and assignment, not proof
that every feature was computed honestly. That is the explicitly approved trust
tradeoff; no synthetic native audit approval is generated.

Each new candidate seals `qualified-device-v1|<qualification-policy-id>` in its
existing policy field. Credit uses the distinct ledger reason
`qualified_device_work`. Responses identify `admissionMode=qualified-device-v1`.
Switching configuration cannot silently convert an old pending audited candidate;
already published receipts replay without new inference or another award even
when the current service configuration is unavailable.

## Search, snapshots and recovery

The existing online queue accepts the earned credits and validates the same
contributor-only membership. One local integration fixture runs the real Worker
router and SQLite transactions through exclusive assignment, upload, settlement,
earned-credit search reservation/completion and exact paid-result recovery.
Native scores, inputs and R2 are synthetic in this fixture, not real admission.

The offline publication snapshot builder accepts independently pinned authority
with scope `qualified-device-community-scene-publications`. Each policy must bind
its prefixed candidate `policyId` to the exact underlying `qualificationPolicyId`,
qualified profiles and native runtime digest. It requires the distinct earned
credit reason and matching original feature bytes, metadata and publication.
Its receipt is `QUALIFIED_DEVICE_PUBLICATIONS_SEALED`, not a native-audit receipt.

To combine earlier audited contributions with new qualified work, authority may
explicitly use `qualified-and-audited-community-scene-publications`; every policy
must then declare `admissionMode` as `audited-v1` or `qualified-device-v1`.
No implicit downgrade is allowed. The receipt is
`MIXED_ADMISSION_PUBLICATIONS_SEALED`. Existing strictly native-audited authority
refuses qualified records. Snapshot integrity, current inventory/deletion control,
anonymous contribution retention and once-only financial reconciliation remain
required. The financial recovery checker validates qualified-work awards too.

## Evidence and next activation work

[Local evidence](evidence/qualified-scene-20261013.json) records 86 passing Node
checks and 42 passing Python checks, no skips, on Windows. Relevant queue,
membership, native-audited Scene, snapshot and financial recovery regressions ran.
The first Python run hit sandbox path-validation restrictions; hidden offline
reruns with filesystem access passed. Initial assembled test failures exposed
missing optional queue setup, acknowledgement/result and empty-queue response fixture mismatches;
They were corrected without changing production schema checks or search APIs.
All original logs remain private under `work/qualified-scene-20261013`.

The local contributor, Scene pilot and refresher tasks were independently read
back as disabled on 13 October. The contributor's PAUSE marker remains, with
Medium/day and Maximum/midnight-to-6-a.m. settings saved. Its last saved status
has zero undelivered batches and was waiting for the disabled service. This
component did not restart it, use an expired lease or claim new accepted work.

Next finish the corresponding qualified Object path with trusted current Gen4,
Scene/protected authority; shared budget/local queue arbitration; and bounded
catalog/import/storage. Before actual processing, prepare a restricted active
coordinator and valid assignments with this admission policy, verify the current
device qualification, and explicitly resolve the operational stop. Native
allowances, endpoints/crons and installed tasks remain unchanged. No cloud
account read, deployment, provider/model download/test or Actions run occurred.
