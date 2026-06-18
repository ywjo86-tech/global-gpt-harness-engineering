from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.orchestrator.audit_log import read_recent_audit_events


def _tail_lines(path: Path, limit: int = 50) -> list[str]:
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return lines[-limit:]


def read_recent_events(project_root: str | Path, *, run_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    root = Path(project_root).resolve()
    runtime_log = root / "logs" / "app.log"
    bridge_audit = root / "runtime" / "jarvis_bridge" / "audit.log"
    run_root = root / "runtime" / "orchestrator_runs" / run_id if run_id else None
    run_audit = run_root / "logs" / "audit.log" if run_root else None
    return {
        "app_log": _tail_lines(runtime_log, limit),
        "bridge_audit": read_recent_audit_events(bridge_audit, limit=limit),
        "run_audit": read_recent_audit_events(run_audit, limit=limit) if run_audit else [],
    }
