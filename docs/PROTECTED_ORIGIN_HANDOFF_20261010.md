# Protected source export and guard

The protection handoff now has a repeatable source-side command and stronger
sealer/scheduler checks in [private VISION PR #17](https://github.com/Andrew454545/VISION/pull/17),
commit `e118a442e0123477c4c64c4b0488ccd509548eff`, pushed and remote-verified.

The command runs the existing native protection exporter twice on the computer
holding the real MMA profile. It binds the complete selected maps and checks
Main, WAL and every selected Arrow/delta file before and after export, including
explicitly absent files. Changes, aliases, junctions, missing selections and
stale snapshots fail with preserved private evidence. Source database bytes
are not copied. Terminal output contains counts and the handoff fingerprint;
private paths, names and coordinates stay in the private output directory.

An independently pinned handoff can now be attached to an import. Admission and
pre-processing verify its exact snapshot and all original source files again.
The new guard has a fixed one-hour origin window and requires its separate
operator pin; it cannot silently fall back to an import without that guard.
The existing Main/WAL, Scene, strict official Gen4, 25 m and quality checks remain.

Windows regression passes **112 of 113 checks**, zero failures and one existing
POSIX-only executable-fixture skip. It includes real hidden child processes,
command-line sealing, selected-map changes with unchanged Main, new WAL/delta,
source aliases, expiry and independent-pin refusal. Exporter/data fixtures are
explicitly synthetic; this does not qualify native inference or Mac execution.

The original eight-row real candidate still refuses its unavailable protected
database and creates no import seal. All 76 owner handoff pins remain verified.
Original failures are retained: a retry-test expectation, a genuine Windows
file-ID rounding bug corrected using exact integers, and an attempted offline
native build whose existing cache lacks `arrow`. No dependencies were downloaded.
See [pinned evidence](evidence/protected-origin-handoff-20261010.json).

The next source-side resource is one fresh run on the owner's real profile using
his existing exporter. The [private source instructions](https://github.com/Andrew454545/VISION/blob/e118a442e0123477c4c64c4b0488ccd509548eff/automation/runtime-source/docs/protected-origin-handoff.md)
give the exact command and failure handoff. This captures origin state; it is
**not portable Object import approval**. A legitimate portable/live protection
design, current runtime authority and real Object settlement/search still need
completion. No full private MMA database transfer is authorized by this helper.

Public admission remains closed. The frozen Windows Scene pilot/refresher and
earlier evidence remain unchanged. No Actions spending, cloud writes, imagery,
Object inference or credit was triggered.
