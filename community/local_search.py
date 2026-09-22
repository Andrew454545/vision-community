"""Search the published Community index on this computer.

The website is the queue and credit desk. After 100,000 units, this command
downloads the shared index (metadata and embeddings only) and ranks it here.
No paid search host is required. This is community-visual-v1, not VISION.app.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

from .contribute import (
    DEFAULT_URL,
    CommunityClient,
    ContributeError,
    default_session_path,
    load_session,
    origin_of,
    require_street_decoder,
    save_session,
)
from .features import embedding_for, mean_embeddings, wrap_heading
from .mma import build_map, dump_map, location_record, parse_map
from .pano import QUERY_VIEW_CAP, render_location_faces, uses_street_views
from .prompt import description_embedding, mix_embeddings, parse_prompt, snap_description_weight
from .rank import (
    accepts,
    candidate_result_count,
    cap_by_country,
    canonicalize_country,
    clamp_max_per_country,
    clamp_result_count,
    exclude_used,
    normalize_filters,
    prune_nearby,
)
from .search import ranked_search_records
from .segments import unpack_pose
from .service import _exclude_points


SHARD_MAGIC = b"VCIDX001"
POSE_BYTES = 176


def _embedding_bytes(value) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return bytes.fromhex(value)
    raise ContributeError("invalid_index")


def records_from_snapshot(locations: list[dict], lane: str) -> list[dict]:
    records = []
    for row in locations:
        location_id = int(row["locationId"])
        pose = {
            "panoId": row.get("panoId") or "",
            "lat": row.get("lat") or 0,
            "lng": row.get("lng") or 0,
            "heading": row.get("heading") or 0,
            "pitch": row.get("pitch") or 0,
            "zoom": row.get("zoom") or 0,
            "country": canonicalize_country(row.get("country") or ""),
            "cameraGeneration": row.get("cameraGeneration") or "",
        }
        records.append(
            {
                "locationId": location_id,
                "lane": lane,
                "embedding": _embedding_bytes(row.get("embedding")),
                "pose": pose,
            }
        )
    return records


def records_from_shard(blob: bytes, lane: str) -> list[dict]:
    if blob[:8] != SHARD_MAGIC:
        raise ContributeError("invalid_index_shard")
    count = int.from_bytes(blob[8:12], "little")
    embed_size = int.from_bytes(blob[12:16], "little")
    record_size = POSE_BYTES + embed_size
    expected = 16 + count * record_size
    if len(blob) < expected:
        raise ContributeError("invalid_index_shard")
    records = []
    offset = 16
    for _ in range(count):
        pose = unpack_pose(blob[offset : offset + POSE_BYTES])
        embedding = bytes(blob[offset + POSE_BYTES : offset + record_size])
        offset += record_size
        records.append(
            {
                "locationId": pose["locationId"],
                "lane": lane,
                "embedding": embedding,
                "pose": {
                    "panoId": pose.get("panoId") or "",
                    "lat": pose.get("lat") or 0,
                    "lng": pose.get("lng") or 0,
                    "heading": pose.get("heading") or 0,
                    "pitch": pose.get("pitch") or 0,
                    "zoom": pose.get("zoom") or 0,
                    "country": canonicalize_country(pose.get("country") or ""),
                    "cameraGeneration": pose.get("cameraGeneration") or "",
                },
            }
        )
    return records


def download_index(session: CommunityClient, *, search_id: str, lane: str) -> list[dict]:
    manifest = session.index_manifest(search_id=search_id, lane=lane)
    shards = manifest.get("shards") if isinstance(manifest, dict) else None
    if isinstance(shards, list) and shards:
        records = []
        for shard in shards:
            key = shard.get("key") if isinstance(shard, dict) else None
            if not isinstance(key, str) or not key.startswith("search-index/"):
                continue
            blob = session.index_shard(search_id=search_id, key=key)
            records.extend(records_from_shard(blob, lane))
        if records:
            return records
    records = []
    after = 0
    while True:
        page = session.published_snapshot(search_id=search_id, lane=lane, after=after, limit=250)
        locations = page.get("locations") if isinstance(page, dict) else None
        if not isinstance(locations, list) or not locations:
            break
        records.extend(records_from_snapshot(locations, lane))
        nxt = page.get("nextAfter")
        if nxt is None:
            break
        after = int(nxt)
    return records


def query_embedding(query_map: dict | None, lane: str, prompt: str | None = None, description_weight: int | None = None) -> bytes:
    visual = None
    if query_map is not None:
        parsed = parse_map(query_map)
        examples = parsed["examples"]
        if any(uses_street_views(example["panoId"]) for example in examples):
            examples = examples[:QUERY_VIEW_CAP]
        vectors = []
        for example in examples:
            faces = render_location_faces(
                {
                    "panoId": example["panoId"],
                    "capture": example.get("capture") or "unknown",
                    "lane": lane,
                    "heading": example.get("heading") or 0,
                    "pitch": example.get("pitch") or 0,
                    "zoom": example.get("zoom") or 0,
                }
            )
            vectors.append(embedding_for(lane, faces))
        visual = mean_embeddings(vectors)
    text = parse_prompt(prompt)
    if text:
        textual = description_embedding(text, lane)
        if visual is None:
            return textual
        return mix_embeddings(visual, textual, snap_description_weight(description_weight, has_json=True, has_prompt=True))
    if visual is None:
        raise ContributeError("invalid_query")
    return visual


def map_from_hits(hits: list[dict], *, query_name: str, lane: str, processed: int) -> dict:
    min_score = hits[-1]["score"] if hits else 0.0
    coordinates = []
    for rank, hit in enumerate(hits, start=1):
        pose = hit.get("pose") or {}
        view_offset = int(hit.get("viewOffset") or 0) if lane == "scene" else 0
        coordinates.append(
            location_record(
                lat=pose.get("lat") or 0,
                lng=pose.get("lng") or 0,
                heading=wrap_heading((pose.get("heading") or 0) + view_offset * 90),
                pitch=pose.get("pitch") or 0,
                zoom=pose.get("zoom") or 0,
                pano_id=pose.get("panoId") or "",
                rank=rank,
                score=hit["score"],
                query_name=query_name,
                lane=lane,
                country=pose.get("country") or "",
                camera_generation=pose.get("cameraGeneration") or "",
                processed_locations=processed,
                min_score=min_score,
                heading_offset=view_offset * 90,
            )
        )
    return build_map(query_name, coordinates)


def local_search(
    *,
    url: str,
    query_map: dict | None,
    lane: str = "scene",
    recovery_code: str | None = None,
    session_path: Path | None = None,
    persist_session: bool = True,
    result_count: int = 200,
    max_per_country: int = 25,
    output_name: str | None = None,
    view_direction: str | None = None,
    country_filter_mode: str = "all",
    countries=None,
    camera_generations=None,
    exclude_map=None,
    prompt: str | None = None,
    description_weight: int | None = None,
    output: Path | None = None,
) -> dict:
    require_street_decoder()
    session = CommunityClient(url)
    created = None
    recovered = None
    if session_path is not None:
        stored = load_session(session_path, url)
        if stored and isinstance(stored.get("recoveryCode"), str) and not recovery_code:
            recovery_code = stored["recoveryCode"]
    if recovery_code:
        recovered = session.recover(recovery_code)
    elif not session.token:
        created = session.create_account()
        recovery_code = created.get("recoveryCode") if isinstance(created, dict) else None
    if persist_session and session_path is not None and recovery_code:
        account_id = None
        if created:
            account_id = created.get("accountId")
        elif recovered:
            account_id = recovered.get("accountId")
        save_session(session_path, url=url, account_id=account_id, recovery_code=recovery_code)
    prompt_text = parse_prompt(prompt)
    parsed = None
    if query_map is not None:
        parsed = parse_map(query_map)
    if parsed is None and not prompt_text:
        raise ContributeError("invalid_query")
    query_name = output_name.strip() if isinstance(output_name, str) and output_name.strip() else (
        parsed["name"] if parsed is not None else prompt_text[:80] or "VISION Community"
    )
    result_count = clamp_result_count(result_count)
    max_per_country = clamp_max_per_country(max_per_country)
    authorized = session.authorize_local_search(
        {
            "idempotencyKey": secrets.token_hex(16),
            "lane": lane,
            "queryMap": query_map,
            "prompt": prompt_text or None,
            "descriptionWeight": description_weight,
            "outputName": query_name,
            "resultCount": result_count,
            "maxPerCountry": max_per_country,
            "viewDirection": view_direction,
            "countryFilterMode": country_filter_mode,
            "countries": countries or [],
            "cameraGenerations": camera_generations or [],
            "excludeMap": exclude_map,
        }
    )
    search_id = authorized["searchId"]
    records = download_index(session, search_id=search_id, lane=lane)
    query = query_embedding(query_map, lane, prompt=prompt_text, description_weight=description_weight)
    country_mode, selected_countries, selected_generations = normalize_filters(
        country_filter_mode, countries, camera_generations
    )
    overfetch = candidate_result_count(result_count, max_per_country)
    accept = lambda record: accepts(record, country_mode, selected_countries, selected_generations)
    matches = ranked_search_records(
        records,
        lane,
        query,
        limit=overfetch,
        accept=accept,
        view_direction=view_direction,
    )
    matches = cap_by_country(
        prune_nearby(exclude_used(matches, _exclude_points(exclude_map))),
        result_count,
        max_per_country,
    )
    document = map_from_hits(matches, query_name=query_name, lane=lane, processed=len(records))
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(dump_map(document), encoding="utf-8")
    report = {
        "ok": True,
        "local": True,
        "searchId": search_id,
        "query": query_name,
        "lane": lane,
        "scanned": len(records),
        "results": len(matches),
        "map": document,
        "output": str(output) if output is not None else None,
    }
    if created is not None:
        report["recoveryCode"] = created.get("recoveryCode")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--query", type=Path, help="map-making.app JSON (same file the site uses)")
    parser.add_argument("--prompt", help="written description, used alone or mixed with --query")
    parser.add_argument("--description-weight", type=int, default=50, help="0=JSON only, 100=description only")
    parser.add_argument("--output", type=Path, help="where to write the result JSON")
    parser.add_argument("--lane", choices=("scene", "object"), default="scene")
    parser.add_argument("--recovery-code", dest="recovery_code")
    parser.add_argument("--session-file", type=Path, dest="session_file")
    parser.add_argument("--no-save-session", action="store_true")
    parser.add_argument("--result-count", type=int, default=200)
    parser.add_argument("--max-per-country", type=int, default=25)
    parser.add_argument("--output-name")
    parser.add_argument("--view-direction", default="bestOfFour")
    parser.add_argument("--country-mode", choices=("all", "include", "exclude"), default="all")
    parser.add_argument("--countries", default="", help="comma-separated country names")
    parser.add_argument("--camera-generations", default="", help="comma-separated camera generations")
    parser.add_argument("--exclude", type=Path, help="previous map JSON; hide results within 25 m")
    args = parser.parse_args()
    try:
        origin_of(args.url)
        if args.query is None and not (args.prompt and str(args.prompt).strip()):
            parser.error("provide --query, --prompt, or both")
        query_map = json.loads(args.query.read_text(encoding="utf-8")) if args.query is not None else None
        session_path = args.session_file or default_session_path()
        stem = (args.output_name or (query_map.get("name") if isinstance(query_map, dict) else None) or args.prompt or "vision-community")
        if not isinstance(stem, str) or not stem.strip():
            stem = "vision-community"
        output = args.output or Path(f"{stem.strip().replace(' ', '-')}.json")
        countries = [part.strip() for part in args.countries.split(",") if part.strip()]
        cameras = [part.strip() for part in args.camera_generations.split(",") if part.strip()]
        exclude_map = json.loads(args.exclude.read_text(encoding="utf-8")) if args.exclude is not None else None
        report = local_search(
            url=args.url,
            query_map=query_map,
            lane=args.lane,
            recovery_code=args.recovery_code,
            session_path=session_path,
            persist_session=not args.no_save_session,
            result_count=args.result_count,
            max_per_country=args.max_per_country,
            output_name=args.output_name,
            view_direction=args.view_direction,
            country_filter_mode=args.country_mode,
            countries=countries,
            camera_generations=cameras,
            exclude_map=exclude_map,
            prompt=args.prompt,
            description_weight=args.description_weight,
            output=output,
        )
    except ContributeError as error:
        hint = "python3 -m pip install -r requirements.txt\n" if error.code == "install_pillow" else ""
        parser.exit(1, f"{hint}{error.code}\n")
    except (OSError, json.JSONDecodeError) as error:
        parser.exit(1, f"invalid_query_file\n")
    except KeyboardInterrupt:
        parser.exit(130, "interrupted\n")
    print(json.dumps({key: report[key] for key in report if key != "map"}, sort_keys=True))
    if report.get("output"):
        print(report["output"], file=sys.stderr)


if __name__ == "__main__":
    main()
