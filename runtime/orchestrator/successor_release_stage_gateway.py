"""Dedicated Production Execution Gateway contract for P2 successor staging.

This gateway is intentionally separate from the generic HOST worker request schema.
It carries no raw command, argv, shell, service-manager, or caller-controlled refspec
surface.  The only dispatch target is SuccessorReleaseStager.execute().
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .production_execution_gateway import GatewayError
from .successor_release_staging import (
    SuccessorReleaseStageRequest,
    SuccessorReleaseStageError,
)

SUCCESSOR_RELEASE_STAGE_GATEWAY_SCHEMA = "orchestration.successor-release-stage-gateway.v1"
SUCCESSOR_RELEASE_STAGE_CAPABILITY_ID = "SUCCESSOR_RELEASE_STAGE"
_FIELDS = {
    "schema_version",
    "request_kind",
    "capability_id",
    "stage_request",
    "stage_intent_digest",
    "phase_request_digest",
    "approval_policy_ref",
    "approval_policy_digest",
    "gateway_digest",
}


class SuccessorReleaseStageGatewayError(GatewayError):
    """Fail-closed successor staging admission/dispatch failure."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(dict(value))).hexdigest()


class _SuccessorReleaseStagerPort(Protocol):
    def execute(self, request: SuccessorReleaseStageRequest) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SuccessorReleaseStageGatewayRequest:
    schema_version: str
    request_kind: str
    capability_id: str
    stage_request: Mapping[str, Any]
    stage_intent_digest: str
    phase_request_digest: str
    approval_policy_ref: str
    approval_policy_digest: str
    gateway_digest: str

    @classmethod
    def from_stage_request(
        cls,
        request: SuccessorReleaseStageRequest,
    ) -> "SuccessorReleaseStageGatewayRequest":
        unsigned: dict[str, Any] = {
            "schema_version": SUCCESSOR_RELEASE_STAGE_GATEWAY_SCHEMA,
            "request_kind": SUCCESSOR_RELEASE_STAGE_CAPABILITY_ID,
            "capability_id": SUCCESSOR_RELEASE_STAGE_CAPABILITY_ID,
            "stage_request": request.to_dict(),
            "stage_intent_digest": request.stage_intent_digest,
            "phase_request_digest": request.phase_request_digest,
            "approval_policy_ref": request.approval_policy_ref,
            "approval_policy_digest": request.approval_policy_digest,
        }
        return cls(**unsigned, gateway_digest=_digest(unsigned))

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
    ) -> "SuccessorReleaseStageGatewayRequest":
        if not isinstance(raw, Mapping) or set(raw) != _FIELDS:
            raise SuccessorReleaseStageGatewayError("successor stage gateway fields mismatch")
        if raw.get("schema_version") != SUCCESSOR_RELEASE_STAGE_GATEWAY_SCHEMA:
            raise SuccessorReleaseStageGatewayError("successor stage gateway schema mismatch")
        if raw.get("request_kind") != SUCCESSOR_RELEASE_STAGE_CAPABILITY_ID:
            raise SuccessorReleaseStageGatewayError("successor stage request kind mismatch")
        if raw.get("capability_id") != SUCCESSOR_RELEASE_STAGE_CAPABILITY_ID:
            raise SuccessorReleaseStageGatewayError("successor stage capability mismatch")
        stage_raw = raw.get("stage_request")
        if not isinstance(stage_raw, Mapping):
            raise SuccessorReleaseStageGatewayError("successor stage request is missing")
        try:
            stage_request = SuccessorReleaseStageRequest.from_mapping(stage_raw)
        except SuccessorReleaseStageError as exc:
            raise SuccessorReleaseStageGatewayError("successor stage request is invalid") from exc
        expected = cls.from_stage_request(stage_request)
        if raw.get("stage_intent_digest") != expected.stage_intent_digest:
            raise SuccessorReleaseStageGatewayError("successor stage intent digest mismatch")
        if raw.get("phase_request_digest") != expected.phase_request_digest:
            raise SuccessorReleaseStageGatewayError("successor stage phase digest mismatch")
        if raw.get("approval_policy_ref") != expected.approval_policy_ref:
            raise SuccessorReleaseStageGatewayError("successor stage policy ref mismatch")
        if raw.get("approval_policy_digest") != expected.approval_policy_digest:
            raise SuccessorReleaseStageGatewayError("successor stage policy digest mismatch")
        unsigned = dict(raw)
        gateway_digest = str(unsigned.pop("gateway_digest") or "")
        if gateway_digest != _digest(unsigned):
            raise SuccessorReleaseStageGatewayError("successor stage gateway digest mismatch")
        return cls(
            schema_version=expected.schema_version,
            request_kind=expected.request_kind,
            capability_id=expected.capability_id,
            stage_request=expected.stage_request,
            stage_intent_digest=expected.stage_intent_digest,
            phase_request_digest=expected.phase_request_digest,
            approval_policy_ref=expected.approval_policy_ref,
            approval_policy_digest=expected.approval_policy_digest,
            gateway_digest=gateway_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_kind": self.request_kind,
            "capability_id": self.capability_id,
            "stage_request": dict(self.stage_request),
            "stage_intent_digest": self.stage_intent_digest,
            "phase_request_digest": self.phase_request_digest,
            "approval_policy_ref": self.approval_policy_ref,
            "approval_policy_digest": self.approval_policy_digest,
            "gateway_digest": self.gateway_digest,
        }


def dispatch_successor_release_stage(
    request: SuccessorReleaseStageGatewayRequest | Mapping[str, Any],
    *,
    stager: _SuccessorReleaseStagerPort,
) -> dict[str, Any]:
    """Validate the exact bounded capability and dispatch only to the stager port."""
    if isinstance(request, SuccessorReleaseStageGatewayRequest):
        admitted = SuccessorReleaseStageGatewayRequest.from_mapping(request.to_dict())
    elif isinstance(request, Mapping):
        admitted = SuccessorReleaseStageGatewayRequest.from_mapping(request)
    else:
        raise SuccessorReleaseStageGatewayError("successor stage gateway request is invalid")
    try:
        stage_request = SuccessorReleaseStageRequest.from_mapping(admitted.stage_request)
        result = stager.execute(stage_request)
    except SuccessorReleaseStageError:
        raise
    except Exception as exc:
        raise SuccessorReleaseStageGatewayError("successor stage dispatch failed") from exc
    if not isinstance(result, Mapping):
        raise SuccessorReleaseStageGatewayError("successor stage result is malformed")
    return dict(result)
