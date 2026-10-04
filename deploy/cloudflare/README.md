# Website deployment — maintainers

Users start at [Getting started](../../README.md). They do not need Cloudflare.

`wrangler.staging.jsonc` targets the existing, confirmed Community staging
account, database and bucket. It preserves private verification, deletion
archives and hourly cleanup. Contributions and paid searches remain closed
while [release checks](../../docs/PRODUCTION_ACCEPTANCE.md) are unfinished.
The retired `wrangler.release-staging.toml` used a different resource pair and
has been removed. Do not create another staging database or import a seed queue
to update the website.

From this folder, using the project's private Node/Wrangler installation:

```sh
node tools/check-staging-config.mjs
node node_modules/wrangler/bin/wrangler.js deploy --config wrangler.staging.jsonc --dry-run
node node_modules/wrangler/bin/wrangler.js deploy --config wrangler.staging.jsonc
```

Run the repository checks before publishing. Afterward, verify the short guide,
privacy headers, resource bindings and closed `/api/capabilities`. No schema
import is needed for a website/code update. Preserve existing records and credits.

The preflight rejects a mixed resource pair, new bindings or an admission
override. Opening processing/search requires a separately measured runtime,
policy and native host rollout. The prototype `wrangler.toml` and placeholder
template are not the current staging deployment instructions.

Online searches spend banked credits only after the validated result and debit
commit together. Shared-index download routes are retired. See
[online search](ONLINE-SEARCH.md), [privacy](../../docs/ACCOUNT_PRIVACY.md) and
[staging evidence](../../docs/STAGING_SCENE_ADMISSION_20261003.md).
