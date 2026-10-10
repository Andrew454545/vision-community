import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from calibration import compare_object_search as comparison


def query(**changes):
    return {"name": "private-query", "query": "private text", "route": "common", "classIds": [3],
            "hotConceptId": None, "semanticText": None, "minimumConfidence": 0.01, "resultCount": 100,
            "cameraGenerations": ["gen4"], "includeCountries": [], "excludeCountries": [],
            "rejectRoadNames": False, "minimumGlobalLocation": None, **changes}


class SearchComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.inputs = self.root / "inputs"; self.inputs.mkdir()
        self.packet = {"contract": comparison.CONTRACT, "resultPruneMeters": 0, "queries": [query()]}
        self.source = b"".join(f"map\t{i}\t{i}\t{i}\t0\t0\t0\tprivate-pano-{i}\tUSA\tgen4\tfalse\t{i}\n".encode() for i in range(3))
        self.locations = comparison.source_locations(self.source, 0)
        self.gold = {"contractVersion": 2, "totalLocations": 3, "queries": [{"name": "private-query", "query": "private text",
            "mode": "objects", "hits": [self.hit(0, 0.9), self.hit(1, 0.8), self.hit(2, 0.7)]}]}
        self.actual = copy.deepcopy(self.gold)

    def hit(self, index, score):
        return {"locationIndex": index, "similarity": score, "viewOffset": 0,
                "location": copy.deepcopy(self.locations[index]), "object": {"classId": 3, "className": "car", "lane": "common",
                "confidence": 0.9, "supportCount": 2, "heading": 359, "pitch": 10, "zoom": 2, "bboxArea": 0.1}}

    def write(self, name, value):
        path = self.inputs / name
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        path.write_bytes(raw)
        return path, comparison.digest(raw)

    def result(self):
        return comparison.compare(*self.write("gold.json", self.gold), *self.write("actual.json", self.actual),
            *self.write("queries.json", self.packet), *self.write("source.tsv", self.source))

    def test_identical_results_are_measured_without_approval_or_private_values(self):
        result = self.result()
        self.assertTrue(result["exactResultMatch"])
        self.assertEqual(result["queries"][0]["sharedHits"], 3)
        for key in ("qualified", "referenceProvenanceVerified", "identicalPixelsVerified", "officialCoverageVerified",
                    "nativeExecutionVerified", "serverAuthorization"):
            self.assertFalse(result[key])
        raw = json.dumps(result)
        for private in ("private-query", "private text", "private-pano", str(self.root)):
            self.assertNotIn(private, raw)

    def test_rank_changes_expose_inverted_reference_gap_and_aim_changes(self):
        hits = self.actual["queries"][0]["hits"]
        hits[0], hits[1] = hits[1], hits[0]
        hits[0]["similarity"], hits[1]["similarity"] = 0.91, 0.89
        hits[0]["object"].update(heading=1, supportCount=3)
        result = self.result()["queries"][0]
        self.assertFalse(result["sameOrder"])
        self.assertEqual(result["rankInversions"], 1)
        self.assertAlmostEqual(result["maximumInvertedReferenceScoreGap"], 0.1)
        self.assertEqual(result["maximumHeadingDegrees"], 2)
        self.assertEqual(result["supportDifferences"], 1)
        self.assertTrue(result["leadingSets"]["10"])

    def test_missing_extra_and_no_shared_results_are_explicit(self):
        self.gold["queries"][0]["hits"] = [self.hit(0, 0.9)]
        self.actual["queries"][0]["hits"] = [self.hit(1, 0.8)]
        result = self.result()["queries"][0]
        self.assertEqual((result["missingHits"], result["extraHits"], result["sharedHits"]), (1, 1, 0))
        self.assertIsNone(result["maximumScoreDifference"])
        self.assertFalse(result["bothEmpty"])

    def test_empty_replies_do_not_imply_hits_were_tested(self):
        for reply in (self.gold, self.actual): reply["queries"][0]["hits"] = []
        result = self.result()["queries"][0]
        self.assertTrue(result["bothEmpty"])
        self.assertEqual(result["sharedHits"], 0)
        self.assertIsNone(result["maximumHeadingDegrees"])

    def test_all_three_native_routes_are_validated(self):
        for route, changes, found in [
            ("hot", {"classIds": [], "hotConceptId": 0}, {"className": "bird nest"}),
            ("semantic", {"classIds": [], "semanticText": "red car"}, {"className": "private text"})]:
            self.packet["queries"] = [query(route=route, **changes)]
            for reply in (self.gold, self.actual):
                for hit in reply["queries"][0]["hits"]:
                    hit["object"].pop("classId", None); hit["object"].update(lane=route, **found)
            self.assertTrue(self.result()["exactResultMatch"])

    def test_path_injection_unknown_query_fields_and_duplicate_names_are_refused(self):
        for change in ({"runtimeManifest": "private-path"}, {"resultCount": True}, {"classIds": [True]},
                       {"classIds": [3, 3]}, {"includeCountries": [[]]}, {"minimumConfidence": float("inf")}):
            with self.subTest(change=change):
                self.packet["queries"] = [query(**change)]
                with self.assertRaises(ValueError): self.result()
        self.packet["queries"] = [query(), query()]
        with self.assertRaises(ValueError): self.result()

    def test_duplicate_and_nonfinite_json_are_refused(self):
        for raw in (b'{"contract":"x","contract":"y"}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.assertRaises(ValueError): comparison.query_packet(raw)
        self.actual["queries"][0]["hits"][0]["similarity"] = float("nan")
        with self.assertRaises(ValueError): self.result()

    def test_wrong_query_identity_reordered_queries_and_unknown_hit_fields_are_refused(self):
        for mutate in (lambda r: r.update(totalLocations=2),
                       lambda r: r["queries"][0].update(name="other"),
                       lambda r: r["queries"][0]["hits"][0].update(privatePath="anything"),
                       lambda r: r["queries"][0]["hits"][0].update(locationIndex=True)):
            self.actual = copy.deepcopy(self.gold); mutate(self.actual)
            with self.assertRaises(ValueError): self.result()

    def test_wrong_source_identity_duplicate_hits_and_unsorted_scores_are_refused(self):
        for mutate in (lambda hits: hits[0]["location"].update(lat=9),
                       lambda hits: hits.append(copy.deepcopy(hits[0])),
                       lambda hits: hits.reverse(),
                       lambda hits: hits[0]["object"].update(classId=2)):
            self.actual = copy.deepcopy(self.gold); mutate(self.actual["queries"][0]["hits"])
            with self.assertRaises(ValueError): self.result()

    def test_all_native_filters_are_checked(self):
        for changes in ({"minimumGlobalLocation": 1}, {"cameraGenerations": ["gen3"]},
                        {"includeCountries": ["CAN"]}, {"excludeCountries": ["USA"]}):
            self.packet["queries"] = [query(**changes)]
            with self.assertRaisesRegex(ValueError, "filter_mismatch"): self.result()
        self.packet["queries"] = [query(rejectRoadNames=True)]
        self.source = self.source.replace(b"false", b"true")
        self.locations = comparison.source_locations(self.source, 0)
        for reply in (self.gold, self.actual):
            for hit in reply["queries"][0]["hits"]: hit["location"] = self.locations[hit["locationIndex"]]
        with self.assertRaisesRegex(ValueError, "filter_mismatch"): self.result()

    def test_distance_and_duplicate_panorama_pruning_are_checked(self):
        self.packet["resultPruneMeters"] = 1
        self.source = self.source.replace(b"\t1\t1\t1\t0", b"\t1\t0\t0\t0")
        self.locations = comparison.source_locations(self.source, 0)
        for reply in (self.gold, self.actual):
            for hit in reply["queries"][0]["hits"]: hit["location"] = self.locations[hit["locationIndex"]]
        with self.assertRaisesRegex(ValueError, "pruning_mismatch"): self.result()

    def test_bad_pin_changed_inputs_and_oversized_files_are_refused(self):
        path, pin = self.write("queries.json", self.packet)
        with self.assertRaisesRegex(ValueError, "pin_mismatch"): comparison.pinned(path, "0" * 64, comparison.MAX_PACKET)
        with self.assertRaisesRegex(ValueError, "input_limit"): comparison.pinned(path, pin, 1)
        original = comparison.pinned
        calls = 0
        def changed(*args):
            nonlocal calls
            calls += 1
            if calls == 5: Path(args[0]).write_bytes(b"changed")
            return original(*args)
        with patch.object(comparison, "pinned", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "pin_mismatch"): self.result()

    def test_failed_cli_is_private_and_never_overwrites_evidence(self):
        args = []
        for flag, name, value in (("reference", "gold.json", self.gold), ("candidate", "actual.json", self.actual),
                                 ("query-packet", "queries.json", self.packet), ("source", "source.tsv", self.source)):
            path, pin = self.write(name, value)
            args += ["--" + flag, str(path), "--" + flag + "-sha256", "0" * 64 if flag == "reference" else pin]
        output = self.root / "report"; args += ["--out", str(output)]
        with patch("sys.stdout", new=io.StringIO()): self.assertEqual(comparison.main(args), 1)
        report = (output / "object-search-comparison.json").read_bytes()
        self.assertEqual(json.loads(report)["status"], "FAILED")
        self.assertNotIn(str(self.root).encode(), report)
        with self.assertRaises(FileExistsError): comparison.main(args)
        self.assertEqual((output / "object-search-comparison.json").read_bytes(), report)


if __name__ == "__main__": unittest.main()
