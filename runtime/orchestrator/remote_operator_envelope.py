"""Immutable remote GPT-operator envelope for the OCPv2 transport extension.

This module validates transport/correlation metadata and then delegates operator-stage
semantics to the existing :class:`OperatorDirectiveV1`.  It owns no execution or
orchestration authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .operator_control import OperatorControlError, OperatorDirectiveV1
from .read_only_host_diagnostic_contract import (
    DiagnosticContractError,
    READ_ONLY_DIAGNOSTIC_CAPABILITY,
    ReadOnlyDiagnosticRequestV1,
)

REMOTE_OPERATOR_ENVELOPE_SCHEMA = "orchestration.remote-operator-envelope.v2"
REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA = "orchestration.remote-operator-envelope.v3"
_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHA40_64 = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")

_TOP_FIELDS = {
    "schema_version", "message_id", "sequence", "issued_at", "expires_at", "actor",
    "transport", "project_id", "run_id", "task_id", "task_execution_id", "gate_id",
    "operator_directive", "directive_digest", "expected", "authorization", "envelope_sha256",
}
_TRANSPORT_FIELDS = {"adapter_id", "channel_id", "source_actor_id", "source_message_id"}
_DIRECTIVE_FIELDS = {
    "schema_version", "project_id", "run_id", "task_id", "task_execution_id",
    "current_stage", "requested_next_stage", "required_capabilities", "state_change_required",
    "input_artifact_digests", "gate_id", "directive_id",
}
_EXPECTED_FIELDS = {
    "continuation_state_sha256", "continuation_owner_epoch", "canonical_run_state_sha256",
    "migration_id", "migration_transaction_sha256", "migration_phase",
    "qualification_evidence_sha256", "source_head", "runtime_release_digest",
}
_AUTH_FIELDS = {"risk_envelope_ref", "risk_envelope_digest", "manual_action_authorization_digest"}
_TOP_FIELDS_V3 = _TOP_FIELDS | {"read_only_request", "read_only_request_digest"}


class RemoteOperatorEnvelopeError(ValueError):
    pass


def canonical_envelope_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_envelope_bytes(value)).hexdigest()


def _safe_id(value: object, label: str, *, allow_empty: bool = False) -> str:
    text = str(value or "")
    if allow_empty and not text:
        return ""
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise RemoteOperatorEnvelopeError(f"SCHEMA_REJECTED: unsafe {label}")
    return text


def _digest(value: object, label: str, *, allow_empty: bool = False) -> str:
    text = str(value or "")
    if allow_empty and not text:
        return ""
    if not _SHA256.fullmatch(text):
        raise RemoteOperatorEnvelopeError(f"SCHEMA_REJECTED: invalid {label}")
    return text


def _head(value: object, label: str, *, allow_empty: bool = False) -> str:
    text = str(value or "")
    if allow_empty and not text:
        return ""
    if not _SHA40_64.fullmatch(text):
        raise RemoteOperatorEnvelopeError(f"SCHEMA_REJECTED: invalid {label}")
    return text


def _timestamp(value: object, label: str) -> datetime:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RemoteOperatorEnvelopeError(f"SCHEMA_REJECTED: invalid {label}") from exc
    if parsed.tzinfo is None:
        raise RemoteOperatorEnvelopeError(f"SCHEMA_REJECTED: {label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _exact_fields(payload: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise RemoteOperatorEnvelopeError(f"SCHEMA_REJECTED: {label} fields mismatch")


@dataclass(frozen=True, slots=True)
class TransportBinding:
    adapter_id: str
    channel_id: str
    source_actor_id: str
    source_message_id: str


@dataclass(frozen=True, slots=True)
class ExpectedBindings:
    continuation_state_sha256: str
    continuation_owner_epoch: int
    canonical_run_state_sha256: str
    migration_id: str
    migration_transaction_sha256: str
    migration_phase: str
    qualification_evidence_sha256: str
    source_head: str
    runtime_release_digest: str


@dataclass(frozen=True, slots=True)
class AuthorizationBindings:
    risk_envelope_ref: str
    risk_envelope_digest: str
    manual_action_authorization_digest: str


@dataclass(frozen=True, slots=True)
class RemoteOperatorEnvelopeV2:
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
    envelope_sha256: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["operator_directive"] = self.operator_directive.to_dict()
        return value


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
    envelope_sha256: str
    read_only_request: ReadOnlyDiagnosticRequestV1
    read_only_request_digest: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["operator_directive"] = self.operator_directive.to_dict()
        value["read_only_request"] = self.read_only_request.to_dict()
        return value


RemoteControlEnvelope = RemoteOperatorEnvelopeV2 | RemoteOperatorEnvelopeV3


def _unsigned_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(payload))
    value.pop("envelope_sha256", None)
    return value


def seal_remote_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with directive/envelope digests computed canonically.

    This helper is for producers/tests.  Validation never silently repairs a digest.
    """
    value = copy.deepcopy(dict(payload))
    directive_payload = value.get("operator_directive")
    if not isinstance(directive_payload, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: operator_directive must be an object")
    try:
        directive = OperatorDirectiveV1.from_mapping(directive_payload)
    except OperatorControlError as exc:
        raise RemoteOperatorEnvelopeError(f"OPERATOR_DIRECTIVE_BLOCKED: {exc}") from exc
    value["directive_digest"] = directive.directive_digest
    value["envelope_sha256"] = _sha(_unsigned_envelope(value))
    return value


def validate_remote_envelope(
    payload: Mapping[str, Any], *, now: datetime | None = None
) -> RemoteOperatorEnvelopeV2:
    if not isinstance(payload, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: envelope must be an object")
    _exact_fields(payload, _TOP_FIELDS, "envelope")
    if payload.get("schema_version") != REMOTE_OPERATOR_ENVELOPE_SCHEMA:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: unsupported remote envelope schema")

    message_id = _safe_id(payload["message_id"], "message ID")
    try:
        sequence = int(payload["sequence"])
    except (TypeError, ValueError) as exc:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: invalid sequence") from exc
    if isinstance(payload["sequence"], bool) or sequence <= 0:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: invalid sequence")

    issued = _timestamp(payload["issued_at"], "issued_at")
    expires = _timestamp(payload["expires_at"], "expires_at")
    if expires <= issued:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: expiry must follow issue time")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if current > expires:
        raise RemoteOperatorEnvelopeError("DIRECTIVE_EXPIRED")
    if str(payload["actor"]) != "GPT_OPERATOR":
        raise RemoteOperatorEnvelopeError("ACTOR_NOT_ALLOWED")

    transport_raw = payload["transport"]
    if not isinstance(transport_raw, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: transport must be an object")
    _exact_fields(transport_raw, _TRANSPORT_FIELDS, "transport")
    transport = TransportBinding(
        adapter_id=_safe_id(transport_raw["adapter_id"], "adapter ID"),
        channel_id=_safe_id(transport_raw["channel_id"], "channel ID"),
        source_actor_id=_safe_id(transport_raw["source_actor_id"], "source actor ID"),
        source_message_id=_safe_id(transport_raw["source_message_id"], "source message ID"),
    )

    project_id = _safe_id(payload["project_id"], "project ID")
    run_id = _safe_id(payload["run_id"], "run ID")
    task_id = _safe_id(payload["task_id"], "task ID")
    task_execution_id = _safe_id(payload["task_execution_id"], "task execution ID")
    gate_id = _safe_id(payload["gate_id"], "gate ID")

    directive_raw = payload["operator_directive"]
    if not isinstance(directive_raw, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: operator_directive must be an object")
    try:
        directive = OperatorDirectiveV1.from_mapping(directive_raw)
    except OperatorControlError as exc:
        raise RemoteOperatorEnvelopeError(f"OPERATOR_DIRECTIVE_BLOCKED: {exc}") from exc
    # Existing contract gets first say on provider/model fields; all other extras are schema failures.
    _exact_fields(directive_raw, _DIRECTIVE_FIELDS, "operator directive")
    envelope_identity = (project_id, run_id, task_id, task_execution_id, gate_id)
    directive_identity = (
        directive.project_id, directive.run_id, directive.task_id,
        directive.task_execution_id, directive.gate_id,
    )
    if envelope_identity != directive_identity:
        raise RemoteOperatorEnvelopeError("OPERATOR_DIRECTIVE_BLOCKED: directive identity mismatch")
    directive_digest = _digest(payload["directive_digest"], "directive digest")
    if directive_digest != directive.directive_digest:
        raise RemoteOperatorEnvelopeError("DIGEST_MISMATCH: directive digest")

    expected_raw = payload["expected"]
    if not isinstance(expected_raw, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: expected must be an object")
    _exact_fields(expected_raw, _EXPECTED_FIELDS, "expected")
    try:
        owner_epoch = int(expected_raw["continuation_owner_epoch"])
    except (TypeError, ValueError) as exc:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: invalid continuation owner epoch") from exc
    if isinstance(expected_raw["continuation_owner_epoch"], bool) or owner_epoch < 0:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: invalid continuation owner epoch")
    expected = ExpectedBindings(
        continuation_state_sha256=_digest(expected_raw["continuation_state_sha256"], "continuation state digest", allow_empty=True),
        continuation_owner_epoch=owner_epoch,
        canonical_run_state_sha256=_digest(expected_raw["canonical_run_state_sha256"], "canonical run state digest", allow_empty=True),
        migration_id=_safe_id(expected_raw["migration_id"], "migration ID", allow_empty=True),
        migration_transaction_sha256=_digest(expected_raw["migration_transaction_sha256"], "migration transaction digest", allow_empty=True),
        migration_phase=_safe_id(expected_raw["migration_phase"], "migration phase", allow_empty=True),
        qualification_evidence_sha256=_digest(expected_raw["qualification_evidence_sha256"], "qualification evidence digest", allow_empty=True),
        source_head=_head(expected_raw["source_head"], "source head", allow_empty=True),
        runtime_release_digest=_digest(expected_raw["runtime_release_digest"], "runtime release digest", allow_empty=True),
    )
    if directive.state_change_required and (
        not expected.continuation_state_sha256 or expected.continuation_owner_epoch <= 0
    ):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: state change requires continuation CAS binding")
    migration_any = bool(expected.migration_id or expected.migration_transaction_sha256 or expected.migration_phase)
    migration_all = bool(expected.migration_id and expected.migration_transaction_sha256 and expected.migration_phase)
    if migration_any and not migration_all:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: migration CAS binding incomplete")

    auth_raw = payload["authorization"]
    if not isinstance(auth_raw, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: authorization must be an object")
    _exact_fields(auth_raw, _AUTH_FIELDS, "authorization")
    authorization = AuthorizationBindings(
        risk_envelope_ref=_safe_id(auth_raw["risk_envelope_ref"], "risk envelope ref", allow_empty=True),
        risk_envelope_digest=_digest(auth_raw["risk_envelope_digest"], "risk envelope digest", allow_empty=True),
        manual_action_authorization_digest=_digest(
            auth_raw["manual_action_authorization_digest"], "manual action authorization digest", allow_empty=True
        ),
    )

    envelope_digest = _digest(payload["envelope_sha256"], "envelope digest")
    if envelope_digest != _sha(_unsigned_envelope(payload)):
        raise RemoteOperatorEnvelopeError("DIGEST_MISMATCH: envelope digest")

    return RemoteOperatorEnvelopeV2(
        schema_version=REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        message_id=message_id,
        sequence=sequence,
        issued_at=str(payload["issued_at"]),
        expires_at=str(payload["expires_at"]),
        actor="GPT_OPERATOR",
        transport=transport,
        project_id=project_id,
        run_id=run_id,
        task_id=task_id,
        task_execution_id=task_execution_id,
        gate_id=gate_id,
        operator_directive=directive,
        directive_digest=directive_digest,
        expected=expected,
        authorization=authorization,
        envelope_sha256=envelope_digest,
    )


def _parse_diagnostic_request(payload: object) -> ReadOnlyDiagnosticRequestV1:
    if not isinstance(payload, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: diagnostic request must be an object")
    try:
        return ReadOnlyDiagnosticRequestV1.from_mapping(payload)
    except DiagnosticContractError as exc:
        raise RemoteOperatorEnvelopeError(f"SCHEMA_REJECTED: invalid diagnostic request: {exc}") from exc


def _validate_diagnostic_directive(payload: object) -> OperatorDirectiveV1:
    if not isinstance(payload, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: operator_directive must be an object")
    if payload.get("state_change_required") is not False:
        raise RemoteOperatorEnvelopeError(
            "SCHEMA_REJECTED: diagnostic state change requires state_change_required literal false"
        )
    capabilities = payload.get("required_capabilities")
    if not isinstance(capabilities, (list, tuple)) or tuple(capabilities) != (READ_ONLY_DIAGNOSTIC_CAPABILITY,):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: diagnostic capability list must be exact")
    try:
        directive = OperatorDirectiveV1.from_mapping(payload)
    except OperatorControlError as exc:
        raise RemoteOperatorEnvelopeError(f"OPERATOR_DIRECTIVE_BLOCKED: {exc}") from exc
    _exact_fields(payload, _DIRECTIVE_FIELDS, "operator directive")
    if directive.state_change_required:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: diagnostic state change is forbidden")
    if directive.required_capabilities != (READ_ONLY_DIAGNOSTIC_CAPABILITY,):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: diagnostic capability must be exact")
    return directive


def seal_remote_control_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Seal V2 unchanged or the additive typed diagnostic V3 envelope."""
    if not isinstance(payload, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: envelope must be an object")
    schema = payload.get("schema_version")
    if schema == REMOTE_OPERATOR_ENVELOPE_SCHEMA:
        return seal_remote_envelope(payload)
    if schema != REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: unsupported remote envelope schema")
    value = copy.deepcopy(dict(payload))
    _exact_fields(value, _TOP_FIELDS_V3, "envelope")
    directive = _validate_diagnostic_directive(value.get("operator_directive"))
    request = _parse_diagnostic_request(value.get("read_only_request"))
    value["directive_digest"] = directive.directive_digest
    value["read_only_request_digest"] = request.request_digest
    value["envelope_sha256"] = _sha(_unsigned_envelope(value))
    return value


def validate_remote_control_envelope(
    payload: Mapping[str, Any], *, now: datetime | None = None
) -> RemoteControlEnvelope:
    """Validate V2 without semantic changes or validate the typed diagnostic V3 extension."""
    if not isinstance(payload, Mapping):
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: envelope must be an object")
    schema = payload.get("schema_version")
    if schema == REMOTE_OPERATOR_ENVELOPE_SCHEMA:
        return validate_remote_envelope(payload, now=now)
    if schema != REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA:
        raise RemoteOperatorEnvelopeError("SCHEMA_REJECTED: unsupported remote envelope schema")
    _exact_fields(payload, _TOP_FIELDS_V3, "envelope")
    directive = _validate_diagnostic_directive(payload.get("operator_directive"))
    request = _parse_diagnostic_request(payload.get("read_only_request"))
    request_digest = _digest(payload.get("read_only_request_digest"), "diagnostic request digest")
    if request_digest != request.request_digest:
        raise RemoteOperatorEnvelopeError("DIGEST_MISMATCH: diagnostic request digest")
    envelope_digest = _digest(payload.get("envelope_sha256"), "envelope digest")
    if envelope_digest != _sha(_unsigned_envelope(payload)):
        raise RemoteOperatorEnvelopeError("DIGEST_MISMATCH: envelope digest")

    # Reuse the exact V2 common-field validator on a synthesized V2 envelope.
    common = copy.deepcopy(dict(payload))
    common.pop("read_only_request", None)
    common.pop("read_only_request_digest", None)
    common["schema_version"] = REMOTE_OPERATOR_ENVELOPE_SCHEMA
    common["envelope_sha256"] = _sha(_unsigned_envelope(common))
    base = validate_remote_envelope(common, now=now)
    if base.operator_directive.directive_digest != directive.directive_digest:
        raise RemoteOperatorEnvelopeError("DIGEST_MISMATCH: directive digest")

    return RemoteOperatorEnvelopeV3(
        schema_version=REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA,
        message_id=base.message_id, sequence=base.sequence, issued_at=base.issued_at,
        expires_at=base.expires_at, actor=base.actor, transport=base.transport,
        project_id=base.project_id, run_id=base.run_id, task_id=base.task_id,
        task_execution_id=base.task_execution_id, gate_id=base.gate_id,
        operator_directive=base.operator_directive, directive_digest=base.directive_digest,
        expected=base.expected, authorization=base.authorization, envelope_sha256=envelope_digest,
        read_only_request=request, read_only_request_digest=request_digest,
    )
