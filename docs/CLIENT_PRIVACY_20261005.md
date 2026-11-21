# Private client diagnostics and Object metadata

Source `fbb203f` corrects two confirmed privacy gaps. The review does not
establish that either exposed a real person's information.

An unexpected service `error` value could become exception/command output and
be saved verbatim in `desktop-failure.json`. Replies now retain only recognized
protocol reasons, with a fixed fallback and the original HTTP status. Shared
local reports retain fixed known desktop, service and native retry reasons;
unknown values become an exception category. Structured values also receive a
fixed public message. Neither short unknown text nor private local paths are
copied into these reports.

Recognized rejection, revoked-account and lost-lease reasons preserve their
existing decisions. An unknown 503 reply keeps the exact saved delivery and
uses persisted cooldown; fresh workers recover it without another synthetic
award. This does not change approval, account creation or credit policy.

The Object encoder previously forwarded the native manifest's absolute source
path, which can contain a person's name. Shared metadata now uses fixed source,
tunnel-evidence and protected-authority labels. It preserves TSV/binary bytes,
checksums, policies and geometry. The private native manifest is copied rather
than mutated, retaining its paths for verification and resume. Invalid source
paths and protected live VISION paths are still rejected before redaction.
Unknown extra manifest fields are not claimed to be comprehensively sanitized.
Hosted Objects remains closed pending independent native admission.

## Verification

All 72 focused client/delivery checks and 67 Object/recovery/snapshot/search
checks pass. The final exact guard group passes 27 checks in 36.092 seconds,
including real loopback HTTP, SQLite and fresh Python workers. That group is
also added to the actual Apple-silicon private-interpreter workflow; it uses no
real account, models, imagery, contribution or service write.

The complete local Windows run executed 574 tests in 438.267 seconds, with
eight expected platform/link skips and one setup error: Windows denied renaming
a temporary Mac source snapshot. The unchanged affected twelve-test suite then
passes in 7.795 seconds (one existing link-permission skip). The exact cause of
the denied rename was not established; no security setting or source/inventory
guard was changed to make it pass. Both logs are preserved. An earlier restricted
temporary-folder attempt is also retained separately from the authorized run.

All seven hosted CI jobs pass at `fbb203f`: [application checks](https://github.com/Andrew454545/vision-community/actions/runs/37287392361)
and [calibration guards](https://github.com/Andrew454545/vision-community/actions/runs/37287392252).
Windows passes the full 574-test suite in 335.252 seconds with two Mac-only
skips; Linux passes it in 88.095 seconds with 31 platform skips. The actual
Apple-silicon private interpreter passes all 27 new client guards in 38.701
seconds without skips, alongside the existing 41 setup, 42 background and 12
control checks. Separate Mac ownership checks pass 13 tests with two Windows-only
skips. Hosted-service checks pass all 232 tests, complete workerd checks and six
dry-run builds; both calibration jobs pass 80 tests. Logs and earlier failures
are retained privately.

Source fixes do not upgrade the installed contributor, change immutable starter
downloads or deploy the website. Provider logging/retention, signed packages,
guided Objects/Both and sustained operation remain separate release gates.
See [the privacy requirements](ACCOUNT_PRIVACY.md) and
[production acceptance](PRODUCTION_ACCEPTANCE.md).
