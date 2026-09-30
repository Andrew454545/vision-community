# Cloudflare deploy

The checked-in `wrangler.toml` is a safe prototype configuration. It deliberately
does not bind a scene verifier, so the Worker reports scene contributions as
unavailable and cannot publish contributor scene output.

Use the staging template before enabling any contributor traffic:

1. Copy `wrangler.staging.toml.example` to `wrangler.staging.toml` and fill in a
   separate D1 database, R2 bucket, private `SCENE_VERIFIER` service binding,
   unique rate-limit namespace, and reviewed `SCENE_POLICY_ID`.
   The private verifier implementation and its separate policy bucket are in
   `scene-verifier/`; deploy and test it before binding it here.
2. Apply `schema.sql` to a new staging database. Existing databases should
   apply `migrations/0002_scene_pipeline.sql` and
   `migrations/0003_object_coverage.sql`; if the lease column already exists,
   run the table/index statements from migration 0002 without repeating the
   `ALTER`.
3. Deploy with `npx wrangler deploy --config wrangler.staging.toml`.
4. Check `/api/capabilities`: scene contributions must show `ready: true`, the
   expected policy ID, and `deviceQualificationRequired: true`.
5. Run the 112-location qualification and one rejected plus one approved audit
   in staging. Confirm rejected work never appears in `published_index` or the
   ledger, and replaying an approved audit earns zero additional units.

The staging template enables Cloudflare's native 120-request-per-minute
per-account/per-route limiter. It is an abuse control only; D1 transactions
remain authoritative for leases, credits, and replay protection. If the
limiter binding is absent, the Worker still runs for local prototype use, but
that configuration is not suitable for public contributor traffic.

The verifier service must authenticate the operator policy and Andrew’s reviewed
reference set. Never accept approval decisions from the browser, expose the
verifier as a public URL, or point staging at the production bucket.

For the prototype ledger and catalog only:

```sh
npx wrangler d1 execute vision-community --remote --file=schema.sql
npx wrangler deploy
```

The Worker seeds a small metadata catalog on first request, verifies volunteer
embeddings, and returns map-making.app JSON.
