# Object feature validation

Object bundles now have bounded content checks in the desktop validator,
Cloudflare gateway and offline snapshot builder. Matching file hashes alone
cannot pass a malformed feature record.

The checks cover native CRCs, finite scores and geometry, ordered unique local
IDs, source-row byte pointers, country/camera/road flags, semantic proposal
flags and boxes, and six-face quality masks and totals. Rejected locations
require the native placeholder records and cannot contain common/hot features.
The score allowance accounts only for float32/uint16 record encoding; it is not
an inference comparison threshold.

Anonymous snapshot exports now rebuild row pointers after removing private
labels. They preserve the native road-presence boolean using generic text and
validate the complete exported bundle before sealing.

## Evidence

- 714 full Python checks pass with eight platform-specific skips; all 95
  focused Object/content/snapshot checks pass without skips.
- 332 gateway and bridge JavaScript checks pass without skips.
- The shared synthetic corpus passes in actual local workerd: eight valid
  formats and 63 rejected formats, including recalculated hashes and CRCs.
- Two preserved native indexes pass the content checks.
- Independent full native verification rejects the stale-pointer two-location
  synthetic export and accepts its repaired counterpart.
- The locally bundled complete Worker passes its D1, publication, replay,
  recovery, credit and lost-coverage guards. CI includes the new workerd check.

These are format, privacy and software checks. Independently recomputed model
outputs, reference accuracy, official coverage, device qualification and
accepted Object publication remain separate requirements. Object admission
remains closed. No production work or credits are created by these tests.
