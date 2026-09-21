"""Send a Community search JSON into map-making.app or print local-import steps.

Website users connect in the browser. This command is for people who searched
on their computer. The API key stays in a local session file, not on the
Community service.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .mma import MMAError, _coordinates
from .mma_cloud import (
    CLOUD_URL,
    CloudError,
    default_cloud_session_path,
    list_maps,
    load_cloud_session,
    save_cloud_session,
    send_map,
)


def _key_from(args_key: str | None, session: dict) -> str:
    return (args_key or os.environ.get("VISION_COMMUNITY_MMA_KEY") or session.get("apiKey") or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", type=Path, help="search result JSON from the site or local_search")
    parser.add_argument("--api-key", help="map-making.app API key (saved locally if --save-key)")
    parser.add_argument("--map-id", help="existing map-making.app map id")
    parser.add_argument("--new-map", action="store_true", help="create a new map with the JSON name")
    parser.add_argument("--list-maps", action="store_true", help="show maps for this key, then exit")
    parser.add_argument("--save-key", action="store_true", help="remember the key on this computer")
    parser.add_argument("--session-file", type=Path)
    parser.add_argument("--origin", default=CLOUD_URL)
    parser.add_argument("--local", action="store_true", help="print how to drop the JSON into the local Map Making App")
    args = parser.parse_args()
    session_path = args.session_file or default_cloud_session_path()
    session = load_cloud_session(session_path)
    key = _key_from(args.api_key, session)
    if args.save_key:
        if not key:
            parser.exit(1, "mma_missing_key\n")
        session["apiKey"] = key
        if args.map_id:
            session["mapId"] = args.map_id
        save_cloud_session(session, session_path)
    if args.list_maps:
        try:
            maps = list_maps(key, origin=args.origin)
        except CloudError as error:
            parser.exit(1, f"{error.code}\n")
        for item in maps:
            print(f"{item['id']}\t{item['name']}")
        return
    if args.json is None:
        parser.exit(1, "provide a search JSON file\n")
    try:
        document = json.loads(args.json.read_text(encoding="utf-8"))
        if not _coordinates(document):
            raise MMAError("empty_mma_map")
    except (OSError, json.JSONDecodeError, MMAError) as error:
        parser.exit(1, f"{getattr(error, 'code', 'invalid_mma_map')}\n")
    if args.local:
        print(args.json.resolve())
        print("Open the local Map Making App, open a map, then drop that file onto the window.")
        return
    try:
        result = send_map(
            document,
            api_key=key,
            map_id=args.map_id or session.get("mapId"),
            new_map=args.new_map,
            origin=args.origin,
        )
    except CloudError as error:
        parser.exit(1, f"{error.code}\n")
    except MMAError as error:
        parser.exit(1, f"{error.code}\n")
    print(f"{result['added']} places added")
    print(result["url"])


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
