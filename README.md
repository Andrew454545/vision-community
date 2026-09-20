# VISION Community

Anonymous, contribution-gated visual search. This repository is **not** an
operational public VISION corpus and does not connect Google Street View.

Each verified scene location earns 1 unit. Each verified object location earns
10 units. **Every search costs exactly 100,000 units.** New accounts start at
zero. The owner uses the same index and the same gate as everyone else.

## What works locally

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s community/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m community.measure
PYTHONDONTWRITEBYTECODE=1 python3 -m community.server --demo
# or, for ranked visual self-test (still synthetic imagery):
PYTHONDONTWRITEBYTECODE=1 python3 -m community.server --visual
```

Open `http://127.0.0.1:8765`. Create an anonymous account, save the recovery
code, and process a batch. Slow, medium, and max change concurrent workers on
the device. The server recomputes `community-visual-v1` embeddings before
credit. Ranked search reads one shared sealed index.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin check --db community/.data/demo.sqlite
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin backup --db community/.data/demo.sqlite --to /tmp/vision-community-backup.sqlite
PYTHONDONTWRITEBYTECODE=1 python3 -m community.admin restore --from-backup /tmp/vision-community-backup.sqlite --db /tmp/vision-community-restored.sqlite
```

`--demo` is the original fixture/label prototype. It must not be deployed as
the finished service. `--visual` is a loopback self-test with invented images
and ranked descriptors. Neither is a rights-cleared public corpus.

## Cost and security

Fast search, a strict credit gate, and only-R2 recurring cost cannot all be
achieved on Cloudflare's free tier. See [ARCHITECTURE.md](ARCHITECTURE.md),
[MEASUREMENTS.md](MEASUREMENTS.md), and [COST_FEASIBILITY.md](COST_FEASIBILITY.md).
No R2 bucket is created by this project.

## Invariants

- Canonical asset, capture, lane, and model have one queue row. Expired leases
  are fenced; stale, forged, duplicate, and replayed submissions do not credit.
- Publication, ledger, and search debit happen in trusted server code.
- Sealed segments are checksummed and the registry fails closed on mismatch.
- Clients never receive the full index or object-store credentials.
