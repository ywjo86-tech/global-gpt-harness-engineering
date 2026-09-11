from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


class ProjectIsolationError(ValueError):
    pass


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_KINDS = frozenset({"state", "approval", "artifact", "run", "secret"})


def _relative(value: str) -> str:
    normalized = value.rstrip("/")
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute() or pure.as_posix() != normalized or ".." in pure.parts or "\\" in value:
        raise ProjectIsolationError("unsafe project-relative path")
    return normalized + ("/" if value.endswith("/") else "")


def _scope_contains(scope: str, path: str) -> bool:
    left = scope.rstrip("/")
    return path == left or (scope.endswith("/") and path.startswith(scope))


def _overlap(left: str, right: str) -> bool:
    return _scope_contains(left if left.endswith("/") else left, right.rstrip("/")) or _scope_contains(right if right.endswith("/") else right, left.rstrip("/"))


def _verified_root(path: str | Path, label: str) -> Path:
    supplied = Path(path)
    if not supplied.is_absolute() or not supplied.is_dir() or supplied != supplied.resolve():
        raise ProjectIsolationError(f"{label} must be an existing absolute root without symlink components")
    return supplied


@dataclass(frozen=True)
class AssetManifest:
    asset_id: str
    scope: str
    capabilities: frozenset[str]
    permissions: frozenset[str]
    owned_files: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AssetManifest":
        exact = {"asset_id", "scope", "capabilities", "permissions", "owned_files"}
        if set(value) != exact:
            raise ProjectIsolationError("asset manifest field mismatch")
        asset_id = value["asset_id"]
        scope = value["scope"]
        if not isinstance(asset_id, str) or not _ID.fullmatch(asset_id):
            raise ProjectIsolationError("unsafe asset ID")
        if scope not in {"global", "project"}:
            raise ProjectIsolationError("invalid asset scope")
        capabilities = frozenset(value["capabilities"])
        permissions = frozenset(value["permissions"])
        if any(not isinstance(item, str) or not item for item in capabilities | permissions):
            raise ProjectIsolationError("invalid manifest capability or permission")
        owned = tuple(_relative(item) for item in value["owned_files"])
        return cls(asset_id, scope, capabilities, permissions, owned)


class ProjectIsolation:
    def __init__(
        self,
        namespace_root: str | Path,
        project_root: str | Path,
        project_id: str,
        alias: str,
        alias_registry: Mapping[str, str],
    ):
        self.namespace_root = _verified_root(namespace_root, "namespace root")
        self.project_root = _verified_root(project_root, "project root")
        if not _ID.fullmatch(project_id) or self.project_root.name != project_id:
            raise ProjectIsolationError("project identity does not match verified root")
        if not _ID.fullmatch(alias):
            raise ProjectIsolationError("unsafe project alias")
        registered = alias_registry.get(alias)
        if registered is not None and registered != project_id:
            raise ProjectIsolationError("alias collision across projects")
        if len({key for key in alias_registry}) != len(alias_registry):
            raise ProjectIsolationError("duplicate aliases")
        self.project_id = project_id
        self.alias = alias
        self.root = self.namespace_root / project_id

    def namespace_path(self, kind: str, relative: str) -> Path:
        if kind not in _KINDS:
            raise ProjectIsolationError("unknown project namespace")
        safe = _relative(relative)
        base = self.root / kind
        target = base.joinpath(*PurePosixPath(safe).parts)
        if target.parent != base and base not in target.parents:
            raise ProjectIsolationError("namespace traversal detected")
        cursor = self.namespace_root
        for part in target.relative_to(self.namespace_root).parts:
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                raise ProjectIsolationError("symlinked namespace path is forbidden")
        return target

    def write_exclusive(self, kind: str, relative: str, payload: bytes) -> Path:
        target = self.namespace_path(kind, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Revalidate after directory creation to close pre-existing symlink paths.
        target = self.namespace_path(kind, relative)
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ProjectIsolationError("immutable project artifact already exists") from exc
        return target

    def read(self, kind: str, relative: str) -> bytes:
        target = self.namespace_path(kind, relative)
        if not target.is_file() or target.is_symlink():
            raise ProjectIsolationError("isolated project artifact is missing or unsafe")
        return target.read_bytes()

    def acquire_owned_lock(self, agent_id: str, owned_file: str) -> Path:
        if not _ID.fullmatch(agent_id):
            raise ProjectIsolationError("unsafe agent ID")
        owned = _relative(owned_file)
        digest = hashlib.sha256(owned.encode("utf-8")).hexdigest()
        payload = json.dumps({"project_id": self.project_id, "agent_id": agent_id, "owned_file": owned}, sort_keys=True, separators=(",", ":")).encode()
        return self.write_exclusive("run", f"owned-locks/{digest}.json", payload)


def route_assets(
    registry: Sequence[AssetManifest],
    *,
    capabilities: set[str],
    permissions: set[str],
    owned_files: Sequence[str],
) -> dict[str, Any]:
    requested = tuple(_relative(item) for item in owned_files)
    selected: list[str] = []
    excluded: dict[str, list[str]] = {}
    for manifest in registry:
        reasons: list[str] = []
        if not capabilities.issubset(manifest.capabilities):
            reasons.append("capability_exact_set_not_satisfied")
        if not permissions.issubset(manifest.permissions):
            reasons.append("permission_exact_set_not_satisfied")
        if any(not any(_scope_contains(scope, path) for scope in manifest.owned_files) for path in requested):
            reasons.append("owned_file_contract_not_satisfied")
        if reasons:
            excluded[manifest.asset_id] = reasons
        else:
            selected.append(manifest.asset_id)
    return {
        "selected": selected,
        "selected_reason": "exact manifest capability, permission, and owned-file contract match",
        "excluded": excluded,
        "substring_matching_used": False,
    }


def validate_parallel_assignments(assignments: Sequence[Mapping[str, Any]]) -> None:
    seen_agents: set[str] = set()
    scopes: list[tuple[str, str]] = []
    for assignment in assignments:
        if set(assignment) != {"agent_id", "independent", "owned_files"}:
            raise ProjectIsolationError("parallel assignment field mismatch")
        agent = assignment["agent_id"]
        if not isinstance(agent, str) or not _ID.fullmatch(agent) or agent in seen_agents:
            raise ProjectIsolationError("invalid or duplicate parallel agent")
        if assignment["independent"] is not True:
            raise ProjectIsolationError("only independent work may run in parallel")
        seen_agents.add(agent)
        for raw in assignment["owned_files"]:
            scope = _relative(raw)
            for prior, prior_agent in scopes:
                if _overlap(scope, prior):
                    raise ProjectIsolationError(f"concurrent owned-file collision: {agent}/{prior_agent}")
            scopes.append((scope, agent))
