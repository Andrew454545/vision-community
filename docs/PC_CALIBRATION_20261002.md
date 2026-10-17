# Windows calibration: 2 October 2026

The final packaged Windows candidate completed the exploratory 1/2/4-thread
matrix. Every setting completed the 112-location check and three fresh
1,024-location trials, with zero fetch/inference errors and complete four-view
masks. Interrupted older trials remain separate; their recovery was not counted
as a fresh repetition.

| ONNX threads | Trial 1 | Trial 2 | Trial 3 | Median |
| --- | --- | --- | --- | --- |
| 1 | 1,379 s | 1,344 s | 1,337 s | 1,344 s |
| 2 | 827 s | 809 s | 829 s | 827 s |
| 4 | 1,196 s | 1,186 s | 1,186 s | 1,186 s |

These were live-imagery trials, not isolated speed measurements. Two threads
were fastest in this sample; it does not establish an all-core maximum or a
production parallel profile. The ordinary input explicitly selected the fp32
image graph, and native logs confirmed the requested CPU pool.

## Identity and comparison

- Native source: `7c51f75d023314445fdfce9962b4c0217e279f99`; 69 native tests pass.
- Final Windows executable SHA-256:
  `6ce8f5c9dbfeb8404da13daa71afecfd07a56f118fc61819d07c1d2330f191ba`.
- Every packaged library was checked against the build receipt. A one-time
  observation of the two-thread process also verified the executable and all
  five DLLs loaded from that exact package.
- The full fixture has SHA-256
  `106c6bbbceb7b0c76892277c69dd7f1e88c7043584b1ca2313db216107aa5752`.

Independent comparison checked all nine fresh PC runs and Andrew's three
supplied Mac runs: 66 pairwise comparisons, including 27 across platforms.
Worst cross-platform view cosine was 0.9986520432 and relative L2 was
0.0519681575. Each run separately retrieved live imagery, so pixel changes and
runtime differences are combined. These measurements cannot define a
same-input tolerance or establish search ranking agreement.

## Fixed-image check of the final package

The exact final executable then replayed Andrew's sealed 16-location/64-view
RGB packet three times at each thread setting, using the same pinned fp32
graph. All nine native indexes and saved-index searches completed. Each
setting repeated identically; packed indexes and native query results also
matched across the three thread settings.

Across all 81 PC/Mac query comparisons, ordered locations and selected views
agreed. Maximum score difference was 0.00010595. All 64 preprocessed inputs
were identical; worst normalized relative L2 was 0.0000361704. Five raw views
differed slightly at four threads versus one, by at most 0.0000001577 relative
L2, without changing packed indexes or search results. Cross-platform packed
bytes remain different. This is a small controlled comparison, not full-corpus
ranking coverage, internal-precision attestation or an approved parallel profile.

The raw inputs, vectors, logs and failure reports stay private. No calibration
output was submitted as a contribution, credited or used to bypass PC
qualification. Broader numerical/ranking checks, representative resource
measurements, a measured policy and live accepted-work recovery remain release
requirements. See [the acceptance checklist](PRODUCTION_ACCEPTANCE.md).
