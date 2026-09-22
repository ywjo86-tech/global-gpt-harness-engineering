"""Additive typed read-only diagnostic envelope for OCPv2.

V2 remains owned by :mod:`remote_operator_envelope`.  This module adds only a
non-state-changing diagnostic extension and a union decoder; it owns no
execution, provider, planning, or mutation authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Mapping, TypeAlias

from .operator_control import OperatorControlError, OperatorDirectiveV1
from .read_only_host_diagnostic_contract import (
    READ_ONLY_DIAGNOSTIC_CAPABILITY,
    ReadOnlyDiagnosticRequestV1,
    DiagnosticContractError,
)
from .remote_operator_envelope import (
    REMOTE_OPERATOR_ENVELOPE_SCHEMA,
    AuthorizationBindings,
    ExpectedBindings,
    RemoteOperatorEnvelopeError,
    RemoteOperatorEnvelopeV2,
    TransportBinding,
    seal_remote_envelope,
    validate_remote_envelope,
)

REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA = "orchestration.remote-operator-envelope.v3"
_V3_FIELDS = {
    "schema_version", "message_id", "sequence", "issued_at", "expires_at", "actor",
    "transport", "project_id", "run_id", "task_id", "task_execution_id", "gate_id",
    "operator_directive", "directive_digest", "expected", "authorization",
    "read_only_request", "read_only_request_digest", "envelope_sha256",
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _unsigned(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value)); result.pop("envelope_sha256", None); return result


def _v2_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result.pop("read_only_request", None)
    result.pop("read_only_request_digest", None)
    result["schema_version"] = REMOTE_OPERATOR_ENVELOPE_SCHEMA
    result["envelope_sha256"] = _sha(_unsigned(result))
    return result


def _validate_diagnostic_request_path(request: ReadOnlyDiagnosticRequestV1) -> None:
    if request.operation not in {"project.file_range", "path.metadata"}:
        return
    value = request.relative_path
    pure = PurePosixPath(value)
    if not value or value.startswith("/") or pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: unsafe diagnostic relative path")


def _typed_request(raw: object) -> ReadOnlyDiagnosticRequestV1:
    if not isinstance(raw, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: read_only_request must be an object")
    try:
        request = ReadOnlyDiagnosticRequestV1.from_mapping(raw)
    except DiagnosticContractError as exc:
        raise RemoteOperatorEnvelopeError(f"SCHEMA_REJECTED: {exc}") from exc
    _validate_diagnostic_request_path(request)
    return request


def _diagnostic_directive(raw: object) -> OperatorDirectiveV1:
    if not isinstance(raw, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: operator_directive must be an object")
    try:
        directive = OperatorDirectiveV1.from_mapping(raw)
    except OperatorControlError as exc:
        raise RemoteOperatorEnvelopeError(f"OPERATOR_DIRECTIVE_BLOCKED: {exc}") from exc
    if directive.state_change_required:
        raise RemoteOperatorEnvelopeError("OPERATOR_DIRECTIVE_BLOCKED: diagnostic request may not change state")
    if tuple(directive.required_capabilities) != (READ_ONLY_DIAGNOSTIC_CAPABILITY,):
        raise RemoteOperatorEnvelopeError("OPERATOR_DIRECTIVE_BLOCKED: diagnostic capability mismatch")
    return directive


@dataclass(frozen=True, slots=True)
class RemoteOperatorEnvelopeV3:
    schema_version: str
    message_id: str
    sequence: int
    issued_at: str
    expires_at: str
    actor: str
    transport: TransportBinding
    project_id: str
    run_id: str
    task_id: str
    task_execution_id: str
    gate_id: str
    operator_directive: OperatorDirectiveV1
    directive_digest: str
    expected: ExpectedBindings
    authorization: AuthorizationBindings
    read_only_request: ReadOnlyDiagnosticRequestV1
    read_only_request_digest: str
    envelope_sha256: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["operator_directive"] = self.operator_directive.to_dict()
        value["read_only_request"] = self.read_only_request.to_dict()
        return value


RemoteControlEnvelope: TypeAlias = RemoteOperatorEnvelopeV2 | RemoteOperatorEnvelopeV3


def seal_remote_control_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    schema = payload.get("schema_version") if isinstance(payload, Mapping) else None
    if schema == REMOTE_OPERATOR_ENVELOPE_SCHEMA:
        return seal_remote_envelope(payload)
    if schema != REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: unsupported remote control envelope schema")
    if set(payload) != _V3_FIELDS:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: diagnostic envelope fields mismatch")
    value = copy.deepcopy(dict(payload))
    directive = _diagnostic_directive(value.get("operator_directive"))
    request = _typed_request(value.get("read_only_request"))
    value["directive_digest"] = directive.directive_digest
    value["read_only_request_digest"] = request.request_digest
    value["envelope_sha256"] = _sha(_unsigned(value))
    return value


def validate_remote_control_envelope(
    payload: Mapping[str, Any], *, now: datetime | None = None
) -> RemoteControlEnvelope:
    if not isinstance(payload, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: envelope must be an object")
    schema = payload.get("schema_version")
    if schema == REMOTE_OPERATOR_ENVELOPE_SCHEMA:
        return validate_remote_envelope(payload, now=now)
    if schema != REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA or set(payload) != _V3_FIELDS:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: unsupported diagnostic envelope")

    request = _typed_request(payload.get("read_only_request"))
    directive = _diagnostic_directive(payload.get("operator_directive"))
    if str(payload.get("read_only_request_digest") or "") != request.request_digest:
        raise RemoteOperatorEnvelopeError("DIGEST_MISMATCH: read-only request digest")
    if str(payload.get("directive_digest") or "") != directive.directive_digest:
        raise RemoteOperatorEnvelopeError("DIGEST_MISMATCH: directive digest")
    if str(payload.get("envelope_sha256") or "") != _sha(_unsigned(payload)):
        raise RemoteOperatorEnvelopeError("DIGEST_MISMATCH: envelope digest")

    base = validate_remote_envelope(_v2_projection(payload), now=now)
    return RemoteOperatorEnvelopeV3(
        schema_version=REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA,
        message_id=base.message_id,
        sequence=base.sequence,
        issued_at=base.issued_at,
        expires_at=base.expires_at,
        actor=base.actor,
        transport=base.transport,
        project_id=base.project_id,
        run_id=base.run_id,
        task_id=base.task_id,
        task_execution_id=base.task_execution_id,
        gate_id=base.gate_id,
        operator_directive=base.operator_directive,
        directive_digest=base.directive_digest,
        expected=base.expected,
        authorization=base.authorization,
        read_only_request=request,
        read_only_request_digest=request.request_digest,
        envelope_sha256=str(payload["envelope_sha256"]),
    )
