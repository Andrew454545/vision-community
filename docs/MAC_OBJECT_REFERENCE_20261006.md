# Windows and Mac Object comparison

The same six images and eleven model/configuration files now have independently
checked detector values on Windows and Mac. Both systems retained the same
detection counts, identities, support counts and order for this one location.
Scores and boxes differ slightly. This closes the missing-values evidence gap;
it does not qualify production contributions.

## Actual measurements

The [Mac run](https://github.com/Andrew454545/vision-community/actions/runs/37430936795)
checks source `d3969124e26897e9648899e7c66a0a36a0296bb6`. It uses the published
Mac executable SHA-256
`29ad87e50d368ee57e33fc1a07b9ec53acae187a2f6dc0ed9aa058a28f7965c0`.
The Windows app-local CPU executable is
`68053a6f5193146d1dc53127c8860f96c7fc7b32bc186b89232797af42ccd400`,
built from native source `67635d5ee9a3435d95c804c13309f3e3206e4d72`.

Mac runs the Common detector and both hybrid queries, `car` and `a car`,
twice on CPU and twice with CoreML requested: twelve fresh detector processes.
The imagery is fetched once and frozen before any inference. Every image,
model, executable and configuration pin passes before/after validation.
The independent laptop recovery verifies all six image bytes against the
previous Windows fixture and every model/configuration checksum against
the Windows runtime. No images or detector values are published in this report.

The table compares Windows CPU with each Mac execution profile. Box coordinates
are normalized to the image dimensions. Numeric differences compare original
corresponding entries; detections are not rearranged to manufacture agreement.

| Mac reference | Lane | Numeric values compared | Maximum score difference | Maximum box difference | Structural changes |
| --- | --- | ---: | ---: | ---: | ---: |
| CPU | Common | 924 | 0.000019589 | 0.000003990 | 0 |
| CPU | Hybrid `car` | 90 | 0.000001610 | 0.000001040 | 0 |
| CPU | Hybrid `a car` | 90 | 0.000001510 | 0.000001040 | 0 |
| CoreML requested | Common | 924 | 0.000350568 | 0.000034990 | 0 |
| CoreML requested | Hybrid `car` | 90 | 0.000001380 | 0.000001640 | 0 |
| CoreML requested | Hybrid `a car` | 90 | 0.000001210 | 0.000001640 | 0 |

All six Mac within-profile repeat comparisons are exact, with no structural
or numerical changes. The two new Windows `a car` repeats are also exact
(90 compared values). Earlier Windows Common/`car` comparisons remain exact
against the four-thread Windows pilot.

Mac CPU versus CoreML-requested Common scores differ by at most
0.000330979 and normalized boxes by 0.000037820, with no structural changes.
Hybrid score differences are at most 0.000001033 (`car`) and 0.000000863
(`a car`), with maximum box difference 0.000000600 for both.
These comparisons were recomputed after decryption and checked against the
original receipt.

The full Mac collection took 1,338.900 seconds, including private downloads
and all twelve commands. The two new Windows query repeats took 254.797 seconds.
Different machines, cache states and workloads make these elapsed times
unsuitable for a throughput or acceleration comparison.

## Private evidence and independent recovery

The public Actions artifact contains authenticated ciphertext only. Its
RSA recipient private key remains on the operator's laptop, outside Git and CI.
The transport is RSA-OAEP-SHA256 with AES-256-GCM; the authenticated header
binds source revision, run and recipient fingerprint. Encryption preserves
privacy, not reference authorship or approval.

Independent GitHub metadata and the downloaded bytes agree on:

- Artifact `11398171943`, run `37430936795`, source `d396912`, attempt 1.
- ZIP: 282,879 bytes; SHA-256
  `544346e6628b9f46b26952fbf9677c1e93c61bd6f21a6fcae8f605349ba88b84`.
- Exactly one encrypted ZIP member; thirteen allowed files after local
  authenticated decryption: a receipt and twelve portable detector outputs.
- Receipt SHA-256
  `3efc3044ff993e53f5693a9078d2cc4c08c58bbeadefb48a6270a4e358f5f432`.

The recovery checks source-file hashes against the exact Git blobs, all twelve
runtime assets, six input identities, each output's size/checksum/schema,
query/detection identities and all repeat results. Credential-bearing API
requests do not follow redirects; signed artifact downloads receive no GitHub
credential. Private detector rows, raw images, indexes, models and keys are
absent from public logs/artifacts in plaintext.

## Engineering decisions and limits

Keep CPU and accelerated execution as separate immutable profiles. The
observed CPU/accelerated differences show why byte equality and a shared
assumed tolerance cannot qualify both. Use Andrew's independently identified
installed production profile as gold, then evaluate Windows and Mac candidates
against it on broader frozen cases and the full indexing path.

No numerical tolerance is approved from this single location. The Common
difference alone is larger than the proposed Scene winning-score bound;
Scene bounds do not apply to Objects. Further cases must include threshold,
overlap/suppression, support-count, semantic-feature and packed-index behavior.
Official historical Generation 4 provenance requires separate trusted evidence;
the fixture's `gen4` label is not coverage proof.

The published older Mac executable does not emit the newer shared CPU-pool
marker. Requested one-thread environment settings therefore do not establish
its actual thread budget. CoreML being requested does not attest placement of
every node, internal precision, or correspondence with Andrew's installed
executable. This run does not replay full indexing or hosted admission,
publication, earned credits, online search, sustained pacing or months of work.

The newer private-build collector is in
[private PR 13](https://github.com/Andrew454545/VISION/pull/13).
Its [first run](https://github.com/Andrew454545/VISION/actions/runs/37428422118)
never started because an Actions budget blocked it; no native success or
output exists for that run. The exact failure is preserved. This published
program comparison does not replace that missing private-build evidence.

Object production qualification remains closed. `DesktopApp.object_canary`
remains unset; no diagnostic receipt grants approval, contributions or credits.

## Application and staging verification

All eleven application jobs pass for `d396912`, using proposed main merge
`b586620`: [application/service](https://github.com/Andrew454545/vision-community/actions/runs/37430936744),
[native packages](https://github.com/Andrew454545/vision-community/actions/runs/37430936601),
[calibration](https://github.com/Andrew454545/vision-community/actions/runs/37430936662)
and [Mac lifecycle](https://github.com/Andrew454545/vision-community/actions/runs/37430936747).
Windows/Linux each run 639 tests (two/31 platform skips); the service passes
240 tests without skips and all actual workerd recovery/privacy/host checks.
Private Mac Python passes 66 setup, 62 delivery, 42 sleep and 23 control guards
without skips. Calibration runs 92 guards per platform with disclosed optional
cryptography/platform skips; the actual Mac reference run passes all 24 focused
guards with cryptography present. Package receipts remain unsigned/unqualified.

The tested Worker is deployed to confirmed staging version
`7b8615ff-3bc8-48ec-bdb7-678f5c41ad85` (6 October, 07:45 UTC).
All sixteen existing bindings remain unchanged. All thirteen website assets
match; privacy headers and explicit closed Object capability/authentication
responses pass readback. No accounts, credits or native work are created.
Initial Python-default-client requests were rejected by Cloudflare with error
1010 before reaching the Worker. The application's genuine client identity
passes; no security protection was changed. Production is unchanged.

Native reference trials now require explicit maintainer action; ordinary
updates run the small guards without model downloads or live imagery. The
[first guards-only update](https://github.com/Andrew454545/vision-community/actions/runs/37433398923)
passes all 24 checks on Linux and skips native Mac inference as intended.
See [the maintainer procedure](OBJECT_REFERENCE_CHECK.md) and
[remaining acceptance work](PRODUCTION_ACCEPTANCE.md).
