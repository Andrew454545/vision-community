"""Validate a pinned MMA exclusion snapshot and apply the native queue rule.

This verifies operator input, not its origin or permission to retrieve imagery.
The caller must independently pin the export and retain its database authority.
"""
from __future__ import annotations

from datetime import datetime
import math

ROOT_MAPS = frozenset(('‼️GEONECTIONS JSON‼️', 'Past Locations'))
FOLDERS = frozenset(('Titled Maps ‼️', 'Titled Maps ‼️ Done✅'))
EARTH_RADIUS_METERS = 6_371_008.8
RADIUS_METERS = 25
INCLUSIVE_EPSILON = 1e-10
MAX_COORDINATES = 500_000
MAX_MAPS = 10_000
THRESHOLD = (2 * math.sin(RADIUS_METERS / EARTH_RADIUS_METERS / 2)) ** 2 * (1 + INCLUSIVE_EPSILON)


class ProtectedReferenceError(ValueError):
    pass


def require(value):
    if not value:
        raise ProtectedReferenceError('invalid_protected_reference')


def point(lat, lng):
    require(type(lat) in (int, float) and type(lng) in (int, float)
            and math.isfinite(lat) and math.isfinite(lng)
            and -90 <= lat <= 90 and -180 <= lng <= 180)
    # Match the native JavaScript queue's operation order and squared chord
    # threshold; no flat-earth distance, rounded coordinates or new epsilon.
    latitude, longitude = lat * math.pi / 180, lng * math.pi / 180
    cosine = math.cos(latitude)
    return cosine * math.cos(longitude), cosine * math.sin(longitude), math.sin(latitude)


class ProtectedReference:
    def __init__(self, document, *, database):
        require(isinstance(document, dict) and type(document.get('schemaVersion')) is int
                and document['schemaVersion'] == 1 and document.get('database') == database
                and isinstance(document.get('generatedAt'), str))
        try:
            generated = datetime.fromisoformat(document['generatedAt'].replace('Z', '+00:00'))
        except ValueError:
            raise ProtectedReferenceError('invalid_protected_reference') from None
        require(generated.tzinfo is not None and generated.utcoffset() is not None)
        maps, coordinates = document.get('sourceMaps'), document.get('coordinates')
        require(isinstance(maps, list) and 4 <= len(maps) <= MAX_MAPS
                and isinstance(coordinates, list) and 1 <= len(coordinates) <= MAX_COORDINATES)
        roots, folders, ids, rows = {name: 0 for name in ROOT_MAPS}, {name: 0 for name in FOLDERS}, set(), 0
        for entry in maps:
            require(isinstance(entry, dict) and isinstance(entry.get('id'), str)
                    and 0 < len(entry['id']) <= 128 and entry['id'] not in ids
                    and type(entry.get('locationCount')) is int and 0 <= entry['locationCount'] < 2**53)
            ids.add(entry['id']); rows += entry['locationCount']
            name, folder = entry.get('name'), entry.get('folder')
            require(isinstance(name, str) and (folder is None or isinstance(folder, str)))
            if folder is None and name in roots:
                roots[name] += 1
            elif folder in folders:
                folders[folder] += 1
            else:
                raise ProtectedReferenceError('invalid_protected_reference')
        require(all(count == 1 for count in roots.values()) and all(count >= 1 for count in folders.values())
                and type(document.get('sourceLocationCount')) is int and document['sourceLocationCount'] == rows
                and type(document.get('uniqueLocationCount')) is int
                and document['uniqueLocationCount'] == len(coordinates) <= rows)
        self.points, seen = [], set()
        for entry in coordinates:
            require(isinstance(entry, dict) and set(entry) == {'lat', 'lng'})
            value = point(entry['lat'], entry['lng'])
            pair = entry['lat'], entry['lng']
            require(pair not in seen)
            seen.add(pair); self.points.append(value)
        self.generated_at = document['generatedAt']
        self.generated_unix_millis = generated.timestamp() * 1000

    def contains(self, lat, lng):
        candidate = point(lat, lng)
        return any(sum((left - right) ** 2 for left, right in zip(candidate, other)) <= THRESHOLD
                   for other in self.points)
