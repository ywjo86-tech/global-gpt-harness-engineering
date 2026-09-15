"""Production closed-registry bridge from Codex dynamic tools to SingleToolBroker."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .codex_dynamic_transport import (
    CrashAfterDurableWrite, CodexAppServerAdapter, ToolRequestEnvelope, ToolResultEnvelope,
)
from .effect_evidence_bridge import collect_governed_write_effect_evidence
from .tool_authorization import (
    ClosedOperationRegistry, OperationIdentity, RegisteredOperation, SingleToolBroker,
    ToolAuthorizationContract, ToolAuthorizationError, ToolEffectJournal, owned_scope_digest,
)


_READ = "PROJECT_OWNED_FILE_READ"
_WRITE = "PROJECT_OWNED_FILE_WRITE"
_LIST = "PROJECT_OWNED_FILE_LIST"
_SENSITIVE_SCOPE_PARTS = frozenset({".git", ".env", "auth.json", "credentials", "credentials.json"})


def _validate_owned_scope(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ToolAuthorizationError("approved owned file is unsafe for Broker access")
    directory_scope = value.endswith("/")
    raw = value[:-1] if directory_scope else value
    candidate = PurePosixPath(raw)
    lowered = {part.lower() for part in candidate.parts}
    if (not raw or candidate.is_absolute() or ".." in candidate.parts or not candidate.parts
            or candidate.as_posix() != raw or lowered.intersection(_SENSITIVE_SCOPE_PARTS)):
        raise ToolAuthorizationError("approved owned file is unsafe for Broker access")
    return directory_scope


def _validate_child_path(value: object) -> str:
    if not isinstance(value, str) or not value or value.endswith("/") or "\\" in value:
        raise ToolAuthorizationError("owned directory child path is unsafe")
    candidate = PurePosixPath(value)
    lowered = {part.lower() for part in candidate.parts}
    if (candidate.is_absolute() or ".." in candidate.parts or not candidate.parts
            or candidate.as_posix() != value or lowered.intersection(_SENSITIVE_SCOPE_PARTS)):
        raise ToolAuthorizationError("owned directory child path is unsafe")
    return candidate.as_posix()


def production_operations() -> tuple[RegisteredOperation, ...]:
    file_id = {"type": "string", "pattern": r"OWNED_[0-9]{4}"}
    relative_path = {
        "type": "string", "minLength": 1,
        "description": "Child file path required only when owned_file_id denotes an approved directory scope.",
    }
    return (
        RegisteredOperation("REG_PROJECT_READ_V1", _READ, "FILE_READ", "READ", "READ_ONLY",
            {"type": "object", "properties": {"owned_file_id": file_id, "relative_path": relative_path},
             "required": ["owned_file_id"], "additionalProperties": False},
            {"type": "object", "properties": {
                "exists": {"type": "boolean"}, "content": {"type": "string"},
            }, "required": ["exists", "content"], "additionalProperties": False}),
        RegisteredOperation("REG_PROJECT_WRITE_V1", _WRITE, "FILE_WRITE", "WRITE", "PROJECT_WRITE",
            {"type": "object", "properties": {
                "owned_file_id": file_id, "relative_path": relative_path, "content": {"type": "string"},
            },
             "required": ["owned_file_id", "content"], "additionalProperties": False},
            {"type": "object", "properties": {"status": {"type": "string"}}, "additionalProperties": False}),
        RegisteredOperation("REG_PROJECT_LIST_V1", _LIST, "FILE_READ", "READ", "READ_ONLY",
            {"type": "object", "properties": {}, "additionalProperties": False},
            {"type": "object", "properties": {
                "owned_file_ids": {"type": "array"},
                "owned_files": {"type": "array"},
            }, "additionalProperties": False}),
    )


def _contract(value: Mapping[str, Any]) -> ToolAuthorizationContract:
    normalized = dict(value)
    normalized["requirement_refs"] = tuple(normalized.get("requirement_refs", ()))
    normalized["plan_task_refs"] = tuple(normalized.get("plan_task_refs", ()))
    return ToolAuthorizationContract(**normalized)


class ProductionToolTransport:
    """The only production Codex tool-effect path; no native executor exists here."""

    def __init__(self, *, request: Mapping[str, Any], workspace_root: Path,
                 journal_root: Path, security_scan) -> None:
        self.request = dict(request)
        self.workspace_root = Path(workspace_root).resolve()
        self.registry = ClosedOperationRegistry(production_operations())
        owned = list(request.get("owned_files", []))
        directory_flags = [_validate_owned_scope(relative) for relative in owned]
        self.file_bindings = {f"OWNED_{index:04d}": relative for index, relative in enumerate(owned, 1)}
        self.directory_bindings = {
            f"OWNED_{index:04d}" for index, is_directory in enumerate(directory_flags, 1) if is_directory
        }
        contracts = {}
        for value in request.get("active_tool_authorization_contracts", []):
            contract = _contract(value)
            contracts[contract.operation_class_id] = contract
        self._security_scan = security_scan
        self.contracts = contracts
        self.journal_root = Path(journal_root)
        self.broker = SingleToolBroker(
            registry=self.registry, contracts=contracts, journal=ToolEffectJournal(journal_root),
            launchers={_READ: self._read, _WRITE: self._write, _LIST: self._list},
            security_scan=security_scan,
        )

    def _target(self, file_id: object, relative_path: object = None, *, require_file: bool = False) -> tuple[Path, str, bool]:
        if not isinstance(file_id, str) or file_id not in self.file_bindings:
            raise ToolAuthorizationError("owned file identity is unknown")
        binding = str(self.file_bindings[file_id])
        directory_scope = file_id in self.directory_bindings
        if directory_scope:
            base = binding[:-1]
            if relative_path is None:
                if require_file:
                    raise ToolAuthorizationError("owned directory write requires child path")
                target = self.workspace_root / base
                scope_ref = binding
                directory_probe = True
            else:
                child = _validate_child_path(relative_path)
                target = self.workspace_root / base / child
                scope_ref = f"{binding}{child}"
                directory_probe = False
        else:
            if relative_path is not None:
                raise ToolAuthorizationError("exact owned file does not accept child path")
            target = self.workspace_root / binding
            scope_ref = binding
            directory_probe = False
        root = self.workspace_root
        try: target.resolve(strict=False).relative_to(root)
        except ValueError as exc: raise ToolAuthorizationError("owned file binding escaped workspace") from exc
        current = target
        while current != root:
            if current.is_symlink(): raise ToolAuthorizationError("owned file binding is unsafe")
            current = current.parent
        return target, scope_ref, directory_probe

    def _ensure_safe_parent(self, target: Path) -> None:
        root = self.workspace_root
        try:
            relative_parent = target.parent.relative_to(root)
        except ValueError as exc:
            raise ToolAuthorizationError("owned file parent escaped workspace") from exc
        current = root
        for part in relative_parent.parts:
            current = current / part
            if current.exists() or current.is_symlink():
                if current.is_symlink() or not current.is_dir():
                    raise ToolAuthorizationError("owned file parent is unsafe")
                continue
            current.mkdir()
            if current.is_symlink() or not current.is_dir():
                raise ToolAuthorizationError("owned file parent is unsafe")

    def _read(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        target, _scope_ref, directory_probe = self._target(
            arguments.get("owned_file_id"), arguments.get("relative_path")
        )
        if not target.exists():
            return {"exists": False, "content": ""}
        if directory_probe:
            if not target.is_dir():
                raise ToolAuthorizationError("owned directory scope is unavailable")
            return {"exists": True, "content": ""}
        if not target.is_file():
            raise ToolAuthorizationError("owned file is unavailable")
        return {"exists": True, "content": target.read_text(encoding="utf-8")}

    def _write(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        target, _scope_ref, _directory_probe = self._target(
            arguments.get("owned_file_id"), arguments.get("relative_path"), require_file=True
        )
        content = arguments.get("content")
        if not isinstance(content, str): raise ToolAuthorizationError("owned file content is malformed")
        if not self._security_scan(content.encode("utf-8")):
            raise ToolAuthorizationError("tool request failed security validation")
        self._ensure_safe_parent(target)
        if target.exists() and not target.is_file():
            raise ToolAuthorizationError("owned file target is unavailable")
        target.write_text(content, encoding="utf-8")
        return {"status": "COMPLETED"}

    def _list(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if arguments: raise ToolAuthorizationError("list operation arguments are invalid")
        return {
            "owned_file_ids": sorted(self.file_bindings),
            "owned_files": [
                {"owned_file_id": file_id, "path": self.file_bindings[file_id]}
                for file_id in sorted(self.file_bindings)
            ],
        }

    def _identity(self, envelope: ToolRequestEnvelope, *, scope_ref: str = "") -> OperationIdentity:
        operation = self.registry.resolve(envelope.operation_class_id)
        contracts = self.request.get("active_tool_authorization_contracts", [])
        matching = next((item for item in contracts
                         if item.get("operation_class_id") == envelope.operation_class_id), {})
        package_binding = matching.get("package_binding_sha256", "")
        plan_digest = str(self.request.get("canonical_plan_sha256") or "")
        requirement_digest = str(matching.get("requirement_digest") or self.request.get("requirement_digest") or "")

        def build(seed: str) -> OperationIdentity:
            dispatch_id = "DISPATCH_" + hashlib.sha256(seed.encode()).hexdigest()[:24]
            return OperationIdentity(
                operation.operation_registration_id, dispatch_id, "CODEX_DYNAMIC_TOOL_CALL_V1",
                envelope.operation_class_id, envelope.worker_task_id, envelope.worker_action_id,
                str(self.request.get("project_id")), str(self.request.get("gate_id")), str(self.request.get("lv_id")),
                str(self.request.get("run_id")), plan_digest, requirement_digest, str(package_binding),
                owned_scope_digest(list(self.request.get("owned_files", []))),
            )

        if envelope.operation_class_id != _WRITE:
            return build(f"{self.request.get('run_id')}|{envelope.provider_call_id}|{envelope.operation_class_id}")

        base_seed = f"{self.request.get('run_id')}|{envelope.operation_class_id}|{scope_ref}"
        identity = build(base_seed)
        attempt = self.request.get("attempt", 1)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 1:
            return identity
        evidence = {item.effect_id: item for item in self.governed_effect_evidence()}
        prior = evidence.get(identity.effect_id)
        if prior is None or prior.mutation_performed or prior.security_passed:
            return identity
        target, _scope, _directory_probe = self._target(
            envelope.arguments.get("owned_file_id"), envelope.arguments.get("relative_path"), require_file=True
        )
        if target.exists():
            return identity
        return build(f"{base_seed}|recovery-attempt|{attempt}")

    def _scope_ref(self, envelope: ToolRequestEnvelope) -> str:
        if envelope.operation_class_id not in {_READ, _WRITE}:
            return ""
        _target, scope_ref, _directory_probe = self._target(
            envelope.arguments.get("owned_file_id"),
            envelope.arguments.get("relative_path"),
            require_file=envelope.operation_class_id == _WRITE,
        )
        return scope_ref

    def handle(self, envelope: ToolRequestEnvelope) -> ToolResultEnvelope:
        scope_ref = self._scope_ref(envelope)
        result, private_result = self.broker.execute_with_private_result(
            self._identity(envelope, scope_ref=scope_ref),
            envelope.arguments,
            scope_ref=scope_ref,
        )
        return ToolResultEnvelope(
            result["status"],
            result["result_presence"],
            result["security_status"],
            private_result if isinstance(private_result, Mapping) else result["bounded_result"],
        )

    def governed_effect_evidence(self):
        contract = self.contracts.get(_WRITE)
        if contract is None:
            return ()
        return collect_governed_write_effect_evidence(
            self.journal_root,
            active_write_contract=contract,
            expected_owned_scope=tuple(self.file_bindings.values()),
        )

    def run(self, *, prompt: str, adapter: CodexAppServerAdapter | None = None,
            timeout: int = 180, dynamic_operation_class_ids: tuple[str, ...] | None = None,
            crash_after_durable_write: bool = False) -> Mapping[str, Any]:
        adapter = adapter or CodexAppServerAdapter()
        if (crash_after_durable_write
                and os.environ.get("HARNESS_RUN_ACTUAL_CODEX_TRANSPORT") != "1"):
            raise ToolAuthorizationError("proof crash injection requires explicit actual-transport opt-in")

        def handle(envelope: ToolRequestEnvelope) -> ToolResultEnvelope:
            result = self.handle(envelope)
            if (crash_after_durable_write and envelope.operation_class_id == _WRITE
                    and result.status == "COMPLETED"):
                raise CrashAfterDurableWrite("injected crash after durable write")
            return result

        outcome = dict(adapter.run_turn(
            prompt=prompt,
            dynamic_tools=self.registry.dynamic_specs(dynamic_operation_class_ids),
            tool_handler=handle,
            worker_task_id=str(
                self.request.get("tool_authorization_projection", {}).get("worker_task_id", "")
            ),
            worker_action_id="PRODUCTION_WORKER_TURN",
            timeout=timeout,
        ))
        outcome["governed_effect_evidence"] = [
            item.canonical_projection()
            for item in self.governed_effect_evidence()
        ]
        return outcome
