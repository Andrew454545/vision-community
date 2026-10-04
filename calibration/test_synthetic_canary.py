import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from calibration.synthetic_canary import MODELS, RGB_BYTES, create_sealed_inputs, image_bytes


class SyntheticCanaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'sealed'
        self.fixture = b'batch\t1\t0\t0\t70.54816\t0\t0\tJe141ivXzUUx4ro1j8_3vw\tTest\tunknown\tno road\n'
        self.pins = [{'name':name,'bytes':1,'sha256':'a'*64} for name in MODELS]

    def create(self, fixture=None, pins=None, checksum=None):
        raw = self.fixture if fixture is None else fixture
        return create_sealed_inputs(self.root,raw,self.pins if pins is None else pins,
            expected_fixture_sha256=hashlib.sha256(raw).hexdigest() if checksum is None else checksum)

    def test_independently_pinned_source_and_complete_deterministic_inventory(self):
        receipt = self.create()
        manifest = json.loads((self.root/'manifest.json').read_text())
        self.assertFalse(receipt['productionQualified'])
        self.assertFalse(receipt['photographicImagery'])
        self.assertFalse(receipt['liveImageryRetrieved'])
        self.assertEqual(len(list(self.root.iterdir())),5)
        self.assertEqual(len(manifest['frames']),4)
        for f in manifest['frames']:
            raw = (self.root/f['rgb']['name']).read_bytes()
            self.assertEqual(len(raw),RGB_BYTES)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),f['rgb']['sha256'])
            self.assertEqual(raw,image_bytes(f['ordinal'],f['view']))
        self.assertEqual(manifest['frames'][0]['headingBits'],'4051a3150dae3e6c')

    def test_every_view_and_image_family_is_deterministic(self):
        checks = [hashlib.sha256(image_bytes(n,v)).hexdigest() for n in (0,1) for v in range(4)]
        self.assertEqual(len(set(checks)),8)
        self.assertEqual(checks,[hashlib.sha256(image_bytes(n,v)).hexdigest() for n in (0,1) for v in range(4)])
        self.assertEqual(len(image_bytes(111,3)),RGB_BYTES)

    def test_invalid_or_changed_source_is_rejected_before_output(self):
        for raw in (b'',self.fixture*2,self.fixture.replace(b'70.54816',b'nan'),self.fixture.replace(b'Je141ivXzUUx4ro1j8_3vw',b'bad')):
            with self.subTest(raw=raw),self.assertRaises(ValueError): self.create(raw)
            self.assertFalse(self.root.exists())
        with self.assertRaisesRegex(ValueError,'fixture_pin_mismatch'): self.create(checksum='0'*64)
        self.assertFalse(self.root.exists())

    def test_models_require_all_four_independent_positive_pins(self):
        for pins in ([],self.pins[:-1],self.pins[:3]+[self.pins[0]],
                     [{**v,'bytes':True} for v in self.pins],[{**v,'sha256':'wrong'} for v in self.pins]):
            with self.subTest(pins=pins),self.assertRaisesRegex(ValueError,'model_pins'): self.create(pins=pins)
            self.assertFalse(self.root.exists())

    def test_existing_directory_is_never_overwritten_or_repaired(self):
        self.root.mkdir()
        sentinel = self.root/'keep'
        sentinel.write_bytes(b'old evidence')
        with self.assertRaises(FileExistsError): self.create()
        self.assertEqual(sentinel.read_bytes(),b'old evidence')

    def test_invalid_requests_cannot_expand_the_112_location_budget(self):
        for ordinal,view in ((True,0),(0,True),(-1,0),(112,0),(0,4)):
            with self.subTest(ordinal=ordinal,view=view),self.assertRaises(ValueError): image_bytes(ordinal,view)

    def test_version_one_pixel_anchors_cannot_change_silently(self):
        anchors = {(0,0):'317b3d114be7013d1c52ecd5da555cba171c5cf263e19c2a9f7a0e9cab1eeb6c',
                   (1,3):'788cddbbcb3c1f21b551e0678e35e986e11bbc309317d3cc2dfba6b46dd01be1',
                   (111,3):'f2724922404987459fd1cee61df09a21217ae96a9124d0540a46cfcceccb5848'}
        for key,digest in anchors.items():
            self.assertEqual(hashlib.sha256(image_bytes(*key)).hexdigest(),digest)

    def test_negative_full_turn_pose_matches_native_float_bits(self):
        self.create(self.fixture.replace(b'70.54816',b'-360'))
        manifest = json.loads((self.root/'manifest.json').read_text())
        self.assertEqual(manifest['frames'][0]['headingBits'],'8000000000000000')
        self.assertEqual(manifest['frames'][1]['headingBits'],'4056800000000000')


if __name__ == '__main__': unittest.main()
