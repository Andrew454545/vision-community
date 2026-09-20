# Architecture decision (2026-09-19)

This project cannot simultaneously provide **fast search**, a **strict credit
gate**, and **only R2 as a recurring expense**. The smallest honest tradeoff is:

1. Keep exclusive leases, verification, credits, and search *authorization* in
   trusted server code. There is no owner role, trial search, or client-side
   index.
2. Publish verified outputs as checksummed, versioned segments with atomic
   registry replacement, following VISION's sealed-segment idea (500,000-location
   capacity, SHA-256 per file, fail-closed loads).
3. Run ranked visual search on a dedicated process that holds sealed segments
   on local disk or RAM. R2, when the owner later approves a bucket, is the
   durable artifact store, not the query engine.
4. Use Cloudflare Workers Free only as a public shell. Official Workers Free
   limits (10 ms CPU/request, 128 MB, 100,000 requests/day) cannot scan a
   multi-million-location visual index. Vectorize Free stores 5 million
   dimensions (~9,765 vectors at 512-d). D1 Free (5 GB, 5 million rows read/day,
   100,000 rows written/day) can hold a small ledger, not the VISION corpus.

## Verification

Every credited `community-visual-v1` embedding is independently recomputed from
the canonical source identity. That is a true guarantee **for this extractor
only**. It is not RF-DETR, YOLOE, or OWLv2. Sampling an expensive model is not
an absolute guarantee. Full trusted recomputation of those models would erase
most volunteer compute savings and would not fit Workers Free.

## Imagery rights

Google Street View Static API policy generally prohibits prefetching, indexing,
storing, or caching imagery. This project does not import Google sources, copy
existing VISION indexes, or use owner API keys. A Wikimedia importer exists as a
rights contract only; ingest stays blocked until written evidence covers fetch,
volunteer redistribution, derived indexes, and result display, and until volume
fits the measured budget.

## What is deployed

The local Python service is the working control plane and search backend. The
Cloudflare Worker, if deployed, serves the anonymous UI and an honest
`operational: false` status. No R2 bucket is created by this work.
