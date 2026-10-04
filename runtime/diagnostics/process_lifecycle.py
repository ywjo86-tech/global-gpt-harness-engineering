"""Read-only process lifecycle diagnostics; this module owns no cleanup authority."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


class ProcessLifecycleDiagnosticError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessLifecycleDiagnosticV1:
    pid: int
    owner_ref: str
    owner_state_exists: bool
    lock_exists: bool
    expected_lifecycle_state: str
    last_semantic_progress: str
    status: str
    orphan_suspicion_reason: str
    recommended_action: str
    cleanup_authorization_required: bool


def collect_process_ownership_facts(
    *,
    pid: int,
    owner_ref: str,
    owner_state_path: str | Path,
    lock_path: str | Path,
    expected_lifecycle_state: str = "UNKNOWN",
    last_semantic_progress: str = "",
    command_digest: str = "",
) -> dict[str, Any]:
    """Collect read-only ownership facts; never signals or reaps a process."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ProcessLifecycleDiagnosticError("valid pid is required")
    state = Path(owner_state_path)
    lock = Path(lock_path)
    return {
        "pid": pid,
        "owner_ref": str(owner_ref),
        "owner_state_path": str(state),
        "owner_state_exists": state.exists() and not state.is_symlink(),
        "lock_path": str(lock),
        "lock_exists": lock.exists() and not lock.is_symlink(),
        "expected_lifecycle_state": str(expected_lifecycle_state),
        "last_semantic_progress": str(last_semantic_progress),
        "command_digest": str(command_digest),
        "collection_mode": "READ_ONLY",
    }


def diagnose_process_lifecycle(
    facts: Mapping[str, Any], *, now: datetime
) -> ProcessLifecycleDiagnosticV1:
    if not isinstance(facts, Mapping):
        raise ProcessLifecycleDiagnosticError("process facts must be a mapping")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ProcessLifecycleDiagnosticError("timezone-aware now is required")
    pid = facts.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ProcessLifecycleDiagnosticError("valid pid is required")
    owner_ref = str(facts.get("owner_ref") or "").strip()
    owner_state_exists = bool(facts.get("owner_state_exists"))
    lock_exists = bool(facts.get("lock_exists"))
    expected = str(facts.get("expected_lifecycle_state") or "UNKNOWN").strip()
    progress = str(facts.get("last_semantic_progress") or "").strip()
    if not owner_ref:
        raise ProcessLifecycleDiagnosticError("owner reference is required")
    if not owner_state_exists and not lock_exists:
        status = "ORPHAN_SUSPECTED"
        reason = "owner state and lock are both missing"
        action = "review process ownership and authorize cleanup if confirmed"
        approval = True
    elif not owner_state_exists or not lock_exists:
        status = "OWNERSHIP_DEGRADED"
        reason = "process ownership evidence is incomplete"
        action = "review owner state and lock consistency"
        approval = False
    else:
        status = "OWNED"
        reason = ""
        action = "none"
        approval = False
    return ProcessLifecycleDiagnosticV1(
        pid=pid,
        owner_ref=owner_ref,
        owner_state_exists=owner_state_exists,
        lock_exists=lock_exists,
        expected_lifecycle_state=expected,
        last_semantic_progress=progress,
        status=status,
        orphan_suspicion_reason=reason,
        recommended_action=action,
        cleanup_authorization_required=approval,
    )
