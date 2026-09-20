# Cloudflare deploy

Public VISION-like prototype. D1 holds the ledger and prototype embeddings.
R2 bucket `vision-community` is bound as `INDEX` for sealed segments.

```sh
npx wrangler d1 execute vision-community --remote --file=schema.sql
npx wrangler deploy
```

The Worker seeds a small metadata catalog on first request, verifies volunteer
embeddings, and returns map-making.app JSON.
