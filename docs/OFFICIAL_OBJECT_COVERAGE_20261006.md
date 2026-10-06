# Official Object coverage verification (2026-10-06)

Five real repository panoramas passed Andrew's current strict native validator
and the unchanged Community importer. The exact IDs, original poses, country,
capture date and official Generation 4 evidence survived a real staging D1
import and independent API readback. They are pending metadata, not indexed
contributions, public search results, approved devices or earned credits.

## Source and native Windows check

Private VISION source `3de01128e7f23f9a1d9c63f6c00f28a3e7ce41dd`
([PR #14](https://github.com/Andrew454545/VISION/pull/14)) requires the requested
panorama's own metadata. A newer Generation 4 panorama's timeline cannot certify
an older camera. The v7 cache policy excludes old v6 entries.

The local build uses exact committed Git blobs, the unchanged Cargo lock and
the committed country authorities. Compiler packages are checksum-pinned from
the publishers: Rust/Cargo 1.96.0, x86_64 Windows GNU, GCC 14.2, MinGW-w64 12.0.0,
MSVCRT and Binutils 2.44. Everything stays in a private workspace; no global
installation, registry, persistent PATH or security setting changes.

All eleven actual native tests pass without skips, including the redirected
historical-camera regression, strict classification, cache/retry/accounting,
failed-window recovery, Unicode/extended paths and preserving existing output.
The locked optimized build passes. Its measured executable SHA-256 is
`12457f707865f1fd3464311b60488f5e4cff1a9cd0e7397bfe841ccb2602eb89`
(11,685,712 bytes). This is a metadata-validator build identity, not a qualified
Scene/Object model runtime or a public download.

The first private extraction hit Windows' ordinary path-length limit; explicit
extended paths resolved it without settings changes. The first isolated native
test omitted two committed country authority files; both are restored and
pinned. The next actual run exposed three Windows publication failures: Unix
directory flushing returned access denied. Completed files now flush before a
same-volume `MoveFileExW(MOVEFILE_WRITE_THROUGH)` directory move without
replacement/copy/reboot flags. Both empty and occupied saved destinations remain
untouched. All initial failures are retained separately from the passing result.
These checks do not establish physical power-loss durability on every filesystem.

Private workflow run
[37489654544](https://github.com/Andrew454545/VISION/actions/runs/37489654544)
at the same source has Windows and Ubuntu jobs, but neither started: GitHub
reports an Actions budget block, with empty runner/step records. The earlier
workflow-context failure and correction are also preserved. The local Windows
result is actual execution; it is not a passing private CI or new Mac build.

## Bounded real metadata and staging

Four evenly spaced rows from the existing 1,024-location fixture and one private
native Object smoke row supplied five original panorama IDs and poses. Their
fixture camera labels were not used as coverage authority. Country codes were
initially empty; the validator required Google's code to match the committed
country tag. One real metadata request, five cache misses, no retries and no
rejections produced five independently classified official Generation 4 records.
No imagery or model inference was retrieved/run for this check.

Input, country authority, actual native execution, manifest and artifacts are
pinned privately. The importer prepared all eight statements from the fresh
schema-2 v7 manifest, one-day cache limit and five-row shard.

Actual local workerd/D1 verified the unchanged bridge. A separate temporary,
authenticated remote D1 binding then addressed only the confirmed Community
staging account/database. A current Time Travel rollback point was retained.
Preflight found no conflicting matching rows. The complete list was applied with
one supported D1 batch, never split statements or an overwrite.

A deliberately failing last guard rolled the entire staging batch back. Success
and exact retry preserved all five IDs/poses/receipts. Independent Cloudflare API
readback from the primary verified them, with no leftover guard. Accounts, total
banked units, leases, publications, ledger and searches remained unchanged. No R2
binding, public operator endpoint or permanent deployment was added.

The private batch SHA-256 is
`703f74abb60818bf8c522e2523c93b9b68d7ab42b67656327bf9f5183ec59bbf`;
its coverage receipt SHA-256 is
`52dd4d9a3fbcd908518691fee551d2973f7fc259c98570eb7477c1d1e7ae2f3e`.
Pose-bearing files stay outside Git and public artifacts.

## Community application checks

Application head `7ba40c1d64cd547e3d5eb2d4fcd85d2e304b7a3a`,
proposed main merge `e4f337f193f3899a90de51ed57df3450e55213e1`,
passes all twelve executed public CI jobs:
[application/service](https://github.com/Andrew454545/vision-community/actions/runs/37482734622),
[packages](https://github.com/Andrew454545/vision-community/actions/runs/37482734485),
[calibration](https://github.com/Andrew454545/vision-community/actions/runs/37482734531),
[Mac lifecycle](https://github.com/Andrew454545/vision-community/actions/runs/37482734679),
and [reference guards](https://github.com/Andrew454545/vision-community/actions/runs/37482734430).
Windows runs 640 checks with two platform skips; Linux 640 with 31. Service
runs 259 without skips, plus actual workerd/D1 transactions. Dedicated reference
guards run 24 with cryptography present. Ordinary updates intentionally skip
native Mac model inference. Skips do not establish the skipped behavior.

Staging version `e1cb51ab-1570-4740-a2ab-3ea44569b4b8` preserves all sixteen
bindings. After import, thirteen website assets/privacy headers, no-store closed
Object capabilities and anonymous qualification refusal pass independent
readback. Object readiness remains false. No installed contributor was polled,
restarted or changed, and none of the eighteen full Scene trials was repeated.

## Still required

Trusted Object device qualification/provider/native audits, coherent qualified
Mac/Windows runtime distribution and actual accepted indexing/delivery/search
remain separate. Wider identical-input model comparisons, justified Scene bounds,
sustained resources, physical restart/endurance and beginner acceptance, signing
resources and hosted recovery/capacity remain open. The five pending metadata rows
do not establish any of those release requirements.
