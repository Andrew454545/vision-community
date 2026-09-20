"""Seal a metadata catalog into checksummed community-visual-v1 segments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .features import MODEL_ID, embedding_for, render_faces
from .segments import SegmentRegistry


def seal_catalog(catalog: dict, root: Path) -> dict:
    registry = SegmentRegistry(root)
    grouped: dict[str, list[tuple[int, bytes, dict]]] = {"scene": [], "object": []}
    for index, location in enumerate(catalog["locations"], start=1):
        lane = location["lane"]
        if lane not in grouped:
            raise ValueError("invalid_lane")
        model = location.get("model") or MODEL_ID
        faces = render_faces(location["panoId"], location["capture"], lane, model)
        grouped[lane].append(
            (
                index,
                embedding_for(lane, faces),
                {
                    "locationId": index,
                    "lat": location["lat"],
                    "lng": location["lng"],
                    "heading": location.get("heading") or 0,
                    "pitch": location.get("pitch") or 0,
                    "zoom": location.get("zoom") or 0,
                    "panoId": location["panoId"],
                    "capture": location["capture"],
                    "country": location.get("country") or "",
                    "cameraGeneration": location.get("cameraGeneration") or "",
                },
            )
        )
    for lane, rows in grouped.items():
        if not rows:
            continue
        registry.publish(
            lane=lane,
            location_ids=[row[0] for row in rows],
            embeddings=b"".join(row[1] for row in rows),
            poses=[row[2] for row in rows],
        )
    document = registry.load()
    document["persistImagery"] = False
    document["publicCorpus"] = False
    registry._write_registry(document)
    return registry.load()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    document = seal_catalog(catalog, args.out)
    print(json.dumps({"sources": document["sources"], "model": document["model"]}, indent=2))


if __name__ == "__main__":
    main()
