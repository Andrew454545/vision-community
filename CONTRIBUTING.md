# Contributing locations

# Windows contributors

1. Download this project as a ZIP and unzip it.
2. Double-click **Start VISION.cmd**.
3. In the VISION window, choose **Download and check files**.
4. Connect an existing account or create one, and save the account code.
5. Choose **Run the short PC check**. This checks 112 fixed locations and must
   be approved before regular work is available.
6. Choose **Start indexing**. Keep the PC awake and connected. You can pause
   safely after the current batch.

The maintainer's 1,024-location calibration runs qualify the approved runtime
profile. Contributors run only the short check. Results are quarantined until
the trusted service audit approves them; a local “complete” report is not an
approval by itself.

The starter stores its private runtime, account session, checkpoints, and
failure reports under your Windows user profile. It does not install Python
globally or require administrator access. Do not send raw imagery, account
codes, or private reports unless Andrew asks for a specific file.

## Advanced maintainers' workflow

The command-line tools remain for maintainers, Mac users, and release testing.
See [README.md](README.md), [calibration/START-HERE.md](calibration/START-HERE.md),
and [docs/REFERENCE-VERIFICATION.md](docs/REFERENCE-VERIFICATION.md). A
maintainer must install a trusted owner policy and independent verifier before
enabling a production scene queue. Numerical similarity by itself does not
publish or credit a location.
