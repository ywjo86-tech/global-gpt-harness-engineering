"""Canonical persisted department registry for AI Office read models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .contracts import canonical_digest
from .workflow import (
    OFFICE_REGISTRY_SCHEMA_V1,
    OFFICE_RUN_SCHEMA_V1,
    OfficeRegistryV1,
    OfficeRunV1,
    WorkflowContractError,
)


class AIOfficeDepartmentRegistryError(ValueError):
    pass


DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1 = "ai-office.dashboard-department-binding.v1"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
        raise AIOfficeDepartmentRegistryError(f"invalid {label}")
    return value.strip()


@dataclass(frozen=True, slots=True)
class DashboardDepartmentBindingV1:
    schema_version: str
    office_id: str
    department_id: str
    project_id: str
    run_id: str
    binding_ref: str

    def __post_init__(self) -> None:
        if self.schema_version != DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1:
            raise AIOfficeDepartmentRegistryError("unsupported department binding schema")
        object.__setattr__(self, "office_id", _safe_component(self.office_id, "office_id"))
        object.__setattr__(self, "department_id", _safe_component(self.department_id, "department_id"))
        object.__setattr__(self, "project_id", _safe_component(self.project_id, "project_id"))
        object.__setattr__(self, "run_id", _safe_component(self.run_id, "run_id"))
        object.__setattr__(self, "binding_ref", _text(self.binding_ref, "binding_ref"))

    @property
    def binding_digest(self) -> str:
        return canonical_digest(asdict(self))


def _safe_component(value: str, label: str) -> str:
    item = str(value).strip()
    if not item or len(item) > 160 or "/" in item or "\\" in item or ".." in item:
        raise AIOfficeDepartmentRegistryError(f"unsafe {label}")
    return item


class AIOfficeDepartmentRegistryStore:
    def __init__(self, state_root: str | Path):
        root = Path(state_root).expanduser().resolve()
        self.root = root / "_workspace" / "ai-office-departments"
        self.registry_path = self.root / "registry.json"
        self.current_root = self.root / "current"
        self.binding_root = self.root / "bindings"

    def _ensure_safe_root(self) -> None:
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise AIOfficeDepartmentRegistryError("unsafe registry root")

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
        if path.is_symlink():
            raise AIOfficeDepartmentRegistryError("unsafe output path")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (
            json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(temp_name, path)
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def publish_registry(self, registry: OfficeRegistryV1) -> Path:
        if not isinstance(registry, OfficeRegistryV1):
            raise AIOfficeDepartmentRegistryError("OfficeRegistryV1 required")
        self._ensure_safe_root()
        if self.registry_path.is_symlink():
            raise AIOfficeDepartmentRegistryError("unsafe registry path")
        payload = asdict(registry)
        payload["department_ids"] = list(registry.department_ids)
        payload["registry_digest"] = registry.registry_digest
        self._atomic_json(self.registry_path, payload)
        return self.registry_path

    def load_registry(self) -> OfficeRegistryV1:
        self._ensure_safe_root()
        path = self.registry_path
        if path.is_symlink() or not path.is_file():
            raise AIOfficeDepartmentRegistryError("unsafe registry path")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AIOfficeDepartmentRegistryError("registry unreadable") from exc
        expected = {
            "schema_version",
            "office_id",
            "department_ids",
            "registry_ref",
            "registry_digest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise AIOfficeDepartmentRegistryError("registry shape mismatch")
        try:
            if not isinstance(value["department_ids"], list):
                raise TypeError("department_ids must be a list")
            registry = OfficeRegistryV1(
                value["schema_version"],
                value["office_id"],
                tuple(value["department_ids"]),
                value["registry_ref"],
            )
        except (TypeError, ValueError, WorkflowContractError) as exc:
            raise AIOfficeDepartmentRegistryError("registry contract invalid") from exc
        if value["schema_version"] != OFFICE_REGISTRY_SCHEMA_V1:
            raise AIOfficeDepartmentRegistryError("registry schema mismatch")
        if str(value["registry_digest"]) != registry.registry_digest:
            raise AIOfficeDepartmentRegistryError("registry digest mismatch")
        return registry

    def _current_path(self, department_id: str) -> Path:
        return self.current_root / f"{_safe_component(department_id, 'department_id')}.json"

    def publish_current_run(self, run: OfficeRunV1) -> Path:
        if not isinstance(run, OfficeRunV1):
            raise AIOfficeDepartmentRegistryError("OfficeRunV1 required")
        registry = self.load_registry()
        if self.current_root.is_symlink() or (
            self.current_root.exists() and not self.current_root.is_dir()
        ):
            raise AIOfficeDepartmentRegistryError("unsafe current run root")
        if run.office_id != registry.office_id:
            raise AIOfficeDepartmentRegistryError("office identity mismatch")
        if run.department_id not in registry.department_ids:
            raise AIOfficeDepartmentRegistryError("department is not registered")
        path = self._current_path(run.department_id)
        if path.is_symlink():
            raise AIOfficeDepartmentRegistryError("unsafe current run path")
        payload = asdict(run)
        payload["run_digest"] = run.run_digest
        self._atomic_json(path, payload)
        return path

    def _load_run(self, path: Path, *, registry: OfficeRegistryV1) -> OfficeRunV1:
        if path.is_symlink() or not path.is_file():
            raise AIOfficeDepartmentRegistryError("unsafe current run path")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AIOfficeDepartmentRegistryError("current run unreadable") from exc
        expected = {
            "schema_version",
            "office_id",
            "department_id",
            "run_id",
            "schedule_ref",
            "workflow_state",
            "revision",
            "external_full_plan_assignment_ref",
            "external_fanin_ref",
            "run_digest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise AIOfficeDepartmentRegistryError("current run shape mismatch")
        try:
            run = OfficeRunV1(
                value["schema_version"],
                value["office_id"],
                value["department_id"],
                value["run_id"],
                value["schedule_ref"],
                value["workflow_state"],
                value["revision"],
                value["external_full_plan_assignment_ref"],
                value["external_fanin_ref"],
            )
        except (TypeError, ValueError, WorkflowContractError) as exc:
            raise AIOfficeDepartmentRegistryError("current run contract invalid") from exc
        if value["schema_version"] != OFFICE_RUN_SCHEMA_V1:
            raise AIOfficeDepartmentRegistryError("current run schema mismatch")
        if str(value["run_digest"]) != run.run_digest:
            raise AIOfficeDepartmentRegistryError("current run digest mismatch")
        if run.office_id != registry.office_id:
            raise AIOfficeDepartmentRegistryError("current run office mismatch")
        if run.department_id not in registry.department_ids:
            raise AIOfficeDepartmentRegistryError("current run department not registered")
        if path.stem != run.department_id:
            raise AIOfficeDepartmentRegistryError("current run path/department mismatch")
        return run

    def _binding_path(self, department_id: str) -> Path:
        return self.binding_root / f"{_safe_component(department_id, 'department_id')}.json"

    def publish_binding(self, binding: DashboardDepartmentBindingV1) -> Path:
        if not isinstance(binding, DashboardDepartmentBindingV1):
            raise AIOfficeDepartmentRegistryError("DashboardDepartmentBindingV1 required")
        registry = self.load_registry()
        if self.binding_root.is_symlink() or (
            self.binding_root.exists() and not self.binding_root.is_dir()
        ):
            raise AIOfficeDepartmentRegistryError("unsafe binding root")
        if binding.office_id != registry.office_id:
            raise AIOfficeDepartmentRegistryError("office identity mismatch")
        if binding.department_id not in registry.department_ids:
            raise AIOfficeDepartmentRegistryError("department is not registered")
        path = self._binding_path(binding.department_id)
        if path.is_symlink():
            raise AIOfficeDepartmentRegistryError("unsafe binding path")
        payload = asdict(binding)
        payload["binding_digest"] = binding.binding_digest
        self._atomic_json(path, payload)
        return path

    def _load_binding(
        self,
        path: Path,
        *,
        registry: OfficeRegistryV1,
    ) -> DashboardDepartmentBindingV1:
        if path.is_symlink() or not path.is_file():
            raise AIOfficeDepartmentRegistryError("unsafe binding path")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AIOfficeDepartmentRegistryError("binding unreadable") from exc
        expected = {
            "schema_version",
            "office_id",
            "department_id",
            "project_id",
            "run_id",
            "binding_ref",
            "binding_digest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise AIOfficeDepartmentRegistryError("binding shape mismatch")
        try:
            binding = DashboardDepartmentBindingV1(
                value["schema_version"],
                value["office_id"],
                value["department_id"],
                value["project_id"],
                value["run_id"],
                value["binding_ref"],
            )
        except (TypeError, ValueError, AIOfficeDepartmentRegistryError) as exc:
            raise AIOfficeDepartmentRegistryError("binding contract invalid") from exc
        if str(value["binding_digest"]) != binding.binding_digest:
            raise AIOfficeDepartmentRegistryError("binding digest mismatch")
        if binding.office_id != registry.office_id:
            raise AIOfficeDepartmentRegistryError("binding office mismatch")
        if binding.department_id not in registry.department_ids:
            raise AIOfficeDepartmentRegistryError("binding department not registered")
        if path.stem != binding.department_id:
            raise AIOfficeDepartmentRegistryError("binding path/department mismatch")
        return binding

    def load_bindings(self) -> tuple[DashboardDepartmentBindingV1, ...]:
        registry = self.load_registry()
        if self.binding_root.is_symlink():
            raise AIOfficeDepartmentRegistryError("unsafe binding root")
        if not self.binding_root.exists():
            return ()
        if not self.binding_root.is_dir():
            raise AIOfficeDepartmentRegistryError("unsafe binding root")
        by_department: dict[str, DashboardDepartmentBindingV1] = {}
        for path in sorted(self.binding_root.glob("*.json")):
            binding = self._load_binding(path, registry=registry)
            if binding.department_id in by_department:
                raise AIOfficeDepartmentRegistryError("duplicate department binding")
            by_department[binding.department_id] = binding
        return tuple(
            by_department[department_id]
            for department_id in registry.department_ids
            if department_id in by_department
        )

    def load_current_runs(self) -> tuple[OfficeRunV1, ...]:
        registry = self.load_registry()
        if self.current_root.is_symlink():
            raise AIOfficeDepartmentRegistryError("unsafe current run root")
        if not self.current_root.exists():
            return ()
        if not self.current_root.is_dir():
            raise AIOfficeDepartmentRegistryError("unsafe current run root")
        by_department: dict[str, OfficeRunV1] = {}
        for path in sorted(self.current_root.glob("*.json")):
            run = self._load_run(path, registry=registry)
            if run.department_id in by_department:
                raise AIOfficeDepartmentRegistryError("duplicate current department run")
            by_department[run.department_id] = run
        return tuple(
            by_department[department_id]
            for department_id in registry.department_ids
            if department_id in by_department
        )
