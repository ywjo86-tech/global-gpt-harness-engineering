"""Canonical provider-runtime observability for MPRF.

This module owns provider/model runtime facts only. Action execution, results,
effects, reconciliation and validation remain external action-runtime truth.
Correlation identifiers are references only and never transfer authority.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contracts import APPROVED_PROVIDER_IDS, MPRFContractError

EVENT_SCHEMA_V1 = "mprf.provider-runtime-event.v1"
CORRELATION_SCHEMA_V1 = "mprf.correlation-projection.v1"
SOURCE_DOMAIN = "MPRF_PROVIDER_RUNTIME"
AUTHORITY_SCOPE = "PROVIDER_RUNTIME_ONLY"
EVENT_TYPES_V1 = frozenset({
    "PROVIDER", "MODEL", "HEALTH", "QUOTA", "TRANSITION", "FAILOVER", "RETRY", "EXCLUSION",
})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MODEL_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_FORBIDDEN_FACT_KEYS = frozenset({
    "action", "action_state", "effect", "effect_id", "result", "result_digest", "receipt",
    "execution_result", "validation", "validation_result", "stdout", "stderr", "content", "prompt",
    "response", "authorization", "credentials", "credential", "secret", "token", "api_key",
    "commit", "push", "staged_tree", "exit_code",
})


class MPRFObservabilityError(MPRFContractError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise MPRFObservabilityError(f"{label} is invalid")
    return value


def _safe_facts(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise MPRFObservabilityError("provider runtime facts must be a mapping")
    out: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not raw_key or raw_key.lower() in _FORBIDDEN_FACT_KEYS:
            raise MPRFObservabilityError("provider runtime facts contain action truth or secret material")
        lowered = raw_key.lower()
        if lowered.startswith("raw_") or any(part in lowered for part in ("password", "credential", "secret", "token")):
            raise MPRFObservabilityError("provider runtime facts contain action truth or secret material")
        if isinstance(raw_value, bool) or raw_value is None or isinstance(raw_value, (int, float)):
            out[raw_key] = raw_value
        elif isinstance(raw_value, str) and len(raw_value) <= 512:
            out[raw_key] = raw_value
        elif isinstance(raw_value, (list, tuple)) and len(raw_value) <= 32 and all(
            isinstance(item, (str, int, float, bool)) or item is None for item in raw_value
        ):
            out[raw_key] = list(raw_value)
        else:
            raise MPRFObservabilityError("provider runtime fact value is not durable-safe")
    return out


def _canonical_digest(value: Mapping[str, Any]) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderRuntimeEventV1:
    schema_version: str
    project_id: str
    project_run_id: str
    task_id: str
    task_execution_id: str
    correlation_id: str
    operation_request_id: str
    provider_id: str
    model_ref: str
    event_type: str
    sequence: int
    occurred_at_utc: str
    facts: Mapping[str, Any]
    source_domain: str = SOURCE_DOMAIN
    authority_scope: str = AUTHORITY_SCOPE
    event_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_SCHEMA_V1:
            raise MPRFObservabilityError("unsupported provider runtime event schema")
        for value, label in (
            (self.project_id, "project_id"), (self.project_run_id, "project_run_id"),
            (self.task_id, "task_id"), (self.task_execution_id, "task_execution_id"),
            (self.correlation_id, "correlation_id"), (self.operation_request_id, "operation_request_id"),
        ):
            _safe_text(value, label)
        if not isinstance(self.model_ref, str) or not _MODEL_REF.fullmatch(self.model_ref):
            raise MPRFObservabilityError("model_ref is invalid")
        if self.provider_id not in APPROVED_PROVIDER_IDS:
            raise MPRFObservabilityError("provider_id is outside the approved provider domain")
        if self.event_type not in EVENT_TYPES_V1:
            raise MPRFObservabilityError("event_type is outside the closed provider-runtime taxonomy")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise MPRFObservabilityError("sequence must be positive")
        if not isinstance(self.occurred_at_utc, str) or not self.occurred_at_utc.endswith("Z"):
            raise MPRFObservabilityError("occurred_at_utc is invalid")
        if self.source_domain != SOURCE_DOMAIN or self.authority_scope != AUTHORITY_SCOPE:
            raise MPRFObservabilityError("provider runtime authority boundary is invalid")
        object.__setattr__(self, "facts", _safe_facts(self.facts))
        unsigned = self.unsigned_dict()
        expected = _canonical_digest(unsigned)
        if self.event_digest and (not _SHA256.fullmatch(self.event_digest) or self.event_digest != expected):
            raise MPRFObservabilityError("provider runtime event digest mismatch")
        object.__setattr__(self, "event_digest", expected)

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "project_run_id": self.project_run_id,
            "task_id": self.task_id,
            "task_execution_id": self.task_execution_id,
            "correlation_id": self.correlation_id,
            "operation_request_id": self.operation_request_id,
            "provider_id": self.provider_id,
            "model_ref": self.model_ref,
            "event_type": self.event_type,
            "sequence": self.sequence,
            "occurred_at_utc": self.occurred_at_utc,
            "facts": dict(self.facts),
            "source_domain": self.source_domain,
            "authority_scope": self.authority_scope,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "event_digest": self.event_digest}


class ProviderRuntimeEventStoreV1:
    """Append-only JSONL store for canonical MPRF provider-runtime facts."""

    def __init__(self, workspace_root: str | Path, project_run_id: str) -> None:
        root = Path(workspace_root)
        if not root.is_absolute() or not root.exists() or root.resolve(strict=True) != root:
            raise MPRFObservabilityError("workspace root must be an existing canonical path")
        _safe_text(project_run_id, "project_run_id")
        self.workspace_root = root
        self.project_run_id = project_run_id
        self.events_path = root / "_workspace" / "mprf" / project_run_id / "events" / "provider-runtime-events.jsonl"
        self.events_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, *, project_id: str, task_id: str, task_execution_id: str, correlation_id: str,
               operation_request_id: str, provider_id: str, model_ref: str, event_type: str,
               facts: Mapping[str, Any] | None = None) -> ProviderRuntimeEventV1:
        safe_facts = _safe_facts(facts)
        try:
            with self.events_path.open("a+", encoding="utf-8") as handle:
                os.chmod(self.events_path, 0o600)
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                handle.seek(0)
                sequence = 0
                for line in handle:
                    try:
                        existing = json.loads(line)
                        event = ProviderRuntimeEventV1(**existing)
                    except (json.JSONDecodeError, TypeError, MPRFObservabilityError) as exc:
                        raise MPRFObservabilityError("existing provider runtime event log is malformed") from exc
                    if event.project_run_id != self.project_run_id:
                        raise MPRFObservabilityError("existing provider runtime event run identity mismatch")
                    sequence = max(sequence, event.sequence)
                event = ProviderRuntimeEventV1(
                    EVENT_SCHEMA_V1, project_id, self.project_run_id, task_id, task_execution_id,
                    correlation_id, operation_request_id, provider_id, model_ref, event_type,
                    sequence + 1, _utc_now(), safe_facts,
                )
                handle.seek(0, os.SEEK_END)
                handle.write(json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                handle.flush(); os.fsync(handle.fileno())
                return event
        except OSError as exc:
            raise MPRFObservabilityError("provider runtime event persistence failed") from exc

    def read_all(self) -> tuple[ProviderRuntimeEventV1, ...]:
        if not self.events_path.exists():
            return ()
        if self.events_path.is_symlink() or not self.events_path.is_file():
            raise MPRFObservabilityError("provider runtime event log is unsafe")
        out: list[ProviderRuntimeEventV1] = []
        try:
            for line in self.events_path.read_text(encoding="utf-8").splitlines():
                out.append(ProviderRuntimeEventV1(**json.loads(line)))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, MPRFObservabilityError) as exc:
            raise MPRFObservabilityError("provider runtime event log is malformed") from exc
        if [item.sequence for item in out] != list(range(1, len(out) + 1)):
            raise MPRFObservabilityError("provider runtime event sequence is not append-only")
        return tuple(out)


def correlation_projection(event: ProviderRuntimeEventV1) -> dict[str, str]:
    if not isinstance(event, ProviderRuntimeEventV1):
        raise MPRFObservabilityError("ProviderRuntimeEvent.v1 is required")
    return {
        "schema_version": CORRELATION_SCHEMA_V1,
        "project_id": event.project_id,
        "project_run_id": event.project_run_id,
        "task_id": event.task_id,
        "task_execution_id": event.task_execution_id,
        "correlation_id": event.correlation_id,
        "operation_request_id": event.operation_request_id,
        "source_domain": SOURCE_DOMAIN,
        "authority_scope": AUTHORITY_SCOPE,
    }
