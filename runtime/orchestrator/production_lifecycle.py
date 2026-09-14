"""Single production artifact producer/consumer path for lifecycle stages."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .lifecycle_binding import (
    LifecycleBindingError, canonical_bytes, seal_envelope, validate_binding,
    validate_envelope,
)


class ProductionLifecycleError(ValueError):
    pass


ARTIFACT_KINDS = (
    "package", "preflight", "worker_request", "worker_result", "review",
    "checkpoint", "lv_exit", "gate_completeness", "gate_checkpoint",
    "gate_exit", "handoff", "recovery_rejection", "recovery_successor",
    "partial_workspace_adoption",
)
SCHEMAS = {kind: f"orchestration.production.{kind}.v2" for kind in ARTIFACT_KINDS}


def produce(kind: str, payload: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
    if kind not in SCHEMAS:
        raise ProductionLifecycleError("unsupported lifecycle artifact kind")
    try:
        return seal_envelope(payload, binding, schema_version=SCHEMAS[kind])
    except LifecycleBindingError as exc:
        raise ProductionLifecycleError(str(exc)) from exc


def consume(kind: str, artifact: Mapping[str, Any], expected_binding: Mapping[str, Any],
            *, predecessor: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if kind not in SCHEMAS:
        raise ProductionLifecycleError("unsupported lifecycle artifact kind")
    try:
        validated = validate_envelope(artifact, schema_version=SCHEMAS[kind],
                                      expected_binding=expected_binding)
        binding = validate_binding(validated["binding"])
    except LifecycleBindingError as exc:
        raise ProductionLifecycleError(str(exc)) from exc
    payload = validated["payload"]
    if payload.get("completion_eligible") is True and (
        kind == "recovery_rejection" or payload.get("status") in {"REJECTED", "INVALID"}
    ):
        raise ProductionLifecycleError("rejected artifact cannot become completion evidence")
    if predecessor is not None:
        prior_digest = predecessor.get("envelope_sha256")
        if binding["predecessor_digest"] != prior_digest:
            raise ProductionLifecycleError("lifecycle predecessor mismatch")
    return validated


def transition(kind: str, payload: Mapping[str, Any], binding: Mapping[str, Any],
               *, predecessor: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The only direct production transition: produce then consume identically."""
    artifact = produce(kind, payload, binding)
    return consume(kind, artifact, binding, predecessor=predecessor)


def assert_no_legacy_direct_consumer(namespace: Mapping[str, Any]) -> None:
    """Reject callable consumer aliases that bypass the common validator."""
    allowed = {consume, transition}
    bypasses = [name for name, value in namespace.items()
                if name.startswith("consume_") and callable(value) and value not in allowed]
    if bypasses:
        raise ProductionLifecycleError("legacy direct consumer bypass detected")


def same_binding(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    try:
        return canonical_bytes(validate_binding(left)) == canonical_bytes(validate_binding(right))
    except LifecycleBindingError:
        return False
