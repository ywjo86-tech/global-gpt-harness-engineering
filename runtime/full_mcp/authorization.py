from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from runtime.orchestrator.tool_authorization import (
    RegisteredOperation,
    ToolAuthorizationContract,
    ToolAuthorizationError,
    ToolAuthorizationRequest,
    authorize_tool_operation,
    validate_contract,
)
from .contracts import (
    FullMCPContractError,
    InvocationContext,
    MCPMetaBinding,
    SHA256_RE,
    canonical_json_bytes,
    context_from_dict,
    validate_invocation_context,
)


class FullMCPAuthorizationError(ValueError):
    pass
def validate_contract_set(
    context: InvocationContext,
    contracts: Sequence[ToolAuthorizationContract],
) -> tuple[ToolAuthorizationContract, ...]:
    validate_invocation_context(context)
    values = tuple(contracts)
    if not values:
        raise FullMCPAuthorizationError("active authorization contract set is empty")
    digests: list[str] = []
    for contract in values:
        try:
            validate_contract(contract)
        except ToolAuthorizationError as exc:
            raise FullMCPAuthorizationError("authorization contract validation failed") from exc
        if contract.contract_status != "ACTIVE":
            raise FullMCPAuthorizationError("authorization contract is not ACTIVE")
        if (
            contract.project_id != context.project_id
            or contract.run_id != context.run_id
            or contract.gate_id != context.gate_id
            or contract.lv_id != context.lv_id
            or contract.canonical_plan_sha256 != context.canonical_plan_sha256
            or contract.package_binding_sha256 != context.dependency_lock_sha256
            or contract.owned_scope_sha256 != context.mutable_scope_sha256
        ):
            raise FullMCPAuthorizationError("authorization contract/context binding mismatch")
        digests.append(contract.contract_digest)
    if tuple(sorted(digests)) != tuple(sorted(context.authorization_contract_digests)):
        raise FullMCPAuthorizationError("authorization contract digest set mismatch")
    return values
def build_context_payload(context: InvocationContext) -> tuple[bytes, str]:
    validate_invocation_context(context)
    payload = {
        "schema_version": "gch.full-mcp.invocation-context-payload.v1",
        "context": context.to_dict(),
    }
    raw = canonical_json_bytes(payload)
    return raw, hashlib.sha256(raw).hexdigest()


@dataclass(slots=True)
class OneShotContextReader:
    fd: int
    expected_sha256: str
    max_bytes: int = 1024 * 1024
    _consumed: bool = field(default=False, init=False, repr=False)

    def read_once(self) -> InvocationContext:
        if self._consumed:
            raise FullMCPAuthorizationError("invocation context replay blocked")
        self._consumed = True
        if not isinstance(self.fd, int) or self.fd < 0:
            raise FullMCPAuthorizationError("invocation context FD is invalid")
        if not isinstance(self.expected_sha256, str) or not SHA256_RE.fullmatch(self.expected_sha256):
            raise FullMCPAuthorizationError("invocation context digest is invalid")
        if not isinstance(self.max_bytes, int) or self.max_bytes < 1:
            raise FullMCPAuthorizationError("invocation context size limit is invalid")
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                chunk = os.read(self.fd, min(65536, self.max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_bytes:
                    raise FullMCPAuthorizationError("invocation context exceeds limit")
                chunks.append(chunk)
        except OSError as exc:
            raise FullMCPAuthorizationError("invocation context read failed") from exc
        finally:
            try:
                os.close(self.fd)
            except OSError:
                pass
        raw = b"".join(chunks)
        if hashlib.sha256(raw).hexdigest() != self.expected_sha256:
            raise FullMCPAuthorizationError("invocation context digest mismatch")
        try:
            payload = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FullMCPAuthorizationError("invocation context JSON is invalid") from exc
        if not isinstance(payload, Mapping) or set(payload) != {"schema_version", "context"}:
            raise FullMCPAuthorizationError("invocation context payload schema is invalid")
        if payload["schema_version"] != "gch.full-mcp.invocation-context-payload.v1":
            raise FullMCPAuthorizationError("invocation context payload version is unsupported")
        if not isinstance(payload["context"], Mapping):
            raise FullMCPAuthorizationError("invocation context payload content is malformed")
        try:
            return context_from_dict(payload["context"])
        except FullMCPContractError as exc:
            raise FullMCPAuthorizationError("invocation context is invalid") from exc


@dataclass(slots=True)
class OperationRequestReplayGuard:
    _seen: set[tuple[str, str]] = field(default_factory=set, init=False, repr=False)

    def consume(self, binding: MCPMetaBinding, context: InvocationContext) -> None:
        try:
            binding.bind_to(context)
        except FullMCPContractError as exc:
            raise FullMCPAuthorizationError("MCP metadata binding rejected") from exc
        replay_key = (context.invocation_context_id, binding.operation_request_id)
        if replay_key in self._seen:
            raise FullMCPAuthorizationError("operation request replay blocked")
        self._seen.add(replay_key)
def authorize_registered_operation(
    *, context: InvocationContext, binding: MCPMetaBinding,
    contract: ToolAuthorizationContract, operation: RegisteredOperation,
    worker_task_id: str, worker_action_id: str,
) -> dict[str, object]:
    try:
        binding.bind_to(context)
        validate_contract(contract)
        operation.validate()
    except (FullMCPContractError, ToolAuthorizationError) as exc:
        raise FullMCPAuthorizationError("authorization input validation failed") from exc
    if contract.contract_digest not in context.authorization_contract_digests:
        raise FullMCPAuthorizationError("authorization contract is not bound to InvocationContext")
    if contract.package_binding_sha256 != context.dependency_lock_sha256:
        raise FullMCPAuthorizationError("authorization package binding does not match dependency lock")
    if (
        contract.operation_class_id != operation.operation_class_id
        or contract.capability_class != operation.capability_class
        or contract.operation_intent != operation.operation_intent
    ):
        raise FullMCPAuthorizationError("registered operation/authorization contract mismatch")
    request = ToolAuthorizationRequest(
        worker_task_id=worker_task_id,
        worker_action_id=worker_action_id,
        operation_class_id=operation.operation_class_id,
        capability_class=operation.capability_class,
        operation_intent=operation.operation_intent,
        scope_binding="IN_SCOPE",
        package_binding_sha256=contract.package_binding_sha256,
        project_id=context.project_id,
        gate_id=context.gate_id,
        lv_id=context.lv_id,
        run_id=context.run_id,
        canonical_plan_sha256=context.canonical_plan_sha256,
        requirement_digest=contract.requirement_digest,
        owned_scope_sha256=context.mutable_scope_sha256,
    )
    return authorize_tool_operation(contract, request)
