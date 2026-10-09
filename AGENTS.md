# Development constraints

GitHub Actions spending is on hold at the user's request (8 October 2026).
Until that restriction is explicitly lifted:

- Do not dispatch or rerun Actions workflows, or add labels that trigger native trials.
- Include `[skip ci]` in development commit messages before pushing. The current
  workflows use push/pull_request events; check for other triggers before pushing
  if workflows change. See [GitHub's skip rules](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).
- Test relevant changes locally with existing private runtimes. Do not install
  tools globally. Record actual platform, skips and limits. Local Windows
  checks cannot replace Mac execution, signing or production acceptance.
- Preserve required checks and release gates. Skipped Actions checks can remain
  pending; do not fabricate successful statuses or weaken branch protections.

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
