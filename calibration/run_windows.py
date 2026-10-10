"""Isolated three-replica scene experiment; no accounts, leases, or submissions.

Uses the Community indexing helper with explicitly recorded inference threads.
Only the standard library is needed. These measurements never grant approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import struct
import subprocess
import sys
import time
import urllib.request
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True
from community.vision_index import (  # noqa: E402
    PACE, index_locations_tsv, parse_json_stdout, require_layout,
)
from community.bootstrap import RELEASE  # noqa: E402
from calibration.quality import decoded_difference  # noqa: E402

FIXTURE = REPO / "calibration/gen4-v1"
RECORD_BYTES = 3080
VIEW_BYTES = 770
LOCATIONS = 1024
EXPECTED_CHECKSUMS_SHA256 = "f7d9cb75d14e3af0b0ece140bf39ef0e384d50ef31f42c723b653ec57a7944a9"
EXPECTED_RUNTIME_SHA256 = "b086083e00e527164b0433579a34d7a8141b05ed492081a4c1aa2f14a9164e87"


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def verify_fixture(folder=FIXTURE):
    if sha(folder / "checksums.json") != EXPECTED_CHECKSUMS_SHA256:
        raise ValueError("fixture_checksum_inventory_changed")
    inventory = json.loads((folder / "checksums.json").read_text())
    for name, expected in inventory.items():
        if Path(name).name != name or sha(folder / name) != expected:
            raise ValueError("fixture_file_changed")
    rows = (folder / "fixture-1024.tsv").read_text().splitlines()
    fields = [row.split("\t") for row in rows]
    if len(rows) != LOCATIONS or any(len(row) != 11 or row[9] != "gen4" for row in fields):
        raise ValueError("invalid_fixture_geometry")
    if len({(r[0], r[1]) for r in fields}) != LOCATIONS or len({r[7] for r in fields}) != LOCATIONS:
        raise ValueError("duplicate_fixture_identity")
    meta = json.loads((folder / "fixture-manifest.json").read_text())
    canary = (folder / "canary-112.tsv").read_text().splitlines()
    if len(canary) != 112 or canary != [rows[i] for i in meta["canary_parent_ordinals_zero_based"]]:
        raise ValueError("canary_changed")
    reference = (folder / "historical-reference.i8").read_bytes()
    record_hashes(reference)
    return inventory


def scene_assets(manifest):
    names = {
        "mma-vision-windows-x86_64.exe", "windows-directml.dll",
        "windows-msvcp140.dll", "windows-msvcp140_1.dll",
        "windows-vcruntime140.dll", "windows-vcruntime140_1.dll",
        "siglip-vision_model.onnx", "siglip-vision_model_fp32.onnx",
        "siglip-text_model.onnx", "siglip-tokenizer.json",
    }
    assets = [item for item in manifest["files"] if item["asset"] in names]
    if len(assets) != len(names) or {a["asset"] for a in assets} != names:
        raise ValueError("required_scene_assets_missing")
    return assets


def download_runtime(root, assets):
    for item in assets:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe_asset_path")
        dest = root / relative
        if dest.is_file() and dest.stat().st_size == item["bytes"] and sha(dest) == item["sha256"]:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_suffix(dest.suffix + ".partial")
        print(f"Downloading {item['asset']} ({item['bytes'] / 1e6:.1f} MB)", flush=True)
        request = urllib.request.Request(f"{RELEASE}/{item['asset']}", headers={"User-Agent": "VISION-calibration"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            if temporary.stat().st_size != item["bytes"] or sha(temporary) != item["sha256"]:
                raise ValueError("runtime_download_checksum_mismatch")
            temporary.replace(dest)
        finally:
            temporary.unlink(missing_ok=True)


def verify_existing_runtime(root, assets):
    """Reuse only the exact pinned assets; never repair an existing runtime."""
    for item in assets:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe_asset_path")
        path = root / relative
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise ValueError("existing_runtime_checksum_mismatch")


def record_hashes(blob):
    if len(blob) != LOCATIONS * RECORD_BYTES:
        raise ValueError("wrong_index_length")
    records = []
    for ordinal in range(LOCATIONS):
        record = blob[ordinal * RECORD_BYTES:(ordinal + 1) * RECORD_BYTES]
        views = [record[i * VIEW_BYTES:(i + 1) * VIEW_BYTES] for i in range(4)]
        for view in views:
            scale = struct.unpack("<e", view[:2])[0]
            if not math.isfinite(scale) or scale <= 0:
                raise ValueError("invalid_view_scale")
        records.append({"ordinal": ordinal, "sha256": hashlib.sha256(record).hexdigest(),
                        "view_sha256": [hashlib.sha256(v).hexdigest() for v in views]})
    return {"payload_sha256": hashlib.sha256(blob).hexdigest(), "locations": LOCATIONS,
            "views": LOCATIONS * 4, "records": records}


def exact_difference(a, b):
    if len(a) != LOCATIONS * RECORD_BYTES or len(a) != len(b):
        raise ValueError("incomparable_geometry")
    views = locations = scales = changed_bytes = 0
    for ordinal in range(LOCATIONS):
        left = a[ordinal * RECORD_BYTES:(ordinal + 1) * RECORD_BYTES]
        right = b[ordinal * RECORD_BYTES:(ordinal + 1) * RECORD_BYTES]
        locations += left != right
        changed_bytes += sum(x != y for x, y in zip(left, right))
        for j in range(4):
            offset = j * VIEW_BYTES
            views += left[offset:offset + VIEW_BYTES] != right[offset:offset + VIEW_BYTES]
            scales += left[offset:offset + 2] != right[offset:offset + 2]
    return {"byte_identical": a == b, "affected_locations": locations, "affected_views": views,
            "affected_scales": scales, "differing_bytes": changed_bytes}


def compare_payloads(candidate, reference):
    return {**exact_difference(candidate, reference),
            "decoded": decoded_difference(candidate, reference)}


def trial_plan(threads):
    """Rotate cells across replicas to reduce systematic time/order effects."""
    if not threads or len(set(threads)) != len(threads) or any(t not in (1, 2, 4) for t in threads):
        raise ValueError("threads_must_be_unique_choices_of_1_2_4")
    return [(count, replica + 1) for replica in range(3)
            for count in threads[replica % len(threads):] + threads[:replica % len(threads)]]


def summarize_trials(summary, payloads):
    cells = {}
    for count in summary["requested_inference_threads"]:
        runs = [run for run in summary["runs"] if run["inference_threads"] == count and run["status"] == "COMPLETE"]
        comparisons = {}
        for a, b in ((1, 2), (1, 3), (2, 3)):
            if (count, a) in payloads and (count, b) in payloads:
                comparisons[f"{a}_vs_{b}"] = compare_payloads(payloads[count, a], payloads[count, b])
        cells[str(count)] = {"completed_replicas": len(runs), "replica_comparisons": comparisons,
                            "median_locations_per_second": statistics.median(r["locations_per_second"] for r in runs) if runs else None}
    baseline = cells.get("1", {})
    if baseline.get("completed_replicas") == 3:
        baseline_rate = baseline["median_locations_per_second"]
        for cell in cells.values():
            if cell["completed_replicas"] == 3:
                cell["observed_rate_ratio_to_one_thread"] = cell["median_locations_per_second"] / baseline_rate
    cross = {}
    for count in summary["requested_inference_threads"]:
        if count == 1:
            continue
        for replica in range(1, 4):
            if (count, replica) in payloads and (1, replica) in payloads:
                cross[f"threads_{count}_vs_1_replica_{replica}"] = compare_payloads(payloads[count, replica], payloads[1, replica])
    summary.update(cells=cells, cross_thread_comparisons=cross,
                   completed_runs=sum(r["status"] == "COMPLETE" for r in summary["runs"]),
                   failed_runs=sum(r["status"] == "FAILED" for r in summary["runs"]),
                   unstarted_runs=sum(r["status"] == "NOT_STARTED" for r in summary["runs"]))
    if len(cells) == 1:
        cell = next(iter(cells.values()))
        summary["replica_comparisons"] = cell["replica_comparisons"]
        summary["median_locations_per_second"] = cell["median_locations_per_second"]


def run_trials(results, root, binary, model, summary, *, indexer=None):
    indexer = indexer or index_locations_tsv
    threads = summary["requested_inference_threads"]
    payloads = {}
    reference = (FIXTURE / "historical-reference.i8").read_bytes()
    plan = trial_plan(threads)
    for count, replica in plan:
        summary["runs"].append({"run": replica, "inference_threads": count, "status": "NOT_STARTED",
                                "cache_state": "fresh index/checkpoint; OS/model cache state NOT_ATTESTED"})
    try:
        for sequence, run in enumerate(summary["runs"], 1):
            count, replica = run["inference_threads"], run["run"]
            parent = results / "runs"
            if len(threads) > 1 or count != 1:
                parent /= f"threads-{count:02d}"
            folder = parent / f"run-{replica:02d}"
            folder.mkdir(parents=True)
            run.update(status="RUNNING", sequence=sequence, evidence_directory=folder.relative_to(results).as_posix())
            write_json(results / "summary.json", summary)
            print(f"Full fixture {sequence}/{len(plan)}: {count} inference thread(s), trial {replica}/3.", flush=True)
            started = time.perf_counter()
            try:
                indexer(FIXTURE / "fixture-1024.tsv", index_dir=folder / "index",
                        checkpoint=folder / "checkpoint.json", output=folder / "output.json",
                        input_path=folder / "input.json", binary=binary, model_dir=model,
                        pace="slow", inference_threads=count, run_id="vision-gen4-calibration-v1",
                        runner=LoggedProcess(folder, root), use_nice=False)
                blob, hashes = verify_output(folder)
                elapsed = time.perf_counter() - started
                historical = compare_payloads(blob, reference)
                payloads[count, replica] = blob
                run.update(status="COMPLETE", wall_seconds=elapsed, locations=LOCATIONS,
                           views=LOCATIONS * 4, payload_sha256=hashes["payload_sha256"],
                           historical_comparison=historical, peak_memory="NOT_ATTESTED",
                           locations_per_second=LOCATIONS / elapsed)
            except (Exception, KeyboardInterrupt) as error:
                run.update(status="FAILED", error=str(error) or type(error).__name__, wall_seconds=time.perf_counter() - started)
                raise
            finally:
                write_json(folder / "run-summary.json", run)
    finally:
        summarize_trials(summary, payloads)
    summary["status"] = "THREE_RUNS_COMPLETE_NOT_APPROVED" if len(threads) == 1 else "THREAD_MATRIX_COMPLETE_NOT_APPROVED"
    summary["parallelism"] = "NOT_TESTED" if threads == [1] else "MEASURED_WITH_LIVE_INPUT_CONFOUNDING"


def report_text(summary):
    lines = ["# Windows scene calibration", "", summary["status"], "",
             "Andrew's historical VISION records are the comparison target. Live source pixels are not frozen; "
             "configuration/provider differences are not isolated. No production approval or numerical acceptance threshold is established.", "",
             f"Completed: {summary.get('completed_runs', 0)}. Failed: {summary.get('failed_runs', 0)}. "
             f"Not started: {summary.get('unstarted_runs', 0)}.", "",
             "| Threads | Trial | Status | Locations/s | Mean cosine vs reference | Lowest cosine |",
             "| ---: | ---: | --- | ---: | ---: | ---: |"]
    for run in summary["runs"]:
        cosine = run.get("historical_comparison", {}).get("decoded", {}).get("cosine_similarity", {})
        number = lambda value: f"{value:.8f}" if value is not None else "—"
        lines.append(f"| {run['inference_threads']} | {run['run']} | {run['status']} | "
                     f"{number(run.get('locations_per_second'))} | {number(cosine.get('mean'))} | {number(cosine.get('min'))} |")
    lines.extend(["", "summary.json includes exact byte differences, decoded cosine distributions, scale-aware relative L2 error, "
                  "unit-vector distances, replica comparisons, and any matched-replica cross-thread comparisons. "
                  "Cosine describes vector direction; it does not establish ranking/search parity. Error and rate ratios are diagnostic, not pass/fail gates.", "",
                  "Thread cells keep batch/chunk size 16, fetch concurrency 8 and one encoder session. "
                  "Cell order rotates across three repetitions. Only the requested thread environment settings change; "
                  "effective backend thread use is not independently attested. Live imagery, OS/model cache, background work and temperature can confound throughput and output differences.", "",
                  "Peak memory, search parity, Gen 1–3 and large-corpus performance are not attested. "
                  "Windows disables an unsupported macOS thermal-state query; this is recorded in the generated input and source hashes. "
                  "OS thermal protections remain in effect.", "",
                  "Local path prefixes in textual return copies are redacted; original evidence remains in the test folder. "
                  "Do not publish the results ZIP automatically.", ""])
    if summary.get("error"):
        lines.extend(["Failure: " + summary["error"], ""])
    return "\n".join(lines)


def verify_output(folder):
    index = folder / "index"
    state = json.loads((folder / "checkpoint.json").read_text())
    manifest = json.loads((index / "manifest.json").read_text())
    if (state.get("nextLocationIndex") != LOCATIONS or state.get("incompleteLocations") != 0
            or manifest.get("indexedLocations") != LOCATIONS):
        raise ValueError("incomplete_index")
    require_layout({**manifest, "feature": "four-view-index"})
    shards = sorted(index.glob("shard-*.i8"))
    if len(shards) != 1 or shards[0].name != "shard-000000.i8":
        raise ValueError("unexpected_shards")
    mask = index / "shard-000000.mask"
    if not mask.is_file() or mask.read_bytes() != b"\x0f" * LOCATIONS:
        raise ValueError("incomplete_view_mask")
    blob = shards[0].read_bytes()
    hashes = record_hashes(blob)
    write_json(folder / "record-hashes.json", hashes)
    return blob, hashes


def child_environment(root):
    # Do not pass ambient model/provider tuning, credentials, or session paths.
    keys = ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE")
    env = {key: os.environ[key] for key in keys if key in os.environ}
    system = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = os.pathsep.join((str(root / "runtime/bin"), str(system / "System32"), str(system)))
    for key, relative in (("TEMP", "temp"), ("TMP", "temp"), ("TMPDIR", "temp"),
                          ("LOCALAPPDATA", "profile/Local"), ("APPDATA", "profile/Roaming"),
                          ("USERPROFILE", "profile"), ("HOME", "profile")):
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    for key in ("RAYON_NUM_THREADS", "VISION_ORT_THREADS", "OMP_NUM_THREADS", "ORT_NUM_THREADS"):
        env[key] = "1"  # The existing Community wrapper's policy, not a VISION prescription.
    return env


class LoggedProcess:
    """Real process adapter; keeps every attempt and prevents silent retries."""
    def __init__(self, folder, root):
        self.folder, self.root = folder, root
        self.calls = 0
        self.index_calls = 0

    def __call__(self, argv, env, cwd):
        self.calls += 1
        if "index-four-views" in argv:
            self.index_calls += 1
            if self.index_calls > 1:
                raise RuntimeError("incomplete_first_attempt_no_automatic_resume")
        # Keep the helper's exact four explicit thread settings and isolate paths.
        effective = child_environment(self.root)
        for key in ("RAYON_NUM_THREADS", "VISION_ORT_THREADS", "OMP_NUM_THREADS", "ORT_NUM_THREADS"):
            effective[key] = env.get(key, "1")
        effective["TMPDIR"] = str(cwd)
        stem = self.folder / f"process-{self.calls:02d}"
        write_json(stem.with_suffix(".json"), {"argv": argv, "cwd": str(cwd),
                   "thread_environment": {k: effective[k] for k in effective if k.endswith("THREADS")}})
        start = time.perf_counter()
        try:
            with stem.with_suffix(".stdout.log").open("wb") as out, stem.with_suffix(".stderr.log").open("wb") as err:
                proc = subprocess.run(argv, cwd=cwd, env=effective, stdout=out, stderr=err, timeout=7200)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            write_json(stem.with_suffix(".exit.json"), {"status": "TIMEOUT", "wall_seconds": time.perf_counter() - start})
            raise RuntimeError("indexer_timeout") from None
        write_json(stem.with_suffix(".exit.json"), {"exit_code": code, "wall_seconds": time.perf_counter() - start})
        if code:
            raise RuntimeError(f"indexer_exit_{code}")
        return code, stem.with_suffix(".stdout.log").read_text(errors="replace"), stem.with_suffix(".stderr.log").read_text(errors="replace")


def make_results_zip(results, root):
    """Only evidence files, with local path prefixes redacted in text copies."""
    packaged = root / "return-package"
    packaged.mkdir()
    for source in results.rglob("*"):
        if not source.is_file():
            continue
        dest = packaged / source.relative_to(results)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix in (".json", ".log", ".md"):
            text = source.read_text(encoding="utf-8", errors="replace")
            for path, label in ((root, "$TEST_ROOT"), (REPO, "$SOURCE"), (Path.home(), "$USER_HOME")):
                for prefix in (str(path).replace("\\", "\\\\"), str(path), path.as_posix()):
                    text = text.replace(prefix, label)
            dest.write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(source, dest)
    write_json(packaged / "checksums.json", {p.relative_to(packaged).as_posix(): sha(p)
                                            for p in sorted(packaged.rglob("*")) if p.is_file()})
    archive = root / "pc-calibration-results.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for file in sorted(packaged.rglob("*")):
            if file.is_file(): z.write(file, file.relative_to(packaged).as_posix())
    archive.with_suffix(".sha256.txt").write_text(sha(archive) + "  " + archive.name + "\n")
    return archive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--allow-downloads", action="store_true")
    parser.add_argument("--allow-live-imagery", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--threads", nargs="+", type=int, choices=(1, 2, 4), default=[1],
                        help="Three full trials for each requested inference-thread count; default: 1")
    parser.add_argument("--reuse-runtime", type=Path,
                        help="Existing private runtime directory; all pinned hashes are rechecked and no files are changed")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        parser.error("This runner requires native x86-64 Windows.")
    if not args.allow_downloads or (not args.prepare_only and not args.allow_live_imagery):
        parser.error("Explicit download/live-imagery consent flags are required.")
    try:
        trial_plan(args.threads)
    except ValueError as error:
        parser.error(str(error))
    root = args.root.resolve()
    results = root / "results"
    results.mkdir(parents=True, exist_ok=False)
    summary = {"status": "INCOMPLETE", "input_identity": "NOT_ISOLATED_END_TO_END",
               "reference": "HISTORICAL_REFERENCE_ONLY", "configuration": "COMMUNITY_CONFIGURATION_GAP",
               "acceptance_thresholds": "NOT_ESTABLISHED", "production_approved": False,
               "parallelism": "NOT_TESTED", "search_parity": "NOT_ATTESTED", "runs": [],
               "requested_inference_threads": args.threads,
               "planned_runs": 0 if args.prepare_only else 3 * len(args.threads),
               "thread_order": "rotated across replicas", "effective_backend_threads": "NOT_ATTESTED"}
    code = 1
    try:
        fixture_inventory = verify_fixture()
        manifest_path = REPO / "community/runtime_manifest.json"
        if sha(manifest_path) != EXPECTED_RUNTIME_SHA256:
            raise ValueError("runtime_manifest_changed")
        assets = scene_assets(json.loads(manifest_path.read_text()))
        write_json(results / "provenance.json", {
            "fixture_inventory": fixture_inventory, "runtime_manifest_sha256": sha(manifest_path),
            "runtime_assets": assets, "community_policy": PACE["slow"],
            "requested_inference_threads": args.threads,
            "windows_thermal_policy": "unsupported macOS thermal query disabled; OS protections unchanged",
            "python": sys.version, "source_python_sha256": {p.relative_to(REPO).as_posix(): sha(p)
                for p in sorted((REPO / "community").glob("*.py"))},
            "runner_sha256": sha(Path(__file__)), "quality_evaluator_sha256": sha(Path(__file__).with_name("quality.py")),
            "log_redaction": "Local path prefixes replaced in return ZIP; binary payloads unchanged",
            "effective_per_operation_provider": "NOT_ATTESTED", "inference_precision": "NOT_ATTESTED"})
        for name in ("machine.json", "python-provenance.json"):
            if (root / name).is_file(): shutil.copyfile(root / name, results / name)
        shutil.copyfile(FIXTURE / "local-vision-observation.json", results / "local-vision-observation.json")
        runtime = args.reuse_runtime.resolve() if args.reuse_runtime else root / "runtime"
        if args.reuse_runtime:
            verify_existing_runtime(runtime, assets)
        else:
            download_runtime(runtime, assets)
        binary = runtime / "bin/mma-vision.exe"
        model = runtime / "models/siglip-b16-224-canonical"
        preflight = results / "preflight"
        preflight.mkdir()
        logger = LoggedProcess(preflight, root)
        _, stdout, _ = logger([str(binary), "index-layout"], child_environment(root), preflight)
        layout = parse_json_stdout(stdout)
        require_layout(layout)
        if layout.get("completeViewMask") != 15: raise ValueError("incomplete_layout")
        if args.prepare_only:
            summary["status"] = "PREREQUISITES_READY_NO_INFERENCE"
            code = 0
        else:
            run_trials(results, root, binary, model, summary)
            code = 0
    except (Exception, KeyboardInterrupt) as error:
        summary["error"] = str(error) or type(error).__name__
        print("The experiment stopped. Failure evidence will be included in the return ZIP.", flush=True)
    finally:
        summary.setdefault("completed_runs", 0)
        summary.setdefault("failed_runs", 0)
        summary.setdefault("unstarted_runs", summary["planned_runs"])
        write_json(results / "summary.json", summary)
        (results / "report.md").write_text(report_text(summary), encoding="utf-8")
        archive = make_results_zip(results, root)
        print(f"Return this file to Andrew: {archive}\nSHA-256: {sha(archive)}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
