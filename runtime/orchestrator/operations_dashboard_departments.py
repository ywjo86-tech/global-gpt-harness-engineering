"""Typed department projection adapter for AI Office Dashboard V2."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.ai_office.department_registry import (
    AIOfficeDepartmentRegistryStore,
    DashboardDepartmentBindingV1,
)
from runtime.ai_office.state_store import AIOfficeStateStore, AIOfficeStateStoreError
from runtime.ai_office.workflow import OFFICE_RUN_SCHEMA_V1, OfficeRunV1

from .operations_read_model import normalize_operations_state


class OperationsDashboardDepartmentSourceError(ValueError):
    pass


_DEPARTMENT_DISPLAY_NAMES = {
    "financial": "Financial Office",
    "accelerator": "Accelerator Office",
    "procurement": "Procurement Office",
    "research": "Research Office",
    "content": "Content Office",
    "development": "Development Office",
    "capability": "AI Capability Acquisition",
}


def _office_run_from_binding(
    state_root: str | Path,
    binding: DashboardDepartmentBindingV1,
) -> OfficeRunV1:
    state = AIOfficeStateStore(
        state_root,
        project_id=binding.project_id,
        run_id=binding.run_id,
    )
    try:
        snapshot = state.load()
    except AIOfficeStateStoreError as exc:
        raise OperationsDashboardDepartmentSourceError(
            "bound canonical AI Office state invalid"
        ) from exc

    assignment_refs = [
        ref.split(":", 1)[1]
        for ref in snapshot.workflow_refs
        if ref.startswith("full-plan-assignment:")
    ]
    fanin_refs = [
        ref.split(":", 1)[1]
        for ref in snapshot.workflow_refs
        if ref.startswith("full-plan-fanin:")
    ]
    return OfficeRunV1(
        OFFICE_RUN_SCHEMA_V1,
        binding.office_id,
        binding.department_id,
        snapshot.run_id,
        binding.binding_ref,
        snapshot.workflow_state,
        snapshot.revision,
        assignment_refs[-1] if assignment_refs else "",
        fanin_refs[-1] if fanin_refs else "",
    )


def read_operations_dashboard_departments(
    state_root: str | Path,
) -> list[dict[str, Any]] | None:
    store = AIOfficeDepartmentRegistryStore(state_root)
    if not store.registry_path.exists() and not store.registry_path.is_symlink():
        return None

    registry = store.load_registry()
    direct_runs = {run.department_id: run for run in store.load_current_runs()}
    bindings = {binding.department_id: binding for binding in store.load_bindings()}
    rows: list[dict[str, Any]] = []

    for department_id in registry.department_ids:
        direct_run = direct_runs.get(department_id)
        binding = bindings.get(department_id)
        if direct_run is not None and binding is not None:
            raise OperationsDashboardDepartmentSourceError(
                "ambiguous canonical department sources"
            )

        display_name = _DEPARTMENT_DISPLAY_NAMES.get(department_id, department_id)
        if binding is not None:
            run = _office_run_from_binding(state_root, binding)
            current_work = f"{binding.project_id} / {run.run_id}"
            source_state = "CANONICAL_STATE_BINDING_V1"
        elif direct_run is not None:
            run = direct_run
            current_work = run.run_id
            source_state = "CANONICAL_OFFICE_RUN_V1"
        else:
            rows.append(
                {
                    "department_id": department_id,
                    "display_name": display_name,
                    "binding_state": "BOUND",
                    "status": "IDLE",
                    "current_work": "현재 canonical run 없음",
                    "progress": None,
                    "source_state": "CANONICAL_REGISTRY_NO_RUN",
                }
            )
            continue

        normalized, _ = normalize_operations_state(run.workflow_state)
        rows.append(
            {
                "department_id": department_id,
                "display_name": display_name,
                "binding_state": "BOUND",
                "status": normalized,
                "current_work": current_work,
                "progress": None,
                "source_state": source_state,
            }
        )
    return rows
