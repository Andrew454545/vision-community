import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from community.owner_search_agent import OwnerSearchAgent, HTTPSCoordinator, OwnerSearchError, _exclusive, MAX_REPLY
from community.search_snapshot import encoded


def job():
    # JavaScript's number spelling must survive the Python transport unchanged.
    raw = '{"contractVersion":2,"policyId":"fixture","runtimeSha256":"' + 'd'*64 + '","snapshotSha256":"' + 'e'*64 + '","requestSha256":"' + 'c'*64 + '","query":{"lane":"scene","prompt":"private café","examples":[],"excluded":[{"lat":1e-7,"lng":2}]}}'
    return {"jobId": "a"*32, "claimToken": "b"*64, "claimUntil": 300, "expiresAt": 3600, "requestJson": raw}


class Engine:
    def __init__(self):
        self.calls = []
        self.failure = False

    def search(self, request, *, raw_query):
        self.calls.append((copy.deepcopy(request), raw_query))
        if self.failure:
            raise ValueError("PRIVATE PROMPT, SECRET and native stderr must not appear")
        return {**{k: v for k, v in request.items() if k != "query"}, "processedLocations": 0, "hits": []}


class Coordinator:
    def __init__(self, value):
        self.job = value
        self.calls = []
        self.delivery_error = None
        self.lose_reply = False
        self.committed = set()
        self.malformed = False

    def post(self, action, value):
        self.calls.append((action, copy.deepcopy(value)))
        if action == "claim":
            saved, self.job = self.job, None
            return {"job": saved, **({"retryAfterSeconds": 30} if saved is None else {})}
        if self.delivery_error:
            raise self.delivery_error
        if self.malformed:
            return {"completed": True, "searchId": "wrong"}
        self.committed.add(value["jobId"])
        if self.lose_reply:
            self.lose_reply = False
            raise OwnerSearchError("coordinator_unavailable")
        return {"completed": True, "searchId": value["jobId"]} if action == "complete" else {"failed": True, "charged": False}


class OwnerSearchAgentTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name).resolve()
        self.coordinator, self.engine = Coordinator(job()), Engine()

    def agent(self):
        return OwnerSearchAgent(self.coordinator, {"scene": self.engine}, self.state)

    def membership_result(self):
        value = json.loads(job()['requestJson'])
        member = '{"sourceIndex":0,"locationId":1,"outputSha256":"'+ 'f'*64 + '\",' + \
            '"pose":{"lat":1e-7,"lng":20,"heading":90,"pitch":0,"zoom":0,"panoId":"fictional-pano",' + \
            '"capture":"fictional","country":"Côte d’Ivoire","cameraGeneration":"gen1"}}'
        return {**{k:v for k,v in value.items() if k!='query'},'processedLocations':1,
            'hits':[{'sourceIndex':0,'locationId':1,'outputSha256':'f'*64,'score':.9,'viewOffset':0}],
            'membership':[{'memberJson':member,'siblings':[]}]}

    def test_optional_scene_proofs_preserve_exact_member_json_and_existing_packet_identity(self):
        packet=self.membership_result();before=encoded(packet)
        self.assertIs(OwnerSearchAgent._result(packet,'scene',{'resultCount':1}),packet)
        self.assertEqual(encoded(packet),before)
        self.assertIn('"lat":1e-7',packet['membership'][0]['memberJson'])

    def test_scene_proof_extension_cannot_enter_object_lane_or_exceed_its_request_bound(self):
        packet=self.membership_result()
        for lane,count in (('object',1),('scene',True),('scene',0),('scene',65),('scene','1')):
            with self.subTest(lane=lane,count=count),self.assertRaises(ValueError):
                OwnerSearchAgent._result(packet,lane,{'resultCount':count})

    def test_unknown_echo_fields_or_malformed_scene_proofs_cannot_enter_a_new_outbox(self):
        changes=[lambda p:p.update(query='PRIVATE prompt'),lambda p:p['hits'][0].update(prompt='PRIVATE'),
            lambda p:p['hits'][0].update(sourceIndex=False),lambda p:p['hits'][0].update(sourceIndex=-1),
            lambda p:p['hits'][0].update(sourceIndex=100000),lambda p:p['hits'][0].update(locationId=True),
            lambda p:p['hits'][0].update(score=float('nan')),lambda p:p['hits'][0].update(viewOffset=True),
            lambda p:p['membership'][0].update(extra='PRIVATE'),lambda p:p['membership'].clear(),
            lambda p:p['membership'][0].update(memberJson='x'*8193),
            lambda p:p['membership'][0].update(siblings=['e'*64]*18),
            lambda p:p['membership'][0].update(siblings=['wrong']),
            lambda p:p['membership'][0].update(memberJson='{"pose":"PRIVATE"}'),
            lambda p:p['hits'][0].update(outputSha256='e'*64)]
        for change in changes:
            packet=self.membership_result();change(packet)
            with self.assertRaises(ValueError):OwnerSearchAgent._result(packet,'scene',{'resultCount':1})

    def test_proof_completion_lost_ack_replays_exact_bytes_before_unavailable_engine(self):
        value=json.loads(self.coordinator.job['requestJson']);value['query']['resultCount']=1
        self.coordinator.job['requestJson']=json.dumps(value,ensure_ascii=False)
        self.coordinator.lose_reply=True
        with patch.object(self.engine,'search',return_value=self.membership_result()) as compute:
            with self.assertRaisesRegex(OwnerSearchError,'coordinator_unavailable'):self.agent().run_once()
            saved=(self.state/'outbox.json').read_bytes()
            compute.side_effect=AssertionError('Saved completion must not recompute')
            self.assertEqual(self.agent().run_once(),{'status':'completed'})
        self.assertEqual(compute.call_count,1)
        self.assertEqual(encoded({'action':'complete','body':self.coordinator.calls[-1][1]}),saved)
        self.assertIn(b'1e-7',saved)

    def test_invalid_proof_reports_only_fixed_failure_without_echoing_private_native_details(self):
        value=json.loads(self.coordinator.job['requestJson']);value['query']['resultCount']=1
        self.coordinator.job['requestJson']=json.dumps(value)
        packet=self.membership_result();packet['membership'][0]['extra']='PRIVATE native detail'
        with patch.object(self.engine,'search',return_value=packet):
            self.assertEqual(self.agent().run_once(),{'status':'failed'})
        self.assertEqual(self.coordinator.calls[-1][0],'fail')
        self.assertNotIn('result',self.coordinator.calls[-1][1])
        self.assertNotIn(b'PRIVATE',(self.state/'failure-owner_search_failed.json').read_bytes())

    @staticmethod
    def binding(value=None):
        request = json.loads((value or job())["requestJson"])
        return {key: request[key] for key in ("contractVersion", "policyId", "runtimeSha256", "snapshotSha256")}

    def test_explicit_bindings_are_copied_and_advertised_without_changing_query_bytes(self):
        pin = self.binding()
        agent = OwnerSearchAgent(self.coordinator, {"scene": self.engine}, self.state, bindings={"scene": pin})
        pin["policyId"] = "changed-after-construction"
        self.assertEqual(agent.run_once(), {"status": "completed"})
        self.assertEqual(self.coordinator.calls[0], ("claim", {"lanes": ["scene"], "bindings": {"scene": self.binding()}}))
        self.assertIn(b'"lat":1e-7', self.engine.calls[0][1])

    def test_both_engines_route_with_distinct_independently_pinned_bindings(self):
        object_job = job()
        object_request = json.loads(object_job["requestJson"])
        object_request.update(policyId="objects.fixture", runtimeSha256="1"*64, snapshotSha256="2"*64)
        object_request["query"]["lane"] = "object"
        object_job.update(jobId="c"*32, requestJson=json.dumps(object_request))
        object_engine = Engine()
        pins = {"scene": self.binding(), "object": self.binding(object_job)}
        agent = OwnerSearchAgent(self.coordinator, {"scene": self.engine, "object": object_engine}, self.state, bindings=pins)
        self.assertEqual(agent.run_once(), {"status": "completed"})
        self.coordinator.job = object_job
        self.assertEqual(agent.run_once(), {"status": "completed"})
        self.assertEqual(len(self.engine.calls), 1)
        self.assertEqual(len(object_engine.calls), 1)
        self.assertEqual(self.coordinator.calls[0], ("claim", {"lanes": ["object", "scene"], "bindings": pins}))
        self.assertEqual(object_engine.calls[0][0]["policyId"], "objects.fixture")

    def test_wrong_claim_identity_is_failed_without_invoking_either_engine(self):
        for field, wrong in (("policyId", "wrong"), ("runtimeSha256", "0"*64), ("snapshotSha256", "0"*64), ("contractVersion", 1)):
            with self.subTest(field=field):
                pins = {"scene": self.binding()}
                self.coordinator.job = job()
                value = json.loads(self.coordinator.job["requestJson"])
                value[field] = wrong
                self.coordinator.job["requestJson"] = json.dumps(value)
                agent = OwnerSearchAgent(self.coordinator, {"scene": self.engine}, self.state, bindings=pins)
                self.assertEqual(agent.run_once(), {"status": "failed"})
                self.assertEqual(self.coordinator.calls[-1][0], "fail")
        self.assertEqual(self.engine.calls, [])

    def test_wrong_result_binding_or_digest_never_reaches_a_completion_outbox(self):
        for field in ("policyId", "runtimeSha256", "snapshotSha256", "requestSha256"):
            with self.subTest(field=field):
                self.coordinator.job = job()
                original = self.engine.search
                def changed(request, *, raw_query, selected=field):
                    return {**original(request, raw_query=raw_query), selected: "wrong"}
                with patch.object(self.engine, "search", changed):
                    agent = OwnerSearchAgent(self.coordinator, {"scene": self.engine}, self.state, bindings={"scene": self.binding()})
                    self.assertEqual(agent.run_once(), {"status": "failed"})
                self.assertEqual(self.coordinator.calls[-1][0], "fail")
                self.assertFalse((self.state / "outbox.json").exists())

    def test_malformed_or_partial_binding_configuration_never_contacts_the_coordinator(self):
        pin = self.binding()
        invalid = [[], {}, {"object": pin}, {"scene": pin, "object": pin}, {"scene": {}},
                   {"scene": {**pin, "contractVersion": 2.0}}, {"scene": {**pin, "policyId": "space invalid"}},
                   {"scene": {**pin, "runtimeSha256": [pin["runtimeSha256"]]}},
                   {"scene": {**pin, "snapshotSha256": "A"*64}}, {"scene": {**pin, "extra": True}}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(OwnerSearchError, "invalid_owner_bindings"):
                OwnerSearchAgent(self.coordinator, {"scene": self.engine}, self.state, bindings=value)
        self.assertEqual(self.coordinator.calls, [])

    def test_saved_completion_replays_unchanged_before_claiming_with_new_pins(self):
        self.coordinator.lose_reply = True
        with self.assertRaises(OwnerSearchError):
            OwnerSearchAgent(self.coordinator, {"scene": self.engine}, self.state, bindings={"scene": self.binding()}).run_once()
        pins = {"scene": {**self.binding(), "snapshotSha256": "9"*64}}
        saved = (self.state / "outbox.json").read_bytes()
        self.assertEqual(OwnerSearchAgent(self.coordinator, {"scene": self.engine}, self.state, bindings=pins).run_once(),
                         {"status": "completed"})
        self.assertEqual(encoded({"action": "complete", "body": self.coordinator.calls[-1][1]}), saved)
        self.assertEqual(len(self.engine.calls), 1)
        self.assertEqual([action for action, _ in self.coordinator.calls], ["claim", "complete", "complete"])

    def test_claim_computes_locally_retains_exact_json_spelling_and_sends_no_account_credentials(self):
        self.assertEqual(self.agent().run_once(), {"status": "completed"})
        request, raw = self.engine.calls[0]
        self.assertEqual(request["query"]["prompt"], "private café")
        self.assertIn(b'"lat":1e-7', raw)
        self.assertIn('café'.encode(), raw)
        self.assertEqual(self.coordinator.calls[0], ("claim", {"lanes": ["scene"]}))
        self.assertEqual(set(self.coordinator.calls[1][1]), {"jobId", "claimToken", "result"})
        self.assertEqual(list(p.name for p in self.state.iterdir()), ["agent.lock"])

    def test_lost_reply_is_replayed_after_restart_before_new_claim_without_recomputing(self):
        self.coordinator.lose_reply = True
        with self.assertRaisesRegex(OwnerSearchError, "coordinator_unavailable"):
            self.agent().run_once()
        saved = (self.state / "outbox.json").read_bytes()
        self.assertNotIn('private café'.encode(), saved)
        self.assertEqual(self.agent().run_once(), {"status": "completed"})
        self.assertEqual(len(self.engine.calls), 1)
        self.assertEqual([action for action, _ in self.coordinator.calls], ["claim", "complete", "complete"])
        self.assertEqual(len(self.coordinator.committed), 1)

    def test_quota_outage_and_ambiguous_ack_preserve_exact_outbox_and_prevent_further_claims(self):
        self.coordinator.delivery_error = OwnerSearchError("coordinator_unavailable", 429)
        with self.assertRaises(OwnerSearchError):
            self.agent().run_once()
        saved = (self.state / "outbox.json").read_bytes()
        for error in [OwnerSearchError("coordinator_unavailable", 401), OwnerSearchError("coordinator_unavailable", 503)]:
            self.coordinator.delivery_error = error
            with self.assertRaises(OwnerSearchError):
                self.agent().run_once()
            self.assertEqual((self.state / "outbox.json").read_bytes(), saved)
        self.coordinator.delivery_error = None
        self.coordinator.malformed = True
        with self.assertRaisesRegex(OwnerSearchError, "invalid_owner_reply"):
            self.agent().run_once()
        self.assertEqual(len(self.engine.calls), 1)

    def test_cancelled_deleted_or_expired_claim_discards_only_the_private_stale_completion(self):
        self.coordinator.delivery_error = OwnerSearchError("coordinator_unavailable", 503)
        with self.assertRaises(OwnerSearchError):
            self.agent().run_once()
        self.coordinator.delivery_error = OwnerSearchError("search_claim_lost", 409)
        self.assertEqual(self.agent().run_once(), {"status": "claim_lost"})
        self.assertFalse((self.state / "outbox.json").exists())
        self.assertEqual(len(self.engine.calls), 1)

    def test_native_failure_keeps_only_fixed_first_report_and_replays_release_when_delivery_fails(self):
        self.engine.failure = True
        self.coordinator.delivery_error = OwnerSearchError("coordinator_unavailable", 503)
        with self.assertRaises(OwnerSearchError):
            self.agent().run_once()
        self.assertEqual(json.loads((self.state / "outbox.json").read_text())["action"], "fail")
        report = self.state / "failure-owner_search_failed.json"
        self.assertEqual(json.loads(report.read_text()), {"success": False, "error": "owner_search_failed"})
        self.coordinator.delivery_error = None
        self.assertEqual(self.agent().run_once(), {"status": "failed"})
        self.coordinator.job = job()
        self.assertEqual(self.agent().run_once(), {"status": "failed"})
        self.assertEqual(json.loads(report.read_text())["error"], "owner_search_failed")
        for path in self.state.iterdir():
            self.assertNotIn(b"PRIVATE PROMPT", path.read_bytes())

    def test_fully_written_pending_outbox_survives_crash_before_rename(self):
        original = self.agent()
        with patch('community.owner_search_agent.os.replace', side_effect=OSError('interrupted rename')):
            with self.assertRaisesRegex(OwnerSearchError, 'owner_outbox_recovery_required'):
                original.run_once()
        self.assertTrue((self.state / "outbox.pending").exists())
        self.assertEqual(self.agent().run_once(), {"status": "completed"})
        self.assertEqual(len(self.engine.calls), 1)

    def test_partial_pending_write_records_failure_and_allows_unpaid_lease_recovery(self):
        self.coordinator.job = None
        (self.state / "outbox.pending").write_bytes(b'{"partial":')
        self.assertEqual(self.agent().run_once(), {"status": "idle", "retryAfterSeconds": 30})
        self.assertFalse((self.state / "outbox.pending").exists())
        self.assertTrue((self.state / "failure-owner_outbox_incomplete.json").exists())
        self.assertFalse(self.engine.calls)

    def test_pause_and_stop_markers_make_no_network_or_engine_calls(self):
        for marker in ("PAUSE", "STOP"):
            path = self.state / marker
            path.write_text("hold")
            self.assertEqual(self.agent().run_once(), {"status": "paused"})
            path.unlink()
        self.assertFalse(self.coordinator.calls)
        self.assertFalse(self.engine.calls)

    def test_pause_during_native_work_saves_completion_without_delivering_until_resumed(self):
        original = self.engine.search
        def search(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.state / "PAUSE").write_text("hold")
            return result
        self.engine.search = search
        self.assertEqual(self.agent().run_once(), {"status": "paused"})
        self.assertTrue((self.state / "outbox.json").exists())
        self.assertEqual(len(self.coordinator.calls), 1)
        self.assertEqual(self.agent().run_once(), {"status": "paused"})
        (self.state / "PAUSE").unlink()
        self.assertEqual(self.agent().run_once(), {"status": "completed"})
        self.assertEqual(len(self.engine.calls), 1)

    def test_second_writer_cannot_claim_or_overwrite_the_outbox(self):
        with _exclusive(self.state):
            with self.assertRaisesRegex(OwnerSearchError, "owner_agent_busy"):
                self.agent().run_once()
        self.assertFalse(self.coordinator.calls)

    def test_malformed_claim_cannot_reach_the_native_engine(self):
        for change in [{"jobId": "../escape"}, {"claimToken": "bad"}, {"claimUntil": 9999},
                       {"requestJson": "x"*81921}, {"extra": "private"}]:
            self.coordinator.job = {**job(), **change}
            with self.assertRaisesRegex(OwnerSearchError, "invalid_owner_reply"):
                self.agent().run_once()
        self.assertFalse(self.engine.calls)

    def test_an_engine_echoing_the_query_cannot_store_or_upload_it_in_a_completion(self):
        self.engine.search = lambda request, **_: {**request, "processedLocations": 0, "hits": []}
        self.assertEqual(self.agent().run_once(), {"status": "failed"})
        self.assertEqual(self.coordinator.calls[-1][0], "fail")

    def test_https_origin_is_explicit_and_credentials_are_never_forwarded_on_redirect(self):
        for origin in ["http://fixture.invalid", "https://user:pass@fixture.invalid", "https://fixture.invalid/path",
                       "https://fixture.invalid:444", "https://fixture.invalid/?secret=x", "https://fixture.invalid/#frag"]:
            with self.assertRaises(OwnerSearchError):
                HTTPSCoordinator(origin, "f"*64)
        coordinator = HTTPSCoordinator("https://fixture.invalid/", "f"*64)
        with patch('community.owner_search_agent.http.client.HTTPSConnection') as factory:
            connection = factory.return_value
            response = connection.getresponse.return_value
            response.status = 302
            response.read.return_value = b'{"redirect":"https://elsewhere.invalid"}'
            with self.assertRaises(OwnerSearchError):
                coordinator.post("claim", {"lanes": ["scene"]})
            self.assertEqual(factory.call_count, 1)
            connection.close.assert_called_once()
        with self.assertRaisesRegex(OwnerSearchError, "invalid_owner_route"):
            coordinator.post("../../escape", {})
        with self.assertRaisesRegex(OwnerSearchError, "owner_payload_limit"):
            coordinator.post("complete", {"payload": "x"*MAX_REPLY})

    def test_https_bounded_reply_never_persists_an_upstream_error_or_secret(self):
        coordinator = HTTPSCoordinator("https://fixture.invalid", "f"*64)
        with patch('community.owner_search_agent.http.client.HTTPSConnection') as factory:
            response = factory.return_value.getresponse.return_value
            response.status = 500
            response.read.return_value = b'{"error":"PRIVATE SECRET FROM UPSTREAM"}'
            with self.assertRaisesRegex(OwnerSearchError, "coordinator_unavailable") as failure:
                coordinator.post("claim", {})
            self.assertNotIn("PRIVATE", str(failure.exception))
            response.read.return_value = b"x"*81921
            with self.assertRaisesRegex(OwnerSearchError, "owner_reply_limit"):
                coordinator.post("claim", {})

    def test_https_binding_configuration_errors_request_operator_repair_without_forwarding_details(self):
        coordinator = HTTPSCoordinator("https://fixture.invalid", "f"*64)
        with patch('community.owner_search_agent.http.client.HTTPSConnection') as factory:
            response = factory.return_value.getresponse.return_value
            response.status = 409
            for code in ("search_binding_required", "search_binding_changed"):
                response.read.return_value = json.dumps({"error": code, "details": "PRIVATE SECRET"}).encode()
                with self.assertRaisesRegex(OwnerSearchError, "owner_binding_configuration_required") as failure:
                    coordinator.post("claim", {})
                self.assertEqual(failure.exception.status, 409)
                self.assertNotIn("PRIVATE", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
