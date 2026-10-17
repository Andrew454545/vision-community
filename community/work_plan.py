"""Saved work choice and one-at-a-time lane handover, without account data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets

WORK_TYPES = {"scene": ("scene",), "object": ("object",), "both": ("scene", "object")}


class WorkPlanError(ValueError):
    pass


class WorkPlan:
    def __init__(self, root: Path):
        self.path = Path(root) / "work-selection.json"
        self.value = {"version": 1, "workType": "scene", "nextLane": "scene", "activeLane": None}
        if self.path.is_symlink():
            raise WorkPlanError("invalid_work_selection")
        if self.path.exists():
            try:
                if not self.path.is_file() or self.path.stat().st_size > 4096:
                    raise ValueError
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if (not isinstance(value, dict) or set(value) != set(self.value)
                        or type(value["version"]) is not int or value["version"] != 1
                        or value["workType"] not in WORK_TYPES
                        or value["nextLane"] not in WORK_TYPES[value["workType"]]
                        or value["activeLane"] not in (None, *WORK_TYPES[value["workType"]])):
                    raise ValueError
                self.value = value
            except (OSError, ValueError, TypeError, KeyError):
                raise WorkPlanError("invalid_work_selection") from None

    @property
    def work_type(self):
        return self.value["workType"]

    @property
    def lanes(self):
        return WORK_TYPES[self.work_type]

    @property
    def next_lane(self):
        return self.value["activeLane"] or self.value["nextLane"]

    def save(self, value):
        if self.path.is_symlink() or self.path.exists() and not self.path.is_file():
            raise WorkPlanError("invalid_work_selection")
        stage = self.path.with_name("work-selection-" + secrets.token_hex(12) + ".tmp")
        try:
            with stage.open("xb") as output:
                output.write((json.dumps(value, sort_keys=True) + "\n").encode())
                output.flush()
                os.fsync(output.fileno())
            os.chmod(stage, 0o600)
            if self.path.is_symlink():
                raise WorkPlanError("invalid_work_selection")
            os.replace(stage, self.path)
        finally:
            stage.unlink(missing_ok=True)
        self.value = value

    def select(self, work_type):
        if not isinstance(work_type, str) or work_type not in WORK_TYPES:
            raise WorkPlanError("invalid_work_selection")
        if self.value["activeLane"] is not None:
            raise WorkPlanError("unfinished_lane_needs_recovery")
        self.save({**self.value, "workType": work_type, "nextLane": WORK_TYPES[work_type][0]})

    def begin(self):
        lane = self.next_lane
        self.save({**self.value, "activeLane": lane})
        return lane

    def finish(self, lane):
        if self.value["activeLane"] != lane:
            raise WorkPlanError("invalid_work_selection")
        following = self.lanes[(self.lanes.index(lane) + 1) % len(self.lanes)]
        self.save({**self.value, "activeLane": None, "nextLane": following})
