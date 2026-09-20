# Measured budget (2026-09-19)

Imagery is not stored. These numbers are for embeddings plus panorama metadata.

## community-visual-v1 (measured)

| Locations | Index bytes | Embed s | Search s | RSS MiB |
| ---: | ---: | ---: | ---: | ---: |
| 200 | 19,200 | 0.24 | 0.017 | 15 |
| 2,000 | 192,000 | 2.54 | 0.047 | 18 |
| 10,000 | 960,000 | 12.04 | 0.186 | 30 |

Scene embedding: **96 bytes**. Object embedding: **128 bytes**. Sealed pose
record: **176 bytes**. Ephemeral six-face working set: 4,608 bytes, discarded.

Linear search already misses Workers Free's 10 ms budget at 2,000 locations.
At 20.96M locations that scan is minutes; at 200M it needs a dedicated host
and an ANN/shard plan.

## Storage (no imagery)

| Artifact | Size | R2 Standard after 10 GB free |
| --- | ---: | ---: |
| Community index + metadata at 20.96M | ~5.3 GiB | $0.00 |
| Community index + metadata at 200M | ~51 GiB | ~$0.61 |
| VISION-scale 3,080-byte embeddings at 20.96M | ~60 GiB | ~$0.75 |
| VISION-scale embeddings + metadata at 200M | ~607 GiB | ~$8.95 |
| Raw imagery if it were stored (500 KiB × 200M) | ~95 TiB | thousands / month |
| Local sealed segment dir today (measured, not uploaded) | ~20 GiB | n/a |

R2 Standard: $0.015/GB-month, 10 GB free. A 200M **index-only** corpus fits a
$20 storage-only budget. Search CPU does not.

## Verdict

Index-only R2 spend at 200M is feasible. Fast gated search still requires a
machine that can hold the sealed segments. Workers Free cannot.
