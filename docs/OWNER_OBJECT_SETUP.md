# Private owner Object runner

**Implemented offline, inactive. Do not run against real credentials, services or
models during the [cost hold](COST_STOP_20261012.md).** This is owner setup, not a
contributor instruction. No cloud resource, key or activation file was created.

The configured runner joins the [saved Object auditor and outbound delivery](OWNER_OBJECT_DELIVERY.md).
It uses existing private runtimes and independently approved policy/assignment
files. It starts no incoming server and installs nothing globally.

## Future approved setup

1. Prepare one private configuration outside the checkout, delivery state and
   native spool. Independently review its SHA-256. Its scope is
   `vision-owner-object-audit-service-v1`, version 1.
2. Use `community.owner_object_credential_provision` with `--config` and
   `--config-sha256`. It asks for the Object audit key twice with input hidden.
   Keys in arguments, environment, files or redirected input are not supported.
3. After explicit operational approval, the runner additionally requires
   `OBJECT-ACTIVATE.private.json` in its private delivery state, bound to this
   exact configuration SHA, origin and environment. No command creates it.
   The search runner's activation does not activate Object verification.
4. Invoke `community.owner_object_service` with the same configuration/pin and
   `--once` for one supervised step. Omitting `--once` runs the interruptible,
   durably paced supervisor. A separate approved OS startup registration is still
   needed for login/restart recovery; none is installed here.

Use the approved private Python runtime for these modules. The configuration has
exact top-level fields `version`, `scope`, `origin`, `environment`, `state`,
`binding` and `native`; secrets are forbidden. The optional `retirement` field
may only be `true`; omit it to leave [published-job cleanup](OWNER_OBJECT_RETIREMENT.md)
off. Adding it changes the configuration SHA and requires independent review
and a matching explicit activation after operational approval. `binding` is the independently
approved Object settlement policy/runtime/quality/protection/resource binding.
`native` has absolute `binary`, `models`, `policy`, `registry` and `spool` paths,
plus `policySha256` and `registrySha256`. The policy pin must match the binding.
Only confirmed Community resource pairs are accepted. Delivery state and spool
must be distinct private directories outside source and all operator input roots.

Configuration and activation checks precede every connection/native action.
Native inputs are opened lazily: committed reply recovery works even if the
native policy/spool is unavailable. New verification still requires the real
auditor's exact source/runtime/model/quality/protection and registry guards.
Owned spool handles close before the runner releases its service lock.

## Credentials and stopping

Windows uses one current-user generic credential, local persistence and the
dedicated Object account/target. Mac uses the existing login Keychain through
the Security framework, with normal OS consent. Passwords travel in memory;
there is no shell command containing a key, Keychain unlock or ACL change.
Vault API evidence is synthetic; real Mac execution and real vault consent
remain unverified.

Setup preserves an existing different key. Deliberate rotation additionally
requires `--replace-sha256` with the independently known old-key SHA-256. Denied
or ambiguous readback preserves the possibly successful write for recovery.
Setup and the runner share `service.lock`; stop the runner before rotation.
No key enumeration, deletion or automatic rollback occurs. See the existing
[credential limits](OWNER_CREDENTIAL_SETUP.md), including OS edits outside this
application's lock and the limits of clearing password memory.

`PAUSE` or `STOP` in delivery state, or either marker in the native spool, prevents
new invocation from connecting or loading native inputs. Markers and saved work
are never cleared by setup/startup. Offline computers cannot process; persistent
jobs and exact outbox replay recover after an approved restart. Authentication
or protocol faults require explicit repair; do not repeatedly recreate keys or
resubmit old jobs. Native failures never retry automatically.

[Windows synthetic evidence](evidence/owner-object-setup-20261013.json) covers
configuration/activation boundaries, dedicated vault setup, the actual saved-job
constructor path and committed replay without native assets. It is not authentic
inference, actual Mac execution, real accepted contributions or launch approval.
Outbound cancellation/deletion, trusted assignment automation, bounded
metadata, approved real startup/credential checks and the
[launch gates](PRODUCTION_ACCEPTANCE.md) remain required.
