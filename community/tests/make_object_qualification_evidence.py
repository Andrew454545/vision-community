"""Emit a fresh synthetic Python-to-JavaScript adapter fixture, never approval."""
import argparse
from pathlib import Path

from community.object_canary import fingerprint
from community.search_snapshot import encoded
from community.tests import test_object_qualification_evidence as fixtures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    cls = fixtures.SavedObjectQualificationEvidenceTests
    cls.setUpClass()
    try:
        case = cls()
        case.setUp()
        adapter = case.adapter()
        proof = adapter.evidence(case.request, now=fixtures.NOW)
        engine, score = case.engine, case.engine.scores.policy
        p = {'version': 1, 'scope': 'saved-full-object-sample-qualification-v1', 'policyId': engine.policy['policyId'],
            'policySha256': engine.policy_sha256, 'scorePolicySha256': engine.scores.policy_sha256,
            'fixtureSha256': engine.scores.fixture.sha256, 'referenceBundleSha256': engine.reference_sha256,
            'frozenViewsManifestSha256': engine.reference['frozenViews']['sha256'],
            'sourceSha256': engine.reference['source']['sha256'], 'locations': proof['report']['locations'],
            'profiles': {case.request['profileId']: fingerprint({'execution': 'cpu', 'threads': 1})},
            'resource': score['resource'], 'validFrom': score['validFrom'], 'validUntil': score['validUntil']}
        packet = {'scope': 'synthetic-private-adapter-fixture-no-inference', 'now': fixtures.NOW,
            'policy': p, 'proof': proof, 'request': case.request}
        with args.out.open('xb') as stream:
            stream.write(encoded(packet))
    finally:
        cls.doClassCleanups()


if __name__ == '__main__':
    main()
