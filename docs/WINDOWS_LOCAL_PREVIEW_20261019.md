# Windows local preview checks, 19 October 2026

The published `local-vision-app-preview-20261017` Windows ZIP now has actual
Windows execution evidence for its two offline self-checks. Its SHA-256 matches
GitHub and the release receipts; all 116 sealed project files match the inventory.
Both the launcher package check and desktop host connection-boundary check exited
successfully in hidden owned processes. No visible WebView window, file panel,
installation, model setup, qualification or imagery request ran. This supplements
Andrew's earlier Mac compilation evidence without relabelling it as Windows use.

Two Windows source fixes accompany this evidence. The native-window builder now
selects the existing Windows Framework compiler before reading Mac cross-compiler
settings, and keeps compiler execution hidden. The original missing-variable
failure was reproduced and retained. Building with those Mac variables absent and
then executing the resulting host's offline self-check both passed.

The launcher now retains bounded private supervisor stdout/stderr and a distinct
exit receipt, including failures before a local window exists. Each stream saves
at most 64 KiB and continues draining excess output. It records truncation and
write/read failures, finishes the receipt before disposal, and gives honest copy
if the receipt cannot be saved. New-start/reopen clicks cannot replace an exited
child before its completion timer has reaped it. Existing worker logs and their
retention rules are unchanged. Private output can contain paths and must not be
posted to public issues or included in public evidence.

Six focused C# fixture checks passed using hidden owned Windows children. They
cover startup/nonzero exit, normal exit, large dual-stream output, missing
executable, receipt refusal and completion/reopen timing. The oversized case
drained 393,216 bytes per stream while saving 65,536. These are real process and
Windows Forms construction checks with synthetic children, not actual user
processing or an interactive installation.

The interrupted 15 October edits are preserved separately; the fix was adapted
to current `cb0bd1b`, keeping Andrew's supervisor, readiness, library and native
window paths. No processing mathematics, models, qualifications, assignments,
cloud configuration, old tasks or provider guards changed. The published preview
ZIP has not been replaced by these source changes.

[Machine-readable evidence](evidence/windows-local-preview-20261019.json) records
exact pins and limits. Reuse these checks. Remaining first-use evidence concerns
interactive Windows setup/window/file panels, the specifically authorized fixed
input qualification, and ultimately a separately permitted tiny live queue and
private return. The Google hold remains; no live probe is authorized by this work.

A clean local Windows kit was then built from `77fbedee28ae100b84e6949a7ed76d0b0ad3ec2f`
using the already verified release native files, SDK and readiness inputs. Its
compiled launcher self-check passed and all 125 ZIP members matched the staged
kit. SHA-256: `914f551c42a860158759b04273d36005d15cbe9429c65d3be2f2001cc6fd5da4`
(23,743,246 bytes). This unsigned local kit is not a replacement published release
and includes no new inference or participant-acceptance claim.
