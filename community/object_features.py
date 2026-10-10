"""Bounded validation of VISION v4 Object feature contents.

Hashes bind transport bytes, not inference. These checks reject malformed
records and inconsistent source/quality data; they never establish accuracy,
official coverage, device qualification or approval to publish.
"""
from __future__ import annotations

import binascii
import math
import re
import struct
import zlib

MAX_LOCATIONS = 1000
MAX_BYTES = 32_000_000
MAX_SOURCE_BYTES = 1024 * 1024
CAMERAS = {"badcam": 1, "gen1": 2, "gen2": 3, "gen3": 4, "gen4": 5, "trekker": 6}
ROAD_TRUE = {"1", "true", "has road name", "has_road_name"}


class FeatureError(ValueError):
    def __init__(self):
        super().__init__("verification_failed")


def require(condition):
    if not condition:
        raise FeatureError()


def crc8(raw):
    value = 0
    for byte in raw:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ (7 if value & 128 else 0)) & 255
    return value


def crc16(raw):
    return binascii.crc_hqx(raw, 0xffff)


def checked32(raw):
    require(len(raw) == 8 and struct.unpack_from("<I", raw, 4)[0] == zlib.crc32(raw[:4]))
    return raw[:4]


def semantic_record(raw):
    require(len(raw) == 144 and struct.unpack_from("<H", raw, 142)[0] == crc16(raw[:142])
            and raw[141] == 1 and raw[140] < 6)
    x1, y1, x2, y2 = struct.unpack_from("<4H", raw, 128)
    shift, scale = struct.unpack_from("<2e", raw, 136)
    require(x1 < x2 and y1 < y2 and math.isfinite(shift)
            and math.isfinite(scale) and scale > 0)
    return raw[140]


def placeholder(raw):
    return (raw[:128] == bytes(128)
            and raw[128:142] == struct.pack("<4H2e2B", 0, 0, 65535, 65535, 0, 1, 0, 1))


def validate_feature_contents(manifest, files, source):
    """Run after envelope validation; independently bound all content reads."""
    total = manifest.get("totalLocations")
    require(type(total) is int and 1 <= total <= MAX_LOCATIONS
            and isinstance(files, dict) and len(files) <= 87
            and all(isinstance(raw, bytes) for raw in files.values())
            and sum(map(len, files.values())) <= MAX_BYTES
            and isinstance(source, bytes) and 0 < len(source) <= MAX_SOURCE_BYTES)
    countries = manifest.get("countries")
    require(isinstance(countries, list) and 0 < len(countries) <= 65536
            and all(isinstance(c, str) for c in countries) and len(set(countries)) == len(countries))
    country_ids = {country: i for i, country in enumerate(countries)}
    offsets = files["location-offsets.bin"]
    metadata = files["location-metadata.bin"]
    require(len(offsets) == total * 8 and len(metadata) == total * 8)
    parts = source.split(b"\n")
    lines = [line + b"\n" for line in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
    require(len(lines) == total)
    expected, position = [], 0
    for i, line in enumerate(lines):
        require(struct.unpack_from("<Q", offsets, i * 8)[0] == position)
        position += len(line)
        fields = line.removesuffix(b"\n").removesuffix(b"\r").decode("utf-8").split("\t")
        require(len(fields) == 12 and all(not any(ord(c) < 32 or ord(c) == 127 for c in f) for f in fields)
                and fields[8] in country_ids)
        require(all(re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", f)
                    for f in fields[2:7]))
        values = [float(f) for f in fields[2:7]]
        require(all(math.isfinite(v) for v in values) and -90 <= values[0] <= 90
                and -180 <= values[1] <= 180 and 0 <= values[2] <= 360
                and -90 <= values[3] <= 90 and 0 <= values[4] <= 4)
        record = checked32(metadata[i * 8:(i + 1) * 8])
        identity = (country_ids[fields[8]], CAMERAS.get(fields[9].strip().lower(), 0),
                    int(fields[10].strip().lower() in ROAD_TRUE))
        require(record[3] <= 1 and (int.from_bytes(record[:2], "little"), record[2], record[3]) == identity)
        expected.append(identity)

    quality = manifest.get("viewQuality")
    require(quality is None or isinstance(quality, dict))
    masks = [63] * total
    if quality:
        require(isinstance(quality, dict))
        raw = files[quality["file"]]
        require(len(raw) == total * 8)
        counts = {"keptViews": 0, "blurRejectedViews": 0, "darkTunnelRejectedViews": 0,
                  "fullyRejectedLocations": 0, "permanentlyInvalidLocations": 0}
        for i in range(total):
            assessed, keep, blur, dark = checked32(raw[i * 8:(i + 1) * 8])
            require(not dark & 64)
            invalid = bool(dark & 128)
            dark &= 63
            if invalid:
                require(assessed == keep == blur == dark == 0)
            else:
                require(assessed == 63 and not (keep | blur) & 192
                        and keep | blur | dark == 63
                        and not (keep & blur or keep & dark or blur & dark))
            masks[i] = keep
            counts["keptViews"] += keep.bit_count()
            counts["blurRejectedViews"] += blur.bit_count()
            counts["darkTunnelRejectedViews"] += dark.bit_count()
            counts["fullyRejectedLocations"] += int(keep == 0)
            counts["permanentlyInvalidLocations"] += int(invalid)
        for key, value in counts.items():
            supplied = quality.get(key, 0) if key == "permanentlyInvalidLocations" else quality.get(key)
            require(type(supplied) is int and supplied == value)
        require(type(manifest.get("permanentlyInvalidLocations", 0)) is int
                and manifest.get("permanentlyInvalidLocations", 0) == counts["permanentlyInvalidLocations"])
    else:
        require(type(manifest.get("permanentlyInvalidLocations", 0)) is int
                and manifest.get("permanentlyInvalidLocations", 0) == 0)

    count = 0
    for entry in [*manifest["classes"], *manifest["hotConcepts"]]:
        raw = files[entry["file"]]
        require(len(raw) % 32 == 0 and len(raw) <= total * 32)
        previous = -1
        for start in range(0, len(raw), 32):
            record = raw[start:start + 32]
            require(record[31] == crc8(record[:31]) and record[28] <= 1)
            local, score, heading, pitch, zoom, area, country, camera, support, road, confidence = struct.unpack(
                "<I5fH3BH", record[:31])
            confidence /= 65535
            require(previous < local < total and masks[local] != 0 and support > 0
                    and (country, camera, road) == expected[local]
                    and all(math.isfinite(v) for v in (score, heading, pitch, zoom, area))
                    and 0 <= score <= 1 and score + 1e-7 >= entry["storageFloor"]
                    and abs(score - confidence) <= 0.5 / 65535 + 1e-7
                    and 0 <= heading < 360 and -90 <= pitch <= 90
                    and 0 <= zoom <= 4 and 0 <= area <= 1)
            previous = local
            count += 1
    raw = files["semantic-pq128.bin"]
    require(len(raw) == total * 16 * 144)
    for ordinal in range(total * 16):
        record = raw[ordinal * 144:(ordinal + 1) * 144]
        face = semantic_record(record)
        keep = masks[ordinal // 16]
        require(bool(keep & (1 << face)) if keep else placeholder(record))
    return {"locations": total, "commonAndHotRecords": count, "semanticRecords": total * 16,
            "qualityRecords": total if quality else 0}
