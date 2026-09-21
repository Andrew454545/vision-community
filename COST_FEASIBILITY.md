# Cost and feasibility notes (2026-09-19)

Official Cloudflare prices were rechecked on this date: [R2](https://developers.cloudflare.com/r2/pricing/),
[Workers](https://developers.cloudflare.com/workers/platform/pricing/),
[Workers limits](https://developers.cloudflare.com/workers/platform/limits/),
[D1](https://developers.cloudflare.com/d1/platform/pricing/),
[Vectorize](https://developers.cloudflare.com/vectorize/platform/pricing/).
[Street View policy](https://developers.google.com/maps/documentation/streetview/policies)
still generally prohibits prefetching, indexing, storing, or caching imagery.

Measured numbers for index-only storage (no imagery) at 20.96M and 200M
locations are in [MEASUREMENTS.md](MEASUREMENTS.md). **Imagery is not stored.**
A 200M community embedding index fits a $20 R2 storage budget. Fast gated
search runs on the user's computer; Workers Free cannot do that scan.

The local VISION scene sealed-segment directory occupies about 20 GB; the full
Application Support directory occupies about 76 GB. Those measurements are not
permission to upload, and Google-derived artifacts stay out of this project.

## R2 storage

Cloudflare lists R2 Standard storage at 10 GB-month free, then $0.015 per
GB-month; reads and writes have separate operation allowances and prices.
Roughly 20 GB of storage alone would be about $0.15/month after the free 10 GB,
if the local bytes could lawfully be stored there. A $20 monthly **storage-only**
budget holds about 1.34 TB including the free tier. Real imagery, replicas,
request operations, and any compute/database service must be budgeted
separately. R2's free egress does not make these other costs zero.

Source: https://developers.cloudflare.com/r2/pricing/

## Other Cloudflare free tiers

- Workers Free: 100,000 requests/day, 10 ms CPU/request, 128 MB memory.
  This is unsuitable for assuming a direct port of a large local ranked-search
  process; measure an actual query and build an index access plan first.
  https://developers.cloudflare.com/workers/platform/pricing/
  https://developers.cloudflare.com/workers/platform/limits/
- D1 Free: 5 GB total storage, 5 million rows read/day, and 100,000 rows
  written/day. Leases, ledger entries, indexes, and imports all consume rows.
  A large corpus and active volunteers could exceed the free tier.
  https://developers.cloudflare.com/d1/platform/pricing/
- Vectorize Free: 5 million stored vector dimensions. At 512 dimensions,
  this is fewer than 10,000 vectors, far short of a multi-million-location
  scene corpus. It is not a free replacement for the current VISION indexes.
  https://developers.cloudflare.com/vectorize/platform/pricing/

## Enforcement versus owner cost

Only a trusted server can keep the full index inaccessible, issue exclusive
leases, maintain the credit ledger, and debit before each search. A browser
cannot prove it ran RF-DETR/OWLv2 or another costly model merely by uploading
an output hash. Sampling makes fraud harder but does not absolutely prove every
contribution. Full independent verification consumes trusted compute; putting
the full index or decryptable shards on the user's device allows offline search
outside the credit gate. This constraint must be resolved explicitly before
claiming the public service meets both zero non-R2 cost and a strict gate.

## What to measure next

1. Rights-approved imagery count and average bytes per source asset; whether
   assets can be streamed from their source without a user or owner API key.
2. Scene/object output bytes per location, model asset download size, and number
   of R2 reads/writes per accepted batch and search.
3. Search latency, CPU, memory, and R2 request count on representative corpus
   shards, compared with the current VISION app's ranking.
4. Verification CPU for a meaningful fraud guarantee, daily work volume, and
   queue/ledger rows or transactions.
5. Actual Cloudflare free-tier behavior and bill caps at the intended scale.

Do not activate a paid service or publish cost claims until these measurements
and the imagery rights are established.
