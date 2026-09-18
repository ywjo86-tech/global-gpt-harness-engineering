"""AI Office public execution contracts.

These DTOs are intentionally provider/model/backend neutral.  They bind office
workflow intent and authorization lineage to the existing Execution Backend
boundary without importing or exposing Full MCP internals.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol

OFFICE_EXECUTION_REQUEST_SCHEMA_V1 = "ai-office.execution-request.v1"
OFFICE_EXECUTION_RESULT_SCHEMA_V1 = "ai-office.execution-result.v1"
MANUAL_ACTION_HANDOFF_SCHEMA_V1 = "ai-office.manual-action-handoff-ref.v1"
NON_MUTATING_CONTINUATION_SCHEMA_V1 = "ai-office.non-mutating-continuation-ref.v1"
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
EFFECT_SEMANTICS = frozenset({"READ_ONLY", "STATE_CHANGING", "RECONCILIATION_ONLY"})
RESULT_STATUSES = frozenset({"COMPLETED", "BLOCKED", "FAILED", "PENDING"})
RECONCILIATION_STATES = frozenset({"NOT_REQUIRED", "PENDING", "CONFIRMED", "AMBIGUOUS", "FAILED"})
FORBIDDEN_KEYS = frozenset({
    "provider", "provider_id", "provider_ref", "model", "model_id", "model_ref",
    "backend", "backend_id", "backend_class", "backend_path", "full_mcp", "full_mcp_class",
    "runtime_handler_class", "internal_class", "internal_path", "stdout", "stderr", "secret", "token",
})
FORBIDDEN_TEXT = ("runtime.full_mcp", "FullMCPBackendAdapter", "ToolEffectJournal", "receipt_store")


class OfficeExecutionContractError(ValueError):
    pass


def canonical_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_id(value: object, field: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise OfficeExecutionContractError(f"{field} is not a safe identifier")
    return value


def _sha(value: object, field: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise OfficeExecutionContractError(f"{field} is not a SHA-256 digest")
    return value


def _safe_ref(value: object, field: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise OfficeExecutionContractError(f"{field} is not a safe reference")
    if value.startswith("/") or any(ord(ch) < 32 for ch in value):
        raise OfficeExecutionContractError(f"{field} is not a safe reference")
    if ".." in value.replace("\\", "/").split("/"):
        raise OfficeExecutionContractError(f"{field} is not a safe reference")
    return value


def _reject_forbidden(value: object, path: str = "public") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_KEYS or any(part in lowered for part in ("password", "credential", "api_key")):
                raise OfficeExecutionContractError(f"forbidden public field at {path}.{key}")
            _reject_forbidden(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_forbidden(item, f"{path}[{index}]")
    elif isinstance(value, str) and any(token in value for token in FORBIDDEN_TEXT):
        raise OfficeExecutionContractError(f"forbidden internal reference at {path}")


def _validate_identity(project_id: str, project_run_id: str, workflow_item_id: str,
                       task_id: str, task_execution_id: str, correlation_id: str) -> None:
    for value, label in (
        (project_id, "project_id"), (project_run_id, "project_run_id"),
        (workflow_item_id, "workflow_item_id"), (task_id, "task_id"),
        (task_execution_id, "task_execution_id"), (correlation_id, "correlation_id"),
    ):
        _safe_id(value, label)


@dataclass(frozen=True, slots=True)
class OfficeExecutionRequestV1:
    schema_version: str
    project_id: str
    project_run_id: str
    workflow_item_id: str
    task_id: str
    task_execution_id: str
    operation_intent_ref: str
    operation_intent_digest: str
    expected_effect_semantics: str
    governance_decision_ref: str
    governance_decision_digest: str
    risk_envelope_ref: str
    risk_envelope_digest: str
    delegated_authorization_ref: str
    delegated_authorization_digest: str
    authorization_binding_ref: str
    authorization_binding_digest: str
    execution_package_ref: str
    execution_package_digest: str
    execution_contract_ref: str
    execution_contract_digest: str
    correlation_id: str

    def __post_init__(self) -> None:
        if self.schema_version != OFFICE_EXECUTION_REQUEST_SCHEMA_V1:
            raise OfficeExecutionContractError("unsupported OfficeExecutionRequest schema")
        _validate_identity(self.project_id, self.project_run_id, self.workflow_item_id,
                           self.task_id, self.task_execution_id, self.correlation_id)
        for value, label in (
            (self.operation_intent_ref, "operation_intent_ref"),
            (self.governance_decision_ref, "governance_decision_ref"),
            (self.risk_envelope_ref, "risk_envelope_ref"),
            (self.delegated_authorization_ref, "delegated_authorization_ref"),
            (self.authorization_binding_ref, "authorization_binding_ref"),
            (self.execution_package_ref, "execution_package_ref"),
            (self.execution_contract_ref, "execution_contract_ref"),
        ):
            _safe_ref(value, label)
        for value, label in (
            (self.operation_intent_digest, "operation_intent_digest"),
            (self.governance_decision_digest, "governance_decision_digest"),
            (self.risk_envelope_digest, "risk_envelope_digest"),
            (self.delegated_authorization_digest, "delegated_authorization_digest"),
            (self.authorization_binding_digest, "authorization_binding_digest"),
            (self.execution_package_digest, "execution_package_digest"),
            (self.execution_contract_digest, "execution_contract_digest"),
        ):
            _sha(value, label)
        if self.expected_effect_semantics not in EFFECT_SEMANTICS:
            raise OfficeExecutionContractError("expected_effect_semantics is invalid")
        if self.expected_effect_semantics == "STATE_CHANGING" and not all((
            self.governance_decision_ref, self.risk_envelope_ref, self.delegated_authorization_ref,
            self.authorization_binding_ref, self.execution_package_ref, self.execution_contract_ref,
        )):
            raise OfficeExecutionContractError("state-changing request authorization lineage is incomplete")
        _reject_forbidden(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def request_digest(self) -> str:
        return canonical_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class OfficeExecutionResultV1:
    schema_version: str
    project_id: str
    project_run_id: str
    workflow_item_id: str
    task_execution_id: str
    correlation_id: str
    request_digest: str
    status: str
    result_digest: str
    effect_ref: str
    audit_ref: str
    reconciliation_state: str
    error_code: str

    def __post_init__(self) -> None:
        if self.schema_version != OFFICE_EXECUTION_RESULT_SCHEMA_V1:
            raise OfficeExecutionContractError("unsupported OfficeExecutionResult schema")
        for value, label in ((self.project_id, "project_id"), (self.project_run_id, "project_run_id"),
                             (self.workflow_item_id, "workflow_item_id"),
                             (self.task_execution_id, "task_execution_id"), (self.correlation_id, "correlation_id")):
            _safe_id(value, label)
        _sha(self.request_digest, "request_digest")
        if self.status not in RESULT_STATUSES:
            raise OfficeExecutionContractError("execution result status is invalid")
        _sha(self.result_digest, "result_digest", allow_empty=self.status != "COMPLETED")
        for value, label in ((self.effect_ref, "effect_ref"), (self.audit_ref, "audit_ref")):
            _safe_ref(value, label, allow_empty=True)
        _safe_id(self.error_code, "error_code", allow_empty=True)
        if self.reconciliation_state not in RECONCILIATION_STATES:
            raise OfficeExecutionContractError("reconciliation_state is invalid")
        _reject_forbidden(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ManualActionHandoffRefV1:
    schema_version: str
    project_id: str
    project_run_id: str
    workflow_item_id: str
    task_execution_id: str
    correlation_id: str
    action_package_ref: str
    action_package_digest: str
    authorization_ref: str
    authorization_digest: str
    source_identity_ref: str
    source_identity_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != MANUAL_ACTION_HANDOFF_SCHEMA_V1:
            raise OfficeExecutionContractError("unsupported ManualActionHandoffRef schema")
        for value, label in ((self.project_id, "project_id"), (self.project_run_id, "project_run_id"),
                             (self.workflow_item_id, "workflow_item_id"),
                             (self.task_execution_id, "task_execution_id"), (self.correlation_id, "correlation_id"),
                             (self.action_package_ref, "action_package_ref"), (self.authorization_ref, "authorization_ref"),
                             (self.source_identity_ref, "source_identity_ref")):
            _safe_id(value, label)
        for value, label in ((self.action_package_digest, "action_package_digest"),
                             (self.authorization_digest, "authorization_digest"),
                             (self.source_identity_digest, "source_identity_digest")):
            _sha(value, label)
        _reject_forbidden(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def handoff_digest(self) -> str:
        return canonical_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class NonMutatingContinuationRefV1:
    schema_version: str
    project_id: str
    project_run_id: str
    workflow_item_id: str
    task_execution_id: str
    correlation_id: str
    required_capabilities: tuple[str, ...]
    execution_authority: str
    dependency_safe: bool
    dependency_safety_ref: str
    dependency_safety_digest: str
    full_plan_router_handoff_ref: str
    full_plan_router_handoff_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != NON_MUTATING_CONTINUATION_SCHEMA_V1:
            raise OfficeExecutionContractError("unsupported NonMutatingContinuationRef schema")
        for value, label in ((self.project_id, "project_id"), (self.project_run_id, "project_run_id"),
                             (self.workflow_item_id, "workflow_item_id"),
                             (self.task_execution_id, "task_execution_id"), (self.correlation_id, "correlation_id"),
                             (self.dependency_safety_ref, "dependency_safety_ref"),
                             (self.full_plan_router_handoff_ref, "full_plan_router_handoff_ref")):
            _safe_ref(value, label)
        capabilities = tuple(self.required_capabilities)
        if not capabilities or len(capabilities) != len(set(capabilities)):
            raise OfficeExecutionContractError("required_capabilities is empty or duplicated")
        for capability in capabilities:
            _safe_id(capability, "required_capability")
        if self.execution_authority != "READ_ONLY":
            raise OfficeExecutionContractError("non-mutating continuation requires READ_ONLY authority")
        if self.dependency_safe is not True:
            raise OfficeExecutionContractError("non-mutating continuation requires dependency-safe proof")
        _sha(self.dependency_safety_digest, "dependency_safety_digest")
        _sha(self.full_plan_router_handoff_digest, "full_plan_router_handoff_digest")
        _reject_forbidden(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self); value["required_capabilities"] = list(self.required_capabilities); return value

    @property
    def continuation_digest(self) -> str:
        return canonical_digest(self.to_dict())


class BackendNeutralExecutionPort(Protocol):
    def __call__(self, request: Mapping[str, Any], **kwargs: Any) -> Mapping[str, Any]: ...
