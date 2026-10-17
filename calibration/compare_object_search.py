"""Bounded offline measurements of pinned native Object search replies.

This accepts a path-free query packet and exact source TSV, never an account,
index download or executable. A match measures saved replies, not provenance,
coverage, quality, device qualification or permission to contribute.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from calibration.compare_object_indexes import ComparisonError, digest, read, require, save, strict_json
from community.object_canary import regular
from community.object_index import HOT_CONCEPTS, OBJECT_CLASSES

CONTRACT = "vision-object-query-replay-v1"
MAX_PACKET, MAX_RESULT, MAX_SOURCE = 128 * 1024, 8 * 1024**2, 1024**2
QUERY_FIELDS = {"name", "query", "route", "classIds", "hotConceptId", "semanticText",
                "minimumConfidence", "resultCount", "cameraGenerations", "includeCountries",
                "excludeCountries", "rejectRoadNames", "minimumGlobalLocation"}
CLASSES = dict(OBJECT_CLASSES)


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def text(value, maximum=256):
    return isinstance(value, str) and 0 < len(value) <= maximum and value.strip() == value \
        and not any(ord(c) < 32 for c in value)


def pinned(path, checksum, maximum):
    raw = read(path, maximum)
    require(isinstance(checksum, str) and len(checksum) == 64
            and all(c in "0123456789abcdef" for c in checksum)
            and digest(raw) == checksum, "search_comparison_pin_mismatch")
    return raw


def query_packet(raw):
    packet = strict_json(raw)
    require(isinstance(packet, dict) and set(packet) == {"contract", "resultPruneMeters", "queries"}
            and packet["contract"] == CONTRACT and number(packet["resultPruneMeters"], 0, 10000)
            and isinstance(packet["queries"], list) and 1 <= len(packet["queries"]) <= 32,
            "invalid_object_query_packet")
    names = set()
    for query in packet["queries"]:
        require(isinstance(query, dict) and set(query) == QUERY_FIELDS
                and text(query["name"]) and text(query["query"])
                and query["name"] not in names
                and number(query["minimumConfidence"], 0, 1)
                and type(query["resultCount"]) is int and 1 <= query["resultCount"] <= 100
                and type(query["rejectRoadNames"]) is bool
                and (query["minimumGlobalLocation"] is None
                     or type(query["minimumGlobalLocation"]) is int
                     and 0 <= query["minimumGlobalLocation"] < 2**53), "invalid_object_replay_query")
        names.add(query["name"])
        for field in ("classIds", "cameraGenerations", "includeCountries", "excludeCountries"):
            values = query[field]
            require(isinstance(values, list) and len(values) <= 80
                    and all(type(v) is int and v in CLASSES if field == "classIds" else text(v, 64)
                            for v in values)
                    and len(values) == len(set(values)), "invalid_object_query_filter")
        route, classes, hot, semantic = (query[k] for k in ("route", "classIds", "hotConceptId", "semanticText"))
        require((route == "common" and classes and hot is None and semantic is None)
                or (route == "hot" and not classes and type(hot) is int
                    and 0 <= hot < len(HOT_CONCEPTS) and semantic is None)
                or (route == "semantic" and not classes and hot is None and text(semantic)),
                "invalid_object_query_route")
    return packet


def source_locations(raw, global_start):
    require(type(global_start) is int and 0 <= global_start < 2**53 - 1024, "invalid_search_global_start")
    lines = raw.decode("utf-8").splitlines()
    require(1 <= len(lines) <= 1000, "invalid_search_source_count")
    result = {}
    for line in lines:
        fields = line.split("\t")
        require(len(fields) == 12, "invalid_search_source_row")
        values = [float(value) for value in fields[2:7]]
        index = int(fields[11])
        require(all(math.isfinite(value) for value in values) and -90 <= values[0] <= 90
                and -180 <= values[1] <= 180 and text(fields[7]) and text(fields[8], 64)
                and text(fields[9], 64) and global_start <= index < global_start + len(lines)
                and index not in result, "invalid_search_source_identity")
        result[index] = dict(zip(("lat", "lng", "heading", "pitch", "zoom"), values),
                             panoId=fields[7], country=fields[8], cameraGeneration=fields[9],
                             hasRoadName=fields[10].strip().lower() in ("1", "true", "has road name", "has_road_name"),
                             globalLocationId=index)
    return result


def distance(left, right):
    lat, lng, other_lat, other_lng = (math.radians(v) for v in
        (left["lat"], left["lng"], right["lat"], right["lng"]))
    a = math.sin((lat - other_lat) / 2)**2 + math.cos(lat) * math.cos(other_lat) * math.sin((lng - other_lng) / 2)**2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def validate_result(raw, packet, locations):
    result = strict_json(raw)
    require(isinstance(result, dict) and set(result) == {"contractVersion", "totalLocations", "queries"}
            and type(result["contractVersion"]) is int and result["contractVersion"] == 2
            and type(result["totalLocations"]) is int and result["totalLocations"] == len(locations)
            and isinstance(result["queries"], list) and len(result["queries"]) == len(packet["queries"]),
            "invalid_object_search_result")
    for query, response in zip(packet["queries"], result["queries"]):
        require(isinstance(response, dict) and set(response) == {"name", "query", "mode", "hits"}
                and response["name"] == query["name"] and response["query"] == query["query"]
                and response["mode"] == "objects" and isinstance(response["hits"], list)
                and len(response["hits"]) <= query["resultCount"], "object_search_query_identity_mismatch")
        seen, panos, previous, accepted = set(), set(), None, []
        for hit in response["hits"]:
            require(isinstance(hit, dict) and set(hit) == {"locationIndex", "similarity", "viewOffset", "location", "object"}
                    and type(hit["locationIndex"]) is int and hit["locationIndex"] in locations
                    and hit["locationIndex"] not in seen
                    and number(hit["similarity"], -1, 1) and type(hit["viewOffset"]) is int
                    and 0 <= hit["viewOffset"] < 6, "invalid_object_search_hit")
            index, score = hit["locationIndex"], hit["similarity"]
            location, found = hit["location"], hit["object"]
            expected = locations[index]
            require(isinstance(location, dict) and set(location) == set(expected)
                    and all(type(location[k]) is type(v) if type(v) in (str, bool, int) else number(location[k], -1e10, 1e10)
                            for k, v in expected.items())
                    and location == expected, "object_search_location_identity_mismatch")
            require(expected["panoId"] not in panos and all(distance(expected, p) >= packet["resultPruneMeters"] for p in accepted),
                    "object_search_pruning_mismatch")
            require(previous is None or (-score, index) >= previous, "object_search_rank_order_invalid")
            require((query["minimumGlobalLocation"] is None or index >= query["minimumGlobalLocation"])
                    and (not query["rejectRoadNames"] or not expected["hasRoadName"])
                    and (not query["cameraGenerations"] or expected["cameraGeneration"] in query["cameraGenerations"])
                    and (not query["includeCountries"] or expected["country"] in query["includeCountries"])
                    and expected["country"] not in query["excludeCountries"], "object_search_filter_mismatch")
            fields = {"className", "lane", "confidence", "supportCount", "heading", "pitch", "zoom", "bboxArea"}
            if query["route"] == "common": fields.add("classId")
            require(isinstance(found, dict) and set(found) == fields and found["lane"] == query["route"]
                    and number(found["confidence"], query["minimumConfidence"], 1)
                    and type(found["supportCount"]) is int and 0 <= found["supportCount"] <= 255
                    and number(found["heading"], 0, 360) and number(found["pitch"], -90, 90)
                    and number(found["zoom"], 0, 20) and number(found["bboxArea"], 0, 1), "invalid_object_search_aim")
            require((query["route"] == "common" and type(found["classId"]) is int
                     and found["classId"] in query["classIds"] and found["className"] == CLASSES[found["classId"]])
                    or (query["route"] == "hot" and found["className"] == HOT_CONCEPTS[query["hotConceptId"]])
                    or (query["route"] == "semantic" and found["className"] == query["query"]), "object_search_class_mismatch")
            seen.add(index); panos.add(expected["panoId"]); accepted.append(expected); previous = (-score, index)
    return result


def measurements(reference, candidate):
    queries = []
    for ordinal, (left, right) in enumerate(zip(reference["queries"], candidate["queries"])):
        gold = {h["locationIndex"]: h for h in left["hits"]}
        actual = {h["locationIndex"]: h for h in right["hits"]}
        shared = gold.keys() & actual.keys()
        left_order, right_order = list(gold), list(actual)
        ranks = {index: rank for rank, index in enumerate(right_order)}
        inversions = [abs(gold[a]["similarity"] - gold[b]["similarity"])
                      for i, a in enumerate(left_order) for b in left_order[i + 1:]
                      if a in shared and b in shared and ranks[a] > ranks[b]]
        entry = {"ordinal": ordinal, "referenceHits": len(gold), "candidateHits": len(actual),
                 "sharedHits": len(shared), "missingHits": len(gold.keys() - actual.keys()),
                 "extraHits": len(actual.keys() - gold.keys()), "sameOrder": left_order == right_order,
                 "bothEmpty": not gold and not actual,
                 "rankInversions": len(inversions), "maximumInvertedReferenceScoreGap": max(inversions, default=0.0),
                 "classDifferences": sum(gold[k]["object"].get("classId") != actual[k]["object"].get("classId") for k in shared),
                 "viewDifferences": sum(gold[k]["viewOffset"] != actual[k]["viewOffset"] for k in shared),
                 "supportDifferences": sum(gold[k]["object"]["supportCount"] != actual[k]["object"]["supportCount"] for k in shared),
                 "maximumScoreDifference": max((abs(gold[k]["similarity"] - actual[k]["similarity"]) for k in shared), default=None)}
        for field in ("confidence", "pitch", "zoom", "bboxArea"):
            entry["maximum" + field[0].upper() + field[1:] + "Difference"] = max(
                (abs(gold[k]["object"][field] - actual[k]["object"][field]) for k in shared), default=None)
        entry["maximumHeadingDegrees"] = max((abs((gold[k]["object"]["heading"] - actual[k]["object"]["heading"] + 180) % 360 - 180)
                                               for k in shared), default=None)
        entry["leadingSets"] = {str(n): set(left_order[:n]) == set(right_order[:n]) for n in (10, 100)}
        queries.append(entry)
    return {"version": 1, "scope": "offline-object-native-search-comparison", "status": "COMPLETE",
            "exactResultMatch": reference == candidate, "queries": queries,
            "qualified": False, "referenceProvenanceVerified": False, "identicalPixelsVerified": False,
            "officialCoverageVerified": False, "nativeExecutionVerified": False, "serverAuthorization": False}


def compare(reference, reference_pin, candidate, candidate_pin, packet_path, packet_pin, source_path, source_pin, global_start=0):
    inputs = [(reference, reference_pin, MAX_RESULT), (candidate, candidate_pin, MAX_RESULT),
              (packet_path, packet_pin, MAX_PACKET), (source_path, source_pin, MAX_SOURCE)]
    left, right, packet_raw, source = [pinned(*item) for item in inputs]
    packet, locations = query_packet(packet_raw), source_locations(source, global_start)
    result = measurements(validate_result(left, packet, locations), validate_result(right, packet, locations))
    result.update(referenceResultSha256=reference_pin, candidateResultSha256=candidate_pin,
                  queryPacketSha256=packet_pin, sourceSha256=source_pin, globalStart=global_start, locations=len(locations))
    require([pinned(*item) for item in inputs] == [left, right, packet_raw, source], "search_comparison_inputs_changed")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference", "candidate", "query-packet", "source"):
        parser.add_argument("--" + name, type=Path, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    parser.add_argument("--global-start", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    output = regular(args.out.absolute().parent, directory=True) / args.out.name
    inputs = [args.reference, args.candidate, args.query_packet, args.source]
    require(all(not output.is_relative_to(p.absolute().parent)
                and not p.absolute().is_relative_to(output) for p in inputs), "search_comparison_output_overlaps_input")
    output.mkdir(exist_ok=False)
    report = output / "object-search-comparison.json"
    save(report, {"status": "INCOMPLETE", "qualified": False})
    try:
        result = compare(args.reference, args.reference_sha256, args.candidate, args.candidate_sha256,
                         args.query_packet, args.query_packet_sha256, args.source, args.source_sha256, args.global_start)
        save(report, result)
        print("Saved Object searches compared; this is not contribution approval.")
        return 0
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
        save(report, {"status": "FAILED", "failureCode": "object_search_comparison_failed", "qualified": False})
        print("Search comparison failed. The report is preserved.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
