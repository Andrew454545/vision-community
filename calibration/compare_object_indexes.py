"""Offline comparison of two pinned, complete native v4 Object indexes.

Measures stored features, not inference provenance or production eligibility.
Locations must have identical TSV bytes. Identical live panorama identifiers
alone do not establish identical downloaded pixels or preprocessing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct

from community.object_canary import regular
from community.object_index import CODEBOOK_SHA256, manifest_file_names, validate_object_index
from community.object_snapshot import public_manifest
from community.vision_index import VisionIndexError

MAX_MANIFEST = 1024 * 1024
MAX_FILES = 32_000_000
CODEBOOK_BYTES = 128 * 256 * 4 * 4
LEASE = "0" * 32


class ComparisonError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ComparisonError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, maximum):
    path = regular(path)
    require(path.stat().st_size <= maximum, "comparison_input_limit")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum, "comparison_input_limit")
    return raw


def strict_json(raw):
    def pairs(entries):
        result = {}
        for key, value in entries:
            require(key not in result, "duplicate_manifest_key")
            result[key] = value
        return result
    def constant(_value):
        raise ComparisonError("nonfinite_manifest_value")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def load_index(path, checksum, source):
    path = regular(path)
    raw = read(path, MAX_MANIFEST)
    require(isinstance(checksum, str) and len(checksum) == 64
            and digest(raw) == checksum, "manifest_pin_mismatch")
    document = strict_json(raw)
    # Paths/source allocation labels are not inference features. Do not follow
    # manifest source paths or change input bytes. Use the same v4 envelope and
    # content validator as submissions, with an in-memory diagnostic label.
    manifest = public_manifest(document)
    names = manifest_file_names(manifest)
    require(len(names) == len(set(names)) and len(names) <= 87
            and all(isinstance(name, str) and name.isascii()
                    and name.endswith(".bin") and name[0].isalnum()
                    and all(c.isalnum() or c in ".-" for c in name)
                    for name in names), "invalid_comparison_file")
    files, remaining = {}, MAX_FILES
    for name in names:
        files[name] = read(path.parent / name, remaining)
        remaining -= len(files[name])
    require(type(manifest.get("globalStart")) is int
            and 0 <= manifest["globalStart"] < 2**53, "invalid_global_start")
    items = []
    for ordinal, line in enumerate(source.decode("utf-8").splitlines()):
        fields = line.split("\t")
        require(len(fields) == 12, "invalid_comparison_source")
        items.append({"locationId": ordinal + 1, "panoId": fields[7],
                      "lat": float(fields[2]), "lng": float(fields[3])})
    try:
        validate_object_index({**manifest, "sourceId": "community-" + LEASE}, files,
                              source, items, lease_id=LEASE, global_start=manifest["globalStart"])
    except VisionIndexError:
        raise ComparisonError("invalid_comparison_index") from None
    return manifest, files, digest(raw)


class PQ128Codebook:
    """VISION's 128 subquantizers, 256 four-float centroids each, little endian.

    The caller supplies an independent pin. CLI comparison always requires
    the canonical v4 model pin; no embeddings or centroids enter the report.
    """
    def __init__(self, raw, checksum):
        require(isinstance(raw, bytes) and len(raw) == CODEBOOK_BYTES,
                "invalid_comparison_codebook_size")
        require(digest(raw) == checksum, "comparison_codebook_pin_mismatch")
        self.values = struct.unpack("<131072f", raw)
        require(all(math.isfinite(value) for value in self.values),
                "nonfinite_comparison_codebook")
        self.sha256 = checksum

    def decode(self, codes):
        require(isinstance(codes, bytes) and len(codes) == 128, "invalid_semantic_codes")
        return tuple(value for subquantizer, code in enumerate(codes)
                     for value in self.values[(subquantizer * 256 + code) * 4:
                                              (subquantizer * 256 + code) * 4 + 4])


def embedding_metrics():
    return {"pairsCompared": 0, "excludedRejectedPairs": 0,
            "undefinedCosinePairs": 0, "undefinedRelativeL2Pairs": 0,
            "minimumCosineSimilarity": None, "maximumAbsoluteL2": 0.0,
            "maximumRelativeL2": None}


def measure_embeddings(result, reference, candidate):
    require(len(reference) == len(candidate) == 512, "invalid_decoded_embedding_dimensions")
    result["pairsCompared"] += 1
    gold_norm = math.sqrt(math.fsum(value * value for value in reference))
    actual_norm = math.sqrt(math.fsum(value * value for value in candidate))
    error = math.sqrt(math.fsum((a - b) ** 2 for a, b in zip(reference, candidate)))
    result["maximumAbsoluteL2"] = max(result["maximumAbsoluteL2"], error)
    if gold_norm == 0 or actual_norm == 0:
        result["undefinedCosinePairs"] += 1
    else:
        cosine = math.fsum(a * b for a, b in zip(reference, candidate)) / (gold_norm * actual_norm)
        cosine = min(1.0, max(-1.0, cosine))
        previous = result["minimumCosineSimilarity"]
        result["minimumCosineSimilarity"] = cosine if previous is None else min(previous, cosine)
    if gold_norm == 0:
        result["undefinedRelativeL2Pairs"] += 1
    else:
        relative = error / gold_norm
        previous = result["maximumRelativeL2"]
        result["maximumRelativeL2"] = relative if previous is None else max(previous, relative)


def compare_lane(reference, candidate):
    def records(raw):
        return {row[0]: row for offset in range(0, len(raw), 32)
                for row in [struct.unpack("<I5fH3BH", raw[offset:offset + 31])]}
    gold, actual = records(reference), records(candidate)
    shared = gold.keys() & actual.keys()
    result = {"referenceRecords": len(gold), "candidateRecords": len(actual),
              "missingRecords": len(gold.keys() - actual.keys()),
              "extraRecords": len(actual.keys() - gold.keys()),
              "sharedRecords": len(shared), "discreteDifferences": 0,
              "maximumScoreDifference": 0.0, "maximumHeadingDegrees": 0.0,
              "maximumPitchDegrees": 0.0, "maximumZoomDifference": 0.0,
              "maximumAreaDifference": 0.0, "maximumConfidenceDifference": 0.0}
    for local in shared:
        left, right = gold[local], actual[local]
        result["discreteDifferences"] += sum(a != b for a, b in zip(left[6:10], right[6:10]))
        differences = [abs(a - b) for a, b in zip(left[1:6], right[1:6])]
        differences[1] = min(differences[1], 360 - differences[1])
        for key, delta in zip(("maximumScoreDifference", "maximumHeadingDegrees",
                               "maximumPitchDegrees", "maximumZoomDifference",
                               "maximumAreaDifference"), differences):
            result[key] = max(result[key], delta)
        result["maximumConfidenceDifference"] = max(result["maximumConfidenceDifference"],
                                                      abs(left[10] - right[10]) / 65535)
    return result


def compare_semantic(reference, candidate, codebook=None, active_locations=None):
    require(len(reference) == len(candidate) and len(reference) % (16 * 144) == 0,
            "incomplete_semantic_comparison")
    locations = len(reference) // (16 * 144)
    if active_locations is None:
        active_locations = [True] * locations
    require(len(active_locations) == locations and all(type(value) is bool for value in active_locations),
            "invalid_semantic_comparison_mask")
    result = {"recordsCompared": len(reference) // 144, "differentRecords": 0,
              "differentCodeBytes": 0, "differentFaces": 0,
              "maximumBoxDifference": 0.0, "maximumLogitShiftDifference": 0.0,
              "maximumLogitScaleDifference": 0.0,
              "decodedEmbeddingDistanceMeasured": False,
              "embeddingMetrics": embedding_metrics() if codebook is not None else None}
    for offset in range(0, len(reference), 144):
        left, right = reference[offset:offset + 144], candidate[offset:offset + 144]
        result["differentRecords"] += left != right
        result["differentCodeBytes"] += sum(a != b for a, b in zip(left[:128], right[:128]))
        result["differentFaces"] += left[140] != right[140]
        if codebook is not None:
            if active_locations[offset // (16 * 144)]:
                measure_embeddings(result["embeddingMetrics"], codebook.decode(left[:128]), codebook.decode(right[:128]))
            else:
                result["embeddingMetrics"]["excludedRejectedPairs"] += 1
        for a, b in zip(struct.unpack_from("<4H", left, 128), struct.unpack_from("<4H", right, 128)):
            result["maximumBoxDifference"] = max(result["maximumBoxDifference"], abs(a - b) / 65535)
        for key, a, b in zip(("maximumLogitShiftDifference", "maximumLogitScaleDifference"),
                             struct.unpack_from("<2e", left, 136), struct.unpack_from("<2e", right, 136)):
            result[key] = max(result[key], abs(a - b))
    if codebook is not None:
        result["codebookSha256"] = codebook.sha256
        result["decodedEmbeddingDistanceMeasured"] = result["embeddingMetrics"]["pairsCompared"] > 0
    return result


def compare(reference, reference_sha256, candidate, candidate_sha256, source_path, codebook_path=None):
    source = read(source_path, MAX_MANIFEST)
    codebook_raw = read(codebook_path, CODEBOOK_BYTES) if codebook_path is not None else None
    codebook = PQ128Codebook(codebook_raw, CODEBOOK_SHA256) if codebook_raw is not None else None
    gold, left, gold_sha = load_index(reference, reference_sha256, source)
    actual, right, actual_sha = load_index(candidate, candidate_sha256, source)
    if codebook is not None:
        require(gold["semantic"]["codebookSha256"] == actual["semantic"]["codebookSha256"] == codebook.sha256,
                "comparison_codebook_identity_mismatch")
    require(gold["countries"] == actual["countries"]
            and gold["globalStart"] == actual["globalStart"], "comparison_identity_mismatch")
    # Quality masks can change; the policy and its independent authorities must
    # be identical before interpreting those changes as execution differences.
    counts = {"records", "bytes", "sha256", "keptViews", "blurRejectedViews",
              "darkTunnelRejectedViews", "fullyRejectedLocations", "permanentlyInvalidLocations"}
    quality = lambda m: {k: v for k, v in m.get("viewQuality", {}).items() if k not in counts}
    require(quality(gold) == quality(actual), "comparison_quality_policy_mismatch")
    lanes = {}
    for group in ("classes", "hotConcepts"):
        lanes[group] = [{"id": entry["id"], **compare_lane(left[entry["file"]], right[entry["file"]])}
                        for entry in gold[group]]
    quality_file = gold.get("viewQuality", {}).get("file")
    quality_changes = (sum(left[quality_file][i:i + 4] != right[quality_file][i:i + 4]
                           for i in range(0, len(left[quality_file]), 8)) if quality_file else 0)
    # A zero-view native placeholder has no searchable embedding. Keep its raw
    # differences visible, but never treat a decoded placeholder as real output.
    active_locations = [bool(left[quality_file][i * 8 + 1] and right[quality_file][i * 8 + 1])
                        if quality_file else True for i in range(gold["totalLocations"])]
    result = {"version": 1, "scope": "offline-object-index-comparison", "status": "COMPLETE",
              "referenceManifestSha256": gold_sha, "candidateManifestSha256": actual_sha,
              "sourceSha256": digest(source), "locations": gold["totalLocations"],
              "exactFeatureMatch": left == right, "viewQualityDifferences": quality_changes,
              "lanes": lanes, "semantic": compare_semantic(left["semantic-pq128.bin"], right["semantic-pq128.bin"],
                                                              codebook, active_locations),
              "qualified": False, "referenceProvenanceVerified": False,
              "identicalPixelsVerified": False, "nativeSearchParityVerified": False,
              "serverAuthorization": False}
    result["nativeCounters"] = {label: {key: manifest.get(key, 0) for key in
                                          ("fetchErrors", "inferenceErrors", "permanentlyInvalidLocations")}
                                for label, manifest in (("reference", gold), ("candidate", actual))}
    # Catch files changed during comparison, including the explicitly selected
    # TSV. Preserve the original pins; never silently accept replacement bytes.
    require(read(source_path, MAX_MANIFEST) == source, "comparison_inputs_changed")
    if codebook_raw is not None:
        require(read(codebook_path, CODEBOOK_BYTES) == codebook_raw, "comparison_inputs_changed")
    require(load_index(reference, gold_sha, source)[:2] == (gold, left)
            and load_index(candidate, actual_sha, source)[:2] == (actual, right),
            "comparison_inputs_changed")
    return result


def save(path, value):
    temporary = path.with_suffix(".next")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-manifest", type=Path, required=True)
    parser.add_argument("--reference-sha256", required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--codebook", type=Path, help="Optional canonical pinned OWLv2 PQ128 codebook")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    # Fresh sibling output only: never write into a reference/candidate folder.
    parent = regular(args.out.absolute().parent, directory=True)
    output = parent / args.out.name
    inputs = [args.reference_manifest, args.candidate_manifest, args.source]
    if args.codebook is not None:
        inputs.append(args.codebook)
    folders = [args.reference_manifest.absolute().parent, args.candidate_manifest.absolute().parent]
    if args.codebook is not None:
        folders.append(args.codebook.absolute().parent)
    for folder in folders:
        require(not output.is_relative_to(folder), "comparison_output_overlaps_input")
    for input_path in inputs:
        require(not input_path.absolute().is_relative_to(output), "comparison_output_overlaps_input")
    output.mkdir(exist_ok=False)
    report = output / "object-index-comparison.json"
    save(report, {"status": "INCOMPLETE", "qualified": False})
    try:
        result = compare(args.reference_manifest, args.reference_sha256,
                         args.candidate_manifest, args.candidate_sha256, args.source, args.codebook)
        save(report, result)
        print("Object index comparison complete; this is not contribution approval.")
        return 0
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
        save(report, {"status": "FAILED", "failureCode": "object_index_comparison_failed", "qualified": False})
        print("Object index comparison failed. The report is preserved.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
