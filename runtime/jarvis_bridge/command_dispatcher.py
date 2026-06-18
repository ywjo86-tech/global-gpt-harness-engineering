from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.orchestrator.audit_log import append_audit_event
from runtime.orchestrator.engine import OrchestrationEngine


ALLOWED_COMMANDS = {"inspect", "plan", "run", "collect", "fanin", "gate", "status", "approve"}


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _command_root(project_root: Path) -> Path:
    root = project_root / "runtime" / "jarvis_bridge" / "commands"
    root.mkdir(parents=True, exist_ok=True)
    return root


def dispatch_command(
    project_root: str | Path,
    command: str,
    *,
    run_id: str | None = None,
    mode: str = "mock",
    approval: str = "",
    execute: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    normalized = command.strip().lower()
    command_root = _command_root(root)
    command_path = command_root / f"{_utc_stamp()}-{normalized}.json"
    payload = {
        "project_root": str(root),
        "command": normalized,
        "run_id": run_id or "",
        "mode": mode,
        "approval": approval,
        "execute": execute,
        "status": "queued",
    }
    command_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    result: dict[str, Any] = {
        "command": normalized,
        "command_path": str(command_path),
        "status": "queued",
        "result_path": "",
        "result": {},
    }
    if not execute:
        append_audit_event(root / "runtime" / "jarvis_bridge" / "audit.log", "command", f"queued {normalized}", run_id=run_id or "", mode=mode)
        return result

    if normalized not in ALLOWED_COMMANDS:
        result["status"] = "unsupported"
        append_audit_event(root / "runtime" / "jarvis_bridge" / "audit.log", "command", f"unsupported {normalized}", run_id=run_id or "", mode=mode)
        return result

    engine = OrchestrationEngine(root)
    if normalized == "approve":
        executed = engine.approve(approval)
    elif normalized == "inspect":
        executed = engine.inspect()
    elif normalized == "plan":
        executed = engine.plan(mode=mode, run_id=run_id)
    elif normalized == "run":
        executed = engine.run(mode=mode, run_id=run_id)
    elif normalized == "collect":
        executed = engine.collect(run_id)
    elif normalized == "fanin":
        executed = engine.fanin(run_id)
    elif normalized == "gate":
        executed = engine.gate(mode=mode, run_id=run_id)
    else:
        executed = engine.status(run_id)

    result_path = command_root / f"{_utc_stamp()}-{normalized}.result.json"
    result_path.write_text(json.dumps(executed, indent=2, ensure_ascii=False), encoding="utf-8")
    result.update(
        {
            "status": "executed",
            "result_path": str(result_path),
            "result": executed,
        }
    )
    append_audit_event(root / "runtime" / "jarvis_bridge" / "audit.log", "command", f"executed {normalized}", run_id=run_id or "", mode=mode)
    return result
