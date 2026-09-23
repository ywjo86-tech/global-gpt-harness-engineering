"""Harness-owned, no-effect host inspection over existing safe read services."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from runtime.full_mcp.filesystem_service import FilesystemService, FilesystemServiceError
from runtime.full_mcp.git_service import GitService, GitServiceError
from runtime.full_mcp.path_policy import PathPolicyError, WorkspacePathPolicy

from .host_inspection_contract import (
    HOST_INSPECTION_RESULT_SCHEMA,
    HostInspectionRequestV1,
    HostInspectionResultV1,
)
from .project_onboarding import OnboardingRegistry, ProjectOnboardingError

_NO_MUTATION_SCOPE = "__HOST_INSPECTION_NO_MUTATION__"


class HostInspectionError(ValueError):
    pass


class HostInspectionPort:
    def __init__(self, *, registry_root: str | Path, read_scopes: Sequence[str] = (".",)) -> None:
        self.registry_root = Path(registry_root).resolve()
        self.read_scopes = tuple(read_scopes)
        if not self.read_scopes:
            raise HostInspectionError("READ_SCOPE_REQUIRED")

    def _registry(self) -> OnboardingRegistry:
        return OnboardingRegistry(self.registry_root / "aliases")

    def _resolve_registered_project(self, alias: str) -> Path:
        try:
            entries = self._registry().entries()
        except ProjectOnboardingError as exc:
            raise HostInspectionError("PROJECT_BINDING_INVALID") from exc
        entry = next((item for item in entries if item.get("alias") == alias), None)
        if entry is None:
            raise HostInspectionError("PROJECT_NOT_REGISTERED")
        try:
            root = Path(str(entry["project_root"]))
            report = self._registry().inspect(root, alias)
        except (KeyError, ProjectOnboardingError, OSError, ValueError) as exc:
            raise HostInspectionError("PROJECT_BINDING_INVALID") from exc
        if report.get("status") != "COMPATIBLE" or report.get("entry") != entry:
            raise HostInspectionError("PROJECT_BINDING_INVALID")
        return root.resolve(strict=True)

    @staticmethod
    def _blocked(request: HostInspectionRequestV1, code: str) -> HostInspectionResultV1:
        return HostInspectionResultV1(
            schema_version=HOST_INSPECTION_RESULT_SCHEMA,
            request_id=request.request_id, correlation_id=request.correlation_id,
            project_alias=request.project_alias, operation=request.operation,
            request_digest=request.request_digest, status="BLOCKED", data={}, error_code=code,
        )

    def _services(self, root: Path) -> tuple[FilesystemService, GitService]:
        policy = WorkspacePathPolicy(
            root, read_scopes=self.read_scopes, mutable_scopes=(_NO_MUTATION_SCOPE,),
        )
        return FilesystemService(policy), GitService(root, policy)

    def inspect(self, request: HostInspectionRequestV1) -> HostInspectionResultV1:
        if not isinstance(request, HostInspectionRequestV1):
            raise HostInspectionError("HOST_INSPECTION_REQUEST_REQUIRED")
        root = self._resolve_registered_project(request.project_alias)
        filesystem, git = self._services(root)
        arguments = dict(request.arguments)
        handlers = {
            "filesystem.read": lambda: filesystem.read(**arguments),
            "filesystem.search": lambda: filesystem.search(**arguments),
            "filesystem.metadata": lambda: filesystem.metadata(**arguments),
            "git.status": lambda: git.status(arguments.get("paths", ())),
            "git.diff": lambda: git.diff(**arguments),
            "git.branch": lambda: git.branch(),
        }
        handler = handlers.get(request.operation)
        if handler is None:
            raise HostInspectionError("HOST_INSPECTION_OPERATION_NOT_AVAILABLE")
        try:
            data = handler()
        except (FilesystemServiceError, GitServiceError) as exc:
            return self._blocked(request, str(getattr(exc, "code", "INSPECTION_BLOCKED")))
        except PathPolicyError as exc:
            return self._blocked(request, "PATH_POLICY_VIOLATION")
        if not isinstance(data, Mapping):
            raise HostInspectionError("HOST_INSPECTION_RESULT_INVALID")
        return HostInspectionResultV1.ok(request, data)
