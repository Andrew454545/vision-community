"""Publish a sealed pool with bounded disk use and independent object readback.

This operator tool never changes assignment, deletes remote objects, or approves
coverage. An explicitly supplied private adapter implements put(key, bytes) and
get(key)->bytes. Credentials do not belong in the repository.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def snapshot(path):
    s = path.stat()
    return [s.st_size, s.st_mtime_ns, s.st_ino]


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def verified_put(adapter, key, data):
    adapter.put(key, data)
    fresh = adapter.get(key)
    if len(fresh) != len(data) or digest(fresh) != digest(data):
        raise RuntimeError("Independent R2 object readback mismatch: " + key)


def publish(args):
    out = args.output.resolve()
    out.mkdir(exist_ok=True)
    source_before = snapshot(args.source)
    if file_digest(args.source) != args.source_sha256:
        raise RuntimeError("Source hash differs from the independently pinned native commit")
    report = json.loads(args.identity_report.read_text())
    if report["sourceRows"] != args.source_rows or report["malformedInputIds"]:
        raise RuntimeError("Identity report has incompatible source bounds or malformed IDs")
    if report["identityComparison"] != "complete-22-byte-panorama-id":
        raise RuntimeError("Complete panorama comparison is required")
    spec = importlib.util.spec_from_file_location("private_pool_adapter", args.adapter)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    pins = {"sourceSha256": args.source_sha256,
            "sourceRows": args.source_rows, "sourceStat": source_before,
            "maskSha256": file_digest(args.mask),
            "identityReportSha256": file_digest(args.identity_report),
            "countryAuthoritySha256": file_digest(args.countries),
            "exporterSha256": file_digest(args.exporter), "prefix": args.prefix}
    pin_path = out / "input-pins.private.json"
    if pin_path.exists() and json.loads(pin_path.read_text()) != pins:
        raise RuntimeError("Resume input identities changed; preserve the earlier attempt")
    save(pin_path, pins)
    journal = out / "verified-shards.private.jsonl"
    prior = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
    # Rendering again enables deterministic recovery without keeping the corpus
    # locally. Prior objects must match fresh local bytes and a fresh remote GET.
    attempt = 0
    while (out / ("render-" + str(attempt))).exists():
        attempt += 1
    rendered = out / ("render-" + str(attempt))
    command = [str(args.exporter), str(args.source), str(args.mask),
               str(args.countries), str(rendered), str(args.source_rows), "500000"]
    receipts = []
    done = None
    with (out / (f"export-{attempt}.stderr.private.log")).open("w") as errors:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=errors, text=True, bufsize=1)
        try:
            for line in proc.stdout:
                event = json.loads(line)
                if event.get("done"):
                    done = event
                    continue
                serial = event["shard"]
                if serial != len(receipts):
                    raise RuntimeError("Noncontiguous exporter shard")
                path = rendered / event["file"]
                data = path.read_bytes()
                key = args.prefix.rstrip("/") + "/" + event["file"]
                receipt = {"shardId": args.shard_id_start + serial,
                           "file": event["file"], "key": key, "rows": event["rows"],
                           "rowStart": event["totalRows"] - event["rows"],
                           "bytes": len(data), "sha256": digest(data)}
                if serial < len(prior):
                    if prior[serial] != receipt:
                        raise RuntimeError("Previously verified shard has changed")
                    fresh = adapter.get(key)
                    if len(fresh) != len(data) or digest(fresh) != receipt["sha256"]:
                        raise RuntimeError("Resume remote readback mismatch")
                else:
                    verified_put(adapter, key, data)
                    with journal.open("a") as stream:
                        stream.write(json.dumps(receipt) + "\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                receipts.append(receipt)
                path.unlink()  # Only our closed, independently verified temporary shard.
                proc.stdin.write("VERIFIED " + event["file"] + "\n")
                proc.stdin.flush()
                print(json.dumps({"stage": "remote-verified", "shard": serial,
                                  "rows": event["totalRows"], "bytes": len(data)}), flush=True)
            code = proc.wait()
            if code or not done or done["totalRows"] != report["eligibleUnique"]:
                raise RuntimeError("Incomplete export; inspect the preserved stderr and journal")
            if done["sourceRows"] != args.source_rows or done["shards"] != len(receipts):
                raise RuntimeError("Exporter completion bounds differ")
            if snapshot(args.source) != source_before:
                raise RuntimeError("Source changed during publication")
            if file_digest(args.mask) != pins["maskSha256"]:
                raise RuntimeError("Identity mask changed during publication")
            manifest = {"version": 1, "contract": "vision-community-pose-catalog-v1",
                        "lane": "scene", "r2Prefix": args.prefix, "rowsPerShard": 500000,
                        "totalRows": done["totalRows"], "rowStart": 0, "shards": receipts,
                        "sourceSha256": args.source_sha256, "allocation": report,
                        "metadataOnly": True, "productionQualified": False,
                        "cameraClassification": "unknown; obsolete positional metadata not reused"}
            body = (json.dumps(manifest, indent=2) + "\n").encode()
            verified_put(adapter, args.prefix.rstrip("/") + "/manifest.json", body)
            save(out / "manifest.private.json", manifest)
            save(out / "complete.private.json", {"manifestSha256": digest(body),
                                                   "manifestBytes": len(body), **done})
            print(json.dumps({"stage": "complete", **done}), flush=True)
        except BaseException:
            # EOF is a cooperative exporter stop at the current closed shard.
            proc.stdin.close()
            proc.wait(timeout=30)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "mask", "countries", "identity-report", "exporter", "adapter", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--source-rows", required=True, type=int)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--shard-id-start", required=True, type=int)
    args = parser.parse_args()
    if not args.prefix.startswith("catalog/") or ".." in args.prefix:
        parser.error("A dedicated catalog prefix is required")
    publish(args)


if __name__ == "__main__":
    main()
