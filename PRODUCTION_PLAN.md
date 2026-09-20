# VISION Community: production design

The running code now includes a rights-aware importer, exclusive leases,
independent `community-visual-v1` verification, checksummed sealed segments,
ranked visual search, recovery codes, and backup/restore. That stack is a
**local** service. It is not a public Street View index and does not claim
VISION Mac-app ranking parity. Cloudflare Workers Free is only a public shell.
R2 is not created until the owner approves a rights-cleared corpus and a
search host. See [ARCHITECTURE.md](ARCHITECTURE.md) and
[MEASUREMENTS.md](MEASUREMENTS.md).

## Updated owner constraints (2026-09-19)

The site is a separate project. Public users pay nothing and supply no Google
API keys; the owner also supplies no API key or paid inference service. Search
requires exactly 100,000 verified scene locations or 10,000 verified object
locations per search, with zero initial searches. The intended recurring bill
is only R2 storage, using free tiers until a measured need for paid storage.
The architecture below is a candidate, not a cost promise: a trusted, fast
search service and strong verification may need paid compute beyond R2. Do not
publish a claim of zero extra cost until the full workload is measured and
shown to fit an available free tier.

## Recommended shape

1. A rights-approved importer assigns each imagery item a stable canonical
   identity: source asset ID, capture/version, task lane, and model version.
   Catalog aliases map to that identity before work enters the queue. The
   database uniqueness constraint is the final duplicate guard.
2. A small application server owns accounts, exclusive work leases, verification
   records, the credit ledger, and search authorization. Keep that state in one
   transactional database. Start with managed Postgres if deploying multiple
   app instances, or SQLite on one server with backups for an initial small
   release. Do not use object storage as the work queue or credit ledger.
3. Volunteers receive a bounded batch and run a versioned scene or object
   worker. Slow, medium, and max set the worker's concurrent jobs and memory
   budget. They never change the number of credits earned per valid item.
4. The server checks assignment, output structure, model version, duplicate
   content, and imagery rights. Hold credits until verification is complete.
   Publish verified outputs as immutable segments with a signed manifest.
5. Put those immutable segments in R2 or another low-egress object store. The
   active search service keeps a local indexed copy on fast disk and applies
   new verified segments incrementally. R2 is the durable artifact store, not
   the query engine. An owner account and every other account query the same
   published index through one server endpoint.
6. The search endpoint checks and deducts 100,000 units in the same database
   transaction that records an idempotent search request. Verified scene work
   earns one unit per location; verified object work earns ten. Query execution
   receives only the authorized request. Server keys and the complete index
   never go to the browser.

## Verification boundary

The current synthetic hash is intentionally forgeable. A hash supplied by a
volunteer does not prove that a model was run. Structural validation, content
checks, duplicate detection, and random server recomputation lower abuse but
cannot prove every volunteer result correct. If every credited result must be
correct, the server has to recompute or otherwise independently verify every
result with a trusted worker; that erases most of the compute savings from
volunteers. Treat the verification standard as a product and cost decision,
not a claim that client code can enforce it.

Exclusive leases prevent two honest clients from being assigned the same
unexpired item. A malicious client can retain input it received or do work
outside the protocol. Keep batches small, expire leases, rate limit claims,
and check a canonical server-side identity again at publication.

## Privacy and public launch gates

- Use neutral branding and a privacy-protected domain registration. No personal
  names, private MMA profile, local filesystem paths, or owner account IDs go
  into the public UI, API responses, logs, source maps, or published artifacts.
- Anonymous random account credentials avoid asking for names or email. A
  hosting provider may still see IP addresses; turn off analytics and minimize
  and expire access logs. Protect or avoid location-sensitive search history.
- Obtain written rights for public fetching, processing, storage of derived
  indexes, redistribution to volunteer workers, and display of search results
  before connecting any real image source. Current Google paths are excluded.
- Port and verify the existing scene/object workers and ranked search to a
  deployable runtime, then compare outputs and ranking to the Mac app.
- Add abuse limits, backups and restore tests, TLS, monitoring, key rotation,
  and a data deletion policy before exposing the service publicly.

The work pool is finite. Once all useful locations are indexed, new users
cannot earn searches from those same locations without wasting work. Before
launch, decide how searches remain available as the backlog shrinks (for
example, new rights-approved sources, new model versions that produce genuinely
new index entries, or a separate paid/free allowance).
