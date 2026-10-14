import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from community.catalog import iter_indexer_tsv
from community.rank import accepts
from community.scene_catalog_metadata import (CLASSIFICATION_POLICY, MetadataError,
    classify_generation, country_authority, metadata_row, prepare_catalog)
from community.vision_index import location_tsv_line


def camera(**changes):
    args = dict(height=6656, country_code='US', year=2011, month=11, latitude=40,
                source='car', has_level_id=False)
    args.update(changes)
    return classify_generation(**args)


class SceneGenerationTest(unittest.TestCase):
    def test_gen2_gen3_transition_requires_country_and_date(self):
        self.assertEqual(camera()['generation'], 'gen2')
        self.assertEqual(camera(month=12)['generation'], 'gen3')
        self.assertEqual(camera(year=2010, country_code='IT')['generation'], 'gen2')
        self.assertEqual(camera(year=2010, country_code='GH')['generation'], 'gen3')
        self.assertEqual(camera(month=0)['generation'], 'unknown')
        self.assertEqual(camera(year=0)['generation'], 'unknown')

    def test_badcam_date_and_latitude_boundaries(self):
        self.assertEqual(camera(country_code='FI', year=2020, month=9)['generation'], 'gen3')
        self.assertEqual(camera(country_code='FI', year=2020, month=10)['generation'], 'badcam')
        self.assertEqual(camera(year=2019, month=2, latitude=52)['generation'], 'gen3')
        self.assertEqual(camera(year=2019, month=2, latitude=52.001)['generation'], 'badcam')
        self.assertEqual(camera(year=2019, month=1, latitude=53)['generation'], 'gen3')
        self.assertEqual(camera(country_code='CY', year=2000)['generation'], 'gen3')
        self.assertEqual(camera(country_code='CY', year=2001)['generation'], 'badcam')

    def test_reference_order_handles_scout_and_indoor_ambiguity(self):
        self.assertEqual(camera(height=1664)['generation'], 'gen1')
        self.assertEqual(camera(height=8192, source='ScOuT')['generation'], 'trekker')
        self.assertEqual(camera(height=8192, has_level_id=True)['generation'], 'gen4')
        self.assertEqual(camera(source='scout')['generation'], 'trekker')
        self.assertEqual(camera(source='scout', has_level_id=True)['generation'], 'unknown')
        self.assertEqual(camera(country_code='CY', source='scout', has_level_id=True)['generation'], 'badcam')

    def test_unknown_and_malformed_metadata_never_guess_gen3(self):
        for changes in ({'height': 4096}, {'year': 2500}, {'month': 13}, {'latitude': float('nan')},
                        {'country_code': 'us'}, {'height': True}, {'has_level_id': 'false'}):
            with self.subTest(changes=changes):
                self.assertEqual(camera(**changes)['generation'], 'unknown')


class SceneCatalogPreparationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.row = {'pano_id': 'synthetic_scene_0001', 'lat': '40', 'lng': '-100',
                    'country_code': 'US', 'capture_year': '2011', 'capture_month': '11',
                    'image_height': '6656', 'heading': '271.25', 'pitch': '-3.5', 'zoom': '1.25',
                    'road_name_state': 'has road name'}

    def source(self, rows, names=None):
        source = self.root / 'input.tsv'
        with source.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=names or list(rows[0]), delimiter='\t')
            writer.writeheader()
            writer.writerows(rows)
        return source, hashlib.sha256(source.read_bytes()).hexdigest()

    def test_country_generation_and_saved_pan_reach_existing_native_input(self):
        row2 = dict(self.row, pano_id='synthetic_scene_0002', country_code='IT', lat='42',
                    capture_year='2020', image_height='8192')
        source, pin = self.source([self.row, row2])
        out = self.root / 'prepared'
        result = prepare_catalog(source, pin, out)
        self.assertEqual(result['generations'], {'gen2': 1, 'gen4': 1})
        self.assertEqual(result['policy'], CLASSIFICATION_POLICY)
        self.assertFalse(result['officialCoverageVerified'])
        self.assertFalse(result['objectEligibilityGranted'])
        self.assertEqual(result['networkRequests'], 0)
        jobs = list(iter_indexer_tsv(out / 'locations.tsv'))
        self.assertEqual([j['country'] for j in jobs], ['USA', 'Italy'])
        self.assertEqual([j['cameraGeneration'] for j in jobs], ['gen2', 'gen4'])
        line = location_tsv_line(dict(jobs[0], locationId=123)).split('\t')
        self.assertEqual(line[4:7], ['271.25', '-3.5', '1.25'])
        self.assertEqual(line[8:10], ['USA', 'gen2'])
        self.assertTrue(accepts(jobs[0], 'include', ['USA'], ['gen2']))
        self.assertFalse(accepts(jobs[0], 'include', ['Italy'], ['gen2']))
        self.assertFalse(accepts(jobs[0], 'all', [], ['gen3']))
        evidence = [json.loads(line) for line in (out / 'metadata.jsonl').read_text().splitlines()]
        self.assertEqual(evidence[0]['classification']['basis'], 'country-date-heuristic')
        self.assertEqual(evidence[0]['captureMonth'], 11)
        for name, item in result['files'].items():
            self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), item['sha256'])
        with self.assertRaises(FileExistsError):
            prepare_catalog(source, pin, out)

    def test_missing_date_stays_unknown_and_missing_road_is_not_declared_absent(self):
        row = dict(self.row, capture_year='', capture_month='')
        row.pop('road_name_state')
        line, evidence = metadata_row(row, 1, country_authority())
        self.assertEqual(line.split('\t')[9:], ['unknown', 'unknown\n'])
        self.assertEqual(evidence['classification']['basis'], 'insufficient-metadata')

    def test_conflicting_country_or_generation_is_preserved_as_failure(self):
        for changes in ({'country': 'Italy'}, {'camera_generation': 'gen4'}, {'heading': 'nan'},
                        {'pano_id': 'https://secret.example'}, {'has_level_id': 'maybe'}):
            with self.subTest(changes=changes), self.assertRaises(MetadataError):
                metadata_row(dict(self.row, **changes), 1, country_authority())
        line, _ = metadata_row(dict(self.row, country='United States'), 1, country_authority())
        self.assertEqual(line.split('\t')[8], 'USA')

    def test_bad_pin_fails_before_creating_output(self):
        source, _ = self.source([self.row])
        output = self.root / 'bad-pin'
        with self.assertRaisesRegex(MetadataError, 'input_digest_mismatch'):
            prepare_catalog(source, '0' * 64, output)
        self.assertFalse(output.exists())

    def test_duplicate_panorama_cannot_silently_change_its_saved_heading(self):
        source, pin = self.source([self.row, dict(self.row, heading='90')])
        output = self.root / 'duplicate'
        with self.assertRaisesRegex(MetadataError, 'duplicate_panorama'):
            prepare_catalog(source, pin, output)
        self.assertFalse((output / 'manifest.json').exists())
        self.assertTrue((output / 'failure-report.json').is_file())

    def test_imagery_or_key_headers_are_refused_and_partial_failure_retained(self):
        source, pin = self.source([dict(self.row, api_key='synthetic-do-not-copy')])
        output = self.root / 'failure'
        with self.assertRaisesRegex(MetadataError, 'invalid_metadata_headers'):
            prepare_catalog(source, pin, output)
        self.assertFalse((output / 'manifest.json').exists())
        report = json.loads((output / 'failure-report.json').read_bytes())
        self.assertEqual(report['reason'], 'invalid_metadata_headers')
        self.assertNotIn('synthetic-do-not-copy', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
