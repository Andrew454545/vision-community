# Restricted Scene activation

Andrew [approved the named finite staging scope](https://github.com/Andrew454545/VISION/pull/17#issuecomment-6161800642)
and [delegated routine implementation/release decisions](https://github.com/Andrew454545/VISION/pull/17#issuecomment-6161867559).
Only the existing `vision-community-staging` gateway/D1/R2 is in that scope.
Native cloud allowances remain zero, recurring jobs stay paused, and no new
plan, resource, Actions run or public admission is authorized. Possible small
coordinator/database charges were explicitly acknowledged; this is not an
ongoing spending authorization or a provider invoice cap.

Automatic approval review initially refused the cloud reads because it required
the laptop user's direct approval rather than the owner agent's GitHub report.
The user directly approved the narrow reads on 14 October. The
[readback](evidence/scene-staging-readonly-20261014.json) confirms matching current
qualification through 18 October 05:51:41 UTC and closed staging endpoints/crons.
One SELECT read seven rows, wrote none and returned one matching record. No secret
values were read. No deployment, cohort or paused-task restart occurred.
The user subsequently approved the exact [finite private trial](FINITE_SCENE_TRIAL.md).
It ran once: two real Scenes completed and server replies accepted two locations
for two earned units. Observed reads reached 2,036 and stopped transport before
credit replay/reconciliation. [The incomplete result](evidence/finite-scene-execution-20261014.json)
and original failures are preserved. Closed staging/configuration restoration was
independently verified. The trial approval is consumed; recurring jobs stay paused.

## Completed without cloud activation

- Read-only local preflight confirms the frozen laptop's saved complete Scene
  comparison still matches the installed native binary, model assets, CPU1
  settings and processing source. Saved profile/policy match the frozen pilot.
  This hashes existing files; it performs no inference and does not establish
  current server authorization or extend an expiry. Private receipt SHA-256:
  `71bf02a6961169713d2636369e72b0b91ce62cb518895cd3b4bd404f1b2ec80e`.
- The desktop guide and Windows/Mac automatic-processing controls now offer
  Scenes for new setup. Saved Object/Both choices stay represented and unchanged;
  they cannot start setup/check/processing or resume an old Object task through
  the first-release controls. Pause/removal and explicit switching to Scenes
  remain available. Day Medium/night Maximum defaults are preserved.
- [Control evidence](evidence/scene-desktop-controls-20261014.json): eight Node
  checks execute both local web controls, and 18 Python checks include actual
  hidden Windows Forms construction with disposable files/mocked tasks.
  The first two Windows PowerShell 5.1 runs refused unsigned scripts under its
  existing execution policy. The final run used the already-installed private
  PowerShell 7 via the test suite's existing `VISION_TEST_POWERSHELL` option,
  with RemoteSigned unchanged. All failure logs are preserved privately under
  `work/scene-resume-20261014`. No policy was changed or bypass flag used. This
  does not establish signed installer/Windows PowerShell 5.1 acceptance.
- Andrew's [exact Mac-only task](https://github.com/Andrew454545/VISION/pull/17#issuecomment-6162053287)
  [passed](https://github.com/Andrew454545/VISION/pull/17#issuecomment-6162119444):
  clean `6c673e88e30aef89e90b936d0d4d5ab6f5e15925` arm64 package build/guards and
  two real macOS sleep-assertion cleanup tests, zero skips. The
  [owner-reported receipt](evidence/mac-scene-maintainer-20261014.json) preserves
  that exact revision, archive digest and limits. No GUI install, signing,
  notarization, native-model execution, cloud access or indexing occurred.
  This earlier exact-commit maintainer result is not a signed candidate or an
  assertion that later changed package inventories were executed on Mac.

## Conditional one-cohort bounds

Before starting, report these limits to the owner and laptop user and verify
current qualification, assigned work and applicable destination-specific consent:

- One exclusive Scene assignment, at most **two locations**, CPU1; one finite
  child with a **600-second** deadline. No fresh qualification or search.
- At most **32 coordinator requests**, **four R2 writes** and **512 KiB** of
  uploaded result data. Count requests and delivered bytes; no second cohort,
  retries beyond those bounds or replacement assignment after a terminal failure.
- Inspect returned coordinator/database operation metadata. Stop further work
  after unexpected failures or cumulative usage exceeding **2,000 rows read**
  or **128 rows written**. These observed stop thresholds cannot reverse a
  charge already incurred and are not provider-enforced billing limits.
- Preserve old accepted work, balances, paid replies, private files, original
  pilot pins and pause markers. Restore the prior closed staging configuration
  and verify shutdown after the finite attempt, including failed/ambiguous cases.

The first user answer covered **reads only**; the separate explicit answer covered
the one finite trial now recorded above. Neither permits new account creation,
a restart of the old pilot, changes to Andrew's computer or another hosted attempt.
Continue local metadata/read-cost work before preparing a separately bounded next
activation. Missing/expired server qualification still stops that path; do not
silently renew it from the local numerical result.

Signing enrollment, trusted clean-device installation, current provider recovery,
measured execution costs, earned-credit hybrid search and new Scene endurance
remain separate launch requirements. Continue from [Scenes first](SCENES_FIRST_RELEASE.md).
