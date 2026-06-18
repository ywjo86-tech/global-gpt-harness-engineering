from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import RuntimeState


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StateStore:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.runtime_dir = self.project_root / "runtime"
        self.state_path = self.runtime_dir / "orchestrator_state.json"
        self.markdown_path = self.project_root / "docs" / "harness" / "orchestration-state.md"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.state = self.load()

    def load(self) -> RuntimeState:
        if self.state_path.exists():
            return RuntimeState.from_dict(json.loads(self.state_path.read_text(encoding="utf-8")))
        return RuntimeState()

    def save(self, state: RuntimeState | dict[str, Any]) -> RuntimeState:
        runtime_state = state if isinstance(state, RuntimeState) else RuntimeState.from_dict(state)
        runtime_state.last_updated = _utc_now()
        payload = runtime_state.to_dict()
        self.state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self._write_markdown(runtime_state)
        self.state = runtime_state
        return runtime_state

    def _write_markdown(self, state: RuntimeState) -> None:
        self.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Orchestration State",
            "",
            f"Project: {self.project_root.name}",
            f"Current phase: {state.current_phase}",
            f"Execution mode: {state.execution_mode}",
            f"Active run ID: {state.active_run_id or 'none'}",
            f"Manual execution required: {state.manual_execution_required}",
            f"Codex CLI available: {state.codex_cli_available}",
            "",
            "Planning",
            f"- planner threads: {len(state.planning_artifact.get('thread_plan', []))}",
            f"- planner agent: {state.planning_artifact.get('planner_agent', 'none')}",
            f"- selected agents: {', '.join(state.planning_artifact.get('selected_agents', [])) or 'none'}",
            f"- execution ready: {state.planning_artifact.get('execution_ready', False)}",
            f"- run root: {state.run_root or 'none'}",
            "",
            "Active Threads",
        ]
        if state.active_threads:
            for thread in state.active_threads:
                lines.append(
                    f"- {thread.get('thread_id', 'unknown')}: {thread.get('assigned_agent', 'unknown')} ({thread.get('status', 'pending')})"
                )
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "Fan-Out",
                f"- status: {state.fanout_status}",
                f"- active threads: {len(state.active_threads)}",
                "",
                "Fan-In",
                f"- status: {state.fanin_status}",
                f"- missing outputs: {len(state.fanin_report.get('missing_outputs', []))}",
                f"- collection status: {state.collection_status}",
                "",
                "Gate Status",
            ]
        )
        gate = state.stage_gate_decision or {}
        if gate:
            lines.extend(
                [
                    f"- decision: {gate.get('decision', 'unknown')}",
                    f"- next step: {gate.get('next_step', '')}",
                    f"- authorization: {gate.get('authorization', '')}",
                ]
            )
        else:
            lines.append("- decision: pending")
        lines.extend(
            [
                "",
                "Collection Report",
                f"- {bool(state.collection_report)}",
                "",
                "Stage Gate Prompt",
                f"- {state.stage_gate_prompt_path or 'none'}",
                "",
                "Approval Required",
                f"- {state.approval_required}",
                "",
                "Next Step",
                f"- {state.next_step or 'none'}",
                "",
                f"Last Updated: {state.last_updated}",
            ]
        )
        self.markdown_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def update(self, **changes: Any) -> RuntimeState:
        payload = self.state.to_dict()
        payload.update(changes)
        state = RuntimeState.from_dict(payload)
        return self.save(state)


def append_log_line(log_path: str | Path, record_type: str, project: str, phase: str, decision: str, evidence: str, next_step: str) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{_utc_now()} | {record_type} | {project} | {phase} | {decision} | {evidence} | {next_step}"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text((existing + ("\n" if existing else "") + line).rstrip() + "\n", encoding="utf-8")
