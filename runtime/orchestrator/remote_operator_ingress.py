"""Non-authoritative OCPv2 ingress validation and existing-operator bridge."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .operator_control import OperatorDirectiveV1
from .remote_operator_envelope import RemoteOperatorEnvelopeV2
from .remote_operator_receipt import ReceiptStatus, RemoteOperatorReceiptStore


@dataclass(frozen=True, slots=True)
class IngressDecision:
    accepted: bool
    result_class: str
    message_id: str
    directive_digest: str
    directive: OperatorDirectiveV1 | None = None


def prepare_existing_operator_directive(envelope: RemoteOperatorEnvelopeV2) -> OperatorDirectiveV1:
    """Re-enter the existing operator contract; no OCP-specific stage authority is created."""
    return OperatorDirectiveV1.from_mapping(envelope.operator_directive.to_dict())


def _blocked(envelope: RemoteOperatorEnvelopeV2, result_class: str) -> IngressDecision:
    return IngressDecision(
        accepted=False,
        result_class=result_class,
        message_id=envelope.message_id,
        directive_digest=envelope.directive_digest,
        directive=None,
    )


def validate_ingress(
    envelope: RemoteOperatorEnvelopeV2,
    *,
    receipt_store: RemoteOperatorReceiptStore,
    allowed_adapter_id: str,
    allowed_channel_id: str,
    allowed_source_actor_ids: Iterable[str],
    expected_risk_envelope_digest: str | None,
) -> IngressDecision:
    """Validate transport/authorization/replay identity before any canonical dispatch.

    Successful validation records transport receipt only.  The returned directive still
    requires the existing Full Plan/continuation/execution-gateway path to perform work.
    """
    allowed_actors = frozenset(str(item) for item in allowed_source_actor_ids)
    if (
        envelope.transport.adapter_id != str(allowed_adapter_id)
        or envelope.transport.channel_id != str(allowed_channel_id)
        or envelope.transport.source_actor_id not in allowed_actors
    ):
        return _blocked(envelope, "SOURCE_NOT_ALLOWED")

    if expected_risk_envelope_digest is not None:
        if envelope.authorization.risk_envelope_digest != str(expected_risk_envelope_digest):
            return _blocked(envelope, "AUTHORIZATION_SCOPE_MISMATCH")

    classification = receipt_store.classify_delivery(envelope)
    if classification == ReceiptStatus.IDEMPOTENT_REPLAY:
        return _blocked(envelope, "IDEMPOTENT_REPLAY")
    if classification == ReceiptStatus.TAMPER_DETECTED:
        return _blocked(envelope, "TAMPER_DETECTED")
    if classification == ReceiptStatus.REPLAY_REJECTED:
        return _blocked(envelope, "REPLAY_REJECTED")

    directive = prepare_existing_operator_directive(envelope)
    receipt_store.record_received(envelope)
    return IngressDecision(
        accepted=True,
        result_class="MESSAGE_RECEIVED",
        message_id=envelope.message_id,
        directive_digest=envelope.directive_digest,
        directive=directive,
    )
