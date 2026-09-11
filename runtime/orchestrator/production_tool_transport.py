"""Production closed-registry bridge from Codex dynamic tools to SingleToolBroker."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .codex_dynamic_transport import CodexAppServerAdapter, ToolRequestEnvelope, ToolResultEnvelope
from .effect_evidence_bridge import collect_governed_write_effect_evidence
from .tool_authorization import (
    DEC007_WORKER_TASK_ID,
    ClosedOperationRegistry, OperationIdentity, RegisteredOperation, SingleToolBroker,
    ToolAuthorizationContract, ToolAuthorizationError, ToolEffectJournal, owned_scope_digest,
)


_READ = "PROJECT_OWNED_FILE_READ"
_WRITE = "PROJECT_OWNED_FILE_WRITE"
_LIST = "PROJECT_OWNED_FILE_LIST"


def production_operations() -> tuple[RegisteredOperation, ...]:
    file_id = {"type": "string", "pattern": r"OWNED_[0-9]{4}"}
    return (
        RegisteredOperation("REG_PROJECT_READ_V1", _READ, "FILE_READ", "READ", "READ_ONLY",
            {"type": "object", "properties": {"owned_file_id": file_id},
             "required": ["owned_file_id"], "additionalProperties": False},
            {"type": "object", "properties": {"content": {"type": "string"}}, "additionalProperties": False}),
        RegisteredOperation("REG_PROJECT_WRITE_V1", _WRITE, "FILE_WRITE", "WRITE", "PROJECT_WRITE",
            {"type": "object", "properties": {"owned_file_id": file_id, "content": {"type": "string"}},
             "required": ["owned_file_id", "content"], "additionalProperties": False},
            {"type": "object", "properties": {"status": {"type": "string"}}, "additionalProperties": False}),
        RegisteredOperation("REG_PROJECT_LIST_V1", _LIST, "FILE_READ", "READ", "READ_ONLY",
            {"type": "object", "properties": {}, "additionalProperties": False},
            {"type": "object", "properties": {"owned_file_ids": {"type": "array"}},
             "additionalProperties": False}),
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
        self.workspace_root = workspace_root
        self.registry = ClosedOperationRegistry(production_operations())
        owned = list(request.get("owned_files", []))
        for relative in owned:
            value = PurePosixPath(relative) if isinstance(relative, str) else PurePosixPath("..")
            lowered = {part.lower() for part in value.parts}
            if (value.is_absolute() or ".." in value.parts or not value.parts
                    or ".git" in lowered or ".env" in lowered
                    or lowered.intersection({"auth.json", "credentials", "credentials.json"})):
                raise ToolAuthorizationError("approved owned file is unsafe for Broker access")
        self.file_bindings = {f"OWNED_{index:04d}": relative for index, relative in enumerate(owned, 1)}
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

    def _target(self, file_id: object) -> Path:
        if not isinstance(file_id, str) or file_id not in self.file_bindings:
            raise ToolAuthorizationError("owned file identity is unknown")
        target = self.workspace_root / self.file_bindings[file_id]
        root = self.workspace_root.resolve()
        try: target.resolve(strict=False).relative_to(root)
        except ValueError as exc: raise ToolAuthorizationError("owned file binding escaped workspace") from exc
        current = target
        while current != self.workspace_root:
            if current.is_symlink(): raise ToolAuthorizationError("owned file binding is unsafe")
            current = current.parent
        return target

    def _read(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        target = self._target(arguments.get("owned_file_id"))
        if not target.is_file(): raise ToolAuthorizationError("owned file is unavailable")
        return {"content": target.read_text(encoding="utf-8")}

    def _write(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        target = self._target(arguments.get("owned_file_id")); content = arguments.get("content")
        if not isinstance(content, str): raise ToolAuthorizationError("owned file content is malformed")
        if not self._security_scan(content.encode("utf-8")):
            raise ToolAuthorizationError("tool request failed security validation")
        if not target.parent.is_dir() or target.parent.is_symlink():
            raise ToolAuthorizationError("owned file parent is unsafe")
        target.write_text(content, encoding="utf-8")
        return {"status": "COMPLETED"}

    def _list(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if arguments: raise ToolAuthorizationError("list operation arguments are invalid")
        return {"owned_file_ids": sorted(self.file_bindings)}

    def _identity(self, envelope: ToolRequestEnvelope, *, scope_ref: str = "") -> OperationIdentity:
        operation = self.registry.resolve(envelope.operation_class_id)
        contracts = self.request.get("active_tool_authorization_contracts", [])
        matching = next((item for item in contracts
                         if item.get("operation_class_id") == envelope.operation_class_id), {})
        package_binding = matching.get("package_binding_sha256", "")
        plan_digest = str(self.request.get("canonical_plan_sha256") or "")
        requirement_digest = str(matching.get("requirement_digest") or self.request.get("requirement_digest") or "")
        if envelope.operation_class_id == _WRITE:
            seed = f"{self.request.get('run_id')}|{envelope.operation_class_id}|{scope_ref}"
        else:
            seed = f"{self.request.get('run_id')}|{envelope.provider_call_id}|{envelope.operation_class_id}"
        dispatch_id = "DISPATCH_" + hashlib.sha256(seed.encode()).hexdigest()[:24]
        return OperationIdentity(
            operation.operation_registration_id, dispatch_id, "CODEX_DYNAMIC_TOOL_CALL_V1",
            envelope.operation_class_id, envelope.worker_task_id, envelope.worker_action_id,
            str(self.request.get("project_id")), str(self.request.get("gate_id")), str(self.request.get("lv_id")),
            str(self.request.get("run_id")), plan_digest, requirement_digest, str(package_binding),
            owned_scope_digest(list(self.request.get("owned_files", []))),
        )

    def _scope_ref(self, envelope: ToolRequestEnvelope) -> str:
        if envelope.operation_class_id not in {_READ, _WRITE}:
            return ""
        file_id = envelope.arguments.get("owned_file_id")
        if not isinstance(file_id, str) or file_id not in self.file_bindings:
            raise ToolAuthorizationError("owned file identity is unknown")
        return str(self.file_bindings[file_id])

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
            timeout: int = 180, dynamic_operation_class_ids: tuple[str, ...] | None = None) -> Mapping[str, Any]:
        adapter = adapter or CodexAppServerAdapter()
        outcome = dict(adapter.run_turn(
            prompt=prompt,
            dynamic_tools=self.registry.dynamic_specs(dynamic_operation_class_ids),
            tool_handler=self.handle,
            worker_task_id=DEC007_WORKER_TASK_ID,
            worker_action_id="PRODUCTION_WORKER_TURN",
            timeout=timeout,
        ))
        outcome["governed_effect_evidence"] = [
            item.canonical_projection()
            for item in self.governed_effect_evidence()
        ]
        return outcome
