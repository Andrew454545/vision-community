# Installed Mac reference inspection, 2026-09-30

This is the response to the reference-evidence request in PR #2 at
`4692c326aff7161b510bc457a01644241ad8dc67`. It records a read-only inspection
of Andrew's installed application. It is not a fresh three-run reference packet
or a numerical acceptance policy. Scene and object processing remain paused
at Andrew's request. No imagery was retrieved and no inference was performed.

## Observed runtime and configuration

Host: macOS 27.0 (26A428), arm64. Installed VISION: version 1.1.0, build 2.
SHA-256 values below were computed from the actual installed files, not inferred
from release labels. The installed scene executable equals the paused scene
worker executable. The installed object executable equals the paused legacy
object worker executable. The separate canonical object executable differs;
do not silently substitute it when reproducing the installed application.
The Community scene executable also differs from the installed scene binary.

The last scene runner startup at 2026-09-30 02:30:01 America/Chicago recorded
the maximum profile: embedding batch 32, two image encoder sessions, fetch
concurrency 32, chunk size 32, Rayon threads 4, ONNX Runtime global threads 4
with spinning disabled, duty cycle 100%. Its input JSON agrees on batch,
sessions, fetch, chunk and duty. Shards contain 50,000 locations. The preceding
standard profile used batch/chunk/fetch 20, one encoder session, Rayon/ORT
threads 3 and duty 31.25%. These are observed local configurations, not
qualified Windows profiles.

The scene binary reports CoreML registration. That does not attest which
nodes actually execute in CoreML, fallback behavior, or arithmetic precision.
Both `vision_model.onnx` and `vision_model_fp32.onnx` exist; file presence does
not establish which graph was selected. Exact preprocessing and selected-model
identity still need an attestation from this executable's inference path.
The available native checkout is not a verified source/build match for the
installed executable, and some source/Git reads stalled on unavailable files.
Its preprocessing code therefore must not be treated as binary provenance.

The installed object executable's read-only `runtime-info` validates the
current model/manifest set and reports runtime identity
`58ee8c307523d3ac06da85d18fd3ad303d6a0442d4edc071918be5e2890b9353`,
schema 3, index contract 4, search contract 2, complete 360x180 six-face cube
coverage, and maximum raw model score without pose or view-order weights.
This identifies assets/contracts, not actual detector results or quality.
The paused object supervisor supplied a 25% duty cycle and invoked
`index-segment` without `--cpu`. Actual provider partitions, precision and
thread counts remain unattested. Its runtime manifest declares RF-DETR
medium 576 batch 4, YOLOE-26L 640, OWLv2 Base Patch16 Ensemble 960 with
512-dimensional features, and PQ128. Model-specific preprocessing still needs
an inference-boundary record rather than architecture names alone.

## Frozen inputs and available commands

The installed `index-four-views --help` exposes only `--input`, `--model-dir`,
`--locations-tsv`, `--index-dir`, `--checkpoint`, and `--output`. The inspected
`FourViewInput` and index loop fetch views from panorama metadata and do not
expose a frozen-view directory, saved tensor input, or per-view input digest.
No usable frozen-input replay path was established. This is an inspection
finding, not proof that no uninspected native capability exists.

`benchmark --help` exposes `--image-cache-dir`, but a benchmark cache is not
an attested substitute for the production four-view indexing path or its
per-view output/mask contract. No benchmark inference was run.

Object diagnostics do expose local image inputs: `detect-images --image`
and `detect-hybrid-images --image`. These can support a separate detector
study after sealed, authorized inputs exist. They do not establish replay of
the complete `index-segment` rendering, proposal, quantization and ranking
pipeline. Object evidence must remain separate from scene qualification.

The public historical 1,024-location packet contains quantized per-view
vectors and masks, not the original unquantized float32 vectors or frozen
pixels. Dequantizing it cannot recover the original float32 output. The
112-location canary remains useful for layout/exploratory checks; neither
fixture is a newly approved production reference.

## Reproducible metadata checks and required comparison capability

Use the actual installed executables, not the separately installed Community
or canonical object executables. Set `SCENE_EXE`, `OBJECT_EXE`, and model
directories to locally verified private paths. These commands inspect metadata
and do not retrieve panoramas or perform inference:

```sh
"$SCENE_EXE" index-layout
"$SCENE_EXE" index-four-views --help
"$SCENE_EXE" benchmark --help
"$OBJECT_EXE" detect-hybrid-images --help
"$OBJECT_EXE" runtime-info \
  --model "$OBJECT_MODELS/rfdetr-medium-576-b4.onnx" \
  --model-manifest "$OBJECT_MODELS/object-model.json" \
  --runtime-manifest "$OBJECT_MODELS/hybrid-object-runtime.json"
```

The next native capability must export and replay the **same production scene
path** against an ordered, sealed 1,024-location/4,096-view manifest, bypassing
network retrieval during replay. Record capture/pose mapping, RGB dimensions
and hashes, preprocessing version and normalized NCHW float32 tensor hashes
at the encoder boundary. Export all 768 float32 values before int8 packing,
the packed records, masks, individual view failures and run timings. Record
the selected graph hash, provider/precision/fallback evidence, binary/runtime
identity, batch/session sizes and both ORT and Rayon thread settings. A rebuilt
instrumented executable needs its own hash and provenance; do not label it
as the currently installed executable.

Then use three clean, separate output/checkpoint directories for Mac repeats
with identical sealed inputs and a fixed recorded configuration. A clean
directory prevents a resumed run from being mistaken for a repeat. Preserve
the original 1,024 ordering and 112 canary mapping, and add a fixed held-out
query set with native query configuration, query embeddings, scores and
rankings. Compare the Windows 1/2/4-thread matrix on those same inputs,
changing only the documented thread setting while holding batch, sessions,
models and preprocessing fixed. Measure per-view and worst-case differences,
missing masks, repeatability, ranking changes, memory and throughput before
Andrew approves numerical bounds. A one-thread label alone does not guarantee
byte-identical output across providers or devices.

For objects, independently seal the actual rendered RF-DETR/YOLOE/OWLv2
inputs and capture detector/proposal/features and held-out rankings through
the relevant native production path. Scene results cannot qualify objects.

The three Mac repeats, full unquantized vectors and held-out rankings are
**not produced** in this inspection because identical frozen inputs and an
attested native replay path are unavailable. No tolerance was invented and
no device, production contribution, deployment or merge was approved.
Private metadata/log evidence is retained locally by Andrew; no external
private download link has been established. The table below is safe metadata
only and contains no imagery, private index bytes, credentials or account data.

## Fresh SHA-256 inventory

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| installed_app | 3529616 | `179dfaa2cfe2feab2e14f191a5a1e873257ff14bd5760b936b6c189df9f49095` |
| installed_scene | 35324112 | `4e3a42023797d878d6f16abc2dc1b400f9ddf94bd48b8bf9a4040ab8b5c59181` |
| installed_object | 23444896 | `2048f18ed4fd79ba37b963b575ef6815a75108b9b128855ecb9f3bdf00abccc6` |
| paused_scene | 35324112 | `4e3a42023797d878d6f16abc2dc1b400f9ddf94bd48b8bf9a4040ab8b5c59181` |
| paused_legacy_object | 23444896 | `2048f18ed4fd79ba37b963b575ef6815a75108b9b128855ecb9f3bdf00abccc6` |
| canonical_object | 23527808 | `29ad87e50d368ee57e33fc1a07b9ec53acae187a2f6dc0ed9aa058a28f7965c0` |
| community_scene | 35059824 | `be0d98af2fab5e96f3cd6397365cfb2523dad66a93612a2b23358a8ae91419f2` |
| siglip-b16-224-canonical/text_model.onnx | 441332132 | `3aa7fdbd20eaa8740cce17bf82913de641fcb632a768fed59f661cdcd0c32553` |
| siglip-b16-224-canonical/tokenizer.json | 2398744 | `4a17c975210be5ab4c36b47d8dae4eefb866dbfb1e676e394aad85dc30a3ae08` |
| siglip-b16-224-canonical/vision_model.onnx | 99499129 | `ef14a954f3d57e1806666432bd9785004c1dc27100aa260eee0cb0f10a5de058` |
| siglip-b16-224-canonical/vision_model_fp32.onnx | 371819850 | `f89d41bac7f4d4b87e010a467d93f98689d708916ed22f5a07f96fdfa26f475f` |
| object-hybrid-v1/hybrid-object-runtime.json | 3249 | `ea6466c65fc39ec2b3ab8387def163aad550c9289debc856a1adcfc0367f6728` |
| object-hybrid-v1/object-model.json | 628 | `78ff4a39eb70353d71c0b9a06a850b06d79a43e60eea97d1e6bf0f4698b7a26f` |
| object-hybrid-v1/owlv2-merges.txt | 524619 | `9fd691f7c8039210e0fced15865466c65820d09b63988b0174bfe25de299051a` |
| object-hybrid-v1/owlv2-pq128-codebook.bin | 524288 | `f28e0e9aeb8bfcd547cad3d2a3d9aa546de74b647cd1cc058a5911bd7dafeb25` |
| object-hybrid-v1/owlv2-text-encoder.onnx | 253720547 | `64cd38a2ca30d0e99a6305b1c30309e887d34679168ea38df1bfa5db68038e51` |
| object-hybrid-v1/owlv2-tokenizer.json | 3642505 | `9d1402bd9f4784e9c77a7e9a342ecc45cb6c4e12b2310e35a2ed3f7b74d05701` |
| object-hybrid-v1/owlv2-vision-proposals.onnx | 364925576 | `4bf7560487a328fa25a0de51c607ce87d32c95289f5a25930ca4897568f2ac58` |
| object-hybrid-v1/owlv2-vocab.json | 1059962 | `e089ad92ba36837a0d31433e555c8f45fe601ab5c221d4f607ded32d9f7a4349` |
| object-hybrid-v1/rfdetr-medium-576-b4.onnx | 120795497 | `00cc60ba7e18ea6b5afeca7d8d3d4a07be0d1e9969dbd1799719a4f802882fd2` |
| object-hybrid-v1/yoloe-26l-hot-prompts.npz | 4486 | `62705fffc47c45eb0b4ed5fd3050e7f8148bc4e352e87ac2d4ffde7343a4bd10` |
| object-hybrid-v1/yoloe-26l-hot.onnx | 111928313 | `fff4e85756a808d36a791d4baede733715fa9d53ce7c308ab13aee0809a7f17b` |
