# Mac timeout cleanup repair

A finite check of Andrew's unchanged supplied Mac executable reproduced a
cleanup failure. Its first process-group stop succeeded and the wrapper exited.
A second stop in the final cleanup raised `PermissionError`, hiding the expected
timeout. The original failed receipt, command logs and private archive remain
unchanged. Archive SHA-256:
`4c03666de54212b8fa0fb9786e067e48a80c34b50aba94d89860b3d871520297`.

The helper now attempts a POSIX group stop once. A first denial still fails; it
is neither suppressed nor retried. A failed group/job close still releases the
parent pipe and stops/waits the wrapper. Windows retains its private
kill-on-close Job Object. Models, native binaries, inference settings and
security protections are unchanged.

Repaired helper SHA-256:
`4dc8cf13a964fc77b4f82409c4aba8c8b6a98dd2052d85718e93039272b0bfeb`.
Four new regression guards cover repeated signals and cleanup failures.
The full local Windows suite passes 465 tests in 225.461 seconds, with two
existing filesystem-link permission skips. All 28 ownership/resource guards
and all 51 calibration guards pass. New cross-platform CI and two actual
supplied-executable timeout checks remain to be confirmed.

The private native probe checks only whether processes belonging to its own
effective user remain in its verified private group, using read-only
[`pgrep -g ... -u ...`](https://raw.githubusercontent.com/apple-oss-distributions/adv_cmds/main/pkill/pkill.1).
Malformed, denied or failed queries cannot pass. It does not signal protected
macOS services, establish their lifetime, or attest descendants that escape
the group. A successful short probe cannot establish overnight stability.

Earlier measured Windows reports used helper `019fc3c0…`, including the
installed background worker and memory diagnostic. They remain historical
evidence for those bytes. The new helper needs fresh runtime/policy pins and
qualification before shipping; no installed worker or production policy was
changed by this repair. The larger Mac reference is running with its separately
pinned older helper and is not interrupted or silently relabeled by this check.
