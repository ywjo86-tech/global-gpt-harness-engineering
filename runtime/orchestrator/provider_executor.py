from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .codex_adapter import create_manual_task, run_task_prompt
from .execution_modes import CODEX_CLI, MANUAL
from .nvidia_adapter import run_nvidia_reasoning_task
from .provider_router import CODEX_PROVIDER, LOCAL_PROVIDER, MANUAL_PROVIDER, NVIDIA_PROVIDER, route_provider
from .result_normalizer import normalize_worker_result, render_worker_handoff_markdown
from .schemas import TaskSlice


def execute_provider_task(
    task: TaskSlice,
    *,
    mode: str,
    project_root: str,
    local_worker: Callable[[TaskSlice], dict[str, Any]],
) -> dict[str, Any]:
    decision = route_provider(mode, task.required_capabilities)
    if decision.provider == LOCAL_PROVIDER:
        payload = local_worker(task)
    elif decision.provider == MANUAL_PROVIDER:
        payload = create_manual_task(task.task_prompt_path, task.output_dir)
    elif decision.provider == CODEX_PROVIDER:
        payload = run_task_prompt(task.task_prompt_path, task.output_dir, CODEX_CLI if mode != MANUAL else MANUAL)
    elif decision.provider == NVIDIA_PROVIDER:
        payload = run_nvidia_reasoning_task(
            prompt=task.input,
            output_dir=task.output_dir,
            project_root=project_root,
            input_files=task.input_files,
        )
    else:
        payload = {"status": "failed", "errors": ["unknown_provider_route"]}

    payload.update({"provider": decision.provider, "route_reason": decision.reason_code, "required_capabilities": list(decision.required_capabilities)})
    if decision.provider == NVIDIA_PROVIDER:
        normalized = normalize_worker_result(payload, task=task, source="nvidia", mode="nvidia", output_dir=task.output_dir)
        result_path = Path(task.result_path or Path(task.output_dir) / "result.json")
        handoff_path = Path(task.handoff_report_path or Path(task.output_dir) / "handoff_report.md")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(__import__("json").dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
        handoff_path.write_text(render_worker_handoff_markdown(normalized), encoding="utf-8")
        return normalized
    return payload
