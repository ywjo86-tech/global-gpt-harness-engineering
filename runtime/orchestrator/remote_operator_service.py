"""Authorization-gated one-shot OCPv2 service loop.

This module owns no scheduling, provider routing, canonical locks, or mutation authority.
It receives transport messages, delegates validation to the supplied ingress function,
and invokes the supplied canonical execution callback only when the selected control mode
permits it.  The callback remains responsible for the existing Full Plan / gateway path.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from .operator_control import OperatorDirectiveV1
from .remote_operator_envelope import RemoteOperatorEnvelopeV2
from .remote_operator_ingress import IngressDecision
from .remote_operator_transport import RawControlEnvelope, RemoteOperatorTransport


class RemoteOperatorServiceError(ValueError):
    pass


class ControlMode(str, Enum):
    DISABLED = "DISABLED"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    CONTROL_READ_ONLY = "CONTROL_READ_ONLY"
    CONTROL_MUTATION_CANARY = "CONTROL_MUTATION_CANARY"
    ACTIVE = "ACTIVE"


@dataclass(frozen=True, slots=True)
class CanaryScope:
    project_id: str
    run_id: str
    task_id: str
    gate_id: str
    directive_id: str

    def matches(self, envelope: RemoteOperatorEnvelopeV2, directive: OperatorDirectiveV1) -> bool:
        return (
            envelope.project_id == self.project_id
            and envelope.run_id == self.run_id
            and envelope.task_id == self.task_id
            and envelope.gate_id == self.gate_id
            and directive.directive_id == self.directive_id
        )


@dataclass(frozen=True, slots=True)
class ServicePollResult:
    mode: str
    received: int = 0
    validated: int = 0
    executed: int = 0
    projected: int = 0
    acknowledged: int = 0
    blocked: int = 0


class RemoteOperatorService:
    def __init__(
        self,
        *,
        transport: RemoteOperatorTransport,
        decode_envelope: Callable[[RawControlEnvelope], RemoteOperatorEnvelopeV2],
        ingress: Callable[[RemoteOperatorEnvelopeV2], IngressDecision],
        execute_authorized: Callable[
            [RemoteOperatorEnvelopeV2, OperatorDirectiveV1], Mapping[str, Any]
        ],
        canary_scope: CanaryScope | None = None,
    ) -> None:
        self.transport = transport
        self.decode_envelope = decode_envelope
        self.ingress = ingress
        self.execute_authorized = execute_authorized
        self.canary_scope = canary_scope

    @staticmethod
    def _projection(
        envelope: RemoteOperatorEnvelopeV2,
        result_class: str,
        *,
        detail: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        projection: dict[str, Any] = {
            "schema_version": "orchestration.remote-service-projection.v1",
            "message_id": envelope.message_id,
            "directive_digest": envelope.directive_digest,
            "project_id": envelope.project_id,
            "run_id": envelope.run_id,
            "gate_id": envelope.gate_id,
            "task_id": envelope.task_id,
            "result_class": str(result_class),
        }
        if detail:
            for key, value in detail.items():
                if key in projection and key != "result_class":
                    continue
                projection[str(key)] = value
        return projection

    def _publish_and_ack(
        self,
        envelope: RemoteOperatorEnvelopeV2,
        projection: Mapping[str, Any],
    ) -> None:
        self.transport.publish_projection(projection)
        self.transport.acknowledge_delivery(envelope.message_id)

    def poll_once(
        self,
        *,
        mode: ControlMode | str,
        batch_limit: int = 16,
    ) -> ServicePollResult:
        try:
            resolved_mode = ControlMode(mode)
        except (TypeError, ValueError) as exc:
            raise RemoteOperatorServiceError("UNKNOWN_MODE") from exc
        if isinstance(batch_limit, bool) or int(batch_limit) <= 0:
            raise RemoteOperatorServiceError("invalid batch limit")
        if resolved_mode == ControlMode.DISABLED:
            return ServicePollResult(mode=resolved_mode.value)

        received = validated = executed = projected = acknowledged = blocked = 0
        for raw in self.transport.receive(limit=int(batch_limit)):
            received += 1
            try:
                envelope = self.decode_envelope(raw)
                decision = self.ingress(envelope)
            except Exception as exc:
                raise RemoteOperatorServiceError("INGRESS_FAILED") from exc
            validated += 1

            if not decision.accepted:
                if decision.result_class == "IDEMPOTENT_REPLAY":
                    self.transport.acknowledge_delivery(envelope.message_id)
                    acknowledged += 1
                    continue
                projection = self._projection(envelope, decision.result_class)
                self._publish_and_ack(envelope, projection)
                projected += 1
                acknowledged += 1
                blocked += 1
                continue

            directive = decision.directive
            if directive is None:
                raise RemoteOperatorServiceError("accepted ingress omitted directive")

            if resolved_mode == ControlMode.OBSERVE_ONLY:
                projection = self._projection(envelope, "OBSERVED")
            elif resolved_mode == ControlMode.CONTROL_READ_ONLY:
                if directive.state_change_required:
                    projection = self._projection(envelope, "MODE_BLOCKED")
                    blocked += 1
                else:
                    projection = self._projection(envelope, "READ_ONLY_ACCEPTED")
            elif resolved_mode == ControlMode.CONTROL_MUTATION_CANARY:
                if directive.state_change_required:
                    if self.canary_scope is None or not self.canary_scope.matches(envelope, directive):
                        projection = self._projection(envelope, "CANARY_SCOPE_MISMATCH")
                        blocked += 1
                    else:
                        result = self.execute_authorized(envelope, directive)
                        if not isinstance(result, Mapping):
                            raise RemoteOperatorServiceError("canonical execution result is malformed")
                        projection = self._projection(
                            envelope,
                            str(result.get("result_class") or "CANONICAL_ACTION_COMPLETED"),
                            detail=result,
                        )
                        executed += 1
                else:
                    projection = self._projection(envelope, "READ_ONLY_ACCEPTED")
            elif resolved_mode == ControlMode.ACTIVE:
                if directive.state_change_required:
                    result = self.execute_authorized(envelope, directive)
                    if not isinstance(result, Mapping):
                        raise RemoteOperatorServiceError("canonical execution result is malformed")
                    projection = self._projection(
                        envelope,
                        str(result.get("result_class") or "CANONICAL_ACTION_COMPLETED"),
                        detail=result,
                    )
                    executed += 1
                else:
                    projection = self._projection(envelope, "READ_ONLY_ACCEPTED")
            else:  # pragma: no cover - enum exhaustiveness guard
                raise RemoteOperatorServiceError("UNKNOWN_MODE")

            self._publish_and_ack(envelope, projection)
            projected += 1
            acknowledged += 1

        return ServicePollResult(
            mode=resolved_mode.value,
            received=received,
            validated=validated,
            executed=executed,
            projected=projected,
            acknowledged=acknowledged,
            blocked=blocked,
        )
