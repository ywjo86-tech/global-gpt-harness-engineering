"""Authorization-gated one-shot OCPv2 service loop.

This module owns no scheduling, provider routing, canonical locks, or mutation authority.
It receives transport messages, delegates validation to the supplied ingress function,
and invokes the supplied canonical execution callback only when the selected control mode
permits it.  The callback remains responsible for the existing Full Plan / gateway path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Mapping

from .operator_control import OperatorDirectiveV1
from .read_only_host_diagnostic_contract import ReadOnlyDiagnosticRequestV1
from .remote_control_envelope import (
    APPROVED_FULL_PLAN_ACTIVATION_KIND, APPROVED_WORK_ACTIVATION_KIND, HOST_INSPECTION_KIND,
    RemoteControlEnvelopeV1, RemoteFullPlanActivationAuthorization, RemoteWorkActivationAuthorization,
    validate_remote_control_envelope,
)
from .remote_operator_envelope import RemoteControlEnvelope, RemoteOperatorEnvelopeV3
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

    def matches(self, envelope: RemoteControlEnvelope, directive: OperatorDirectiveV1) -> bool:
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
    diagnosed: int = 0
    projected: int = 0
    acknowledged: int = 0
    blocked: int = 0
    inspected: int = 0
    activated: int = 0
    full_plan_activated: int = 0


class RemoteOperatorService:
    def __init__(
        self,
        *,
        transport: RemoteOperatorTransport,
        decode_envelope: Callable[[RawControlEnvelope], Any],
        ingress: Callable[[RemoteControlEnvelope], IngressDecision],
        execute_authorized: Callable[
            [RemoteControlEnvelope, OperatorDirectiveV1], Mapping[str, Any]
        ],
        execute_read_only: Callable[
            [RemoteControlEnvelope, OperatorDirectiveV1, ReadOnlyDiagnosticRequestV1], Mapping[str, Any]
        ] | None = None,
        canary_scope: CanaryScope | None = None,
        after_projection_published: Callable[[Any, Mapping[str, Any]], None] | None = None,
        inspect_authorized: Callable[[RemoteControlEnvelopeV1], Mapping[str, Any]] | None = None,
        host_inspection_enabled: bool = False,
        activate_authorized: Callable[[RemoteControlEnvelopeV1], Mapping[str, Any]] | None = None,
        work_activation_enabled: bool = False,
        activation_policy_ref: str = "",
        activate_full_plan_authorized: Callable[[RemoteControlEnvelopeV1], Mapping[str, Any]] | None = None,
        full_plan_activation_enabled: bool = False,
        full_plan_activation_policy_ref: str = "",
    ) -> None:
        self.transport = transport
        self.decode_envelope = decode_envelope
        self.ingress = ingress
        self.execute_authorized = execute_authorized
        self.execute_read_only = execute_read_only
        self.canary_scope = canary_scope
        self.after_projection_published = after_projection_published
        self.inspect_authorized = inspect_authorized
        self.host_inspection_enabled = bool(host_inspection_enabled)
        self.activate_authorized = activate_authorized
        self.work_activation_enabled = bool(work_activation_enabled)
        self.activation_policy_ref = str(activation_policy_ref or "")
        self.activate_full_plan_authorized = activate_full_plan_authorized
        self.full_plan_activation_enabled = bool(full_plan_activation_enabled)
        self.full_plan_activation_policy_ref = str(full_plan_activation_policy_ref or "")

    @staticmethod
    def _projection(
        envelope: RemoteControlEnvelope,
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

    @staticmethod
    def _inspection_status_projection(
        envelope: RemoteControlEnvelopeV1, result_class: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "orchestration.remote-inspection-status-projection.v1",
            "message_id": envelope.message_id,
            "request_id": envelope.payload.request_id,
            "correlation_id": envelope.payload.correlation_id,
            "project_alias": envelope.payload.project_alias,
            "operation": envelope.payload.operation,
            "request_digest": envelope.payload.request_digest,
            "result_class": str(result_class),
        }

    @staticmethod
    def _activation_status_projection(
        envelope: RemoteControlEnvelopeV1, result_class: str,
    ) -> dict[str, Any]:
        payload = envelope.payload
        return {
            "schema_version": "orchestration.remote-activation-status-projection.v1",
            "message_id": envelope.message_id,
            "activation_request_id": payload.activation_request_id,
            "project_alias": payload.project_alias,
            "request_digest": payload.request_digest,
            "result_class": str(result_class),
        }

    @staticmethod
    def _full_plan_activation_status_projection(
        envelope: RemoteControlEnvelopeV1, result_class: str,
    ) -> dict[str, Any]:
        payload = envelope.payload
        return {
            "schema_version": "orchestration.remote-full-plan-activation-status-projection.v1",
            "message_id": envelope.message_id,
            "activation_request_id": payload.activation_request_id,
            "project_alias": payload.project_alias,
            "request_digest": payload.request_digest,
            "result_class": str(result_class),
        }

    @staticmethod
    def _recover_expired_remote_control(
        raw: RawControlEnvelope,
        exc: Exception,
    ) -> RemoteControlEnvelopeV1 | None:
        """Recover only a fully authenticated expired v1 request, never malformed input."""
        if str(exc) != "remote control request expired":
            return None
        try:
            value = json.loads(raw.content.decode("utf-8"))
            if not isinstance(value, Mapping):
                return None
            issued_raw = str(value.get("issued_at") or "")
            issued_at = datetime.fromisoformat(issued_raw.replace("Z", "+00:00"))
            envelope = validate_remote_control_envelope(value, now=issued_at)
        except Exception:
            return None
        # The configured transport already scopes the repository. Re-check every signed
        # transport binding that is present in RawControlEnvelope before consuming the
        # expired request. Any mismatch remains a hard ingress failure.
        if (
            envelope.transport.adapter_id != "GITHUB_CONTROL_V1"
            or envelope.transport.channel_id != raw.source_channel_id
            or envelope.transport.source_actor_id != raw.source_actor_id
            or envelope.transport.source_message_id != raw.source_message_id
        ):
            return None
        return envelope

    def _publish_and_ack(
        self,
        envelope: Any,
        projection: Mapping[str, Any],
    ) -> None:
        self.transport.publish_projection(projection)
        self.transport.acknowledge_delivery(envelope.message_id)
        if self.after_projection_published is not None:
            self.after_projection_published(envelope, projection)

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

        received = validated = executed = diagnosed = projected = acknowledged = blocked = inspected = activated = full_plan_activated = 0
        for raw in self.transport.receive(limit=int(batch_limit)):
            received += 1
            expired_remote_control = False
            try:
                envelope = self.decode_envelope(raw)
            except Exception as exc:
                envelope = self._recover_expired_remote_control(raw, exc)
                if envelope is None:
                    raise RemoteOperatorServiceError("INGRESS_FAILED") from exc
                expired_remote_control = True
            validated += 1

            if expired_remote_control:
                if envelope.request_kind == HOST_INSPECTION_KIND:
                    projection = self._inspection_status_projection(envelope, "HOST_INSPECTION_EXPIRED")
                elif envelope.request_kind == APPROVED_WORK_ACTIVATION_KIND:
                    projection = self._activation_status_projection(envelope, "WORK_ACTIVATION_EXPIRED")
                elif envelope.request_kind == APPROVED_FULL_PLAN_ACTIVATION_KIND:
                    projection = self._full_plan_activation_status_projection(envelope, "FULL_PLAN_ACTIVATION_EXPIRED")
                else:  # validator already rejects unknown kinds; keep a fail-closed guard.
                    raise RemoteOperatorServiceError("UNKNOWN_REMOTE_CONTROL_KIND")
                self._publish_and_ack(envelope, projection)
                projected += 1
                acknowledged += 1
                blocked += 1
                continue

            if isinstance(envelope, RemoteControlEnvelopeV1):
                if envelope.request_kind == HOST_INSPECTION_KIND:
                    if not self.host_inspection_enabled or self.inspect_authorized is None:
                        projection = self._inspection_status_projection(envelope, "HOST_INSPECTION_DISABLED")
                        blocked += 1
                    else:
                        try:
                            projection = self.inspect_authorized(envelope)
                            if not isinstance(projection, Mapping):
                                raise RemoteOperatorServiceError("host inspection result projection is malformed")
                            inspected += 1
                        except Exception:
                            projection = self._inspection_status_projection(envelope, "HOST_INSPECTION_ERROR")
                            blocked += 1
                elif envelope.request_kind == APPROVED_FULL_PLAN_ACTIVATION_KIND:
                    if resolved_mode != ControlMode.ACTIVE:
                        projection = self._full_plan_activation_status_projection(envelope, "MODE_BLOCKED")
                        blocked += 1
                    elif not self.full_plan_activation_enabled or self.activate_full_plan_authorized is None:
                        projection = self._full_plan_activation_status_projection(envelope, "FULL_PLAN_ACTIVATION_DISABLED")
                        blocked += 1
                    elif (
                        not isinstance(envelope.authorization, RemoteFullPlanActivationAuthorization)
                        or not self.full_plan_activation_policy_ref
                        or envelope.authorization.full_plan_activation_policy_ref != self.full_plan_activation_policy_ref
                    ):
                        projection = self._full_plan_activation_status_projection(envelope, "FULL_PLAN_ACTIVATION_AUTHORIZATION_MISMATCH")
                        blocked += 1
                    else:
                        try:
                            projection = self.activate_full_plan_authorized(envelope)
                            if not isinstance(projection, Mapping):
                                raise RemoteOperatorServiceError("Full Plan activation result projection is malformed")
                            full_plan_activated += 1
                        except Exception:
                            projection = self._full_plan_activation_status_projection(envelope, "FULL_PLAN_ACTIVATION_ERROR")
                            blocked += 1
                elif envelope.request_kind == APPROVED_WORK_ACTIVATION_KIND:
                    if resolved_mode != ControlMode.ACTIVE:
                        projection = self._activation_status_projection(envelope, "MODE_BLOCKED")
                        blocked += 1
                    elif not self.work_activation_enabled or self.activate_authorized is None:
                        projection = self._activation_status_projection(envelope, "WORK_ACTIVATION_DISABLED")
                        blocked += 1
                    elif (
                        not isinstance(envelope.authorization, RemoteWorkActivationAuthorization)
                        or not self.activation_policy_ref
                        or envelope.authorization.activation_policy_ref != self.activation_policy_ref
                    ):
                        projection = self._activation_status_projection(envelope, "ACTIVATION_AUTHORIZATION_MISMATCH")
                        blocked += 1
                    else:
                        try:
                            projection = self.activate_authorized(envelope)
                            if not isinstance(projection, Mapping):
                                raise RemoteOperatorServiceError("work activation result projection is malformed")
                            activated += 1
                        except Exception:
                            projection = self._activation_status_projection(envelope, "WORK_ACTIVATION_ERROR")
                            blocked += 1
                else:
                    raise RemoteOperatorServiceError("UNKNOWN_REMOTE_CONTROL_KIND")
                self._publish_and_ack(envelope, projection)
                projected += 1
                acknowledged += 1
                continue

            try:
                decision = self.ingress(envelope)
            except Exception as exc:
                raise RemoteOperatorServiceError("INGRESS_FAILED") from exc

            if not decision.accepted:
                projection = self._projection(envelope, decision.result_class)
                self._publish_and_ack(envelope, projection)
                projected += 1
                acknowledged += 1
                blocked += 1
                continue

            directive = decision.directive
            if directive is None:
                raise RemoteOperatorServiceError("accepted ingress omitted directive")

            is_diagnostic = isinstance(envelope, RemoteOperatorEnvelopeV3)

            if resolved_mode == ControlMode.OBSERVE_ONLY:
                projection = self._projection(envelope, "OBSERVED")
            elif resolved_mode == ControlMode.CONTROL_READ_ONLY:
                if directive.state_change_required:
                    projection = self._projection(envelope, "MODE_BLOCKED")
                    blocked += 1
                elif is_diagnostic:
                    if self.execute_read_only is None:
                        projection = self._projection(envelope, "READ_ONLY_DIAGNOSTIC_UNAVAILABLE")
                        blocked += 1
                    else:
                        result = self.execute_read_only(envelope, directive, envelope.read_only_request)
                        if not isinstance(result, Mapping):
                            raise RemoteOperatorServiceError("diagnostic execution result is malformed")
                        projection = self._projection(envelope, "READ_ONLY_DIAGNOSTIC_COMPLETED", detail=result)
                        diagnosed += 1
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
                elif is_diagnostic:
                    projection = self._projection(envelope, "MODE_BLOCKED")
                    blocked += 1
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
                elif is_diagnostic:
                    if self.execute_read_only is None:
                        projection = self._projection(envelope, "READ_ONLY_DIAGNOSTIC_UNAVAILABLE")
                        blocked += 1
                    else:
                        result = self.execute_read_only(envelope, directive, envelope.read_only_request)
                        if not isinstance(result, Mapping):
                            raise RemoteOperatorServiceError("diagnostic execution result is malformed")
                        projection = self._projection(envelope, "READ_ONLY_DIAGNOSTIC_COMPLETED", detail=result)
                        diagnosed += 1
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
            diagnosed=diagnosed,
            projected=projected,
            acknowledged=acknowledged,
            blocked=blocked,
            inspected=inspected,
            activated=activated,
            full_plan_activated=full_plan_activated,
        )
