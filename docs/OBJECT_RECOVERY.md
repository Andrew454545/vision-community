# Object indexing interruptions

Object processing is still awaiting runtime/model qualification and trusted
inference auditing. These recovery protections do not approve Windows/Linux
object processing, enable parallel inference or install an unattended object
worker. The existing unattended Windows worker processes Scenes only.

The Python object launcher now uses the same bounded native-process runner as
Scenes. Each native indexing, verification or search command has a two-hour
timeout. On Windows helpers run without a console window and below normal
priority. Output and error logs stay in the private run folder, beside a
`process-*.exit.json` record. Long logs are kept on disk; the launcher only reads
their last 1 MiB into memory.

An indexing process that exits unsuccessfully can be restarted from its saved
checkpoint, up to three failed attempts per run. Clean pauses may resume while
the checkpoint advances. Five consecutive clean exits without progress stop
the run, and a total launch limit prevents an oscillating checkpoint from
keeping it alive indefinitely. Missing/corrupt checkpoint data, backward progress,
launch failures and timeouts stop with evidence for review. Retrying does not
mean every error is safe to ignore.

The launcher retains each failure in a separate `object-failure-*.json`, with
its stage, error code and attempt counts. It preserves existing checkpoints,
partial indexes and native logs. It must pass both the normal and full native
index verification before returning successfully. A failure during verification
does not erase completed data or treat it as approved.

If processing stops, preserve the run folder and review the failure report.
Resolve the cause before retrying. Never edit a checkpoint or fabricate a
completed marker. The object queue command can release a failed lease; keeping
local files does not prove current ownership or authorize their later upload.
A dedicated unattended object workflow with lease/delivery recovery remains
unfinished. Search commands are also bounded; a timeout produces no search
result or approval.

The two-hour limit has not been measured for every device or unusually large
manual batch. A valid slow workload may need a separately reviewed batch/runtime
configuration. Model files, native flags, CPU provider selection and the existing
25% native duty cycle are unchanged. The reference-quality/parallel gate remains
open; synthetic recovery tests do not establish model parity or throughput.
