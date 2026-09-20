# Cloudflare free-tier shell

This Worker serves the anonymous UI and an honest status endpoint.
It does **not** host the credit ledger, sealed index, or ranked search.

Do not add `r2_buckets` or create a bucket from here. Do not enable Workers Paid.

```sh
npx wrangler deploy
```
