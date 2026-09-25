"""Additive typed remote-control envelope for governed OCP requests."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .approved_full_plan_activation_contract import (
    ApprovedFullPlanActivationContractError,
    ApprovedFullPlanActivationRequestV1,
)
from .approved_work_binding import (
    ApprovedWorkActivationRequestV1,
    ApprovedWorkBindingError,
)
from .host_inspection_contract import (
    HostInspectionContractError,
    HostInspectionRequestV1,
)
from .project_onboarding_remote import (
    ProjectOnboardingRemoteError,
    ProjectOnboardingRequest,
)
from .successor_release_staging import (
    SuccessorReleaseStageError,
    SuccessorReleaseStageRequest,
)
from .remote_operator_envelope import (
    REMOTE_OPERATOR_ENVELOPE_SCHEMA,
    RemoteOperatorEnvelopeV2,
    TransportBinding,
    validate_remote_envelope,
)

REMOTE_CONTROL_ENVELOPE_SCHEMA = "orchestration.remote-control-envelope.v1"
HOST_INSPECTION_KIND = "HOST_INSPECTION"
APPROVED_WORK_ACTIVATION_KIND = "APPROVED_WORK_ACTIVATION"
APPROVED_FULL_PLAN_ACTIVATION_KIND = "APPROVED_FULL_PLAN_ACTIVATION"
PROJECT_ONBOARDING_KIND = "PROJECT_ONBOARDING"
SUCCESSOR_RELEASE_STAGE_KIND = "SUCCESSOR_RELEASE_STAGE"
_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TOP_FIELDS = {
    "schema_version", "request_kind", "message_id", "sequence", "issued_at", "expires_at",
    "actor", "transport", "payload", "payload_digest", "authorization", "envelope_sha256",
}
_TRANSPORT_FIELDS = {"adapter_id", "channel_id", "source_actor_id", "source_message_id"}
_INSPECTION_AUTH_FIELDS = {"inspection_policy_ref"}
_ACTIVATION_AUTH_FIELDS = {"activation_policy_ref"}
_FULL_PLAN_ACTIVATION_AUTH_FIELDS = {"full_plan_activation_policy_ref"}
_PROJECT_ONBOARDING_AUTH_FIELDS = {"project_onboarding_policy_ref"}
_SUCCESSOR_RELEASE_STAGE_AUTH_FIELDS = {"successor_release_stage_policy_ref"}


class RemoteControlEnvelopeError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise RemoteControlEnvelopeError(f"invalid {label}")
    return text


def _digest(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA256.fullmatch(text):
        raise RemoteControlEnvelopeError(f"invalid {label}")
    return text


def _timestamp(value: object, label: str) -> datetime:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RemoteControlEnvelopeError(f"invalid {label}") from exc
    if parsed.tzinfo is None:
        raise RemoteControlEnvelopeError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise RemoteControlEnvelopeError(f"{label} fields mismatch")


def _unsigned(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(payload))
    value.pop("envelope_sha256", None)
    return value


def _payload_request_digest(request: object) -> str:
    if isinstance(request, SuccessorReleaseStageRequest):
        return request.phase_request_digest
    value = getattr(request, "request_digest", None)
    if not isinstance(value, str):
        raise RemoteControlEnvelopeError("payload request digest unavailable")
    return value


@dataclass(frozen=True, slots=True)
class RemoteControlAuthorization:
    inspection_policy_ref: str

    def __post_init__(self) -> None:
        _safe_id(self.inspection_policy_ref, "inspection policy ref")


@dataclass(frozen=True, slots=True)
class RemoteWorkActivationAuthorization:
    activation_policy_ref: str

    def __post_init__(self) -> None:
        _safe_id(self.activation_policy_ref, "activation policy ref")


@dataclass(frozen=True, slots=True)
class RemoteFullPlanActivationAuthorization:
    full_plan_activation_policy_ref: str

    def __post_init__(self) -> None:
        _safe_id(self.full_plan_activation_policy_ref, "Full Plan activation policy ref")


@dataclass(frozen=True, slots=True)
class RemoteProjectOnboardingAuthorization:
    project_onboarding_policy_ref: str

    def __post_init__(self) -> None:
        _safe_id(self.project_onboarding_policy_ref, "project onboarding policy ref")


@dataclass(frozen=True, slots=True)
class RemoteSuccessorReleaseStageAuthorization:
    successor_release_stage_policy_ref: str

    def __post_init__(self) -> None:
        _safe_id(self.successor_release_stage_policy_ref, "successor release stage policy ref")


RemotePayload = (
    HostInspectionRequestV1
    | ApprovedWorkActivationRequestV1
    | ApprovedFullPlanActivationRequestV1
    | ProjectOnboardingRequest
    | SuccessorReleaseStageRequest
)
RemoteAuthorization = (
    RemoteControlAuthorization
    | RemoteWorkActivationAuthorization
    | RemoteFullPlanActivationAuthorization
    | RemoteProjectOnboardingAuthorization
    | RemoteSuccessorReleaseStageAuthorization
)


@dataclass(frozen=True, slots=True)
class RemoteControlEnvelopeV1:
    schema_version: str
    request_kind: str
    message_id: str
    sequence: int
    issued_at: str
    expires_at: str
    actor: str
    transport: TransportBinding
    payload: RemotePayload
    payload_digest: str
    authorization: RemoteAuthorization
    envelope_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_kind": self.request_kind,
            "message_id": self.message_id,
            "sequence": self.sequence,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "actor": self.actor,
            "transport": asdict(self.transport),
            "payload": self.payload.to_dict(),
            "payload_digest": self.payload_digest,
            "authorization": asdict(self.authorization),
            "envelope_sha256": self.envelope_sha256,
        }


def _validated_inspection_payload(raw: object) -> HostInspectionRequestV1:
    if not isinstance(raw, Mapping):
        raise RemoteControlEnvelopeError("host inspection payload must be an object")
    try:
        return HostInspectionRequestV1.from_mapping(raw)
    except HostInspectionContractError as exc:
        raise RemoteControlEnvelopeError(f"invalid host inspection payload: {exc}") from exc


def _validated_activation_payload(raw: object) -> ApprovedWorkActivationRequestV1:
    if not isinstance(raw, Mapping):
        raise RemoteControlEnvelopeError("approved work activation payload must be an object")
    try:
        return ApprovedWorkActivationRequestV1.from_mapping(raw)
    except ApprovedWorkBindingError as exc:
        raise RemoteControlEnvelopeError(f"invalid approved work activation payload: {exc}") from exc


def _validated_full_plan_activation_payload(raw: object) -> ApprovedFullPlanActivationRequestV1:
    if not isinstance(raw, Mapping):
        raise RemoteControlEnvelopeError("approved Full Plan activation payload must be an object")
    try:
        return ApprovedFullPlanActivationRequestV1.from_mapping(raw)
    except ApprovedFullPlanActivationContractError as exc:
        raise RemoteControlEnvelopeError(f"invalid approved Full Plan activation payload: {exc}") from exc


def _validated_project_onboarding_payload(raw: object) -> ProjectOnboardingRequest:
    if not isinstance(raw, Mapping):
        raise RemoteControlEnvelopeError("project onboarding payload must be an object")
    try:
        return ProjectOnboardingRequest.from_mapping(raw)
    except ProjectOnboardingRemoteError as exc:
        raise RemoteControlEnvelopeError(f"invalid project onboarding payload: {exc}") from exc


def _validated_successor_release_stage_payload(raw: object) -> SuccessorReleaseStageRequest:
    if not isinstance(raw, Mapping):
        raise RemoteControlEnvelopeError("successor release stage payload must be an object")
    try:
        return SuccessorReleaseStageRequest.from_mapping(raw)
    except SuccessorReleaseStageError as exc:
        raise RemoteControlEnvelopeError(f"invalid successor release stage payload: {exc}") from exc


def _validated_payload(kind: object, raw: object) -> RemotePayload:
    if kind == HOST_INSPECTION_KIND:
        return _validated_inspection_payload(raw)
    if kind == APPROVED_WORK_ACTIVATION_KIND:
        return _validated_activation_payload(raw)
    if kind == APPROVED_FULL_PLAN_ACTIVATION_KIND:
        return _validated_full_plan_activation_payload(raw)
    if kind == PROJECT_ONBOARDING_KIND:
        return _validated_project_onboarding_payload(raw)
    if kind == SUCCESSOR_RELEASE_STAGE_KIND:
        return _validated_successor_release_stage_payload(raw)
    raise RemoteControlEnvelopeError("unsupported request kind")


def seal_remote_control_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise RemoteControlEnvelopeError("remote control envelope must be an object")
    value = copy.deepcopy(dict(payload))
    if set(value) != _TOP_FIELDS:
        raise RemoteControlEnvelopeError("remote control envelope fields mismatch")
    if value.get("schema_version") != REMOTE_CONTROL_ENVELOPE_SCHEMA:
        raise RemoteControlEnvelopeError("unsupported remote control schema")
    request = _validated_payload(value.get("request_kind"), value.get("payload"))
    value["payload_digest"] = _payload_request_digest(request)
    value["envelope_sha256"] = _sha(_unsigned(value))
    return value


def _validate_transport(raw: object) -> TransportBinding:
    if not isinstance(raw, Mapping):
        raise RemoteControlEnvelopeError("transport must be an object")
    _exact_fields(raw, _TRANSPORT_FIELDS, "transport")
    return TransportBinding(
        adapter_id=_safe_id(raw["adapter_id"], "adapter ID"),
        channel_id=_safe_id(raw["channel_id"], "channel ID"),
        source_actor_id=_safe_id(raw["source_actor_id"], "source actor ID"),
        source_message_id=_safe_id(raw["source_message_id"], "source message ID"),
    )


def validate_remote_control_envelope(
    payload: Mapping[str, Any], *, now: datetime | None = None,
) -> RemoteControlEnvelopeV1:
    if not isinstance(payload, Mapping):
        raise RemoteControlEnvelopeError("remote control envelope must be an object")
    _exact_fields(payload, _TOP_FIELDS, "remote control envelope")
    if payload.get("schema_version") != REMOTE_CONTROL_ENVELOPE_SCHEMA:
        raise RemoteControlEnvelopeError("unsupported remote control schema")
    request_kind = str(payload.get("request_kind") or "")
    if request_kind not in {
        HOST_INSPECTION_KIND,
        APPROVED_WORK_ACTIVATION_KIND,
        APPROVED_FULL_PLAN_ACTIVATION_KIND,
        PROJECT_ONBOARDING_KIND,
        SUCCESSOR_RELEASE_STAGE_KIND,
    }:
        raise RemoteControlEnvelopeError("unsupported request kind")
    message_id = _safe_id(payload["message_id"], "message ID")
    try:
        sequence = int(payload["sequence"])
    except (TypeError, ValueError) as exc:
        raise RemoteControlEnvelopeError("invalid sequence") from exc
    if isinstance(payload["sequence"], bool) or sequence <= 0:
        raise RemoteControlEnvelopeError("invalid sequence")
    issued = _timestamp(payload["issued_at"], "issued_at")
    expires = _timestamp(payload["expires_at"], "expires_at")
    if expires <= issued:
        raise RemoteControlEnvelopeError("expiry must follow issue time")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if current > expires:
        raise RemoteControlEnvelopeError("remote control request expired")
    if str(payload["actor"]) != "GPT_OPERATOR":
        raise RemoteControlEnvelopeError("actor not allowed")
    transport = _validate_transport(payload["transport"])
    request = _validated_payload(request_kind, payload["payload"])
    payload_digest = _digest(payload["payload_digest"], "payload digest")
    if payload_digest != _payload_request_digest(request):
        raise RemoteControlEnvelopeError("payload digest mismatch")
    auth_raw = payload["authorization"]
    if not isinstance(auth_raw, Mapping):
        raise RemoteControlEnvelopeError("authorization must be an object")
    if request_kind == HOST_INSPECTION_KIND:
        _exact_fields(auth_raw, _INSPECTION_AUTH_FIELDS, "authorization")
        authorization: RemoteAuthorization = RemoteControlAuthorization(
            inspection_policy_ref=str(auth_raw["inspection_policy_ref"]),
        )
    elif request_kind == APPROVED_WORK_ACTIVATION_KIND:
        _exact_fields(auth_raw, _ACTIVATION_AUTH_FIELDS, "authorization")
        authorization = RemoteWorkActivationAuthorization(
            activation_policy_ref=str(auth_raw["activation_policy_ref"]),
        )
    elif request_kind == APPROVED_FULL_PLAN_ACTIVATION_KIND:
        _exact_fields(auth_raw, _FULL_PLAN_ACTIVATION_AUTH_FIELDS, "authorization")
        authorization = RemoteFullPlanActivationAuthorization(
            full_plan_activation_policy_ref=str(auth_raw["full_plan_activation_policy_ref"]),
        )
    elif request_kind == PROJECT_ONBOARDING_KIND:
        _exact_fields(auth_raw, _PROJECT_ONBOARDING_AUTH_FIELDS, "authorization")
        authorization = RemoteProjectOnboardingAuthorization(
            project_onboarding_policy_ref=str(auth_raw["project_onboarding_policy_ref"]),
        )
    else:
        _exact_fields(auth_raw, _SUCCESSOR_RELEASE_STAGE_AUTH_FIELDS, "authorization")
        authorization = RemoteSuccessorReleaseStageAuthorization(
            successor_release_stage_policy_ref=str(auth_raw["successor_release_stage_policy_ref"]),
        )
        if authorization.successor_release_stage_policy_ref != request.approval_policy_ref:
            raise RemoteControlEnvelopeError("successor release stage authorization mismatch")
    envelope_digest = _digest(payload["envelope_sha256"], "envelope digest")
    if envelope_digest != _sha(_unsigned(payload)):
        raise RemoteControlEnvelopeError("envelope digest mismatch")
    return RemoteControlEnvelopeV1(
        schema_version=REMOTE_CONTROL_ENVELOPE_SCHEMA,
        request_kind=request_kind,
        message_id=message_id,
        sequence=sequence,
        issued_at=str(payload["issued_at"]),
        expires_at=str(payload["expires_at"]),
        actor="GPT_OPERATOR",
        transport=transport,
        payload=request,
        payload_digest=payload_digest,
        authorization=authorization,
        envelope_sha256=envelope_digest,
    )


def decode_remote_control_payload(
    raw: Mapping[str, Any], *, now: datetime | None = None,
) -> RemoteControlEnvelopeV1 | RemoteOperatorEnvelopeV2:
    if not isinstance(raw, Mapping):
        raise RemoteControlEnvelopeError("remote control payload must be an object")
    schema = raw.get("schema_version")
    if schema == REMOTE_CONTROL_ENVELOPE_SCHEMA:
        return validate_remote_control_envelope(raw, now=now)
    if schema == REMOTE_OPERATOR_ENVELOPE_SCHEMA:
        return validate_remote_envelope(raw, now=now)
    raise RemoteControlEnvelopeError("unsupported remote control schema")
