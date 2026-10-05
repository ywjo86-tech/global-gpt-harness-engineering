"""Read-only selection of current operational blockers.

Historical Full Plan failures remain evidence, but operational health is bound to
one latest registered run per project.  Delivery state never clears a blocker:
BLOCKED/FAILED/WAITING_APPROVAL are derived directly from the current canonical
run state.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


_NON_ACTIONABLE_ATTENTION_STATES = frozenset({
    "COMPLETED",
    "CANCELLED",
    "SUPERSEDED",
    "RETIRED",
})
_DIRECT_BLOCKING_STATES = frozenset({
    "BLOCKED",
    "FAILED",
    "WAITING_APPROVAL",
})


def current_registered_job_keys(
    jobs: Sequence[Mapping[str, Any]],
) -> frozenset[tuple[str, str]]:
    """Return one latest registered run per project using canonical job-file mtime."""
    latest: dict[str, tuple[int, str]] = {}
    for job in jobs:
        project_id = str(job.get("project_id") or "")
        run_id = str(job.get("run_id") or "")
        job_path = Path(str(job.get("job_path") or ""))
        if not project_id or not run_id or not job_path.is_file() or job_path.is_symlink():
            continue
        try:
            registered_ns = job_path.stat().st_mtime_ns
        except OSError:
            continue
        candidate = (registered_ns, run_id)
        previous = latest.get(project_id)
        if previous is None or candidate > previous:
            latest[project_id] = candidate
    return frozenset((project_id, value[1]) for project_id, value in latest.items())


def blocking_attention_events(
    attention_events: Sequence[Mapping[str, Any]],
    *,
    current_job_keys: frozenset[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in attention_events:
        state = str(item.get("state") or "").upper()
        if state in _NON_ACTIONABLE_ATTENTION_STATES:
            continue
        if current_job_keys is not None:
            identity = (
                str(item.get("project_id") or ""),
                str(item.get("run_id") or ""),
            )
            if identity not in current_job_keys:
                continue
        rows.append(dict(item))
    return rows


def discover_current_state_blockers(
    jobs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    current = current_registered_job_keys(jobs)
    by_key = {
        (str(job.get("project_id") or ""), str(job.get("run_id") or "")): job
        for job in jobs
    }
    rows: list[dict[str, Any]] = []
    for project_id, run_id in sorted(current):
        job = by_key.get((project_id, run_id))
        if not job:
            continue
        state_root = Path(str(job.get("harness_state_root") or "")).expanduser()
        state_path = (
            state_root
            / "_workspace"
            / "production-full-plan"
            / project_id
            / run_id
            / "state.json"
        )
        if state_path.is_symlink() or not state_path.is_file():
            rows.append({
                "project_id": project_id,
                "run_id": run_id,
                "state": "UNKNOWN",
                "kind": "CURRENT_STATE_UNAVAILABLE",
                "reason": "CURRENT_CANONICAL_RUN_STATE_UNAVAILABLE",
                "source_ref": str(state_path),
                "synthetic_read_only": True,
            })
            continue
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            rows.append({
                "project_id": project_id,
                "run_id": run_id,
                "state": "UNKNOWN",
                "kind": "CURRENT_STATE_INVALID",
                "reason": "CURRENT_CANONICAL_RUN_STATE_INVALID",
                "source_ref": str(state_path),
                "synthetic_read_only": True,
            })
            continue
        state_name = str(state.get("state") or "").upper()
        if state_name not in _DIRECT_BLOCKING_STATES:
            continue
        rows.append({
            "project_id": project_id,
            "run_id": run_id,
            "state": state_name,
            "kind": state_name,
            "reason": str(
                state.get("terminal_reason")
                or state.get("last_error")
                or state_name
            ),
            "current_gate": state.get("current_gate"),
            "source_ref": str(state_path),
            "synthetic_read_only": True,
        })
    return rows


def merge_operational_blockers(
    attention_blockers: Sequence[Mapping[str, Any]],
    state_blockers: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge current blockers without allowing delivery to erase state blockers."""
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in (*state_blockers, *attention_blockers):
        project_id = str(item.get("project_id") or "")
        run_id = str(item.get("run_id") or "")
        state = str(item.get("state") or "UNKNOWN").upper()
        key = (project_id, run_id, state)
        current = rows.get(key)
        value = dict(item)
        if current is None:
            rows[key] = value
            continue
        # Prefer the real attention event because it carries event_id/delivery class.
        if value.get("event_id") and not current.get("event_id"):
            rows[key] = value
    return [
        rows[key]
        for key in sorted(rows)
    ]
