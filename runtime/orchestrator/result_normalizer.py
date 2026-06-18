from __future__ import annotations

from pathlib import Path
from typing import Any


SCHEMA_VERSION = "orchestration.worker.result.v1"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, (tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return [str(value)]


def _task_payload(task: Any | None) -> dict[str, Any]:
    if task is None:
        return {}
    if hasattr(task, "as_request_payload"):
        return dict(task.as_request_payload())
    if isinstance(task, dict):
        return dict(task)
    return {}


def _first_non_empty(payload: dict[str, Any], keys: tuple[str, ...], default: Any = "") -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _status_from_payload(payload: dict[str, Any], summary: str, findings: list[str], artifacts: list[str]) -> str:
    status = str(_first_non_empty(payload, ("status", "state", "result"), "")).strip().lower()
    if status in {"done", "success", "ok"}:
        return "completed"
    if status in {"blocked", "failed", "error", "failure"}:
        return "failed"
    if status in {"manual_pending", "manual_fallback", "waiting_manual"}:
        return status
    if status:
        return status
    if summary or findings or artifacts:
        return "completed"
    return "pending"


def _default_mode(payload: dict[str, Any], status: str, source: str) -> str:
    mode = str(_first_non_empty(payload, ("mode", "execution_mode"), "")).strip().lower().replace("_", "-")
    if mode:
        return mode
    if status.startswith("manual"):
        return "manual"
    if source == "codex-cli":
        return "codex-cli"
    return "mock"


def normalize_worker_result(
    payload: dict[str, Any] | None,
    *,
    task: Any | None = None,
    source: str = "worker",
    mode: str = "",
    prompt_path: str = "",
    output_dir: str = "",
    run_id: str = "",
    run_root: str = "",
) -> dict[str, Any]:
    payload = dict(payload or {})
    task_payload = _task_payload(task) or dict(payload.get("task") or {})

    thread_id = str(
        _first_non_empty(
            payload,
            ("thread_id", "thread"),
            task_payload.get("thread_id", ""),
        )
    ).strip()
    agent_name = str(
        _first_non_empty(
            payload,
            ("agent_name", "assigned_agent", "agent"),
            task_payload.get("assigned_agent", ""),
        )
    ).strip()
    summary = str(_first_non_empty(payload, ("summary", "notes", "message", "output"), "")).strip()
    findings = _as_list(_first_non_empty(payload, ("findings", "issues", "observations", "highlights"), []))
    warnings = _as_list(_first_non_empty(payload, ("warnings", "cautions", "risks"), []))
    errors = _as_list(_first_non_empty(payload, ("errors", "blockers", "failures"), []))
    artifacts = _as_list(_first_non_empty(payload, ("artifacts", "files", "outputs"), []))
    next_step = str(_first_non_empty(payload, ("next_step", "next", "recommendation"), "")).strip()
    approval_classification = str(
        _first_non_empty(payload, ("approval_classification", "risk_class"), task_payload.get("risk_class", "general"))
    ).strip() or "general"
    validation_criteria = _as_list(_first_non_empty(payload, ("validation_criteria",), task_payload.get("validation_criteria", [])))
    editable_scope = _as_list(_first_non_empty(payload, ("editable_scope",), task_payload.get("editable_scope", [])))
    forbidden_scope = _as_list(_first_non_empty(payload, ("forbidden_scope",), task_payload.get("forbidden_scope", [])))
    input_files = _as_list(_first_non_empty(payload, ("input_files",), task_payload.get("input_files", [])))
    status = _status_from_payload(payload, summary, findings, artifacts)
    normalized_mode = _default_mode(payload, status, source) if not mode else str(mode).strip().lower().replace("_", "-")
    handoff_report_path = str(
        _first_non_empty(
            payload,
            ("handoff_report_path",),
            str(Path(output_dir) / "handoff_report.md") if output_dir else task_payload.get("handoff_report_path", ""),
        )
    ).strip()
    result_path = str(
        _first_non_empty(
            payload,
            ("result_path",),
            str(Path(output_dir) / "result.json") if output_dir else task_payload.get("result_path", ""),
        )
    ).strip()
    manual_execution_path = str(
        _first_non_empty(
            payload,
            ("manual_execution_path",),
            task_payload.get("manual_execution_path", ""),
        )
    ).strip()
    project_root = str(_first_non_empty(payload, ("project_root",), task_payload.get("project_root", ""))).strip()

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "mode": normalized_mode,
        "run_id": str(_first_non_empty(payload, ("run_id",), run_id or task_payload.get("run_id", ""))).strip(),
        "run_root": str(_first_non_empty(payload, ("run_root",), run_root or task_payload.get("run_root", ""))).strip(),
        "project_root": project_root,
        "thread_id": thread_id,
        "agent_name": agent_name,
        "status": status,
        "summary": summary,
        "findings": findings,
        "warnings": warnings,
        "errors": errors,
        "artifacts": artifacts,
        "next_step": next_step,
        "approval_classification": approval_classification,
        "validation_criteria": validation_criteria,
        "editable_scope": editable_scope,
        "forbidden_scope": forbidden_scope,
        "input_files": input_files,
        "prompt_path": str(_first_non_empty(payload, ("prompt_path",), prompt_path)).strip(),
        "output_dir": str(_first_non_empty(payload, ("output_dir",), output_dir)).strip(),
        "handoff_report_path": handoff_report_path,
        "result_path": result_path,
        "manual_execution_path": manual_execution_path,
        "task_purpose": str(_first_non_empty(payload, ("task_purpose",), task_payload.get("input", ""))).strip(),
        "task": task_payload,
    }
    if payload.get("raw_payload") is not None:
        normalized["raw_payload"] = payload["raw_payload"]
    return normalized


def _bullet_block(title: str, items: list[str]) -> list[str]:
    lines = [title]
    if items:
        lines.extend(f"- {item}" for item in items)
    else:
        lines.append("- none")
    return lines


def render_worker_handoff_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Worker Handoff",
        "",
        f"Schema Version: {result.get('schema_version', SCHEMA_VERSION)}",
        f"Source: {result.get('source', '')}",
        f"Mode: {result.get('mode', '')}",
        f"Run ID: {result.get('run_id', '')}",
        f"Thread: {result.get('thread_id', '')}",
        f"Agent: {result.get('agent_name', '')}",
        f"Status: {result.get('status', '')}",
        "",
        "Summary",
        result.get("summary", "") or "none",
        "",
    ]
    for title, key in (
        ("Findings", "findings"),
        ("Warnings", "warnings"),
        ("Errors", "errors"),
        ("Artifacts", "artifacts"),
        ("Validation Criteria", "validation_criteria"),
        ("Editable Scope", "editable_scope"),
        ("Forbidden Scope", "forbidden_scope"),
        ("Input Files", "input_files"),
    ):
        lines.extend(_bullet_block(title, _as_list(result.get(key))))
        lines.append("")
    lines.extend(
        [
            "Next Step",
            result.get("next_step", "") or "none",
            "",
            "Approval Classification",
            result.get("approval_classification", "") or "none",
            "",
            "Paths",
            f"- prompt: {result.get('prompt_path', '') or 'none'}",
            f"- output: {result.get('output_dir', '') or 'none'}",
            f"- handoff: {result.get('handoff_report_path', '') or 'none'}",
            f"- result: {result.get('result_path', '') or 'none'}",
            f"- manual: {result.get('manual_execution_path', '') or 'none'}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
