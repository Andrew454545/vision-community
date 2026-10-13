"""Finite synthetic loopback integration fixture; no authentic inference."""
import sys
import threading
import time

from community import object_qualification_host as host
from community.object_canary import fingerprint
from community.search_snapshot import encoded
from community.tests import test_object_qualification_host as fixtures


def main():
    current = int(time.time())
    # All policies, permits, outputs, models, profiles and accounts below are
    # synthetic test material. This never creates an actual transfer consent.
    fixtures.NOW = current
    fixtures.fixtures.NOW = current
    fixtures.fixtures.index_fixture.NOW = current
    cls = fixtures.OwnedSampleTests
    cls.setUpClass()
    case, server, thread = cls(), None, None
    try:
        case.setUp()
        owned = case.owned_store()
        server = host.make_server(owned, 'synthetic-private-sample-secret-0000000000')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        e, s = case.engine, case.engine.scores.policy
        policy = {'version': 1, 'scope': 'saved-full-object-sample-qualification-v1', 'policyId': e.policy['policyId'],
            'policySha256': e.policy_sha256, 'scorePolicySha256': e.scores.policy_sha256,
            'fixtureSha256': e.scores.fixture.sha256, 'referenceBundleSha256': e.reference_sha256,
            'frozenViewsManifestSha256': e.reference['frozenViews']['sha256'],
            'sourceSha256': e.reference['source']['sha256'], 'locations': 100,
            'profiles': {case.request['profileId']: fingerprint({'execution': 'cpu', 'threads': 1})},
            'resource': s['resource'], 'validFrom': s['validFrom'], 'validUntil': s['validUntil']}
        print(encoded({'scope': 'synthetic-owned-sample-host-no-inference', 'port': server.server_port,
            'policy': policy, 'request': case.request}).decode(), end='', flush=True)
        closed = threading.Event()
        def wait_parent():
            sys.stdin.buffer.read(1)
            closed.set()
        threading.Thread(target=wait_parent, daemon=True).start()
        return 0 if closed.wait(180) else 124
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(2)
        case.doCleanups()
        cls.doClassCleanups()


if __name__ == '__main__':
    raise SystemExit(main())
