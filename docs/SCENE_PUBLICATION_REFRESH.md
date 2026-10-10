# Seal newly accepted Scene work

The offline operator tool `community.scene_publication_snapshot` replaces
handwritten output-approval lists with correlated native audit and credit
evidence. It does not download data, change admission, grant credit, activate
hosting or perform an automatic remote refresh.

Supply three independently pinned private exports from the same confirmed
Community environment:

- The current publication inventory used by `community.search_snapshot`.
- A consistent control-plane read containing `candidates`, `qualifications`,
  `accounts` and `ledger`. Candidates must be published, their owners undeleted,
  qualifications valid when submitted and each exact lease credited once as
  `verified_work`. Include only audits represented in the current inventory;
  never include credentials or recovery codes.
- Operator authority with scope `native-audited-community-scene-publications`,
  `inputModel`, `snapshotPolicyId` and `policies`. Each allowed policy pins its
  `policyId`, `profileIds` and native `runtimeSha256`. Production additionally
  requires explicit production authority and refuses staging policies.

All three documents require `version: 1` and the exact confirmed `resource`
pair. Volunteer checksums or claimed qualification are not these exports.
The artifact cache contains the published R2 bytes under the existing hashed
cache filenames. The tool correlates the complete original submission hash,
every selected record, pose, owner, profile and earned-credit claim before using
the existing snapshot builder and verifier. It refuses ambiguous claims,
changed bytes and history, resource mixing and overwriting an existing output.
Failure reports remain private and retain fixed reasons.

Run with the existing private Python runtime:

```text
python -m community.scene_publication_snapshot --environment staging --inventory inventory.private.json --inventory-sha256 <pin> --control control.private.json --control-sha256 <pin> --authority authority.private.json --authority-sha256 <pin> --cache artifact-cache --output new-seal
```

For an append, also pass the pinned `--previous` snapshot directory and
`--previous-sha256`. The resulting `receipt.json` contains only aggregate
measurements and input/output pins. `snapshot/` is the engine input. Private
intermediate metadata stays in the chosen output folder.

On 10 October, the tool sealed all eight real native-audited Windows Scene
publications using fresh primary D1 control readback and the pinned published
artifact. Its records and members exactly match those already used by the real
earned-credit search. The affected Windows selection passes **152 checks**,
with no skips or failures in the authorized run; the earlier restricted socket
and filesystem failures are preserved. This does not replace Mac checks.

The later [scheduled Windows pilot](WINDOWS_SCENE_WEEK_PILOT_20261010.md) appended
two genuine background contributions using fresh primary D1 exports and actual
published R2 bytes. All eight previous record bytes and ordinals were preserved;
native earned-credit search returned the complete ten-location snapshot and
exact paid recovery passed. Collection and activation were operator steps.

Scheduled collection, guarded hosted activation, deletion-driven removal and
concurrent refresh/recovery remain integration work. Before activation, recheck
current publication/deletion authority; an old audit cannot restore deleted work.
The existing append guard intentionally refuses removal or changed history.
Do not treat this offline component as completed automatic service refresh.
