"""Exclusive catalog batches so volunteers index separate parts of the corpus.

The remaining-location catalog excludes locally indexed and locally reserved
panoramas. Legacy families remain recognizable for historical work. Each account
keeps one shard until it is finished or abandoned.
"""

from __future__ import annotations
import re


TAIL_PREFIX = "catalog/all-locations-tail-v1/"
FULL_PREFIX = "catalog/all-locations-full-v1/"
INDEXED_PREFIX = "catalog/vision-indexed-v1/"
REMAINING_PREFIX = "catalog/official-remaining-v1/"
RETIRED_PREFIXES = (TAIL_PREFIX, FULL_PREFIX, INDEXED_PREFIX)
STEAL_AFTER_SECONDS = 6 * 60 * 60
FAMILY_ORDER = ("new-places", "whole-map", "already-indexed", "other")
FAMILY_LABELS = {
    "new-places": "New places",
    "whole-map": "Whole map",
    "already-indexed": "Already-indexed places",
    "other": "Other places",
}


def available_catalog_sql(table: str = "pose_catalog") -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", table, re.I):
        raise ValueError("invalid_sql_alias")
    return f"(COALESCE({table}.held,0)=0 AND " + " AND ".join(
        f"{table}.r2_key NOT LIKE '{prefix}%'" for prefix in RETIRED_PREFIXES) + ")"


def available_location_sql(table: str = "locations") -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", table, re.I):
        raise ValueError("invalid_sql_alias")
    return (f"({table}.catalog_shard IS NULL OR EXISTS (SELECT 1 FROM pose_catalog allocation "
            f"WHERE allocation.lane={table}.lane AND allocation.shard_id={table}.catalog_shard "
            f"AND {available_catalog_sql('allocation')}))")


def family_for_key(r2_key: str | None) -> str:
    key = r2_key or ""
    if key.startswith((TAIL_PREFIX, REMAINING_PREFIX)):
        return "new-places"
    if key.startswith(FULL_PREFIX):
        return "whole-map"
    if key.startswith(INDEXED_PREFIX):
        return "already-indexed"
    return "other"


def family_label(family: str) -> str:
    return FAMILY_LABELS.get(family, FAMILY_LABELS["other"])


def family_priority(family: str) -> int:
    try:
        return FAMILY_ORDER.index(family)
    except ValueError:
        return len(FAMILY_ORDER)


def family_priority_sql(column: str = "r2_key") -> str:
    return (
        "CASE"
        f" WHEN ({column} LIKE '{TAIL_PREFIX}%' OR {column} LIKE '{REMAINING_PREFIX}%') THEN 0"
        f" WHEN {column} LIKE '{FULL_PREFIX}%' THEN 1"
        f" WHEN {column} LIKE '{INDEXED_PREFIX}%' THEN 2"
        " ELSE 3 END"
    )


def parse_part(value) -> int | None:
    if value is None or value == "":
        return None
    if type(value) is bool or isinstance(value, (dict, list)):
        raise ValueError("invalid_part")
    if type(value) is int:
        part = value
    elif isinstance(value, float) and value.is_integer():
        part = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        part = int(value.strip())
    else:
        raise ValueError("invalid_part")
    if part < 1 or part > 1_000_000:
        raise ValueError("invalid_part")
    return part


def describe_part(*, part: int, part_count: int, family: str, rows_left: int, lane: str = "scene") -> dict:
    family_name = family if family in FAMILY_LABELS else "other"
    noun = "objects" if lane == "object" else "places"
    return {
        "part": part,
        "partCount": part_count,
        "family": family_name,
        "familyLabel": family_label(family_name),
        "rowsLeftInPart": max(0, int(rows_left)),
        "partLabel": f"Batch {part} of {part_count}",
        "separateParts": True,
        "lane": lane,
        "summary": (
            f"Batch {part} of {part_count} · {family_label(family_name)}. "
            f"Other people have different batches, so you are not indexing the same {noun}."
        ),
    }
