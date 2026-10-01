import copy
import hashlib
import http.client
import json
import os
import platform
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from community import native_scene_search as native
from community.search_snapshot import (CONFIRMED_RESOURCE, build_snapshot, cache_file,
                                       digest, encoded)


def query(**changes):
    return {"lane": "scene", "prompt": "a road", "examples": [], "excluded": [], "queryName": "road",
            "descriptionWeight": 100, "viewDirection": "bestOfFour", "resultCount": 200,
            "maxPerCountry": 25, "filters": {"mode": "all", "countries": [], "generations": []},
            "objectConfidence": "balanced", "rejectRoadNames": False, "minimumGlobalLocation": None, **changes}


class NativeSceneSearchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.runtime = self.root / "runtime"
        (self.runtime / "models").mkdir(parents=True)
        self.binary = self.runtime / "native.exe"
        self.binary.write_bytes(b"synthetic-unexecuted-native-binary")
        (self.runtime / "countries.txt").write_text("Italy\nUSA\n", encoding="utf-8")
        for name in native.MODEL_FILES:
            (self.runtime / "models" / name).write_bytes(b"synthetic-model-" + name.encode())
        self.config = {"version": 1, "contractVersion": 2, "nativeLayout": 4,
                       "adapterSha256": native.file_digest(Path(native.__file__)),
                       "pythonVersion": platform.python_version(),
                       "sourceFiles": {name: {"bytes": (Path(native.__file__).parent/name).stat().st_size,
                            "sha256":native.file_digest(Path(native.__file__).parent/name)} for name in native.SOURCE_FILES},
                       "policyId": "synthetic-only", "executable": "native.exe", "queryModes": ["textOnly"],
                       "files": {p.relative_to(self.runtime).as_posix(): {"bytes": p.stat().st_size,
                                  "sha256": native.file_digest(p)} for p in self.runtime.rglob("*") if p.is_file()}}
        self.config_path = self.runtime / "runtime.json"
        self.config_path.write_bytes(encoded(self.config))
        cache = self.root / "cache"
        cache.mkdir()
        key = "four-view-v4/synthetic-only.i8"
        records = [(b"\x00\x3c" + bytes([i+1])*768)*4 for i in range(4)]
        cache_file(cache, key).write_bytes(b"".join(records))
        self.rows = [{"id": i+30, "asset_id": f"synthetic-pano-{i}", "capture": "synthetic-only", "lane": "scene",
                      "model": "synthetic-input", "state": "published", "contributor_id": "private-account-never-exported",
                      "lat": 10+i, "lon": 20, "heading": 270.25, "pitch": 5, "zoom": 1, "country": "Italy" if i<2 else "USA",
                      "camera_generation": "gen4", "output_sha256": digest(records[i]), "four_view_sha256": digest(records[i]),
                      "location_output_sha256": digest(records[i]), "four_view_key": key} for i in range(4)]
        inventory = encoded({"version": 1, "resource": CONFIRMED_RESOURCE, "rows": self.rows})
        policy = encoded({"version": 1, "policyId": "synthetic-only", "inputModel": "synthetic-input",
                          "outputModel": "vision-four-view-v4", "references": [
                              {"assetId": r["asset_id"], "capture": r["capture"], "lat": r["lat"], "lng": r["lon"],
                               "heading": r["heading"], "pitch": r["pitch"], "zoom": r["zoom"],
                               "approvedSha256": [r["output_sha256"]]} for r in self.rows]})
        (self.root / "inventory.json").write_bytes(inventory)
        (self.root / "policy.json").write_bytes(policy)
        self.snapshot = self.root / "snapshot"
        report = build_snapshot(self.root / "inventory.json", digest(inventory), self.root / "policy.json",
                                digest(policy), cache, self.snapshot)
        self.snapshot_pin = report["snapshotSha256"]
        self.work = self.root / "work"
        self.work.mkdir()
        self.engine = self.start()

    def start(self, work=None):
        return native.NativeSceneEngine(self.config_path, digest(self.config_path.read_bytes()), self.snapshot,
                                        self.snapshot_pin, work or self.work)

    def request(self, q=None):
        q = q or query()
        return {"contractVersion": 2, "policyId": "synthetic-only", "runtimeSha256": self.engine.runtime_sha256,
                "snapshotSha256": self.snapshot_pin, "requestSha256": digest(json.dumps(q, ensure_ascii=False,
                separators=(",", ":")).encode()), "query": q}

    def output(self, definition, hits=None):
        return {"version": 4, "completed": True, "totalLocations": 4, "nextLocationIndex": 4,
                "fetchErrors": 0, "inferenceErrors": 0, "incompleteLocations": 0, "queries": [
                    {**{k: definition[k] for k in ("name", "query", "mode")}, "hits": hits if hits is not None else [
                        {"locationIndex": i, "similarity": .8-i*.1, "viewOffset": 0,
                         "location": copy.deepcopy(m["pose"])} for i, m in enumerate(self.engine.members)]}]}

    def fake_native(self, command, job, timeout):
        source = json.loads((job / "input.json").read_bytes())
        (job / "output.json").write_bytes(encoded(self.output(source["queries"][0])))

    def test_mount_preserves_contributed_records_ordinals_masks_without_account_ids(self):
        self.assertEqual((self.engine.index / "shard-000000.i8").read_bytes(), (self.snapshot / "scene-records.i8").read_bytes())
        self.assertEqual((self.engine.index / "shard-000000.mask").read_bytes(), bytes([15])*4)
        self.assertEqual([line.split("\t")[1] for line in (self.engine.index / "locations.tsv").read_text().splitlines()], ["30", "31", "32", "33"])
        self.engine.verify_mount()
        for p in self.engine.index.iterdir():
            self.assertNotIn(b"private-account-never-exported", p.read_bytes())
        with self.assertRaises(FileExistsError):
            self.start()

    def test_native_source_hash_includes_algorithm_prefix_and_known_fnv_bytes(self):
        source = self.root / "known-hash.tsv"
        source.write_bytes(b"hello")
        self.assertEqual(native.fnv_file(source), "fnv1a64:a430d84680aabd0b")

    def test_real_native_command_is_allowlisted_and_no_shell_or_reference_index_is_used(self):
        request = self.request()
        with patch.object(native, "run_native", side_effect=self.fake_native) as run:
            result = self.engine.search(request)
        self.assertEqual([h["locationId"] for h in result["hits"]], [30, 31, 32, 33])
        self.assertEqual(result["processedLocations"], 4)
        self.assertNotIn("query", result)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], [str(self.binary), "search-four-view-index"])
        self.assertEqual(command[command.index("--index-dir")+1], str(self.engine.index))
        self.assertFalse(list(self.work.glob("query-*")))

    def test_runtime_adapter_models_and_native_mount_changes_are_rejected_before_execution(self):
        for target in [self.binary, self.runtime / "models/text_model.onnx", self.engine.index / "shard-000000.mask"]:
            before = target.read_bytes()
            target.write_bytes(before+b"corrupt")
            with self.subTest(target=target.name), patch.object(native, "run_native") as run:
                with self.assertRaises(native.NativeSearchError):
                    self.engine.search(self.request())
                run.assert_not_called()
            target.write_bytes(before)
        # Model byte restoration with changed mtime must rebuild rather than lie
        # about the native size/mtime-based identity, even with valid strong pins.
        manifest = json.loads((self.engine.index / "manifest.json").read_bytes())
        manifest["modelIdentity"] = "changed"
        (self.engine.index / "manifest.json").write_bytes(encoded(manifest))
        with self.assertRaises(native.NativeSearchError):
            self.engine.verify_mount()

    def test_runtime_missing_assets_bad_pins_adapter_or_traversal_cannot_start(self):
        for change in [lambda c: c.update(adapterSha256="f"*64), lambda c: c.update(executable="../secret.exe"),
                       lambda c: c.update(pythonVersion="0.0.0"),
                       lambda c: c["sourceFiles"]["features.py"].update(sha256="f"*64),
                       lambda c: c["files"].pop("models/text_model.onnx"),
                       lambda c: c["files"]["native.exe"].update(sha256="f"*64)]:
            config = copy.deepcopy(self.config)
            change(config)
            self.config_path.write_bytes(encoded(config))
            new = self.root / f"invalid-{len(list(self.root.iterdir()))}"
            new.mkdir()
            with self.assertRaises(native.NativeSearchError):
                self.start(new)

    def test_gateway_pins_hash_and_unsupported_modes_lanes_roads_fail_closed(self):
        for field, value in [("contractVersion", 1), ("policyId", "other"), ("runtimeSha256", "f"*64),
                             ("snapshotSha256", "f"*64), ("requestSha256", "f"*64)]:
            request = self.request()
            request[field] = value
            with self.subTest(field=field), self.assertRaises(native.NativeSearchError):
                self.engine.search(request)
        for q in [query(lane="object"), query(rejectRoadNames=True), query(descriptionWeight=50),
                  query(resultCount=True), query(minimumGlobalLocation=-1), query(prompt=""), query(examples=[{}])]:
            with self.subTest(q=q), self.assertRaises(native.NativeSearchError):
                self.engine.search(self.request(q))

    def test_exact_gateway_json_spelling_is_retained_for_unicode_and_scientific_coordinates(self):
        q = query(prompt="雪の道", excluded=[{"panoId": "", "lat": 1e-7, "lng": 2}])
        raw_query = json.dumps(q, ensure_ascii=False, separators=(",", ":")).replace("1e-07", "1e-7").encode()
        request = self.request(q)
        request["requestSha256"] = digest(raw_query)
        raw = json.dumps({k: v for k,v in request.items() if k != "query"}, separators=(",", ":"))[:-1].encode() + b',"query":' + raw_query+b'}'
        self.assertEqual(native.query_bytes(raw), raw_query)
        with patch.object(native, "run_native", side_effect=self.fake_native):
            self.assertEqual(len(self.engine.search(native.strict_json(raw), raw_query=native.query_bytes(raw))["hits"]), 4)
        with self.assertRaisesRegex(native.NativeSearchError, "search_request_mismatch"):
            self.engine.search(request)

    def test_country_view_camera_import_exclusions_and_caps_preserve_score_order(self):
        q = query(resultCount=2, maxPerCountry=1, minimumGlobalLocation=1)
        d = self.engine.validate_request(self.request(q))
        self.assertEqual([h["sourceIndex"] for h in self.engine.select_hits(q, d, self.output(d), 4)], [1, 2])
        q = query(excluded=[{"panoId": "synthetic-pano-0", "lat": 80, "lng": 90}])
        d = self.engine.validate_request(self.request(q))
        self.assertEqual([h["sourceIndex"] for h in self.engine.select_hits(q, d, self.output(d), 4)], [1,2,3])
        q = query(filters={"mode":"include", "countries":["Italy"], "generations":["gen4"]}, viewDirection="right")
        d = self.engine.validate_request(self.request(q))
        self.assertEqual(d["includeCountries"], ["Italy"])
        self.assertEqual(d["viewOffsets"], [1])
        out = self.output(d)
        for h in out["queries"][0]["hits"]:
            h["viewOffset"] = 1
        with self.assertRaisesRegex(native.NativeSearchError, "native_filter_mismatch"):
            self.engine.select_hits(q, d, out, 4)

    def test_ties_invalid_ordinals_poses_views_scores_and_incomplete_native_results_are_denied(self):
        q = query()
        d = self.engine.validate_request(self.request(q))
        out = self.output(d)
        out["queries"][0]["hits"][1]["similarity"] = .8
        self.assertEqual([h["sourceIndex"] for h in self.engine.select_hits(q,d,out,4)], [0,1,2,3])
        cases = [lambda o: o.update(completed=False), lambda o: o.update(inferenceErrors=1),
                 lambda o: o["queries"][0]["hits"][0].update(locationIndex=True),
                 lambda o: o["queries"][0]["hits"][0].update(viewOffset=4),
                 lambda o: o["queries"][0]["hits"][0].update(similarity=float("nan")),
                 lambda o: o["queries"][0]["hits"][0]["location"].update(panoId="different"),
                 lambda o: o["queries"][0]["hits"].reverse()]
        for change in cases:
            out = self.output(d)
            change(out)
            with self.subTest(change=change), self.assertRaises(native.NativeSearchError):
                self.engine.select_hits(q,d,out,4)

    def test_candidate_exhaustion_fails_instead_of_returning_false_empty_or_short_search(self):
        q = query(resultCount=2, minimumGlobalLocation=2)
        d = self.engine.validate_request(self.request(q))
        out = self.output(d)
        out["queries"][0]["hits"] = out["queries"][0]["hits"][:2]
        with self.assertRaisesRegex(native.NativeSearchError, "search_candidate_budget_exceeded"):
            self.engine.select_hits(q,d,out,2)
        q = query(resultCount=1)
        self.assertEqual(len(self.engine.select_hits(q,d,out,2)), 1)

    def test_busy_timeouts_and_failures_leave_only_redacted_reports_and_release_slot(self):
        self.engine.busy.acquire()
        with self.assertRaisesRegex(native.NativeSearchError, "search_engine_busy"):
            self.engine.search(self.request())
        self.engine.busy.release()
        request = self.request(query(prompt="private-sensitive-prompt"))
        with patch.object(native, "run_native", side_effect=native.NativeSearchError("native_search_timeout")):
            with self.assertRaisesRegex(native.NativeSearchError, "native_search_timeout"):
                self.engine.search(request)
        self.assertFalse(list(self.work.glob("query-*")))
        report = next(self.work.glob("failure-*.json")).read_bytes()
        self.assertNotIn(b"private-sensitive-prompt", report)
        self.assertNotIn(str(self.root).encode(), report)
        with patch.object(native, "run_native", side_effect=self.fake_native):
            self.engine.search(request)

    def test_actual_helper_timeout_is_killed_and_native_log_growth_is_bounded(self):
        for index, script, reason in [(0, "import time; time.sleep(30)", "native_search_timeout"),
                                     (1, "import sys,time;sys.stdout.write('a'*1100000);sys.stdout.flush();time.sleep(30)", "native_output_limit")]:
            job = self.root / f"child-{index}"
            job.mkdir()
            with self.subTest(reason=reason), self.assertRaisesRegex(native.NativeSearchError, reason):
                native.run_native([sys.executable, "-c", script], job, 2)
        # Success/nonzero exits also use a real child, with no inherited secrets.
        job = self.root / "child-success"
        job.mkdir()
        script = "import os; assert 'VISION_SEARCH_ENGINE_SECRET' not in os.environ; assert all(os.environ[k]=='1' for k in ('RAYON_NUM_THREADS','VISION_ORT_THREADS','OMP_NUM_THREADS','ORT_NUM_THREADS'))"
        with patch.dict(os.environ, {key: '99' for key in ('RAYON_NUM_THREADS','VISION_ORT_THREADS','OMP_NUM_THREADS','ORT_NUM_THREADS')}):
            native.run_native([sys.executable, "-c", script], job, 2)

    def test_repeated_native_failure_preserves_one_original_report_without_unbounded_files(self):
        with patch.object(native, "run_native", side_effect=native.NativeSearchError("native_search_timeout")):
            for _ in range(3):
                with self.assertRaises(native.NativeSearchError):
                    self.engine.search(self.request())
        self.assertEqual(len(list(self.work.glob("failure-*.json"))), 1)
        self.assertFalse(list(self.work.glob("query-*")))

    def test_duplicate_json_nonfinite_and_linked_input_are_rejected(self):
        for raw in [b'{"query":{},"query":{}}', b'{"x":NaN}']:
            with self.assertRaises(native.NativeSearchError):
                native.strict_json(raw)
        link = self.root / "link"
        try:
            link.symlink_to(self.runtime, target_is_directory=True)
        except OSError:
            return  # No security/privilege changes to create links on Windows.
        with self.assertRaisesRegex(native.NativeSearchError, "linked_engine_path"):
            native.plain_path(link / "runtime.json")

    def test_actual_private_http_auth_route_bounds_success_and_failure_recovery(self):
        secret = "synthetic-local-only-secret-32-characters"
        server = native.make_server(self.engine, secret)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def post(body, auth=secret, path="/search", headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("POST", path, body, {"Authorization":"Bearer "+auth, "Content-Type":"application/json", **(headers or {})})
            response = connection.getresponse()
            result = response.status, response.getheader("Cache-Control"), json.loads(response.read())
            connection.close()
            return result
        self.assertEqual(post(b"{}", auth="wrong")[0], 401)
        self.assertEqual(post(b"{}", path="/elsewhere")[0], 404)
        # Reject the excessive declared length before reading its body. Sending
        # that unread body can reset TCP on Windows and hide the denial response.
        self.assertEqual(post(b"", headers={"Content-Length":str(native.MAX_REQUEST+1)})[0], 400)
        self.assertEqual(post(b'{"query":{},"query":{}}')[0], 503)
        with patch.object(native, "run_native", side_effect=self.fake_native):
            status, cache, result = post(json.dumps(self.request(), ensure_ascii=False, separators=(",", ":")).encode())
            self.assertEqual((status,cache), (200,"no-store"))
            self.assertEqual(result["processedLocations"], 4)
            self.assertEqual(post(json.dumps(self.request(query(lane="object"))).encode())[0], 503)


if __name__ == "__main__":
    unittest.main()
