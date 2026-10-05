"""Canonical daily model-usage projection for AI Office Dashboard V2."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .model_usage_evidence import ModelUsageEvidenceError, normalize_turn_usage

MODEL_USAGE_REGISTRY_SCHEMA_V1 = "orchestration.model-usage-registry.v1"
MODEL_USAGE_SOURCE_V1 = "CANONICAL_MODEL_USAGE_V1"
MODEL_USAGE_EVIDENCE_SOURCE_V1 = "CODEX_TURN_COMPLETED"
_KST = ZoneInfo("Asia/Seoul")
_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


class OperationsDashboardModelUsageError(ValueError):
    pass


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: Mapping[str, Any], digest_key: str) -> str:
    return hashlib.sha256(_canonical_bytes({
        key: child for key, child in value.items() if key != digest_key
    })).hexdigest()


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise OperationsDashboardModelUsageError(f"{label} required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationsDashboardModelUsageError(f"{label} invalid") from exc
    if parsed.tzinfo is None:
        raise OperationsDashboardModelUsageError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _registry_path(state_root: str | Path) -> Path:
    return (
        Path(state_root).expanduser().resolve()
        / "_workspace" / "model-usage" / "registry.json"
    )


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.is_symlink():
        raise OperationsDashboardModelUsageError("unsafe model usage registry path")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise OperationsDashboardModelUsageError("unsafe model usage registry parent")
    data = _canonical_bytes(value) + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize_model_usage_registry(
    state_root: str | Path,
    *,
    activated_at: str,
    registry_ref: str,
) -> Path:
    root = Path(state_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise OperationsDashboardModelUsageError("state root unavailable")
    ref = str(registry_ref or "").strip()
    if not ref or len(ref) > 512:
        raise OperationsDashboardModelUsageError("model usage registry_ref invalid")
    activation = _timestamp(activated_at, "model usage activated_at").isoformat()
    payload: dict[str, Any] = {
        "schema_version": MODEL_USAGE_REGISTRY_SCHEMA_V1,
        "activated_at": activation,
        "evidence_source": MODEL_USAGE_EVIDENCE_SOURCE_V1,
        "registry_ref": ref,
    }
    payload["registry_digest"] = _digest(payload, "registry_digest")
    path = _registry_path(root)
    if path.exists() or path.is_symlink():
        existing = read_model_usage_registry(root)
        if existing == payload:
            return path
        raise OperationsDashboardModelUsageError("model usage registry conflict")
    _atomic_json(path, payload)
    return path


def read_model_usage_registry(state_root: str | Path) -> dict[str, Any]:
    path = _registry_path(state_root)
    if path.is_symlink() or not path.is_file():
        raise OperationsDashboardModelUsageError("model usage registry unavailable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperationsDashboardModelUsageError("model usage registry unreadable") from exc
    expected = {
        "schema_version", "activated_at", "evidence_source",
        "registry_ref", "registry_digest",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise OperationsDashboardModelUsageError("model usage registry shape mismatch")
    if value["schema_version"] != MODEL_USAGE_REGISTRY_SCHEMA_V1:
        raise OperationsDashboardModelUsageError("model usage registry schema mismatch")
    if value["evidence_source"] != MODEL_USAGE_EVIDENCE_SOURCE_V1:
        raise OperationsDashboardModelUsageError("model usage evidence source binding mismatch")
    _timestamp(value["activated_at"], "model usage activated_at")
    if not isinstance(value["registry_ref"], str) or not value["registry_ref"].strip():
        raise OperationsDashboardModelUsageError("model usage registry_ref invalid")
    digest = value.get("registry_digest")
    if not isinstance(digest, str) or len(digest) != 64 or digest != _digest(value, "registry_digest"):
        raise OperationsDashboardModelUsageError("model usage registry digest mismatch")
    return value


def unavailable_model_usage_projection() -> dict[str, Any]:
    return {
        "source_state": "UNAVAILABLE",
        "period": "TODAY_ASIA_SEOUL",
        "usage": None,
        "cost": {
            "status": "UNAVAILABLE",
            "estimated_usd": None,
            "reason": "NO_CANONICAL_USAGE_SOURCE",
        },
    }


def validate_model_usage_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OperationsDashboardModelUsageError("model usage projection mapping required")
    payload = dict(value)
    if set(payload) != {"source_state", "period", "usage", "cost"}:
        raise OperationsDashboardModelUsageError("model usage projection shape mismatch")
    if payload["period"] != "TODAY_ASIA_SEOUL":
        raise OperationsDashboardModelUsageError("model usage period mismatch")
    source = payload["source_state"]
    if source not in {MODEL_USAGE_SOURCE_V1, "UNAVAILABLE"}:
        raise OperationsDashboardModelUsageError("model usage source_state invalid")
    cost = payload["cost"]
    if not isinstance(cost, Mapping) or set(cost) != {"status", "estimated_usd", "reason"}:
        raise OperationsDashboardModelUsageError("model cost projection invalid")
    if cost["status"] != "UNAVAILABLE" or cost["estimated_usd"] is not None:
        raise OperationsDashboardModelUsageError("unverified model cost must remain unavailable")
    if cost["reason"] not in {"NO_VERIFIED_RATE_CARD", "NO_CANONICAL_USAGE_SOURCE"}:
        raise OperationsDashboardModelUsageError("model cost reason invalid")
    usage = payload["usage"]
    if source == "UNAVAILABLE":
        if usage is not None:
            raise OperationsDashboardModelUsageError("unavailable model usage must be null")
        return payload
    if not isinstance(usage, Mapping):
        raise OperationsDashboardModelUsageError("canonical model usage mapping required")
    expected_usage = {"execution_count", *_USAGE_FIELDS, "input_output_tokens"}
    if set(usage) != expected_usage:
        raise OperationsDashboardModelUsageError("canonical model usage shape mismatch")
    for key in expected_usage:
        raw = usage[key]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise OperationsDashboardModelUsageError(f"canonical model usage {key} invalid")
    if usage["input_output_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
        raise OperationsDashboardModelUsageError("model usage input/output total mismatch")
    if cost["reason"] != "NO_VERIFIED_RATE_CARD":
        raise OperationsDashboardModelUsageError("canonical usage requires explicit missing rate card")
    return payload


def _process_usage(path: Path) -> tuple[datetime, dict[str, int]] | None:
    if path.is_symlink() or not path.is_file():
        raise OperationsDashboardModelUsageError("unsafe model usage evidence path")
    if path.stat().st_size > 1024 * 1024:
        raise OperationsDashboardModelUsageError("model usage evidence exceeds size bound")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperationsDashboardModelUsageError("model usage evidence unreadable") from exc
    if not isinstance(value, dict):
        raise OperationsDashboardModelUsageError("model usage process evidence invalid")
    structured = value.get("structured_events")
    if not isinstance(structured, Mapping):
        return None
    usage = structured.get("turn_usage")
    if usage is None:
        return None
    if value.get("schema_version") != "orchestration.production-worker-process.v1":
        raise OperationsDashboardModelUsageError("model usage process schema mismatch")
    if value.get("structured_strict") is not True:
        raise OperationsDashboardModelUsageError("model usage evidence not strict")
    if structured.get("structured_terminal_status") != "SUCCEEDED":
        raise OperationsDashboardModelUsageError("model usage terminal status mismatch")
    if structured.get("turn_usage_source") != MODEL_USAGE_EVIDENCE_SOURCE_V1:
        raise OperationsDashboardModelUsageError("model usage evidence source mismatch")
    observed = _timestamp(structured.get("turn_usage_observed_at"), "model usage observed_at")
    try:
        normalized = normalize_turn_usage(usage)
    except ModelUsageEvidenceError as exc:
        raise OperationsDashboardModelUsageError("model usage turn evidence invalid") from exc
    return observed, normalized


def read_operations_dashboard_model_usage(
    state_root: str | Path,
    *,
    now: datetime | None = None,
    max_process_files: int = 10000,
) -> dict[str, Any]:
    root = Path(state_root).expanduser().resolve()
    registry = _registry_path(root)
    if not registry.exists() and not registry.is_symlink():
        return unavailable_model_usage_projection()
    reg = read_model_usage_registry(root)
    activation = _timestamp(reg["activated_at"], "model usage activated_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = current.astimezone(_KST).date()
    totals = {key: 0 for key in _USAGE_FIELDS}
    execution_count = 0
    events_root = root / "_workspace" / "orchestration-runs"
    paths = sorted(events_root.glob("**/executor.process.json")) if events_root.is_dir() else []
    if len(paths) > max_process_files:
        raise OperationsDashboardModelUsageError("model usage process scan bound exceeded")
    for path in paths:
        observed_usage = _process_usage(path)
        if observed_usage is None:
            continue
        observed, usage = observed_usage
        if observed < activation:
            continue
        if (observed - current).total_seconds() > 30:
            raise OperationsDashboardModelUsageError("model usage evidence timestamp is in the future")
        if observed.astimezone(_KST).date() != today:
            continue
        execution_count += 1
        for key in _USAGE_FIELDS:
            totals[key] += usage[key]
    projection = {
        "source_state": MODEL_USAGE_SOURCE_V1,
        "period": "TODAY_ASIA_SEOUL",
        "usage": {
            "execution_count": execution_count,
            **totals,
            "input_output_tokens": totals["input_tokens"] + totals["output_tokens"],
        },
        "cost": {
            "status": "UNAVAILABLE",
            "estimated_usd": None,
            "reason": "NO_VERIFIED_RATE_CARD",
        },
    }
    return validate_model_usage_projection(projection)
