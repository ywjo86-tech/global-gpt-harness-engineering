"""Durable operational acceptance records separate from Full Plan terminal state."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .durable_io import atomic_write_json

OPERATIONAL_ACCEPTANCE_SCHEMA_V1 = "orchestration.operational-acceptance-record.v1"
_TERMINAL = frozenset({"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"})


class OperationalAcceptanceError(ValueError):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class OperationalAcceptanceRecordV1:
    schema_version: str
    project_id: str
    run_id: str
    authority_core_sha256: str
    full_plan_terminal_state_sha256: str
    terminal_reason: str
    post_change_gate_evidence_digest: str
    monitor_health_receipt_refs: tuple[str, ...]
    process_lifecycle_diagnostic_refs: tuple[str, ...]
    runtime_release_identity_refs: tuple[str, ...]
    status: str
    failures: tuple[str, ...]
    created_at: str
    record_sha256: str

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in (
            "monitor_health_receipt_refs",
            "process_lifecycle_diagnostic_refs",
            "runtime_release_identity_refs",
            "failures",
        ):
            value[key] = list(value[key])
        value.pop("record_sha256")
        return value

    def to_dict(self) -> dict[str, Any]:
        value = self.unsigned_dict()
        value["record_sha256"] = self.record_sha256
        return value


def build_operational_acceptance_record(
    *,
    project_id: str,
    run_id: str,
    full_plan_terminal_state: Mapping[str, Any],
    post_change_gate: Mapping[str, Any],
    monitor_health_receipt_refs: Sequence[str] = (),
    process_lifecycle_diagnostic_refs: Sequence[str] = (),
    runtime_release_identity_refs: Sequence[str] = (),
    created_at: str | None = None,
) -> OperationalAcceptanceRecordV1:
    if not isinstance(full_plan_terminal_state, Mapping) or not isinstance(post_change_gate, Mapping):
        raise OperationalAcceptanceError("acceptance inputs must be mappings")
    terminal_state = str(full_plan_terminal_state.get("state") or "").upper()
    if terminal_state not in _TERMINAL:
        raise OperationalAcceptanceError("Full Plan terminal state required")
    failures = tuple(str(item) for item in post_change_gate.get("failures", ()) if str(item))
    status = "ACCEPTED" if post_change_gate.get("status") == "PASS" and not failures else "BLOCKED"
    state_sha = str(full_plan_terminal_state.get("state_sha256") or "")
    authority = str(full_plan_terminal_state.get("authority_core_sha256") or "")
    if len(state_sha) != 64 or len(authority) != 64:
        raise OperationalAcceptanceError("terminal state authority digests required")
    gate_digest = str(post_change_gate.get("gate_evidence_sha256") or "")
    if len(gate_digest) != 64:
        gate_digest = _digest(post_change_gate)
    unsigned = {
        "schema_version": OPERATIONAL_ACCEPTANCE_SCHEMA_V1,
        "project_id": str(project_id),
        "run_id": str(run_id),
        "authority_core_sha256": authority,
        "full_plan_terminal_state_sha256": state_sha,
        "terminal_reason": str(full_plan_terminal_state.get("terminal_reason") or full_plan_terminal_state.get("last_error") or terminal_state),
        "post_change_gate_evidence_digest": gate_digest,
        "monitor_health_receipt_refs": [str(item) for item in monitor_health_receipt_refs if str(item)],
        "process_lifecycle_diagnostic_refs": [str(item) for item in process_lifecycle_diagnostic_refs if str(item)],
        "runtime_release_identity_refs": [str(item) for item in runtime_release_identity_refs if str(item)],
        "status": status,
        "failures": list(failures),
        "created_at": created_at or _now(),
    }
    return OperationalAcceptanceRecordV1(
        schema_version=unsigned["schema_version"],
        project_id=unsigned["project_id"],
        run_id=unsigned["run_id"],
        authority_core_sha256=authority,
        full_plan_terminal_state_sha256=state_sha,
        terminal_reason=unsigned["terminal_reason"],
        post_change_gate_evidence_digest=gate_digest,
        monitor_health_receipt_refs=tuple(unsigned["monitor_health_receipt_refs"]),
        process_lifecycle_diagnostic_refs=tuple(unsigned["process_lifecycle_diagnostic_refs"]),
        runtime_release_identity_refs=tuple(unsigned["runtime_release_identity_refs"]),
        status=status,
        failures=tuple(unsigned["failures"]),
        created_at=unsigned["created_at"],
        record_sha256=_digest(unsigned),
    )


class OperationalAcceptanceStore:
    def __init__(self, state_root: str | Path) -> None:
        root = Path(state_root).resolve()
        if root.is_symlink() or not root.is_dir():
            raise OperationalAcceptanceError("acceptance state root unsafe")
        self.base = root / "_workspace" / "operational-acceptance"

    def _path(self, record: OperationalAcceptanceRecordV1) -> Path:
        return self.base / record.project_id / f"{record.run_id}.json"

    def _history_path(self, record: OperationalAcceptanceRecordV1) -> Path:
        return self.base / record.project_id / record.run_id / f"{record.record_sha256}.json"

    def _latest_path(self, project_id: str, run_id: str) -> Path:
        return self.base / str(project_id) / str(run_id) / "latest.json"

    def save_observation(self, record: OperationalAcceptanceRecordV1) -> OperationalAcceptanceRecordV1:
        """Append immutable acceptance evidence and atomically advance latest."""
        if record.record_sha256 != _digest(record.unsigned_dict()):
            raise OperationalAcceptanceError("acceptance record digest mismatch")
        history = self._history_path(record)
        history.parent.mkdir(parents=True, exist_ok=True)
        if history.parent.is_symlink():
            raise OperationalAcceptanceError("acceptance history path unsafe")
        if history.exists():
            existing = json.loads(history.read_text(encoding="utf-8"))
            if existing != record.to_dict():
                raise OperationalAcceptanceError("conflicting acceptance history record")
        else:
            atomic_write_json(history, record.to_dict())
        atomic_write_json(self._latest_path(record.project_id, record.run_id), record.to_dict())
        return record

    def load_latest(self, project_id: str, run_id: str) -> OperationalAcceptanceRecordV1:
        latest = self._latest_path(project_id, run_id)
        if latest.is_file() and not latest.is_symlink():
            value = json.loads(latest.read_text(encoding="utf-8"))
            return self._from_mapping(value)
        return self.load(project_id, run_id)

    @staticmethod
    def _from_mapping(value: Mapping[str, Any]) -> OperationalAcceptanceRecordV1:
        record = OperationalAcceptanceRecordV1(
            schema_version=str(value["schema_version"]),
            project_id=str(value["project_id"]),
            run_id=str(value["run_id"]),
            authority_core_sha256=str(value["authority_core_sha256"]),
            full_plan_terminal_state_sha256=str(value["full_plan_terminal_state_sha256"]),
            terminal_reason=str(value["terminal_reason"]),
            post_change_gate_evidence_digest=str(value["post_change_gate_evidence_digest"]),
            monitor_health_receipt_refs=tuple(value["monitor_health_receipt_refs"]),
            process_lifecycle_diagnostic_refs=tuple(value["process_lifecycle_diagnostic_refs"]),
            runtime_release_identity_refs=tuple(value["runtime_release_identity_refs"]),
            status=str(value["status"]),
            failures=tuple(value["failures"]),
            created_at=str(value["created_at"]),
            record_sha256=str(value["record_sha256"]),
        )
        if record.schema_version != OPERATIONAL_ACCEPTANCE_SCHEMA_V1 or record.record_sha256 != _digest(record.unsigned_dict()):
            raise OperationalAcceptanceError("acceptance record invalid")
        return record

    def save_once(self, record: OperationalAcceptanceRecordV1) -> OperationalAcceptanceRecordV1:
        if record.record_sha256 != _digest(record.unsigned_dict()):
            raise OperationalAcceptanceError("acceptance record digest mismatch")
        path = self._path(record)
        if path.exists():
            existing = self.load(record.project_id, record.run_id)
            if existing.to_dict() != record.to_dict():
                raise OperationalAcceptanceError("conflicting acceptance record")
            return existing
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise OperationalAcceptanceError("acceptance path unsafe")
        atomic_write_json(path, record.to_dict())
        return record

    def load(self, project_id: str, run_id: str) -> OperationalAcceptanceRecordV1:
        path = self.base / str(project_id) / f"{run_id}.json"
        if path.is_symlink() or not path.is_file():
            raise OperationalAcceptanceError("acceptance record missing")
        value = json.loads(path.read_text(encoding="utf-8"))
        return self._from_mapping(value)
