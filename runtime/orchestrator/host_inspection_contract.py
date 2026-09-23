"""Typed, no-effect contracts for bounded Harness host inspection."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

HOST_INSPECTION_REQUEST_SCHEMA = "orchestration.host-inspection-request.v1"
HOST_INSPECTION_RESULT_SCHEMA = "orchestration.host-inspection-result.v1"
HOST_INSPECTION_OPERATIONS = frozenset({
    "filesystem.read", "filesystem.search", "filesystem.metadata",
    "git.status", "git.diff", "git.branch",
    "user_service.properties", "harness.attention",
})
HOST_INSPECTION_STATUSES = frozenset({"OK", "PARTIAL", "STALE", "UNAVAILABLE", "BLOCKED", "ERROR"})
_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SAFE_ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FORBIDDEN_ARGUMENT_KEYS = frozenset({
    "root", "project_root", "workspace_root", "cwd", "executable", "argv",
    "env", "environment", "provider", "provider_id", "provider_ref",
    "model", "model_id", "model_ref", "backend", "shell", "command",
})


class HostInspectionContractError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise HostInspectionContractError(f"invalid {label}")
    return text


def _validate_arguments(value: object, *, key: str = "arguments") -> None:
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            name = str(raw_key)
            if name in _FORBIDDEN_ARGUMENT_KEYS:
                raise HostInspectionContractError(f"forbidden arguments key: {name}")
            _validate_arguments(nested, key=name)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _validate_arguments(nested, key=key)
        return
    if isinstance(value, str) and key in {"path", "directory"}:
        if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
            raise HostInspectionContractError("absolute caller path is forbidden in arguments")


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(copy.deepcopy(dict(value)))


@dataclass(frozen=True, slots=True)
class HostInspectionRequestV1:
    schema_version: str
    request_id: str
    correlation_id: str
    project_alias: str
    operation: str
    arguments: Mapping[str, Any]
    state_change_required: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != HOST_INSPECTION_REQUEST_SCHEMA:
            raise HostInspectionContractError("unsupported host inspection request schema")
        object.__setattr__(self, "request_id", _safe_id(self.request_id, "request ID"))
        object.__setattr__(self, "correlation_id", _safe_id(self.correlation_id, "correlation ID"))
        if not _SAFE_ALIAS.fullmatch(str(self.project_alias or "")) or ".." in self.project_alias:
            raise HostInspectionContractError("invalid project alias")
        if self.operation not in HOST_INSPECTION_OPERATIONS:
            raise HostInspectionContractError("host inspection operation is not allowed")
        if not isinstance(self.arguments, Mapping):
            raise HostInspectionContractError("arguments must be an object")
        _validate_arguments(self.arguments)
        object.__setattr__(self, "arguments", _freeze_mapping(self.arguments))
        if self.state_change_required is not False:
            raise HostInspectionContractError("host inspection state change is forbidden")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "HostInspectionRequestV1":
        expected = {
            "schema_version", "request_id", "correlation_id", "project_alias",
            "operation", "arguments", "state_change_required",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise HostInspectionContractError("host inspection request fields mismatch")
        return cls(
            schema_version=str(payload["schema_version"]),
            request_id=str(payload["request_id"]), correlation_id=str(payload["correlation_id"]),
            project_alias=str(payload["project_alias"]), operation=str(payload["operation"]),
            arguments=payload["arguments"], state_change_required=payload["state_change_required"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "project_alias": self.project_alias,
            "operation": self.operation,
            "arguments": copy.deepcopy(dict(self.arguments)),
            "state_change_required": self.state_change_required,
        }

    @property
    def request_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class HostInspectionResultV1:
    schema_version: str
    request_id: str
    correlation_id: str
    project_alias: str
    operation: str
    request_digest: str
    status: str
    data: Mapping[str, Any]
    error_code: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != HOST_INSPECTION_RESULT_SCHEMA:
            raise HostInspectionContractError("unsupported host inspection result schema")
        _safe_id(self.request_id, "request ID")
        _safe_id(self.correlation_id, "correlation ID")
        if not _SAFE_ALIAS.fullmatch(str(self.project_alias or "")) or ".." in self.project_alias:
            raise HostInspectionContractError("invalid project alias")
        if self.operation not in HOST_INSPECTION_OPERATIONS:
            raise HostInspectionContractError("host inspection result operation is not allowed")
        if not _SHA256.fullmatch(str(self.request_digest or "")):
            raise HostInspectionContractError("invalid request digest")
        if self.status not in HOST_INSPECTION_STATUSES:
            raise HostInspectionContractError("invalid host inspection result status")
        if not isinstance(self.data, Mapping):
            raise HostInspectionContractError("result data must be an object")
        object.__setattr__(self, "data", _freeze_mapping(self.data))
        if self.error_code:
            _safe_id(self.error_code, "error code")

    @classmethod
    def ok(cls, request: HostInspectionRequestV1, data: Mapping[str, Any]) -> "HostInspectionResultV1":
        if not isinstance(data, Mapping):
            raise HostInspectionContractError("result data must be an object")
        return cls(
            schema_version=HOST_INSPECTION_RESULT_SCHEMA,
            request_id=request.request_id, correlation_id=request.correlation_id,
            project_alias=request.project_alias, operation=request.operation,
            request_digest=request.request_digest, status="OK", data=data, error_code="",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "project_alias": self.project_alias,
            "operation": self.operation,
            "request_digest": self.request_digest,
            "status": self.status,
            "data": copy.deepcopy(dict(self.data)),
            "error_code": self.error_code,
        }
