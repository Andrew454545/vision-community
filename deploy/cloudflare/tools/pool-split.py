"""Split a sealed identity mask into disjoint, bounded publication streams.

An optional verified prefix reuses already uploaded, ordered shards. The union
of that prefix and all output masks must equal every bit of the sealed input.
This tool is offline and never changes a source or a remote object.
"""
import argparse
import hashlib
import json
from pathlib import Path


def split(mask, source_rows, reused, parts):
    if len(mask) != (source_rows + 7) // 8 or (source_rows % 8 and mask[-1] >> (source_rows % 8)):
        raise ValueError("Mask bounds differ from the sealed source")
    if reused < 0 or parts < 1 or parts > 16:
        raise ValueError("Invalid split bounds")
    remaining = bytearray(mask)
    count = sum(byte.bit_count() for byte in mask)
    if reused > count:
        raise ValueError("Verified prefix exceeds the sealed eligible count")
    needed = reused
    for at, byte in enumerate(remaining):
        if not needed:
            break
        if byte.bit_count() <= needed:
            needed -= byte.bit_count()
            remaining[at] = 0
        else:
            for bit in range(8):
                if needed and byte & (1 << bit):
                    remaining[at] &= ~(1 << bit)
                    needed -= 1
    outputs = []
    for part in range(parts):
        start = len(mask) * part // parts
        end = len(mask) * (part + 1) // parts
        value = bytearray(len(mask))
        value[start:end] = remaining[start:end]
        outputs.append(value)
    # Complete byte comparison, in addition to cardinality. No hash-based
    # membership decisions or probabilistic duplicate checks are used.
    if b"".join(outputs[p][len(mask)*p//parts:len(mask)*(p+1)//parts]
                for p in range(parts)) != remaining:
        raise RuntimeError("Partition union differs from the sealed remainder")
    if sum(sum(b.bit_count() for b in value) for value in outputs) + reused != count:
        raise RuntimeError("Partition cardinality differs from the sealed input")
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mask", type=Path, required=True)
    parser.add_argument("--identity-report", type=Path, required=True)
    parser.add_argument("--source-rows", type=int, required=True)
    parser.add_argument("--reuse-verified-prefix", type=int, default=0)
    parser.add_argument("--parts", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = args.mask.read_bytes()
    authority = json.loads(args.identity_report.read_text())
    if authority["sourceRows"] != args.source_rows or authority["malformedInputIds"]:
        parser.error("The sealed identity authority has incompatible bounds or malformed input")
    if authority["identityComparison"] != "complete-22-byte-panorama-id":
        parser.error("Complete panorama identity authority is required")
    if sum(b.bit_count() for b in data) != authority["eligibleUnique"]:
        parser.error("Mask cardinality differs from the sealed identity authority")
    args.output.mkdir()  # Refuse to replace an earlier attempt.
    outputs = split(data, args.source_rows, args.reuse_verified_prefix, args.parts)
    original = hashlib.sha256(data).hexdigest()
    authority_pin = hashlib.sha256(args.identity_report.read_bytes()).hexdigest()
    report = {"sourceRows": args.source_rows, "originalMaskSha256": original,
              "originalIdentityReportSha256": authority_pin,
              "reusedVerifiedPrefix": args.reuse_verified_prefix, "parts": [],
              "completeDisjointUnionVerified": True}
    for serial, value in enumerate(outputs):
        path = args.output / f"part-{serial:02d}.bits"
        path.write_bytes(value)
        count = sum(b.bit_count() for b in value)
        identity = {"sourceRows": args.source_rows, "eligibleUnique": count,
                    "malformedInputIds": 0, "identityComparison": "complete-22-byte-panorama-id",
                    "derivedMaskSha256": hashlib.sha256(value).hexdigest(),
                    "originalMaskSha256": original, "disjointSubset": True,
                    "originalIdentityReportSha256": authority_pin,
                    "productionQualified": False}
        (args.output / f"part-{serial:02d}.json").write_text(json.dumps(identity) + "\n")
        report["parts"].append({"part": serial, "eligibleUnique": count,
                                "maskSha256": identity["derivedMaskSha256"]})
    (args.output / "split-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
