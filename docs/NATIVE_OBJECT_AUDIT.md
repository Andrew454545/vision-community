# Native Object auditing

`community.native_object_verifier` independently reruns the CPU Object program
for a small quarantined batch. It is an operator component, not a download or
an instruction for volunteers. Hosted Object admission remains closed.

The component requires independently pinned operator policy, runtime and
assignment files. Never generate those pins from an uploader's claimed policy
or accept an uploader's coverage labels as trusted assignment data.

## What an audit checks

1. Verify every runtime/model/library and adapter source checksum. Model
   manifests must name the pinned local files; external paths are refused.
2. Bind the exact source TSV to the trusted assignment: location IDs, poses,
   country, road flags and `official-gen4-historical-v2-exact-pano` evidence.
3. Require the operator's protected quality authority and implementation
   identity. Frozen diagnostic indexes cannot become contributions.
4. Check the native runtime contract, rerun all three Object model lanes with
   inline blur filtering, then fully verify the fresh native index.
5. Compare every Common, Hot, semantic and quality record, fully verify again,
   and recheck the original inputs, runtime and protected database fingerprints.

Both operating systems use an explicit CPU reference with one shared inference
thread. Native children inherit only necessary OS settings and private working
paths. They run under the existing descendant ownership helper. Timeout,
interruption, changed inputs, unavailable models and incomplete verification
leave a failed report with a pending decision; they cannot approve work.

Reports and native logs stay in a fresh private output directory. Existing
results cannot be overwritten, and output cannot overlap an input directory.
The decision report omits account codes, panorama IDs, coordinates, country
names, machine paths and raw model values. Individual native logs may contain
private paths and must not be posted publicly. Every native invocation has a
durable start/exit receipt. Completed reports bind the policy, runtime profile,
assignment, source and both index manifests by SHA-256. The time limit is shared
across native commands;
runtime/model hashing is also checked before the decision.

## Deliberate limits

- At most **four locations and 900 seconds** per audit. Operators can choose
  smaller limits. The earlier 16-location Windows timeout remains a failure.
- Missing/extra detections, selected view/support changes, quality mask changes,
  semantic face changes and different PQ codes are always refused.
- Numerical tolerances must be explicit, finite and within conservative adapter
  ceilings. Those ceilings are validation limits, **not production tolerances**.
  No default approval bounds or admitted runtime profiles are supplied.
- Live retrieval does not prove identical pixels. Reports label this limitation;
  the comparator does not turn image variation into an exception to the bounds.
- This adapter supports the existing sealed protected-database contract and
  the no-tunnel-evidence policy. Darkness is kept. External tunnel evidence
  requires a separate pinned transport and remains unsupported here.
- There is no account, credit, publication, deployment or device-qualification
  operation. `serverAuthorization` and `productionQualified` remain false, even
  when an operator audit decision is `approved`.

## Operator contract

The independently pinned policy contains:

- `version: 1`, `scope: "trusted-native-object-audit"`, `policyId`;
- `environment` and the exact confirmed Community `resource` pair;
- `runtimeProfileSha256` from `object_canary.runtime_profile`, `sourceFiles`
  from `native_scene_verifier.source_pins`, and explicit admitted `profiles`;
- `qualityImplementationIdentity`, independently pinned `protectedAuthority`
  (`path`, `bytes`, `sha256`), `maxLocations`, `timeoutSeconds`;
- `auditThresholds.lanes` with all six fields in `LANE_LIMITS`, and
  `auditThresholds.semantic` with all three fields in `SEMANTIC_LIMITS`.

The assignment contains `version: 1`, `scope: "trusted-object-assignment"`,
`policyId`, matching `resource`, admitted `profileId`, `leaseId`, exact
`sourceSha256` and `records`. Each record includes the complete assigned TSV
fields, `locationId`, `coverageValidator` and `coverageEvidenceSha256`.
The authority must come from the operator's real sealed protected import;
do not construct a fake MMA database to get past the guard.

Run from the project folder with the private runtime:

```text
python -m community.native_object_verifier --binary <program> --models <models> --policy <policy.json> --policy-sha256 <trusted-pin> --assignment <assignment.json> --assignment-sha256 <trusted-pin> --source <locations.tsv> --candidate <quarantined-index> --candidate-sha256 <trusted-manifest-pin> --out <new-private-folder>
```

A complete comparison returns exit code 0 for either `approved` or `rejected`;
the caller must inspect the decision. Setup or execution failure returns 1.
Failure before safe output creation is reported to stdout; retain that output.
An interrupted process leaves the last durable incomplete receipt.

Before publication, the hosted coordinator must still validate the current
qualification, lease/account ownership, official coverage, immutable complete
candidate binding, privacy fences and once-only credit transaction. An audit
receipt alone is insufficient authority to publish or pay.

## Validation — 9 October 2026

Synthetic tests exercise native rerun requirements, both full verifications,
small numerical differences, PQ changes, diagnostic rejection, assignment and
late input tampering, timeout/interrupt preservation, input/output separation,
model path redirection, private child environments and resource isolation.
They do not execute real models or certify coverage.

The full local Windows application regression completes **745 tests**, with
**eight existing platform/permission skips** and no failures or errors. This
includes all 21 synthetic auditor tests. The earlier script-host selection
failure remains preserved; the final run uses the existing private PowerShell
with its unchanged policy. The later schedule correction passes **87 focused
background, control, storage-pressure, HTTP recovery and startup checks**, with
one existing file-link permission skip. The runs overlap; do not add their counts.
The results are recorded in
[the evidence summary](evidence/native-object-audit-20261009.json).

An actual Windows CPU `runtime-info` call independently checked the existing
native executable and eleven model files with a private owned process. Its
runtime and quality implementation identities match the prior cross-platform
evidence. No model inference, imagery retrieval, account, publication or credit
was created. The first attempt exposed an unnecessary DirectML requirement;
its failed report remains preserved. The corrected checker requires app-local
C++ dependencies and pins every adjacent DLL, including DirectML if present.

The unattended Object command now defaults to one location per batch at every
pace, matching the guided application. It continues through successive batches;
explicit operator counts remain supported. This improves recovery boundaries
without claiming an approved parallel runtime or guaranteed throughput.
