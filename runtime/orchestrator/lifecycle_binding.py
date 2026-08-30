"""Strict canonical bindings shared by production lifecycle artifacts."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any


class LifecycleBindingError(ValueError):
    """Fail-closed binding error whose representation never includes payloads."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self)!r})"


SCHEMA_VERSION = "orchestration.lifecycle-binding.v1"
DIGEST_FIELDS = frozenset({
    "source_artifact_sha256", "projection_sha256", "payload_sha256",
    "sidecar_sha256", "envelope_sha256", "canonical_plan_sha256",
    "active_transition_sha256", "owned_scope_digest", "predecessor_digest",
    "artifact_sha256",
})
IDENTITY_FIELDS = frozenset({
    "project_id", "gate_id", "lv_id", "run_id", "recovery_id",
    "approval_event_id", "branch", "baseline_head", "current_head",
})
FIELDS = frozenset({"schema_version", *DIGEST_FIELDS, *IDENTITY_FIELDS,
                    "attempt", "hard_stop"})
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_SELF_FIELDS = frozenset({"projection_sha256", "payload_sha256", "sidecar_sha256",
                          "envelope_sha256", "artifact_sha256"})


def canonical_bytes(value: Any) -> bytes:
    """RFC-8259-compatible deterministic UTF-8 JSON (no NaN or key coercion)."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LifecycleBindingError("canonical serialization failed") from exc


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def blank_self_projection(value: Mapping[str, Any], self_field: str) -> dict[str, Any]:
    """Return the canonical digest projection with exactly its self-field blank.

    A digest never hashes a value containing itself.  The field remains present
    with the empty-string sentinel, making omission and circular self-binding
    distinguishable and deterministic.
    """
    if self_field not in _SELF_FIELDS or self_field not in value:
        raise LifecycleBindingError("invalid digest self-field")
    projected = dict(value)
    projected[self_field] = ""
    return projected


def digest_projection(value: Mapping[str, Any], self_field: str) -> str:
    return sha256(blank_self_projection(value, self_field))


def build_binding(**values: Any) -> dict[str, Any]:
    candidate = {"schema_version": SCHEMA_VERSION, **values}
    validate_binding(candidate)
    return candidate


def validate_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LifecycleBindingError("binding must be an object")
    keys = set(value)
    if keys != FIELDS:
        raise LifecycleBindingError("binding schema fields mismatch")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise LifecycleBindingError("unsupported binding schema version")
    for field in DIGEST_FIELDS:
        item = value.get(field)
        if not isinstance(item, str) or not _SHA.fullmatch(item):
            raise LifecycleBindingError(f"invalid digest field: {field}")
    # Digest roles are intentionally non-interchangeable. Equal values indicate
    # accidental role reuse, not a valid lifecycle binding.
    digest_values = [value[field] for field in sorted(DIGEST_FIELDS)]
    if len(digest_values) != len(set(digest_values)):
        raise LifecycleBindingError("digest role collision")
    for field in IDENTITY_FIELDS:
        item = value.get(field)
        if not isinstance(item, str) or not _ID.fullmatch(item):
            raise LifecycleBindingError(f"invalid identity field: {field}")
    attempt = value.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt <= 0:
        raise LifecycleBindingError("attempt must be a positive integer")
    if value.get("hard_stop") is not True:
        raise LifecycleBindingError("hard_stop must be true")
    return dict(value)


def seal_envelope(payload: Mapping[str, Any], binding: Mapping[str, Any], *,
                  schema_version: str) -> dict[str, Any]:
    validated = validate_binding(binding)
    if not isinstance(schema_version, str) or not _ID.fullmatch(schema_version):
        raise LifecycleBindingError("invalid envelope schema version")
    envelope = {"schema_version": schema_version, "binding": validated,
                "payload": dict(payload), "envelope_sha256": ""}
    envelope["envelope_sha256"] = digest_projection(envelope, "envelope_sha256")
    return envelope


def validate_envelope(envelope: Mapping[str, Any], *, schema_version: str,
                      expected_binding: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, Mapping) or set(envelope) != {
        "schema_version", "binding", "payload", "envelope_sha256"
    }:
        raise LifecycleBindingError("envelope schema fields mismatch")
    if envelope.get("schema_version") != schema_version:
        raise LifecycleBindingError("unsupported envelope schema version")
    actual = validate_binding(envelope.get("binding", {}))
    expected = validate_binding(expected_binding)
    if canonical_bytes(actual) != canonical_bytes(expected):
        raise LifecycleBindingError("envelope binding mismatch")
    digest = envelope.get("envelope_sha256")
    if not isinstance(digest, str) or digest != digest_projection(envelope, "envelope_sha256"):
        raise LifecycleBindingError("envelope digest mismatch")
    if not isinstance(envelope.get("payload"), Mapping):
        raise LifecycleBindingError("envelope payload must be an object")
    return dict(envelope)
