# Contributing locations

**Preview: processing and online search are not open yet.**

## Windows contributors

1. [Download the Windows preview](https://github.com/Andrew454545/vision-community/releases/download/windows-starter-preview-20261004/VISION-Community-Windows.zip) and choose **Extract All**.
2. Double-click **Start VISION.cmd**.
3. If asked, type **Y** and press **Enter** in the small starter window.
   In the VISION page, choose **Set up this PC**.
4. Connect an existing account or create one, and save the account code.
5. Choose **Run the PC check**. This checks 112 fixed locations and must
   be approved before regular work is available.
6. Choose **Start helping**. Keep the PC awake and connected. You can pause
   safely after the current batch.

For automatic day/night processing, close VISION and open **Background VISION.cmd**.
Use the same saved account code. [Short automatic-processing guide](START-HERE.md#automatic-processing).

The maintainer's 1,024-location calibration runs qualify the approved runtime
profile. Contributors run only the short check. Results are quarantined until
the trusted service audit approves them; a local “complete” report is not an
approval by itself.

The starter stores its private runtime, checkpoints and failure reports on this
PC. Automatic processing also saves your private account code locally so it can
reconnect after a restart. It does not install Python
globally or require administrator access. Do not send raw imagery, account
codes, or private reports unless Andrew asks for a specific file.

## Advanced maintainers' workflow

The command-line tools remain for maintainers, Mac users, and release testing.
See [the development guide](docs/DEVELOPER_GUIDE.md), [calibration/START-HERE.md](calibration/START-HERE.md),
and [docs/REFERENCE-VERIFICATION.md](docs/REFERENCE-VERIFICATION.md). A
maintainer must install a trusted owner policy and independent verifier before
enabling a production scene queue. Numerical similarity by itself does not
publish or credit a location.
