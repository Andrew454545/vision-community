# Staging scene admission evidence — 2026-10-03

Production remains closed. The exploratory trial archives are unchanged and
were not uploaded as contributions. This is an operator experiment in the
confirmed Community staging database and bucket only.

## What passed

- Independently checked the final Windows executable, five app-local libraries,
  four models, Linux runtime manifest and all 46 image helper files against
  their recorded checksums and Git blobs.
- Recomputed the packed comparison on Andrew's sealed 16-location Mac sample:
  minimum cosine `0.9999926663366517`, maximum relative L2
  `0.0038298156673653686`. This is a small controlled sample.
- Completed a fresh 112-location Windows screen with zero errors in 313.995
  seconds. The independently pinned private service qualified its exact profile
  for the staging experiment.
- Activated the verifier-only bundle and restored the same durable seal after
  a real Container restart. Search remained unavailable without a contributed
  snapshot. Compute was stopped after the recovery check.
- All 13 public staging files matched source bytes and retained privacy headers.

## Engineering decision and failure

The separate decision `staging.vision-scene-fp32-20261003` reviewed three complete
1,024-location runs for an isolated one-thread experiment; it does not promote
their original exploratory reports to production approval. Its historical
canary bounds are cosine `0.99` / relative L2 `0.125`, a coarse readiness check
on changing live pixels. Every new contribution instead requires complete
native recomputation under cosine `0.99999` / relative L2 `0.005`, a small margin
over the controlled packed comparison. The measured hosted batch cap stays eight.

The first submission attempt found an empty staging queue. A second encountered
the CLI's missing D1 permission; the existing authorized Cloudflare connector
registered the small metadata-only queue. Both failed attempts are preserved.
The actual new eight-location contribution then completed local indexing but
was rejected by the independent audit. It earned **zero credits** and published
**zero locations**. Its metadata/checksum validation passes locally. Comparing
that batch with the earlier PC screen gives minimum cosine
`0.9999360032913255` / maximum relative L2 `0.011318360717324106`; these live inputs
are not frozen, so this alone cannot identify the cause or justify new bounds.

Staging's public contribution policy is now disabled. The private seal and
failure evidence remain available for diagnosis. Production resources were not
changed. Do not widen the policy merely to pass this test.

## Safeguards and next checks

The gateway reserves policy IDs beginning `staging.` for the confirmed staging
environment/bucket. Four mixed or production configurations stop before a native
call; five actual local workerd cases and the unit regression verify this.

An explicit staging operator policy may request private audit measurements:
reason, location/view counts, reference checksum and two comparison extrema.
No account details, location metadata, imagery, vectors or native stderr are
included. The option defaults off and cannot be enabled by a production policy.
It changes neither the bounds nor the approval decision. Sealed image/helper
pins must be updated before using it on the hosted service.

Explicit bundle replacement now boots the pinned runtime without first loading
the previous seal. This permits an image/helper upgrade to replace an
incompatible old policy; failed validation retains the old durable pointer and
stops candidate compute. Retrying the same seal still verifies its recovery.

Next: diagnose the rejected live comparison against controlled input evidence,
then repeat real audited contribution and exactly-once credit, seal a
contributor-only staging snapshot, and exercise hosted paid search. Wider quality,
portable Objects, parallel resource budgets and production recovery remain
separate acceptance gates.

Local validation: 385 Python tests pass (two local link-permission skips),
188 JavaScript tests pass, and 37 private-host plus five staging-isolation cases
pass in actual workerd. Hosted diagnostic deployment and final branch CI still
need their own receipts.
