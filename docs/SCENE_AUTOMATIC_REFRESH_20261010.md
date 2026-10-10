# Automatic Scene search refresh

The restricted staging pilot now has a windowless hourly refresher independent
of Codex. It collects accepted Scene publications, verifies their native audit
and earned credit, and prepares an immutable append. A private guarded activation
changes the native bundle and search snapshot together. New searches use that
snapshot; saved paid results keep their original result and debit.

The [dated receipt](evidence/scene-automatic-refresh-20261010.json) records **222
passing targeted checks**, actual local workerd/D1/R2 checks, deployed staging
bindings and a real ten-location search. That search charged two genuinely earned
units once; exact replay and fresh-process recovery passed. The original paid
reply remains unchanged. Primary D1 reconciles 18 earned units minus 12 spent,
leaving **six banked units**. No synthetic funding was added.

The actual scheduled refresher completed its first collection and seal with
`CURRENT_NO_CHANGE`: all ten locations already belonged to the active snapshot.
It performed no activation. **The first future real append activation still needs
an actual scheduled receipt.** Component append/restart tests pass; this baseline
is not evidence that another real batch has already been refreshed.

## Recovery and limits

- Capture is one primary-first D1 query. It excludes tokens, recovery hashes,
  queries and balances. The sealer checks actual published R2 bytes, original
  submissions, accepted policy/profile/runtime, membership and once-only credit.
- Preparation is saved before upload or activation. Upload is content-addressed,
  create-only and read back. Source membership is rechecked before activation;
  an older attempt cannot replace another operator's newer bundle. A lost reply
  recovers from the exact durable head without repeating activation, including
  when later accepted work has arrived.
- An unchanged snapshot uses no native compute. Refresh defers when fewer than
  two native operations are available or at most four starts remain. Existing
  limits stay **48 operations / 12 starts per UTC day**. Accepted work and credit
  survive deferral, although search publication may wait for allowance renewal.
- The finite current-user task shares the pilot's shutdown lock, observes its
  stop/failure/attention flags, pins its own frozen source, limits attempts and
  private storage, and stops by **17 October 06:27:14 UTC**, one hour before the
  pilot's target end. It never deploys or reopens admission. Sleep/shutdown pause
  work; sign-in recovery resumes it. No claim of computation while off is made.
- The qualified CPU1 client, native image/runtime, two-location audit limit,
  invitation, search price and pilot start pins are unchanged. This separately
  recorded backend service update finished at **10 October 08:11:20 UTC**.
  Public and Object admission remain closed.

Account deletion retains already verified anonymous contributions under the
[existing privacy contract](ACCOUNT_PRIVACY.md). Retention additionally requires
an explicit operator setting, matching irreversible deletion receipt, original
published native candidate and earned-credit claim. Revoked qualifications cannot
admit new work. Synthetic deletion-authority checks pass; no real account was
deleted for this check. Removal or changed publication history still fails the
append guard and needs a separate authorized migration.

## Operator use

`community.scene_refresh` is a private staging operator tool, not a contributor
setup step. Its pinned configuration names only the confirmed staging D1/R2 pair,
private services, qualified authority, template and current snapshot. It uses the
existing private Python/Node/Wrangler runtimes and saved Cloudflare sign-in.

```text
python -m community.scene_refresh --config settings.private.json --config-sha256 <pin> --root private-refresh
```

Serialize it with the staging shutdown controller. Preserve its prepared files,
state and failure reports across retries. A trust/pointer mismatch needs operator
review; transient transport and native-allowance failures defer safely. The
installed pilot wrapper supplies the finite schedule, source/storage bounds and
shared lock; the command alone does not install a scheduler.

The original restricted-runtime failures, immediate post-deploy 503, missing
frozen import, refused task-owner comparison and their corrections are preserved
privately. The failed first refresher task is disabled after exact action/SID
verification. Its corrected replacement completed the recorded baseline.
Equivalent Mac/Object acceptance, physical interruptions, the complete endurance
gate, trusted signing, provider recovery and rollout remain open.
