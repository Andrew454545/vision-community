# Full PC comparison recovery — 4 October 2026

The first fresh one-thread native trial completed all 1,024 locations and all
twelve searches. The matrix's final file check then failed because it omitted
`initial-evidence.json` from its expected inventory. The pinned native source
creates that startup receipt and retains it after completion. This was a
verifier compatibility defect; the original failed report remains unchanged.

The native index took 8,142.665 seconds (135.711 minutes), with 7,833.656 seconds
of cumulative owned CPU time. Peak job committed memory was 1,005,056,000 bytes;
the maximum sampled sum of working sets was 825,532,416 bytes. Working-set
samples are not an exact simultaneous or unique physical-memory measurement.
The checkpoint records 1,024 completed locations and zero fetch, inference or
incomplete-location errors. Both commands exited successfully, observed the
requested one-thread pool and verified owned descendant cleanup. The failed
matrix receipt records restoration of the prior sleep-request flags.

The corrected verifier requires the native startup receipt. It checks that its
input, model, graph and metadata match the completed evidence, while its status
is incomplete, frames/tensors are empty, and failure is null. It continues to
verify every tensor byte and rejects missing or unknown files. It can write a
separate offline verification folder without modifying the original case.

All 75 calibration tests pass in 7.173 seconds. Three added guards cover altered
or missing startup receipts, unexpected files, and separate verification with
every original file unchanged. Two earlier attempts could not create Python
temporary folders under the restricted Windows runtime; those logs are kept.
The passing run used the authorized local runtime with workspace temporary
storage. No protection was disabled.

The original native output, failed receipt, logs and tensors are retained. A
separate offline check and guarded finite continuation preserve the first
trial's provenance instead of labelling it a new execution. Ten private
continuation guards pass in 0.206 seconds, covering file/source/configuration
pins, verified launch permission, exact completed-command provenance and no
automatic repetition after start, failure or completion.

The separate offline check succeeds against the actual completed first case:
all 12,288 PC tensor files are byte/hash verified and retained, including raw
preprocessing. Complete Mac transport, original runtime profiles and all
original files are independently rechecked unchanged. No new native command
runs in this check. An earlier private report writer used a nonexistent
return field after validation; its log and separate output are preserved.

Every one of the 4,096 preprocessing hashes matches the Mac reference; the Mac
preprocessing bytes remain omitted, so this is hash comparison only. Maximum
relative-L2 differences are 0.000016379 for normalized floats and 0.000016386
for pooler output. Decoded packed vectors have minimum cosine 0.999980029 and
maximum relative-L2 error 0.006384468. Quantization can magnify a small float
difference into a different packed coordinate.

All twelve queries preserve the top-ten and top-100 sets. Full location order
matches for `road`; the other eleven queries have reordered pairs. Maximum
rank displacement is six, maximum absolute score difference is 0.000224190,
and one selected view differs in `snowy landscape`. These are measured
diagnostic results, not new acceptance thresholds or byte-identical parity.

All six Community CI jobs pass at `6a0cf3f`, including the complete Windows
suite and both 75-test calibration jobs. The remaining eight trials are handed
to a separate limited Windows task after saved-setting verification. It has
a 40-hour outer limit, pins the corrected code and retained first case, and
requires a verified launch receipt. It rechecks the original inputs before
new inference; registration or a started marker alone is not native progress.

One native trial cannot approve a parallel profile. The remaining rotated
1/2/4-thread repeats, held-out tolerance, trusted live imagery, actual accepted
background work and restart/endurance evidence remain release gates. This
comparison creates no accounts, submissions or credits, uploads no results and
does not inspect or modify the installed contributor.
