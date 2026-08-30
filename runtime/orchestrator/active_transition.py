"""Atomic canonical active-LV transition records for production resumes."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class ActiveTransitionError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def activate_canonical_lv_transition(harness_root: str | Path, *, project_id: str, gate_id: str,
                                    lv_id: str, run_id: str, approval_event_id: str,
                                    plan_sha256: str, branch: str, baseline_head: str,
                                    current_head: str, predecessor_digest: str,
                                    owned_files: list[str], completion_conditions: list[str]) -> dict[str, Any]:
    if not all(isinstance(x, str) and x for x in (project_id, gate_id, lv_id, run_id, approval_event_id, plan_sha256, branch, baseline_head, current_head, predecessor_digest)):
        raise ActiveTransitionError("transition binding is incomplete")
    payload: dict[str, Any] = {
        "schema_version": "orchestration.canonical-active-lv-transition.v1",
        "project_id": project_id, "gate_id": gate_id, "lv_id": lv_id, "run_id": run_id,
        "approval_event_id": approval_event_id, "plan_sha256": plan_sha256, "branch": branch,
        "baseline_head": baseline_head, "current_head": current_head,
        "predecessor_completion_digest": predecessor_digest,
        "owned_file_scope": list(owned_files), "completion_conditions": list(completion_conditions),
        "transition_type": "SYSTEM_TRANSITION", "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    unsigned = dict(payload)
    payload["record_hash"] = hashlib.sha256(_canonical(unsigned)).hexdigest()
    root = Path(harness_root).resolve() / "_workspace" / "global-gate" / project_id / "state"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{gate_id}-{run_id}-active-transition.json"
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise ActiveTransitionError("existing transition artifact is unsafe")
        existing = json.loads(target.read_text(encoding="utf-8"))
        comparable_existing = {k: v for k, v in existing.items() if k not in {"created_at", "record_hash"}}
        comparable_new = {k: v for k, v in payload.items() if k not in {"created_at", "record_hash"}}
        if comparable_existing != comparable_new:
            raise ActiveTransitionError("active transition conflict")
        if existing.get("record_hash") != hashlib.sha256(_canonical({k: v for k, v in existing.items() if k != "record_hash"})).hexdigest():
            raise ActiveTransitionError("existing transition hash mismatch")
        return existing
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=str(root))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return payload
