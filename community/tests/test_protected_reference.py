"""Synthetic geographic boundaries, using the unchanged native queue constants."""
import copy
import math
import unittest

from community import protected_reference as protected


def document(coordinates):
    return {'schemaVersion': 1, 'database': 'synthetic-database', 'generatedAt': '2026-10-09T00:00:00Z',
        'sourceLocationCount': len(coordinates), 'uniqueLocationCount': len(coordinates),
        'sourceMaps': [
            {'id': 'root-1', 'name': '‼️GEONECTIONS JSON‼️', 'folder': None, 'locationCount': len(coordinates)},
            {'id': 'root-2', 'name': 'Past Locations', 'folder': None, 'locationCount': 0},
            {'id': 'folder-1', 'name': 'one', 'folder': 'Titled Maps ‼️', 'locationCount': 0},
            {'id': 'folder-2', 'name': 'two', 'folder': 'Titled Maps ‼️ Done✅', 'locationCount': 0}],
        'coordinates': coordinates}


class ProtectedReferenceTests(unittest.TestCase):
    def load(self, doc): return protected.ProtectedReference(doc, database='synthetic-database')

    def test_exact_inclusive_25m_and_outside_with_unchanged_native_epsilon(self):
        reference = self.load(document([{'lat': 0, 'lng': 0}]))
        for meters in (0, 24.999, 25):
            self.assertTrue(reference.contains(math.degrees(meters / protected.EARTH_RADIUS_METERS), 0))
        self.assertFalse(reference.contains(math.degrees(25.001 / protected.EARTH_RADIUS_METERS), 0))
        self.assertFalse(reference.contains(0, 180))

    def test_dateline_and_pole_do_not_use_flat_coordinate_distance(self):
        reference = self.load(document([{'lat': 0, 'lng': 179.99995}, {'lat': 90, 'lng': 0}]))
        self.assertTrue(reference.contains(0, -179.99995))
        self.assertTrue(reference.contains(90, 150))
        self.assertFalse(reference.contains(89.999, 150))

    def test_missing_duplicate_or_unexpected_selectors_and_bad_counts_are_refused(self):
        original = document([{'lat': 0, 'lng': 0}])
        for mode in ('root', 'folder', 'id', 'count', 'boolean', 'duplicate-coordinate', 'unhashable-selector'):
            with self.subTest(mode=mode):
                value = copy.deepcopy(original)
                if mode == 'root': value['sourceMaps'][0]['name'] = 'other'
                elif mode == 'folder': value['sourceMaps'][2]['folder'] = 'other'
                elif mode == 'id': value['sourceMaps'][1]['id'] = 'root-1'
                elif mode == 'count': value['sourceLocationCount'] = 2
                elif mode == 'boolean': value['uniqueLocationCount'] = True
                elif mode == 'unhashable-selector': value['sourceMaps'][0]['folder'] = []
                else:
                    value['coordinates'] *= 2; value['uniqueLocationCount'] = 2
                    value['sourceMaps'][0]['locationCount'] = 2; value['sourceLocationCount'] = 2
                with self.assertRaises(protected.ProtectedReferenceError): self.load(value)

    def test_database_date_and_invalid_coordinate_values_cannot_be_overridden(self):
        original = document([{'lat': 0, 'lng': 0}])
        for field, replacement in [('database', 'other'), ('generatedAt', 'invalid'),
                                   ('generatedAt', '2026-10-09T00:00:00'), ('schemaVersion', True)]:
            with self.subTest(field=field, replacement=replacement):
                value = copy.deepcopy(original); value[field] = replacement
                with self.assertRaises(protected.ProtectedReferenceError): self.load(value)
        reference = self.load(original)
        for bad in (float('nan'), float('inf'), True, '0', 91, -91):
            with self.assertRaises(protected.ProtectedReferenceError): reference.contains(bad, 0)
        for bad in (181, -181, None):
            with self.assertRaises(protected.ProtectedReferenceError): reference.contains(0, bad)


if __name__ == '__main__': unittest.main()
