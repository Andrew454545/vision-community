"""VISION-compatible ranking: score order, country/generation filters, per-country cap."""

from __future__ import annotations

from .source import haversine_meters


CAMERA_GENERATIONS = ("badcam", "gen1", "gen2", "gen3", "gen4", "trekker")
ALL_GENERATIONS = frozenset(CAMERA_GENERATIONS)
COUNTRY_MODES = ("all", "include", "exclude")
RESULT_PRUNE_METERS = 100
PAST_LOCATION_METERS = 25
MAX_EXCLUDE_LOCATIONS = 10_000
COUNTRY_ALIASES = {
    "United States": "USA",
    "United States of America": "USA",
}


def clamp_result_count(value, default: int = 200) -> int:
    if type(value) is not int:
        return default
    return min(10_000, max(1, value))


def clamp_max_per_country(value, default: int = 25) -> int:
    if type(value) is not int:
        return default
    return min(10_000, max(1, value))


def normalize_filters(
    country_mode: str | None,
    countries,
    generations,
) -> tuple[str, list[str], list[str]]:
    mode = country_mode if country_mode in COUNTRY_MODES else "all"
    selected = []
    seen = set()
    if isinstance(countries, list):
        for item in countries:
            if isinstance(item, str) and item.strip():
                name = canonicalize_country(item.strip())
                if name not in seen:
                    seen.add(name)
                    selected.append(name)
    gens = []
    gen_seen = set()
    if isinstance(generations, list):
        for item in generations:
            if item in ALL_GENERATIONS and item not in gen_seen:
                gen_seen.add(item)
                gens.append(item)
    if not gens or set(gens) == ALL_GENERATIONS:
        gens = []
    if mode != "include" and (mode == "all" or not selected):
        mode = "all"
        selected = []
    selected = sorted(selected) if selected else []
    return mode, selected, gens


def canonicalize_country(name: str | None) -> str:
    value = (name or "").strip()
    return COUNTRY_ALIASES.get(value, value)


def candidate_result_count(result_count: int, max_per_country: int) -> int:
    result_count = clamp_result_count(result_count)
    max_per_country = clamp_max_per_country(max_per_country)
    if max_per_country >= result_count:
        return result_count
    return min(10_000, max(result_count, result_count * 4))


def prune_nearby(hits: list[dict], meters: float = RESULT_PRUNE_METERS) -> list[dict]:
    selected = []
    seen_panos = set()
    for hit in hits:
        pose = hit.get("pose") if isinstance(hit.get("pose"), dict) else hit
        pano = str(pose.get("panoId") or pose.get("asset_id") or "")
        if pano and pano in seen_panos:
            continue
        lat = float(pose.get("lat") or 0)
        lng = float(pose.get("lng") or pose.get("lon") or 0)
        if any(
            haversine_meters(
                lat,
                lng,
                float((prior.get("pose") if isinstance(prior.get("pose"), dict) else prior).get("lat") or 0),
                float(
                    (prior.get("pose") if isinstance(prior.get("pose"), dict) else prior).get("lng")
                    or (prior.get("pose") if isinstance(prior.get("pose"), dict) else prior).get("lon")
                    or 0
                ),
            )
            < meters
            for prior in selected
        ):
            continue
        if pano:
            seen_panos.add(pano)
        selected.append(hit)
    return selected


def exclude_used(hits: list[dict], excluded, meters: float = PAST_LOCATION_METERS) -> list[dict]:
    """Drop hits within 25 m of a previous map, matching VISION Past Locations."""
    if not excluded:
        return hits
    points = []
    for item in excluded:
        if not isinstance(item, dict):
            continue
        try:
            lat = float(item.get("lat") or 0)
            lng = float(item.get("lng") or item.get("lon") or 0)
        except (TypeError, ValueError):
            continue
        pano = str(item.get("panoId") or item.get("pano_id") or "")
        points.append((lat, lng, pano))
        if len(points) >= MAX_EXCLUDE_LOCATIONS:
            break
    if not points:
        return hits
    kept = []
    for hit in hits:
        pose = hit.get("pose") if isinstance(hit.get("pose"), dict) else hit
        pano = str(pose.get("panoId") or pose.get("asset_id") or "")
        lat = float(pose.get("lat") or 0)
        lng = float(pose.get("lng") or pose.get("lon") or 0)
        if any(
            (pano and pano == prior_pano)
            or haversine_meters(lat, lng, prior_lat, prior_lng) < meters
            for prior_lat, prior_lng, prior_pano in points
        ):
            continue
        kept.append(hit)
    return kept


def pose_fields(record: dict) -> tuple[str, str]:
    pose = record.get("pose") if isinstance(record.get("pose"), dict) else record
    country = canonicalize_country(pose.get("country") or "")
    generation = pose.get("cameraGeneration") or pose.get("camera_generation") or ""
    return country, generation


def accepts(record: dict, mode: str, countries: list[str], generations: list[str]) -> bool:
    country, generation = pose_fields(record)
    if generations and generation not in generations:
        return False
    if mode == "include":
        return country in countries
    if mode == "exclude":
        return country not in countries
    return True


def cap_by_country(hits: list[dict], result_count: int, max_per_country: int) -> list[dict]:
    counts: dict[str, int] = {}
    selected = []
    for hit in hits:
        country, _generation = pose_fields(hit)
        if counts.get(country, 0) >= max_per_country:
            continue
        counts[country] = counts.get(country, 0) + 1
        selected.append(hit)
        if len(selected) >= result_count:
            break
    return selected
