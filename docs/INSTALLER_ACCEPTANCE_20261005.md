# Installer and beginner acceptance, 5 October 2026

This records what the native Windows and Mac candidates now prove in CI, what
was fixed, and what still needs signing credentials, a genuinely clean device
or a maintainer decision. None of it grants device, runtime or production
approval. Every receipt and report keeps `productionQualified: false`.

## Actual lifecycle evidence

Both jobs build two different revisions (the second is a local empty commit
that is never pushed) and use a disposable runner account. Synthetic account,
index, checkpoint, pending-delivery and failure files must stay byte-identical.
No account, service request, model, imagery or native work is used.

| Platform | Job | Result |
| --- | --- | --- |
| Windows Server runner (`windows-latest`), per-user install | `native launcher packages / windows-lifecycle` ([run 37385117246](https://github.com/Andrew454545/vision-community/actions/runs/37385117246)) | 27 of 27 pass: installer stopped at 0/150/400 ms, install, shortcuts, removal entry, interrupted leftovers removed, keyboard (Enter) repeat install, changed file refused before consent, changed-copy removal refused, repair, update while the old version is open, old version retired after closing, active-batch removal refused without interruption, cooperative idle handover, complete removal, private files kept, startup left stopped |
| macOS 26 runner, `~/Applications` | `mac app lifecycle` ([run 37383331234](https://github.com/Andrew454545/vision-community/actions/runs/37383331234)) | 19 of 19 pass: Gatekeeper rejects the quarantined unsigned download (read-only assessment), install, open/quit without consent or processing, repeat, changed file refused, repair, update, removal, private files kept |

The Windows harness drives the real windows with UI Automation and window
messages. It refuses to run beside an existing VISION program, private folder,
task or removal entry. Checks are in `packaging/windows/Check-Lifecycle.ps1` and
`packaging/check_mac_lifecycle.py`.

## Defects fixed

- A changed Windows installation could not be repaired: setup and removal both
  refused it, and the advice ("get the current download") produced the same
  refusal. Setup now repairs it in place from the verified payload. Removal
  explains that you open the setup and choose **Install VISION** first.
- A Windows update left every earlier revision folder behind permanently.
  Closed previous versions are now retired; an open one is retried next setup.
- An interrupted Windows setup left `staging-…` folders forever; CI reproduced
  this at 150 ms. Setup now removes them under an install lock, which also
  prevents two setups racing.
- Removal left an empty Start-menu folder and program folder. It also created a
  private folder with a stop marker for people who had never opened VISION.
- The Windows launcher asked for download consent before discovering damaged
  files. It now checks first and gives actionable messages for setup already
  running, VISION still open and a conflicting shortcut. Enter activates the
  main button (Return on Mac).
- The guided page told native-app users to open `Background VISION.cmd`/
  `.command` "in the extracted folder", which the app does not have. It now
  names the app's **Automatic processing** button
  ([PR #13](https://github.com/Andrew454545/vision-community/pull/13)).

## Launch blockers found

1. **The Windows launcher cannot start on a default Windows 10/11 client.**
   `VISION.exe` runs `powershell.exe -File …\Start-Vision.ps1` without an
   execution-policy argument. Windows clients default to `Restricted`, which
   blocks every script file, signed or not. CI reproduced this: with the
   runner's CurrentUser scope set to the client default and then restored, the
   launcher's own detached script did not run (`effectiveChildPolicy:
   Restricted`, `unsignedScriptLaunchSucceeded: false`). Hosted runners use
   `Unrestricted`, so the existing package checks could not see this.
   Signing does not fix it. The chosen production path is to move bootstrap,
   controls and removal into the signed native application, while respecting
   enterprise restrictions. Do not add an execution-policy bypass or ask users
   to change security settings. The integration's policy diagnostic now uses
   inherited process-only Restricted policy and restores its environment; it
   never changes machine or user policy. This does not fix the launch path.
2. **No signing accounts.** Unsigned candidates are rejected by Gatekeeper and
   will show SmartScreen warnings. The gated workflow and account setup are in
   [signing account setup](SIGNING-ACCOUNT-SETUP.md)
   ([PR #14](https://github.com/Andrew454545/vision-community/pull/14)). It has
   never run with real credentials.
3. **Mac removal leaves automatic startup running.** The LaunchAgent runs from
   the private folder, so moving the app to Trash leaves work scheduled with no
   controls left to stop it. A Mac removal path is needed (for example, a
   **Remove VISION** button that removes the agent before the app is trashed).
4. **Guide labels at release time.** `START-HERE.md` and `START HERE.html`
   correctly describe the published preview (**Set up this PC**, **Run the PC
   check**, **PC approved**). The current page says **Set up this computer**,
   **Run the computer check** and **Computer approved**. Update the guides in
   the same change that replaces the download link.

## Requires signing credentials

- Mac: Developer ID signature, hardened runtime, notarization accepted,
  stapled ticket, `spctl` acceptance of the downloaded, quarantined app.
- Windows: valid timestamped signatures from the exact publisher on every
  script and the executable, SmartScreen reputation for that publisher.
- Re-running both lifecycle jobs against signed artifacts.

## Requires a genuinely clean device and a real person

- First run from a browser download with default security settings (Mark of
  the Web, SmartScreen, Gatekeeper, default execution policy).
- Narrator and VoiceOver reading the launcher. Windows PowerShell's managed
  UI Automation client sees the WinForms buttons as unlabelled panes. Narrator
  uses the native client and may announce them correctly; this is unverified.
- Display scaling of 150–200% and high-contrast themes on the launcher window.
- Real sign-out/restart with automatic processing enabled, then removal while
  a native batch is actually running (CI uses a cooperative fixture worker).
- A nontechnical person completing setup, account-code saving, pause/resume and
  account-code recovery with only the shipped instructions.
