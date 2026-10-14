# Development constraints

## First-release priority: Scenes only

Read [Scenes first](docs/SCENES_FIRST_RELEASE.md) before choosing new work. The user
requested a Scene-processing/online-Scene-search first release to get contributors
started sooner; Objects follow later. Prioritize actual Scene activation, platform
qualification/install, earned-credit search, recovery, cost and unattended-operation
gaps. Object development and its launch gates are deferred, not erased or approved.
Keep Object capability/routes closed. This changes product priority, not the
operational spending stop, signing requirements or private-transfer authority.

## Latest product decision (13 October 2026)

Read [the approved hybrid direction](docs/HYBRID_LAUNCH_DECISION_20261013.md)
before the older cost options. The user explicitly chose reference-sample device
qualification with lighter routine upload checks, online banked-credit search,
$10/month processing **plus R2**, and local overflow. Implement this as a distinct
admission policy; do not misrepresent qualified-device uploads as independently
recomputed. Preserve Gen4/protected authority, numerical qualification, unique
assignments and once-only credit. The old Free-only recommendation is superseded.
Source implementation is authorized. The operational stop remains while the
concrete hybrid activation path is prepared; Actions use follows the separate
13 October essential-only policy below.

## Current owner cost hold (12 October 2026)

Read [the recorded stop](docs/COST_STOP_20261012.md) and
[the cost architecture](docs/COST_OPTIONS_20261012.md) first.
Andrew paused all Community cloud compute and requested an architecture
recommendation before implementation. Do not restart local indexing, the Scene
pilot/refresher, cloud services, provider tests or deployments. Do not
make Cloudflare account reads or account-wide changes. Offline analysis and
source maintenance preserving the hold are allowed. Keep native allowances at
zero, workers.dev/previews off and crons empty; preserve data, credentials and
all evidence. Ordinary requests to continue do not lift this specific hold.
The three recorded Windows tasks remain disabled; this supersedes the general
instruction below to keep the contributor recovery task enabled.

The laptop user explicitly approved implementing the recommended cheaper design
**locally** on 12 October, after being asked about that specific scope. Offline
architecture implementation and meaningful local synthetic verification may
proceed. This does not authorize cloud access, resource/account/data migration,
deployment, paid tests or restarting indexing/pilots. Preserve the
operational hold, signing requirements and authentic release gates. Start from
[queued search delivery](docs/QUEUED_SEARCH_DELIVERY.md); do not mistake its offline
accounting evidence for real inference qualification or Free-plan capacity.

## GitHub Actions: essential use only (13 October 2026)

The user added Actions allowance but explicitly required the absolute minimum
usage: "Not unless you absolutely have to use it." This supersedes the earlier
blanket Actions spending hold only for unavoidable work.

- Default to local checks. Do not dispatch/rerun workflows or add native-trigger
  labels for routine development, documentation, repeated audits or confirmation
  of already-passing checks.
- Use Actions only for an essential release/platform check that cannot reasonably
  run with available local devices/runtimes. Record why it is necessary, select
  the smallest existing workflow/job and finite timeout, preserve its result,
  and reuse that evidence. Do not run a broad matrix merely because allowance
  is available. Rerun only after fixing a relevant failure or changing its inputs.
- Include `[skip ci]` in development commit messages before pushing. The current
  workflows use push/pull_request events; check for other triggers before pushing
  if workflows change. See [GitHub's skip rules](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).
- Test relevant changes locally with existing private runtimes. Do not install
  tools globally. Record actual platform, skips and limits. Local Windows
  checks cannot replace Mac execution, signing or production acceptance.
- Preserve required checks and release gates. Skipped Actions checks can remain
  pending; do not fabricate successful statuses or weaken branch protections.
- This exception does not lift the Cloudflare operational stop, authorize new
  paid cloud services or live provider tests, or permit unrelated account changes.

Windows local checks must not open console windows on the user's desktop. Use
windowless subprocesses, or a hidden test console when fixtures need inherited
console handles, and capture output in private logs. Set per-run `TEMP`, `TMP`
and `TMPDIR` under the workspace; the restricted host temporary folder may deny
test file creation. Retire terminal finite test tasks only after verifying their
exact action, current-user ownership and preserved result; keep the contributor's
recovery task enabled. Do not close unrelated terminals.

Continue from `docs/PRODUCTION_ACCEPTANCE.md`. Keep failure evidence and existing
work. Never access the `geonections-images` R2 bucket. Use only confirmed
VISION Community resources. Keep local indexing independent of Codex.
