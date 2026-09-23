"""Additive typed remote-control envelope for non-mutating OCP requests."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .host_inspection_contract import (
    HostInspectionContractError,
    HostInspectionRequestV1,
)
from .remote_operator_envelope import (
    REMOTE_OPERATOR_ENVELOPE_SCHEMA,
    RemoteOperatorEnvelopeV2,
    TransportBinding,
    validate_remote_envelope,
)

REMOTE_CONTROL_ENVELOPE_SCHEMA = "orchestration.remote-control-envelope.v1"
HOST_INSPECTION_KIND = "HOST_INSPECTION"
_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TOP_FIELDS = {
    "schema_version", "request_kind", "message_id", "sequence", "issued_at", "expires_at",
    "actor", "transport", "payload", "payload_digest", "authorization", "envelope_sha256",
}
_TRANSPORT_FIELDS = {"adapter_id", "channel_id", "source_actor_id", "source_message_id"}
_AUTH_FIELDS = {"inspection_policy_ref"}


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


@dataclass(frozen=True, slots=True)
class RemoteControlAuthorization:
    inspection_policy_ref: str

    def __post_init__(self) -> None:
        _safe_id(self.inspection_policy_ref, "inspection policy ref")


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
    payload: HostInspectionRequestV1
    payload_digest: str
    authorization: RemoteControlAuthorization
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


def seal_remote_control_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise RemoteControlEnvelopeError("remote control envelope must be an object")
    value = copy.deepcopy(dict(payload))
    if set(value) != _TOP_FIELDS:
        raise RemoteControlEnvelopeError("remote control envelope fields mismatch")
    if value.get("schema_version") != REMOTE_CONTROL_ENVELOPE_SCHEMA:
        raise RemoteControlEnvelopeError("unsupported remote control schema")
    if value.get("request_kind") != HOST_INSPECTION_KIND:
        raise RemoteControlEnvelopeError("unsupported request kind")
    request = _validated_inspection_payload(value.get("payload"))
    value["payload_digest"] = request.request_digest
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
    if payload.get("request_kind") != HOST_INSPECTION_KIND:
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
    request = _validated_inspection_payload(payload["payload"])
    payload_digest = _digest(payload["payload_digest"], "payload digest")
    if payload_digest != request.request_digest:
        raise RemoteControlEnvelopeError("payload digest mismatch")
    auth_raw = payload["authorization"]
    if not isinstance(auth_raw, Mapping):
        raise RemoteControlEnvelopeError("authorization must be an object")
    _exact_fields(auth_raw, _AUTH_FIELDS, "authorization")
    authorization = RemoteControlAuthorization(
        inspection_policy_ref=str(auth_raw["inspection_policy_ref"]),
    )
    envelope_digest = _digest(payload["envelope_sha256"], "envelope digest")
    if envelope_digest != _sha(_unsigned(payload)):
        raise RemoteControlEnvelopeError("envelope digest mismatch")
    return RemoteControlEnvelopeV1(
        schema_version=REMOTE_CONTROL_ENVELOPE_SCHEMA,
        request_kind=HOST_INSPECTION_KIND,
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
