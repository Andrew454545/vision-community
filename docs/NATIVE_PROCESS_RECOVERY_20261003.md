# Native process recovery: 3 October 2026

If the Python helper exited abruptly, its native indexer could remain alive after
the private-folder lock was released. A replacement helper could then overlap
with the original writer. Native commands now have a startup gate and a private
process owner. Windows uses a non-inheritable kill-on-close Job Object; POSIX
uses a new process session and a blocking parent pipe. No shell or security
setting changes are required. See [Microsoft's process ownership documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

Every invocation saves a unique `STARTED` receipt before launch and records its
supervisor after ownership is established. Normal completion or timeout updates
that receipt; forced caller exit leaves it unfinished. Native work cannot start
if ownership or the receipt cannot be established. Logs and checkpoints remain.
The hidden Windows interpreter uses its own private `python.exe` companion for
the pipe wrapper; it does not search for a global installation.

Nine bounded real-process tests cover exact arguments/environment/working
directory and logs, startup gating, ownership/receipt failure, missing binaries,
child/grandchild timeout and abrupt exit, and the actual windowless interpreter.
A separate PC-profile regression confirms that changing the helper invalidates
the admitted profile. The Windows source snapshot requires and includes it.

## Actual native evidence

The installed private **Python 3.14.7 windowless launcher** started the unchanged
pinned Windows FP32 scene engine in an isolated diagnostic folder. After eight
of sixteen locations were checkpointed and another native command was active,
the caller was force-terminated. The supervisor and native process stopped,
the folder lock became available, and the saved checkpoint stopped changing.
The original unfinished receipt remained intact.

The same index then resumed to sixteen complete locations, zero fetch/inference
errors and complete view masks. It passed the Community record/layout checker
with its actual 50,000-location shard setting. Three native saved-index searches
completed with sixteen unique hits each. Live imagery was retrieved independently;
this is recovery evidence, not a cross-run ranking comparison. This diagnostic
used eight-location checkpoint chunks and created no account, credit or upload.

Final helper SHA-256:
`019fc3c055eb680dab4bfafd4851d3a082580f1a3a115b7ca6016a6433726f7f`.
Native executable SHA-256:
`6ce8f5c9dbfeb8404da13daa71afecfd07a56f118fc61819d07c1d2330f191ba`.
Private windowless interruption receipt SHA-256:
`a536faf17902afd91384266f24fce994b968b16be8aa7c94645829bfab6e4502`.

A separate frozen sixteen-location replay of the earlier ownership helper
matched all 192 tensor hashes, packed payloads and three native query rankings
against the verified baseline. Its search omitted a required cache argument on
the first attempt; independent reconciliation passed without replacing that
failed report. A sealed study deliberately refused checkpoint reuse. Two later
diagnostic setups used the wrong shard size and were correctly rejected by the
Community checker. Those reports remain failures. The corrected normal-layout
run and final windowless run have separate successful receipts.

## Limits

These are finite local diagnostics. They do not establish accepted production
lease recovery, an OS restart, sleep/wake, overnight boundaries or weeks of
operation. Original reference/calibration material remains uncredited and private.
The new helper changes runtime identity: regenerate the source/runtime/policy
pins and rerun qualification before admitting it. Published immutable previews
and hosted images retain their recorded versions; no production gate was opened.
