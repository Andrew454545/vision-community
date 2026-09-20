# Measured budget (2026-09-19)

No R2 bucket was created. No VISION index or Google imagery was uploaded.
These numbers were produced by `python3 -m community.measure` on a 14-core
local machine.

## community-visual-v1

| Locations | Index bytes | Embed s | Search s | RSS MiB |
| ---: | ---: | ---: | ---: | ---: |
| 200 | 19,200 | 0.26 | 0.004 | 14 |
| 2,000 | 192,000 | 2.44 | 0.033 | 16 |
| 10,000 | 960,000 | 12.01 | 0.171 | 25 |

Scene record: **96 bytes**. Object record: **128 bytes**. Raw six-face test
payload: 4,608 bytes and is not stored. VISION sealed scene embeddings are
**3,080 bytes/location** (read from a local segment manifest, not copied).

Linear search at 10,000 locations already exceeds Workers Free's 10 ms CPU
budget (33 ms at 2,000). Extrapolating linearly, a 20,955,444-location scan
would be on the order of **six minutes** and need RAM well above 128 MB even
for the compact Community descriptor. Fast search therefore needs a dedicated
search process (and, at VISION scale, an ANN/shard plan), not Workers Free.

## Storage projections (not permission to upload)

| Artifact | Size | R2 Standard storage after 10 GB free |
| --- | ---: | ---: |
| Community visual scene index at 20.9M locations | 1.87 GiB | $0.00 |
| VISION int8 scene index at 20.9M × 3,080 B | 60.1 GiB | ~$0.75 |
| Raw imagery if 500 KiB were stored per location | ~9,992 GiB | ~$150 |
| Local sealed segment directory (measured, not uploaded) | ~20 GiB | n/a |
| Local VISION Application Support (measured, not uploaded) | ~76 GiB | n/a |

R2 Standard (official, Aug 2026): $0.015/GB-month, 10 GB-month free, Class A
$4.50/million (1M free), Class B $0.36/million (10M free), egress free.
Storing raw imagery blows past a $20 storage-only budget. A compact derived
index can sit in the R2 free tier **if and when a rights-cleared corpus and a
search host exist**. That still does not pay for search CPU.

## Cloudflare free tiers rechecked

- Workers Free: 100,000 requests/day, 10 ms CPU/request, 128 MB.
- D1 Free: 5 GB total, 5 million rows read/day, 100,000 rows written/day.
- Vectorize Free: 5 million stored dimensions (<10,000 vectors at 512-d).

## Verdict

Fast gated search and only-R2 spend cannot all be achieved. Create the R2
bucket only after the owner approves a rights-cleared source and a search host.
Do not enable a paid Cloudflare plan without that approval.
