"""Runtime-bound system-level operational acceptance.

V1 acceptance remains tied to a specific terminal Full Plan run.  This V2
record answers a different question: is the *current* Harness operational
runtime healthy enough to be represented as accepted at the system level?
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .durable_io import atomic_write_json
from .operations_current_attention import (
    CURRENT_ATTENTION_SOURCE_V1,
    validate_current_attention_projection,
)

SYSTEM_ACCEPTANCE_SCHEMA_V2 = "orchestration.operational-system-acceptance.v2"


class OperationalSystemAcceptanceError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    unsigned = {k: v for k, v in value.items() if k != "record_sha256"}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _aware_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise OperationalSystemAcceptanceError("created_at required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationalSystemAcceptanceError("created_at invalid") from exc
    if parsed.tzinfo is None:
        raise OperationalSystemAcceptanceError("created_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class OperationalSystemAcceptanceV2:
    schema_version: str
    created_at: str
    runtime_source_identity: str
    expected_runtime_source_identity: str
    registered_project_count: int
    blocking_project_count: int
    post_change_gate_evidence_digest: str
    current_attention_projection_sha256: str
    monitor_health_receipt_refs: tuple[str, ...]
    process_lifecycle_diagnostic_refs: tuple[str, ...]
    status: str
    blocking_reasons: tuple[str, ...]
    record_sha256: str

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["monitor_health_receipt_refs"] = list(self.monitor_health_receipt_refs)
        value["process_lifecycle_diagnostic_refs"] = list(
            self.process_lifecycle_diagnostic_refs
        )
        value["blocking_reasons"] = list(self.blocking_reasons)
        value.pop("record_sha256")
        return value

    def to_dict(self) -> dict[str, Any]:
        value = self.unsigned_dict()
        value["record_sha256"] = self.record_sha256
        return value


def build_operational_system_acceptance(
    *,
    runtime_source_identity: str,
    expected_runtime_source_identity: str,
    registered_project_count: int,
    post_change_gate: Mapping[str, Any],
    current_attention_projection: Mapping[str, Any],
    monitor_health_receipt_refs: Sequence[str] = (),
    process_lifecycle_diagnostic_refs: Sequence[str] = (),
    created_at: str | None = None,
) -> OperationalSystemAcceptanceV2:
    runtime = str(runtime_source_identity or "").strip()
    expected = str(expected_runtime_source_identity or "").strip()
    if not runtime or not expected:
        raise OperationalSystemAcceptanceError("runtime identities required")
    if (
        isinstance(registered_project_count, bool)
        or not isinstance(registered_project_count, int)
        or registered_project_count < 0
    ):
        raise OperationalSystemAcceptanceError("registered project count invalid")
    if not isinstance(post_change_gate, Mapping):
        raise OperationalSystemAcceptanceError("post-change gate required")

    attention = validate_current_attention_projection(current_attention_projection)
    blocking_reasons: list[str] = []

    if runtime != expected:
        blocking_reasons.append("RUNTIME_SOURCE_MISMATCH")
    if attention["runtime_source_identity"] != expected:
        blocking_reasons.append("ATTENTION_RUNTIME_SOURCE_MISMATCH")

    gate_expected = str(post_change_gate.get("expected_runtime_source_identity") or "")
    if gate_expected != expected:
        blocking_reasons.append("POST_CHANGE_RUNTIME_BINDING_MISMATCH")
    gate_failures = [
        str(item)
        for item in post_change_gate.get("failures", ())
        if str(item)
    ]
    if post_change_gate.get("status") != "PASS" or gate_failures:
        blocking_reasons.extend(
            f"POST_CHANGE:{item}" for item in gate_failures
        )
        if not gate_failures:
            blocking_reasons.append("POST_CHANGE:BLOCKED")

    items = attention.get("items") or []
    project_ids = {
        str(item.get("project_id") or "")
        for item in items
        if str(item.get("project_id") or "")
    }
    if project_ids:
        blocking_reasons.append(f"CURRENT_OPERATIONAL_BLOCKERS:{len(project_ids)}")

    gate_digest = str(post_change_gate.get("gate_evidence_sha256") or "")
    if len(gate_digest) != 64:
        gate_digest = hashlib.sha256(_canonical(dict(post_change_gate))).hexdigest()
    attention_digest = str(attention.get("projection_sha256") or "")
    if len(attention_digest) != 64:
        raise OperationalSystemAcceptanceError("attention projection digest required")

    timestamp = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    _aware_timestamp(timestamp)
    reasons = tuple(dict.fromkeys(blocking_reasons))
    unsigned = {
        "schema_version": SYSTEM_ACCEPTANCE_SCHEMA_V2,
        "created_at": timestamp,
        "runtime_source_identity": runtime,
        "expected_runtime_source_identity": expected,
        "registered_project_count": registered_project_count,
        "blocking_project_count": len(project_ids),
        "post_change_gate_evidence_digest": gate_digest,
        "current_attention_projection_sha256": attention_digest,
        "monitor_health_receipt_refs": [
            str(item) for item in monitor_health_receipt_refs if str(item)
        ],
        "process_lifecycle_diagnostic_refs": [
            str(item) for item in process_lifecycle_diagnostic_refs if str(item)
        ],
        "status": "ACCEPTED" if not reasons else "BLOCKED",
        "blocking_reasons": list(reasons),
    }
    record_sha256 = hashlib.sha256(_canonical(unsigned)).hexdigest()
    return OperationalSystemAcceptanceV2(
        schema_version=unsigned["schema_version"],
        created_at=unsigned["created_at"],
        runtime_source_identity=unsigned["runtime_source_identity"],
        expected_runtime_source_identity=unsigned[
            "expected_runtime_source_identity"
        ],
        registered_project_count=unsigned["registered_project_count"],
        blocking_project_count=unsigned["blocking_project_count"],
        post_change_gate_evidence_digest=unsigned[
            "post_change_gate_evidence_digest"
        ],
        current_attention_projection_sha256=unsigned[
            "current_attention_projection_sha256"
        ],
        monitor_health_receipt_refs=tuple(
            unsigned["monitor_health_receipt_refs"]
        ),
        process_lifecycle_diagnostic_refs=tuple(
            unsigned["process_lifecycle_diagnostic_refs"]
        ),
        status=unsigned["status"],
        blocking_reasons=tuple(unsigned["blocking_reasons"]),
        record_sha256=record_sha256,
    )


def validate_operational_system_acceptance(
    value: Mapping[str, Any],
) -> OperationalSystemAcceptanceV2:
    if not isinstance(value, Mapping):
        raise OperationalSystemAcceptanceError("system acceptance mapping required")
    required = {
        "schema_version",
        "created_at",
        "runtime_source_identity",
        "expected_runtime_source_identity",
        "registered_project_count",
        "blocking_project_count",
        "post_change_gate_evidence_digest",
        "current_attention_projection_sha256",
        "monitor_health_receipt_refs",
        "process_lifecycle_diagnostic_refs",
        "status",
        "blocking_reasons",
        "record_sha256",
    }
    if set(value) != required:
        raise OperationalSystemAcceptanceError("system acceptance shape mismatch")
    if value.get("schema_version") != SYSTEM_ACCEPTANCE_SCHEMA_V2:
        raise OperationalSystemAcceptanceError("system acceptance schema mismatch")
    _aware_timestamp(value.get("created_at"))
    for key in ("runtime_source_identity", "expected_runtime_source_identity"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise OperationalSystemAcceptanceError("system acceptance runtime identity missing")
    for key in ("registered_project_count", "blocking_project_count"):
        count = value.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise OperationalSystemAcceptanceError("system acceptance count invalid")
    if value["blocking_project_count"] > value["registered_project_count"]:
        raise OperationalSystemAcceptanceError("blocking count exceeds registered projects")
    if value.get("status") not in {"ACCEPTED", "BLOCKED"}:
        raise OperationalSystemAcceptanceError("system acceptance status invalid")
    reasons = value.get("blocking_reasons")
    if (
        value.get("status") == "ACCEPTED"
        and (value.get("blocking_project_count") != 0 or reasons)
    ):
        raise OperationalSystemAcceptanceError("accepted system record contains blockers")
    if value.get("status") == "BLOCKED" and not reasons:
        raise OperationalSystemAcceptanceError("blocked system record requires reason")
    for key in (
        "monitor_health_receipt_refs",
        "process_lifecycle_diagnostic_refs",
        "blocking_reasons",
    ):
        if not isinstance(value.get(key), list) or any(
            not isinstance(item, str) for item in value[key]
        ):
            raise OperationalSystemAcceptanceError("system acceptance list invalid")
    for key in (
        "post_change_gate_evidence_digest",
        "current_attention_projection_sha256",
        "record_sha256",
    ):
        digest = value.get(key)
        if not isinstance(digest, str) or len(digest) != 64:
            raise OperationalSystemAcceptanceError("system acceptance digest invalid")
    if value["record_sha256"] != _digest(value):
        raise OperationalSystemAcceptanceError("system acceptance digest mismatch")

    return OperationalSystemAcceptanceV2(
        schema_version=value["schema_version"],
        created_at=value["created_at"],
        runtime_source_identity=value["runtime_source_identity"],
        expected_runtime_source_identity=value["expected_runtime_source_identity"],
        registered_project_count=value["registered_project_count"],
        blocking_project_count=value["blocking_project_count"],
        post_change_gate_evidence_digest=value["post_change_gate_evidence_digest"],
        current_attention_projection_sha256=value[
            "current_attention_projection_sha256"
        ],
        monitor_health_receipt_refs=tuple(value["monitor_health_receipt_refs"]),
        process_lifecycle_diagnostic_refs=tuple(
            value["process_lifecycle_diagnostic_refs"]
        ),
        status=value["status"],
        blocking_reasons=tuple(value["blocking_reasons"]),
        record_sha256=value["record_sha256"],
    )


def operational_system_acceptance_path(state_root: str | Path) -> Path:
    return (
        Path(state_root).expanduser().resolve()
        / "operations-v2"
        / "operational-system-acceptance.json"
    )


def record_operational_system_acceptance(
    state_root: str | Path,
    record: OperationalSystemAcceptanceV2,
) -> Path:
    root = Path(state_root).expanduser().resolve()
    if root.is_symlink() or not root.is_dir():
        raise OperationalSystemAcceptanceError("system acceptance root unsafe")
    validated = validate_operational_system_acceptance(record.to_dict())
    history = (
        root
        / "_workspace"
        / "operational-system-acceptance"
        / f"{validated.record_sha256}.json"
    )
    current = operational_system_acceptance_path(root)
    history.parent.mkdir(parents=True, exist_ok=True)
    if history.parent.is_symlink() or current.is_symlink():
        raise OperationalSystemAcceptanceError("system acceptance path unsafe")
    if not history.exists():
        atomic_write_json(history, validated.to_dict())
    else:
        existing = json.loads(history.read_text(encoding="utf-8"))
        if existing != validated.to_dict():
            raise OperationalSystemAcceptanceError(
                "conflicting system acceptance history"
            )
    return atomic_write_json(current, validated.to_dict())


def load_operational_system_acceptance(
    state_root: str | Path,
) -> OperationalSystemAcceptanceV2:
    path = operational_system_acceptance_path(state_root)
    if path.is_symlink() or not path.is_file():
        raise OperationalSystemAcceptanceError("system acceptance missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperationalSystemAcceptanceError("system acceptance unreadable") from exc
    return validate_operational_system_acceptance(value)
