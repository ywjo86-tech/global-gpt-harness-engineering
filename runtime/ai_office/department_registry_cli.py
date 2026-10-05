"""Safe CLI for publishing and validating AI Office dashboard department bindings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .department_registry import (
    DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
    AIOfficeDepartmentRegistryError,
    AIOfficeDepartmentRegistryStore,
    DashboardDepartmentBindingV1,
)
from .state_store import AIOfficeStateStore, AIOfficeStateStoreError
from .workflow import OFFICE_REGISTRY_SCHEMA_V1, OfficeRegistryV1


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Manage canonical AI Office dashboard department registry bindings."
    )
    value.add_argument("--state-root", required=True)
    commands = value.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--office-id", required=True)
    init.add_argument("--registry-ref", required=True)
    init.add_argument("--department-id", action="append", required=True)

    bind = commands.add_parser("bind")
    bind.add_argument("--department-id", required=True)
    bind.add_argument("--project-id", required=True)
    bind.add_argument("--run-id", required=True)
    bind.add_argument("--binding-ref", required=True)

    commands.add_parser("validate")
    return value


def _state_root(raw: str) -> Path:
    root = Path(raw).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise AIOfficeDepartmentRegistryError("state root unavailable")
    return root


def _validate_binding_target(
    state_root: Path,
    *,
    project_id: str,
    run_id: str,
) -> None:
    try:
        AIOfficeStateStore(
            state_root,
            project_id=project_id,
            run_id=run_id,
        ).load()
    except (AIOfficeStateStoreError, OSError, ValueError) as exc:
        raise AIOfficeDepartmentRegistryError(
            "binding target state invalid"
        ) from exc


def _summary(
    store: AIOfficeDepartmentRegistryStore,
    *,
    validate_targets: bool,
    state_root: Path,
) -> dict[str, object]:
    registry = store.load_registry()
    runs = store.load_current_runs()
    bindings = store.load_bindings()
    direct_ids = {run.department_id for run in runs}
    binding_ids = {binding.department_id for binding in bindings}
    if direct_ids & binding_ids:
        raise AIOfficeDepartmentRegistryError(
            "ambiguous canonical department sources"
        )
    if validate_targets:
        for binding in bindings:
            _validate_binding_target(
                state_root,
                project_id=binding.project_id,
                run_id=binding.run_id,
            )
    return {
        "schema_version": "ai-office.dashboard-department-registry-cli-result.v1",
        "status": "PASS",
        "office_id": registry.office_id,
        "department_count": len(registry.department_ids),
        "current_run_count": len(runs),
        "binding_count": len(bindings),
        "registry_digest": registry.registry_digest,
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    state_root = _state_root(args.state_root)
    store = AIOfficeDepartmentRegistryStore(state_root)

    if args.command == "init":
        registry = OfficeRegistryV1(
            OFFICE_REGISTRY_SCHEMA_V1,
            args.office_id,
            tuple(args.department_id),
            args.registry_ref,
        )
        store.publish_registry(registry)
        result = _summary(
            store,
            validate_targets=False,
            state_root=state_root,
        )
    elif args.command == "bind":
        registry = store.load_registry()
        direct = {
            run.department_id
            for run in store.load_current_runs()
        }
        if args.department_id in direct:
            raise AIOfficeDepartmentRegistryError(
                "direct current run already exists for department"
            )
        _validate_binding_target(
            state_root,
            project_id=args.project_id,
            run_id=args.run_id,
        )
        store.publish_binding(
            DashboardDepartmentBindingV1(
                DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
                registry.office_id,
                args.department_id,
                args.project_id,
                args.run_id,
                args.binding_ref,
            )
        )
        result = _summary(
            store,
            validate_targets=True,
            state_root=state_root,
        )
    else:
        result = _summary(
            store,
            validate_targets=True,
            state_root=state_root,
        )

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
