# Offline recovery test results

The scheduled Windows recovery test completed all 24 rounds on 8 October 2026.
Each round ran the same 80 existing checks in a different order, in a new
Python process using an immutable copy of application source `fc0b430`.

- 1,920 test executions: 1,896 passed, 24 skipped, zero failures or errors.
- The only skip in each round was the existing unprivileged symbolic-link test;
  Windows did not permit that fixture. Security settings were unchanged.
- Checks covered disposable financial restore/replay, storage pressure,
  pending submissions and recovery from lost replies over local HTTP.
- The nominal hourly schedule completed in 85,242.281 seconds elapsed,
  including waits. This was repeated finite work, not continuous processing.
- Independent readback matched every round report to the final summary and
  verified the preserved source snapshot. Logs and failure history remain private.
- The finished one-time scheduled task was removed; contributor startup settings
  and the installed application were unchanged.

This does not verify real contributions, live Cloudflare restore, physical
restart/sleep recovery, Mac behavior, thermal limits or months of operation.
It leaves those production acceptance requirements open. The separate Object
overnight diagnostic ended at its deadline after 17 of 24 successful rounds;
its incomplete result and failure report are preserved.
