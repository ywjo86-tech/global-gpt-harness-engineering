"""Harness-owned, no-effect host inspection over existing safe read services."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from runtime.full_mcp.filesystem_service import FilesystemService, FilesystemServiceError
from runtime.full_mcp.git_service import GitService, GitServiceError
from runtime.full_mcp.path_policy import PathPolicyError, WorkspacePathPolicy

from .host_inspection_contract import (
    HOST_INSPECTION_RESULT_SCHEMA,
    HostInspectionRequestV1,
    HostInspectionResultV1,
)
from .project_onboarding import OnboardingRegistry, ProjectOnboardingError
from .production_attention_watch import discover_pending_attention
from .user_service_observer import UserServiceObserver, UserServiceObserverError

_NO_MUTATION_SCOPE = "__HOST_INSPECTION_NO_MUTATION__"


class HostInspectionError(ValueError):
    pass


class HostInspectionPort:
    def __init__(
        self, *, registry_root: str | Path, read_scopes: Sequence[str] = (".",),
        allowed_service_units: frozenset[str] | None = None,
        service_runner: Callable[[Sequence[str]], object] | None = None,
        attention_search_root: str | Path | None = None,
    ) -> None:
        self.registry_root = Path(registry_root).resolve()
        self.read_scopes = tuple(read_scopes)
        if not self.read_scopes:
            raise HostInspectionError("READ_SCOPE_REQUIRED")
        self.service_observer = None
        if allowed_service_units:
            self.service_observer = UserServiceObserver(allowed_units=allowed_service_units, runner=service_runner)
        self.attention_search_root = None if attention_search_root is None else Path(attention_search_root).resolve()

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

    def _inspect_service(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.service_observer is None:
            raise UserServiceObserverError("SERVICE_OBSERVER_UNAVAILABLE")
        if set(arguments) != {"unit_id"}:
            raise UserServiceObserverError("SERVICE_ARGUMENTS_INVALID")
        return self.service_observer.read(str(arguments["unit_id"]))

    def _inspect_attention(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if arguments:
            raise HostInspectionError("ATTENTION_ARGUMENTS_INVALID")
        if self.attention_search_root is None:
            raise HostInspectionError("ATTENTION_OBSERVER_UNAVAILABLE")
        pending = discover_pending_attention(
            self.attention_search_root, stale_after_seconds=120, user_attention_after_seconds=300,
        )
        return {"pending": pending}

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
            "user_service.properties": lambda: self._inspect_service(arguments),
            "harness.attention": lambda: self._inspect_attention(arguments),
        }
        handler = handlers.get(request.operation)
        if handler is None:
            raise HostInspectionError("HOST_INSPECTION_OPERATION_NOT_AVAILABLE")
        try:
            data = handler()
        except (FilesystemServiceError, GitServiceError, UserServiceObserverError) as exc:
            return self._blocked(request, str(getattr(exc, "code", None) or str(exc) or "INSPECTION_BLOCKED"))
        except PathPolicyError as exc:
            return self._blocked(request, "PATH_POLICY_VIOLATION")
        if not isinstance(data, Mapping):
            raise HostInspectionError("HOST_INSPECTION_RESULT_INVALID")
        return HostInspectionResultV1.ok(request, data)
