"""Fresh Python-to-JavaScript private protection packet; synthetic data only."""
import argparse
from pathlib import Path

from community.search_snapshot import encoded
from community.tests import test_object_eligibility as fixtures


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    case=fixtures.ObjectEligibilityTests()
    try:
        case.setUp()
        value=case.adapter.evidence(case.request)
        rows=[{'id':r['locationId'],'evidence_sha256':r['coverageEvidenceSha256']} for r in value['records']]
        packet={'scope':'synthetic-private-live-object-protection-no-inference',
            'policy':case.policy,'request':case.request,'proof':value,'rows':rows}
        with args.out.open('xb') as stream:stream.write(encoded(packet))
    finally:case.doCleanups()


if __name__=='__main__':main()
