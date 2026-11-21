# Saved-delivery reply validation — 5 October 2026 UTC

Source `b25b9aa0a314c0b1c620dc239d8a3ed17f0bd66d` corrects a malformed success
reply that could previously accept negative counts or
contradictory pending/rejected flags. The local journal could then mark a
delivery complete and clear its retry payload. This audit identifies a source
defect; it does not establish that the hosted service produced such a reply
or that a real contributor lost work.

The guided client now validates every submission/audit acknowledgement,
including clients without a local journal. Counts must be nonnegative safe
integers, flags must be booleans, and a supplied submission identifier must
match the requested delivery. Pending/rejected replies cannot also claim
accepted work or earned units. An accepted count cannot exceed the saved
batch's output count before the journal retires that payload.

Invalid acknowledgements preserve the exact ready/pending row and become the
fixed `invalid_submission_result` service error. Automatic processing saves its
cooldown and retries later; it does not claim local acceptance or permanently
stop merely because a reply is malformed. Explicit valid rejection still
preserves evidence and stops for review. Corrupt saved local payloads also
require review instead of being silently discarded.

## Validation

All **62 focused delivery/background/storage tests** pass in 21.194 seconds.
Five added tests cover:

- Malformed counts, flags, contradictory states and identities leave ready and
  pending SQLite rows unchanged.
- Wrong submission identity is retryable and preserves the original output.
- Guided clients without journals also reject malformed success.
- Corrupt saved JSON cannot be retired by an acceptance acknowledgement.
- Actual loopback HTTP and SQLite recovery across fresh Python workers keeps
  the account and payload after a malformed audit, makes no request before the
  saved cooldown expires, then settles once after a valid response. The fixture
  creates no new account, lease, qualification or real credit.

All **552 local Windows application tests** pass in 470.206 seconds with eight
expected platform/filesystem skips. The existing private PowerShell 7 runs
under its unchanged policy; no security setting or global installation changes.
[Application CI](https://github.com/Andrew454545/vision-community/actions/runs/37275771107)
and [calibration CI](https://github.com/Andrew454545/vision-community/actions/runs/37275771724)
pass all seven jobs at this exact source. Actual Windows passes 552 tests in
395.370 seconds with two Mac-only skips; Linux passes 552 in 51.272 seconds
with 31 platform skips. The hosted-service suite passes all 232 tests and
complete workerd checks. Actual Mac passes 41 setup, 42 sleep/background,
12 control and 13 ownership guards; only the two Windows-only ownership checks
skip. Both calibration jobs pass all 80 guards.
No real service, model, imagery or contribution is used by these fixtures.
This source change does not update an installed contributor or immutable
download. See [production acceptance](PRODUCTION_ACCEPTANCE.md).
