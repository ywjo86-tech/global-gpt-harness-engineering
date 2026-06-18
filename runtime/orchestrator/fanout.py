from __future__ import annotations

import json
from pathlib import Path

from .schemas import TaskSlice


def build_fanout_plan(tasks: list[TaskSlice]) -> list[dict[str, object]]:
    plan: list[dict[str, object]] = []
    for task in tasks:
        plan.append(task.as_request_payload())
    return plan


def write_json(path: str | Path, payload: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

