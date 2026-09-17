"""Versioned public execution DTOs that intentionally expose no Full MCP internals."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

PUBLIC_EXECUTION_REQUEST_SCHEMA_V1 = "orchestration.public-execution-request.v1"
PUBLIC_EXECUTION_RESULT_SCHEMA_V1 = "orchestration.public-execution-result.v1"
PUBLIC_EXECUTION_STATUS_SCHEMA_V1 = "orchestration.public-execution-status.v1"
PUBLIC_RECONCILIATION_RESULT_SCHEMA_V1 = "orchestration.public-reconciliation-result.v1"
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
PUBLIC_STATUSES = frozenset({"COMPLETED", "BLOCKED", "FAILED", "PENDING"})
RECONCILIATION_STATES = frozenset({"NOT_REQUIRED", "PENDING", "CONFIRMED", "AMBIGUOUS", "FAILED"})
FORBIDDEN_PUBLIC_KEYS = frozenset({
    "tool_effect_journal", "effect_journal", "journal_path", "receipt_store", "receipt_store_path",
    "operation_registry", "registry_handle", "internal_class", "internal_path", "full_mcp_class",
})
FORBIDDEN_PUBLIC_TEXT = ("ToolEffectJournal", "runtime.full_mcp", "operation_registry.py", "receipt_store")


class PublicExecutionContractError(ValueError):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise PublicExecutionContractError(f"{field} is not a safe identifier")
    return value


def _sha(value: str, field: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return value
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise PublicExecutionContractError(f"{field} is not a SHA-256 digest")
    return value


def _assert_public_value(value: object, path: str = "public") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in FORBIDDEN_PUBLIC_KEYS:
                raise PublicExecutionContractError(f"forbidden internal field at {path}.{key_text}")
            _assert_public_value(item, f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_public_value(item, f"{path}[{index}]")
    elif isinstance(value, str) and any(token in value for token in FORBIDDEN_PUBLIC_TEXT):
        raise PublicExecutionContractError(f"forbidden internal reference at {path}")


@dataclass(frozen=True, slots=True)
class PublicExecutionRequestV1:
    schema_version: str
    operation_class: str
    public_arguments: Mapping[str, Any]
    authorization_ref: str
    operation_request_id: str
    correlation_id: str
    policy_digests: tuple[str, ...]
    expected_effect_semantics: str

    def __post_init__(self) -> None:
        if self.schema_version != PUBLIC_EXECUTION_REQUEST_SCHEMA_V1:
            raise PublicExecutionContractError("unsupported public execution request schema")
        _safe_id(self.operation_class, "operation_class")
        _safe_id(self.authorization_ref, "authorization_ref")
        _safe_id(self.operation_request_id, "operation_request_id")
        _safe_id(self.correlation_id, "correlation_id")
        if not isinstance(self.public_arguments, Mapping):
            raise PublicExecutionContractError("public_arguments must be an object")
        _assert_public_value(self.public_arguments)
        digests = tuple(self.policy_digests)
        if len(digests) != len(set(digests)):
            raise PublicExecutionContractError("policy_digests contains duplicates")
        for digest in digests:
            _sha(digest, "policy_digest")
        if self.expected_effect_semantics not in {"READ_ONLY", "STATE_CHANGING", "RECONCILIATION_ONLY"}:
            raise PublicExecutionContractError("expected_effect_semantics is invalid")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["policy_digests"] = list(self.policy_digests)
        value["public_arguments"] = dict(self.public_arguments)
        return value

    @property
    def request_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class PublicExecutionResultV1:
    schema_version: str
    operation_request_id: str
    correlation_id: str
    status: str
    result_digest: str
    effect_ref: str
    reconciliation_state: str
    error_code: str
    audit_ref: str

    def __post_init__(self) -> None:
        if self.schema_version != PUBLIC_EXECUTION_RESULT_SCHEMA_V1:
            raise PublicExecutionContractError("unsupported public execution result schema")
        _safe_id(self.operation_request_id, "operation_request_id")
        _safe_id(self.correlation_id, "correlation_id")
        if self.status not in PUBLIC_STATUSES:
            raise PublicExecutionContractError("public execution status is invalid")
        _sha(self.result_digest, "result_digest", allow_empty=self.status != "COMPLETED")
        if self.effect_ref:
            _safe_id(self.effect_ref, "effect_ref")
        if self.reconciliation_state not in RECONCILIATION_STATES:
            raise PublicExecutionContractError("reconciliation_state is invalid")
        if self.error_code:
            _safe_id(self.error_code, "error_code")
        if self.audit_ref:
            _safe_id(self.audit_ref, "audit_ref")
        _assert_public_value(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PublicExecutionStatusV1:
    schema_version: str
    operation_request_id: str
    correlation_id: str
    status: str
    effect_ref: str
    reconciliation_state: str
    error_code: str
    audit_ref: str

    def __post_init__(self) -> None:
        if self.schema_version != PUBLIC_EXECUTION_STATUS_SCHEMA_V1:
            raise PublicExecutionContractError("unsupported public execution status schema")
        _safe_id(self.operation_request_id, "operation_request_id")
        _safe_id(self.correlation_id, "correlation_id")
        if self.status not in PUBLIC_STATUSES or self.reconciliation_state not in RECONCILIATION_STATES:
            raise PublicExecutionContractError("public execution status projection is invalid")
        for value, field in ((self.effect_ref, "effect_ref"), (self.error_code, "error_code"), (self.audit_ref, "audit_ref")):
            if value:
                _safe_id(value, field)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PublicReconciliationResultV1:
    schema_version: str
    operation_request_id: str
    correlation_id: str
    reconciliation_state: str
    effect_ref: str
    result_digest: str
    audit_ref: str

    def __post_init__(self) -> None:
        if self.schema_version != PUBLIC_RECONCILIATION_RESULT_SCHEMA_V1:
            raise PublicExecutionContractError("unsupported public reconciliation schema")
        _safe_id(self.operation_request_id, "operation_request_id")
        _safe_id(self.correlation_id, "correlation_id")
        if self.reconciliation_state not in RECONCILIATION_STATES:
            raise PublicExecutionContractError("reconciliation_state is invalid")
        if self.effect_ref:
            _safe_id(self.effect_ref, "effect_ref")
        _sha(self.result_digest, "result_digest", allow_empty=True)
        if self.audit_ref:
            _safe_id(self.audit_ref, "audit_ref")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def public_execution_request_from_mapping(raw: Mapping[str, Any]) -> PublicExecutionRequestV1:
    try:
        value = dict(raw)
        value["policy_digests"] = tuple(value.get("policy_digests", ()))
        return PublicExecutionRequestV1(**value)
    except (TypeError, KeyError) as exc:
        raise PublicExecutionContractError("public execution request payload is malformed") from exc


def public_execution_result_from_mapping(raw: Mapping[str, Any]) -> PublicExecutionResultV1:
    try:
        return PublicExecutionResultV1(**dict(raw))
    except (TypeError, KeyError) as exc:
        raise PublicExecutionContractError("public execution result payload is malformed") from exc
