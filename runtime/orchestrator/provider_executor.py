from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .codex_adapter import create_manual_task, run_task_prompt
from .execution_modes import CODEX_CLI, MANUAL
from .nvidia_adapter import run_nvidia_reasoning_task
from .provider_adapter_registry import ProviderAdapterRegistry
from .provider_router import (
    CODEX_PROVIDER, LOCAL_PROVIDER, MANUAL_PROVIDER, NVIDIA_PROVIDER,
    RouterDecisionV2, route_provider,
)
from .result_normalizer import normalize_worker_result, render_worker_handoff_markdown
from .schemas import TaskSlice


def _run_nvidia_governed_adapter(task: TaskSlice, decision: RouterDecisionV2, project_root: str) -> dict[str, Any]:
    return run_nvidia_reasoning_task(
        prompt=task.input, output_dir=task.output_dir, project_root=project_root,
        input_files=task.input_files, model=decision.model_ref, require_explicit_model=True,
        fallback_models=decision.model_fallback_refs,
    )


def _run_codex_governed_adapter(task: TaskSlice, decision: RouterDecisionV2, project_root: str) -> dict[str, Any]:
    return run_task_prompt(
        task.task_prompt_path, task.output_dir, CODEX_CLI, project_root=project_root,
        required_capabilities=task.required_capabilities, model_ref=decision.model_ref,
    )


DEFAULT_PROVIDER_ADAPTER_REGISTRY = ProviderAdapterRegistry({
    NVIDIA_PROVIDER: _run_nvidia_governed_adapter,
    CODEX_PROVIDER: _run_codex_governed_adapter,
})


def _persist_nvidia_result(payload: dict[str, Any], task: TaskSlice) -> dict[str, Any]:
    normalized = normalize_worker_result(
        payload, task=task, source="nvidia", mode="nvidia", output_dir=task.output_dir
    )
    result_path = Path(task.result_path or Path(task.output_dir) / "result.json")
    handoff_path = Path(task.handoff_report_path or Path(task.output_dir) / "handoff_report.md")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(__import__("json").dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    handoff_path.write_text(render_worker_handoff_markdown(normalized), encoding="utf-8")
    return normalized


def _execute_governed(
    task: TaskSlice,
    *,
    decision: RouterDecisionV2,
    project_root: str,
    adapter_registry: ProviderAdapterRegistry | None = None,
) -> dict[str, Any]:
    if not decision.eligible:
        return {
            "status": "action_provider_blocked" if decision.stage == "ACTION" else "route_blocked",
            "mode": "hybrid",
            "provider": "",
            "model": "",
            "route_reason": decision.reason_code,
            "router_decision_digest": decision.decision_digest,
            "runtime_stage": decision.stage,
            "action_state": decision.action_state,
            "required_capabilities": list(decision.required_capabilities),
            "errors": [decision.reason_code],
            "next_step": "GPT_OPERATOR_REVIEW_REQUIRED",
        }

    if decision.stage == "ACTION" and decision.provider_ref != CODEX_PROVIDER:
        # The legacy provider executor has no Broker/tool-authorization context.
        # Never mistake proposal generation for an applied state change. Durable
        # Full Plan uses production_worker_executor.PROVIDER_ACTION instead.
        return {
            "status": "action_provider_blocked", "mode": "hybrid",
            "provider": decision.provider_ref, "model": decision.model_ref,
            "route_reason": "production_action_backend_required",
            "router_decision_digest": decision.decision_digest,
            "runtime_stage": decision.stage, "action_state": "ACTION_BACKEND_REQUIRED",
            "required_capabilities": list(decision.required_capabilities),
            "errors": ["production_action_backend_required"],
            "next_step": "DURABLE_FULL_PLAN_ACTION_BACKEND_REQUIRED",
        }

    registry = adapter_registry or DEFAULT_PROVIDER_ADAPTER_REGISTRY
    adapter = registry.resolve(decision.provider_ref)
    if adapter is None:
        return {
            "status": "action_provider_blocked" if decision.stage == "ACTION" else "route_blocked",
            "mode": "hybrid", "provider": decision.provider_ref, "model": decision.model_ref,
            "route_reason": "provider_adapter_unavailable",
            "router_decision_digest": decision.decision_digest,
            "runtime_stage": decision.stage, "action_state": "ROUTE_BLOCKED",
            "required_capabilities": list(decision.required_capabilities),
            "errors": ["provider_adapter_unavailable"],
            "next_step": "PROVIDER_ADAPTER_REGISTRATION_REQUIRED",
        }
    payload = dict(adapter(task, decision, project_root))

    if decision.provider_ref == CODEX_PROVIDER and str(payload.get("status", "")) in {"manual_fallback", "manual_pending"}:
        return {
            "status": "action_provider_blocked",
            "mode": "hybrid",
            "provider": "",
            "model": "",
            "route_reason": "codex_unavailable_manual_action_candidate",
            "router_decision_digest": decision.decision_digest,
            "runtime_stage": decision.stage,
            "action_state": "ACTION_PROVIDER_BLOCKED",
            "manual_action_candidate": payload.get("manual_execution_path", ""),
            "backend_failure_class": payload.get("backend_failure_class", ""),
            "errors": [str(payload.get("reason", "codex unavailable"))],
            "next_step": "GPT_AUTHORIZED_MANUAL_ACTION_OR_QUEUE_BLOCK",
        }

    actual_model = str(payload.get("model", "")).strip() if decision.provider_ref == NVIDIA_PROVIDER else decision.model_ref
    payload.update({
        "provider": decision.provider_ref,
        "model": actual_model or decision.model_ref,
        "routed_model": decision.model_ref,
        "route_reason": decision.reason_code,
        "router_decision_digest": decision.decision_digest,
        "runtime_stage": decision.stage,
        "action_state": "ACTION_RUNNING" if decision.stage == "ACTION" else f"{decision.stage}_RUNNING",
        "required_capabilities": list(decision.required_capabilities),
    })
    if decision.provider_ref == NVIDIA_PROVIDER:
        return _persist_nvidia_result(payload, task)
    return payload


def execute_provider_task(
    task: TaskSlice,
    *,
    mode: str,
    project_root: str,
    local_worker: Callable[[TaskSlice], dict[str, Any]],
    router_decision: RouterDecisionV2 | None = None,
    adapter_registry: ProviderAdapterRegistry | None = None,
) -> dict[str, Any]:
    if router_decision is not None:
        return _execute_governed(
            task, decision=router_decision, project_root=project_root, adapter_registry=adapter_registry
        )

    decision = route_provider(mode, task.required_capabilities)
    if decision.provider == LOCAL_PROVIDER:
        payload = local_worker(task)
    elif decision.provider == MANUAL_PROVIDER:
        payload = create_manual_task(task.task_prompt_path, task.output_dir)
    elif decision.provider == CODEX_PROVIDER:
        payload = run_task_prompt(
            task.task_prompt_path, task.output_dir, CODEX_CLI if mode != MANUAL else MANUAL,
            project_root=project_root, required_capabilities=task.required_capabilities,
        )
    elif decision.provider == NVIDIA_PROVIDER:
        payload = run_nvidia_reasoning_task(
            prompt=task.input, output_dir=task.output_dir, project_root=project_root,
            input_files=task.input_files,
        )
    else:
        payload = {"status": "failed", "errors": ["unknown_provider_route"]}

    payload.update({
        "provider": decision.provider,
        "route_reason": decision.reason_code,
        "required_capabilities": list(decision.required_capabilities),
    })
    if decision.provider == NVIDIA_PROVIDER:
        return _persist_nvidia_result(payload, task)
    return payload
